#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HARDENED_PATH = Path(__file__).with_name("custom_nodes_hardened.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_hardened", _HARDENED_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load hardened custom-node installer: {_HARDENED_PATH}")
hardened = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hardened)

profiled = hardened.profiled
base = hardened.base
_ORIGINAL_PERSIST_PROFILE = profiled.persist_profile


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip(".-")
    return cleaned[:120] or fallback


def _hff_python() -> Path:
    configured = os.environ.get("HFF_VENV", "")
    if configured:
        candidate = Path(configured) / "bin" / "python"
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _remote_target(report: dict, run_path: Path) -> tuple[str, str, str] | None:
    repo = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO")
        or os.environ.get("HFF_REPO")
        or os.environ.get("HF_MY_REPO_ID")
        or ""
    ).strip()
    if not repo:
        return None

    repo_type = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO_TYPE")
        or os.environ.get("HFF_REPO_TYPE")
        or os.environ.get("HF_MY_REPO_TYPE")
        or "model"
    ).strip()
    if repo_type not in {"model", "dataset"}:
        repo_type = "model"

    prefix = os.environ.get(
        "CUSTOM_NODE_PROFILE_REMOTE_PREFIX", "telemetry/custom_nodes/v1"
    ).strip().strip("/")

    run_id = str(report.get("run_id") or run_path.stem.removeprefix("run-"))
    match = re.match(r"(\d{4})(\d{2})(\d{2})", run_id)
    if match:
        year, month, day = match.groups()
    else:
        now = datetime.now(timezone.utc)
        year, month, day = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")

    hostname = _safe_component(
        str(report.get("environment", {}).get("hostname") or socket.gethostname()),
        "unknown-host",
    )
    filename = f"{hostname}__{run_path.name}"
    remote_path = f"{prefix}/{year}/{month}/{day}/{filename}"
    return repo, repo_type, remote_path


def publish_profile(run_path: Path, report: dict) -> None:
    if not _enabled("CUSTOM_NODE_PROFILE_PUBLISH", True):
        return
    if not os.environ.get("HF_TOKEN"):
        print(
            "[custom-nodes] profile publish skipped: HF_TOKEN is not set",
            file=sys.stderr,
            flush=True,
        )
        return

    target = _remote_target(report, run_path)
    if target is None:
        print(
            "[custom-nodes] profile publish skipped: no telemetry repository configured",
            file=sys.stderr,
            flush=True,
        )
        return
    repo, repo_type, remote_path = target

    hff_py = Path(os.environ.get("HFF_PY") or Path(__file__).with_name("hff.py"))
    if not hff_py.is_file():
        print(
            f"[custom-nodes] profile publish skipped: hff.py not found: {hff_py}",
            file=sys.stderr,
            flush=True,
        )
        return

    try:
        timeout = max(1.0, float(os.environ.get("CUSTOM_NODE_PROFILE_PUBLISH_TIMEOUT", "45")))
    except ValueError:
        timeout = 45.0

    command = [
        str(_hff_python()),
        str(hff_py),
        "--repo",
        repo,
        "--type",
        repo_type,
        "put",
        str(run_path),
        remote_path,
        "--message",
        f"custom-node profile {report.get('run_id', run_path.stem)}",
    ]

    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        print(
            f"[custom-nodes] profile publish timed out after {timeout:g}s; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return
    except Exception as error:
        print(
            f"[custom-nodes] profile publish failed: {error}; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"hff exited {completed.returncode}"
        print(
            f"[custom-nodes] profile publish failed: {message}; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return

    print(
        f"[custom-nodes] profile published: hf://{repo}/{remote_path}",
        file=sys.stderr,
        flush=True,
    )


def persist_and_publish(report: dict, status_path: Path, log_dir: Path) -> Path:
    run_path = _ORIGINAL_PERSIST_PROFILE(report, status_path, log_dir)
    publish_profile(run_path, report)
    return run_path


# profiled_install resolves persist_profile through its module globals, so replacing
# the module attribute adds publication without changing the profiler itself.
profiled.persist_profile = persist_and_publish


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
