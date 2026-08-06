#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BASE_PATH = Path(__file__).with_name("custom_nodes.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_base", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load custom-node installer: {_BASE_PATH}")
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)

_SIZE_RE = re.compile(r"\(([0-9]+(?:\.[0-9]+)?)\s*(kB|MB|GB)\)", re.I)
_SIZE_MULTIPLIERS = {"kb": 1000, "mb": 1000**2, "gb": 1000**3}
_ORIGINAL_RUN_COMMAND = base.run_command
_ORIGINAL_CLONE_NODE = base.clone_node
_ORIGINAL_INSTALL_NODE = base.install_node
_ORIGINAL_INSTALL = base.install
_ORIGINAL_PRINT_STATUS = base.print_status_report
_CONTEXT = threading.local()
_LOCK = threading.Lock()
_RUN: dict[str, Any] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"


def elapsed(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started), 3)


def git_commit(destination: Path) -> str:
    if not (destination / ".git").exists():
        return ""
    completed = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def log_offset(log: Any) -> tuple[Path | None, int]:
    if log is None:
        return None, 0
    try:
        log.flush()
        path = Path(log.name)
        return path, path.stat().st_size
    except (AttributeError, OSError, TypeError):
        return None, 0


def parse_log(path: Path | None, offset: int) -> dict[str, int]:
    if path is None:
        return {}
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            text = handle.read().decode(errors="replace")
    except OSError:
        return {}

    download_bytes = 0
    for line in text.splitlines():
        if "Downloading " not in line:
            continue
        match = _SIZE_RE.search(line)
        if match:
            download_bytes += int(float(match.group(1)) * _SIZE_MULTIPLIERS[match.group(2).lower()])

    return {
        "using_cached_count": text.count("Using cached "),
        "download_count": sum("Downloading " in line for line in text.splitlines()),
        "download_bytes_observed": download_bytes,
        "wheel_build_count": text.count("Building wheel for ") + text.count("Building editable for "),
        "successfully_built_count": sum(
            len(line.removeprefix("Successfully built ").split())
            for line in text.splitlines()
            if line.startswith("Successfully built ")
        ),
        "successfully_installed_count": sum(
            len(line.removeprefix("Successfully installed ").split())
            for line in text.splitlines()
            if line.startswith("Successfully installed ")
        ),
    }


def classify_command(command: list[str]) -> str:
    words = [str(value) for value in command]
    executable = Path(words[0]).name if words else ""
    if executable == "git":
        for action in ("clone", "fetch", "pull", "checkout"):
            if action in words[1:]:
                return f"git_{action}"
        return "git_other"
    if "install" in words and (executable.startswith("pip") or "-m" in words and "pip" in words):
        return "pip"
    if words and Path(words[-1]).name == "install.py":
        return "install_py"
    return "other"


def profiled_run_command(command: list[str], *, cwd=None, env=None, log=None) -> int:
    node_id = getattr(_CONTEXT, "node_id", "")
    path, offset = log_offset(log)
    started = time.perf_counter()
    rc = _ORIGINAL_RUN_COMMAND(command, cwd=cwd, env=env, log=log)
    record = {
        "kind": classify_command(command),
        "seconds": elapsed(started),
        "returncode": rc,
        "command": [str(value) for value in command],
        **parse_log(path, offset),
    }
    if node_id:
        with _LOCK:
            _RUN.setdefault("commands", {}).setdefault(node_id, []).append(record)
    return rc


def profiled_clone_node(item, custom_dir: Path, log_dir: Path):
    node_id, node = item
    destination = custom_dir / base.local_name(node)
    before = git_commit(destination)
    started = time.perf_counter()
    _CONTEXT.node_id = node_id
    try:
        result = _ORIGINAL_CLONE_NODE(item, custom_dir, log_dir)
    finally:
        _CONTEXT.node_id = ""
    after = git_commit(destination)
    with _LOCK:
        _RUN.setdefault("clone", {})[node_id] = {
            "seconds": elapsed(started),
            "action": "update" if before else "clone",
            "commit_before": before,
            "commit_after": after,
            "commit_changed": bool(before and after and before != after),
        }
    return result


def effective_requirements(item, custom_dir: Path) -> dict[str, Any]:
    node_id, node = item
    destination = custom_dir / base.local_name(node)
    pip_config = node.get("pip", {})
    requirements = pip_config.get("requirements", {})
    files = requirements.get("files", ["requirements.txt"])
    removals = {base.normalize_name(name) for name in requirements.get("remove", [])}
    additions = list(requirements.get("add", []))
    effective: list[str] = []
    found: list[str] = []
    for relative in files:
        path = destination / relative
        if not path.is_file():
            continue
        found.append(relative)
        for line in path.read_text(errors="replace").splitlines():
            if base.requirement_name(line) not in removals:
                effective.append(line)
    effective.extend(additions)
    payload = {
        "requirements": effective,
        "pip_options": pip_config.get("options", ["--upgrade-strategy", "only-if-needed"]),
        "constraint_mode": pip_config.get("constraint_mode", "inherit"),
        "constraints": pip_config.get("constraints", []),
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "files_requested": list(files),
        "files_found": found,
        "effective_line_count": len(effective),
        "removed_names": sorted(removals),
        "added_count": len(additions),
        "fingerprint": fingerprint,
    }


def profiled_install_node(item, custom_dir: Path, log_dir: Path, *, dry_run: bool):
    node_id = item[0]
    requirements = effective_requirements(item, custom_dir)
    started = time.perf_counter()
    _CONTEXT.node_id = node_id
    try:
        result = _ORIGINAL_INSTALL_NODE(item, custom_dir, log_dir, dry_run=dry_run)
    finally:
        _CONTEXT.node_id = ""
    with _LOCK:
        _RUN.setdefault("install", {})[node_id] = {
            "seconds": elapsed(started),
            "requirements": requirements,
        }
    return result


def environment_profile() -> dict[str, Any]:
    result: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "pip_bin": os.environ.get("PIP_BIN", os.environ.get("PIP", "pip")),
        "pip_cache_dir": os.environ.get("PIP_CACHE_DIR", ""),
        "gpu_name": os.environ.get("GPU_NAME", ""),
        "gpu_arch": os.environ.get("GPU_ARCH", ""),
        "torch_channel": os.environ.get("TORCH_CHANNEL", ""),
        "torch_cuda_requested": os.environ.get("TORCH_CUDA", ""),
    }
    try:
        result["torch_version"] = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        result["torch_version"] = ""
    except Exception as error:
        result["torch_probe_error"] = str(error)
    return result


def sum_command_stats(records: list[dict[str, Any]], kinds: set[str]) -> dict[str, Any]:
    selected = [record for record in records if record.get("kind") in kinds]
    return {
        "executed": bool(selected),
        "seconds": round(sum(float(record.get("seconds", 0)) for record in selected), 3),
        "commands": len(selected),
        "returncode": max((int(record.get("returncode", 0)) for record in selected), default=0),
        "using_cached_count": sum(int(record.get("using_cached_count", 0)) for record in selected),
        "download_count": sum(int(record.get("download_count", 0)) for record in selected),
        "download_bytes_observed": sum(
            int(record.get("download_bytes_observed", 0)) for record in selected
        ),
        "wheel_build_count": sum(int(record.get("wheel_build_count", 0)) for record in selected),
        "successfully_built_count": sum(
            int(record.get("successfully_built_count", 0)) for record in selected
        ),
        "successfully_installed_count": sum(
            int(record.get("successfully_installed_count", 0)) for record in selected
        ),
    }


def enrich_report(report: dict[str, Any], *, wall_seconds: float) -> None:
    commands = _RUN.get("commands", {})
    clone_profiles = _RUN.get("clone", {})
    install_profiles = _RUN.get("install", {})
    clone_starts = [value["started"] for value in _RUN.get("clone_windows", {}).values()]
    clone_ends = [value["finished"] for value in _RUN.get("clone_windows", {}).values()]
    install_starts = [value["started"] for value in _RUN.get("install_windows", {}).values()]
    install_ends = [value["finished"] for value in _RUN.get("install_windows", {}).values()]

    report["profile_schema_version"] = 1
    report["run_id"] = _RUN["run_id"]
    report["environment"] = _RUN["environment"]
    report["timing"] = {
        "wall_seconds": round(wall_seconds, 3),
        "clone_phase_seconds": round(max(clone_ends) - min(clone_starts), 3)
        if clone_starts and clone_ends
        else 0.0,
        "clone_work_seconds": round(
            sum(float(value.get("seconds", 0)) for value in clone_profiles.values()), 3
        ),
        "install_phase_seconds": round(max(install_ends) - min(install_starts), 3)
        if install_starts and install_ends
        else 0.0,
    }

    for item in report.get("nodes", []):
        node_id = item.get("id", "")
        node_commands = commands.get(node_id, [])
        clone = clone_profiles.get(node_id, {})
        install = install_profiles.get(node_id, {})
        git_profile = sum_command_stats(node_commands, {"git_clone", "git_fetch", "git_pull", "git_checkout"})
        pip_profile = sum_command_stats(node_commands, {"pip"})
        install_py_profile = sum_command_stats(node_commands, {"install_py"})
        clone_seconds = float(clone.get("seconds", git_profile.get("seconds", 0)) or 0)
        install_seconds = float(install.get("seconds", 0) or 0)
        item["timing"] = {
            "clone_seconds": round(clone_seconds, 3),
            "install_seconds": round(install_seconds, 3),
            "total_seconds": round(clone_seconds + install_seconds, 3),
        }
        item["source_profile"] = {**clone, "git": git_profile}
        item["install_profile"] = {
            "seconds": round(install_seconds, 3),
            "prepare_seconds": round(
                max(0.0, install_seconds - pip_profile["seconds"] - install_py_profile["seconds"]),
                3,
            ),
            "requirements": install.get("requirements", {}),
            "pip": {**pip_profile, "cache_dir": os.environ.get("PIP_CACHE_DIR", "")},
            "install_py": install_py_profile,
            "other_commands": [
                record for record in node_commands if record.get("kind") not in {
                    "git_clone", "git_fetch", "git_pull", "git_checkout", "pip", "install_py"
                }
            ],
        }


def profile_dir(log_dir: Path) -> Path:
    return Path(os.environ.get("CUSTOM_NODE_PROFILE_DIR", str(log_dir / "profiles")))


def persist_profile(report: dict[str, Any], status_path: Path, log_dir: Path) -> Path:
    destination = profile_dir(log_dir)
    destination.mkdir(parents=True, exist_ok=True)
    run_path = destination / f"run-{report['run_id']}.json"
    report["profile_file"] = str(run_path)
    base.write_status(status_path, report)
    base.write_status(run_path, report)
    base.write_status(destination / "latest.json", report)
    with (destination / "history.jsonl").open("a") as handle:
        handle.write(json.dumps(report, separators=(",", ":")) + "\n")

    keep = max(1, int(os.environ.get("CUSTOM_NODE_PROFILE_KEEP_RUNS", "50")))
    old = sorted(destination.glob("run-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in old[keep:]:
        path.unlink(missing_ok=True)
    return run_path


def print_profile_summary(report: dict[str, Any], path: Path) -> None:
    print()
    print(f"Custom-node profile: {path}")
    rows = []
    for item in report.get("nodes", []):
        timing = item.get("timing", {})
        install = item.get("install_profile", {})
        rows.append(
            [
                item.get("id", ""),
                f"{float(timing.get('clone_seconds', 0)):.1f}",
                f"{float(install.get('pip', {}).get('seconds', 0)):.1f}",
                f"{float(install.get('install_py', {}).get('seconds', 0)):.1f}",
                f"{float(timing.get('total_seconds', 0)):.1f}",
                install.get("pip", {}).get("using_cached_count", 0),
                install.get("pip", {}).get("wheel_build_count", 0)
                + install.get("install_py", {}).get("wheel_build_count", 0),
            ]
        )
    base.print_table(["ID", "GIT(s)", "PIP(s)", "INSTALL.PY(s)", "TOTAL(s)", "CACHE", "BUILDS"], rows)
    timing = report.get("timing", {})
    print(
        "Profile summary: "
        f"wall={timing.get('wall_seconds', 0):.1f}s "
        f"clone_phase={timing.get('clone_phase_seconds', 0):.1f}s "
        f"install_phase={timing.get('install_phase_seconds', 0):.1f}s"
    )


def profiled_install(args, manifest: dict) -> int:
    if getattr(args, "plan", False):
        return _ORIGINAL_INSTALL(args, manifest)

    _RUN.clear()
    _RUN.update(
        {
            "run_id": run_id_now(),
            "environment": environment_profile(),
            "commands": {},
            "clone": {},
            "install": {},
            "clone_windows": {},
            "install_windows": {},
        }
    )
    started = time.perf_counter()
    rc = _ORIGINAL_INSTALL(args, manifest)
    wall = elapsed(started)

    log_dir = Path(
        os.environ.get("CUSTOM_LOG_DIR", os.environ.get("COMFY_LOGS", "/workspace/logs") + "/custom_nodes")
    )
    status_path = base.status_file_path(log_dir)
    if not status_path.is_file():
        return rc
    report = json.loads(status_path.read_text())
    enrich_report(report, wall_seconds=wall)
    path = persist_profile(report, status_path, log_dir)
    print_profile_summary(report, path)
    return rc


def clone_with_window(item, custom_dir, log_dir):
    node_id = item[0]
    started = time.perf_counter()
    with _LOCK:
        _RUN.setdefault("clone_windows", {})[node_id] = {"started": started, "finished": started}
    try:
        return profiled_clone_node(item, custom_dir, log_dir)
    finally:
        with _LOCK:
            _RUN["clone_windows"][node_id]["finished"] = time.perf_counter()


def install_with_window(item, custom_dir, log_dir, *, dry_run):
    node_id = item[0]
    started = time.perf_counter()
    with _LOCK:
        _RUN.setdefault("install_windows", {})[node_id] = {"started": started, "finished": started}
    try:
        return profiled_install_node(item, custom_dir, log_dir, dry_run=dry_run)
    finally:
        with _LOCK:
            _RUN["install_windows"][node_id]["finished"] = time.perf_counter()


def print_status_with_profile(report: dict, status_path: Path) -> None:
    _ORIGINAL_PRINT_STATUS(report, status_path)
    if not report.get("profile_schema_version"):
        return
    print_profile_summary(report, Path(report.get("profile_file", status_path)))


base.run_command = profiled_run_command
base.clone_node = clone_with_window
base.install_node = install_with_window
base.install = profiled_install
base.print_status_report = print_status_with_profile


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
