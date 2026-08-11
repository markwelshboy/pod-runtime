#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
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


def _hff_python() -> Path:
    configured = os.environ.get("HFF_VENV", "")
    if configured:
        candidate = Path(configured) / "bin" / "python"
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


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

    repo = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO")
        or os.environ.get("HFF_REPO")
        or os.environ.get("HF_MY_REPO_ID")
        or ""
    ).strip()
    if not repo:
        print(
            "[custom-nodes] profile publish skipped: no telemetry repository configured",
            file=sys.stderr,
            flush=True,
        )
        return

    repo_type = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO_TYPE")
        or os.environ.get("HFF_REPO_TYPE")
        or os.environ.get("HF_MY_REPO_TYPE")
        or "model"
    ).strip()
    if repo_type not in {"model", "dataset"}:
        repo_type = "model"

    prefix = (
        os.environ.get("CUSTOM_NODE_PROFILE_REMOTE_PREFIX")
        or os.environ.get("HFF_TELEMETRY_PREFIX")
        or "telemetry/custom_nodes/v1"
    ).strip()

    telemetry_py = Path(
        os.environ.get("HFF_TELEMETRY_PY") or Path(__file__).with_name("hff_telemetry.py")
    )
    if not telemetry_py.is_file():
        print(
            f"[custom-nodes] profile publish skipped: hff telemetry helper not found: {telemetry_py}",
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
        str(telemetry_py),
        "--repo",
        repo,
        "--type",
        repo_type,
        "--prefix",
        prefix,
        str(run_path),
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
        message = detail[-1] if detail else f"hff telemetry exited {completed.returncode}"
        print(
            f"[custom-nodes] profile publish failed: {message}; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return

    uri = (completed.stdout or "").strip().splitlines()
    published = uri[-1] if uri else "<unknown>"
    print(
        f"[custom-nodes] profile published: {published}",
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
