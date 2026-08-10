#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import importlib.util
import os
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

_PROFILED_PATH = Path(__file__).with_name("custom_nodes_profiled.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_profiled", _PROFILED_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load profiled custom-node installer: {_PROFILED_PATH}")
profiled = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(profiled)
base = profiled.base

_STATUS_LOCK = threading.Lock()
_ORIGINAL_STATUS_PRINTER = profiled._ORIGINAL_PRINT_STATUS


def _timeout_seconds(kind: str) -> float | None:
    if kind.startswith("git_") or kind == "git_other":
        raw = os.environ.get("CUSTOM_NODE_GIT_TIMEOUT", "600")
    elif kind == "pip":
        raw = os.environ.get("CUSTOM_NODE_PIP_TIMEOUT", "1800")
    elif kind == "install_py":
        raw = os.environ.get("CUSTOM_NODE_INSTALL_TIMEOUT", "900")
    else:
        raw = os.environ.get("CUSTOM_NODE_COMMAND_TIMEOUT", "0")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else None


def _terminate_process_group(process: subprocess.Popen[Any], log) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(
            f"WARN: process group {process.pid} survived SIGKILL wait",
            file=log or sys.stderr,
            flush=True,
        )


def hardened_raw_run_command(command: list[str], *, cwd=None, env=None, log=None) -> int:
    kind = profiled.classify_command(command)
    timeout = _timeout_seconds(kind)
    environment = env.copy() if env is not None else os.environ.copy()
    if kind.startswith("git_") or kind == "git_other":
        environment.setdefault("GIT_TERMINAL_PROMPT", "0")
        environment.setdefault("GCM_INTERACTIVE", "never")

    print("+", shlex.join(command), file=log or sys.stderr, flush=True)
    if timeout:
        print(
            f"[custom-nodes] timeout={timeout:g}s kind={kind}",
            file=log or sys.stderr,
            flush=True,
        )

    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT if log else None,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: {kind} command timed out after {timeout:g}s; "
            f"terminating process group {process.pid}",
            file=log or sys.stderr,
            flush=True,
        )
        _terminate_process_group(process, log)
        return 124


def recompute_summary(report: dict) -> None:
    ok = failed = running = pending = 0
    for item in report.get("nodes", []):
        clone = item.get("clone", "pending")
        install_state = item.get("install", "pending")
        if clone == "failed" or install_state == "failed":
            failed += 1
        elif clone == "ok" and install_state not in {"pending", "running", "failed"}:
            ok += 1
        elif clone == "running" or install_state == "running":
            running += 1
        else:
            pending += 1
    report["summary"] = {
        "total": len(report.get("nodes", [])),
        "ok": ok,
        "failed": failed,
        "running": running,
        "pending": pending,
    }


def _write_status(status_path: Path, report: dict) -> None:
    with _STATUS_LOCK:
        recompute_summary(report)
        base.write_status(status_path, report)


def hardened_install(args, manifest: dict) -> int:
    requested_sets = args.sets or os.environ.get("CUSTOM_NODE_SETS", "")
    set_names = base.requested_set_names(requested_sets)
    nodes = base.resolve_nodes(manifest, requested_sets)
    custom_dir = Path(
        args.custom_dir
        or os.environ.get(
            "CUSTOM_DIR", os.environ.get("COMFY_HOME", "/workspace/ComfyUI") + "/custom_nodes"
        )
    )
    log_dir = Path(
        os.environ.get(
            "CUSTOM_LOG_DIR", os.environ.get("COMFY_LOGS", "/workspace/logs") + "/custom_nodes"
        )
    )
    custom_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    status_path = base.status_file_path(log_dir)

    base.print_plan(manifest, requested_sets)
    if args.plan:
        return 0

    report = {
        "schema_version": 1,
        "started_at": base.utc_now(),
        "finished_at": None,
        "sets": set_names,
        "dry_run": bool(args.dry_run),
        "custom_dir": str(custom_dir),
        "timeouts": {
            "git_seconds": _timeout_seconds("git_clone") or 0,
            "pip_seconds": _timeout_seconds("pip") or 0,
            "install_py_seconds": _timeout_seconds("install_py") or 0,
        },
        "nodes": [
            {
                "id": node_id,
                "local": base.local_name(node),
                "remote": node["remote"],
                "clone": "pending",
                "install": "pending",
                "commit": "",
                "log": str(log_dir / f"{base.local_name(node)}.log"),
                "clone_started_at": None,
                "clone_finished_at": None,
                "install_started_at": None,
                "install_finished_at": None,
            }
            for node_id, node in nodes
        ],
    }
    by_id = {item["id"]: item for item in report["nodes"]}
    _write_status(status_path, report)

    clone_failures: list[str] = []

    def clone_task(item):
        node_id = item[0]
        state = by_id[node_id]
        state["clone"] = "running"
        state["clone_started_at"] = base.utc_now()
        _write_status(status_path, report)
        node_id, rc, commit = base.clone_node(item, custom_dir, log_dir)
        state = by_id[node_id]
        state["clone"] = "ok" if rc == 0 else "failed"
        state["clone_finished_at"] = base.utc_now()
        state["commit"] = commit
        if rc:
            state["install"] = "skipped-clone-failed"
        _write_status(status_path, report)
        return node_id, rc

    clone_jobs = max(1, int(os.environ.get("MAX_CUSTOM_NODE_JOBS", "8")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=clone_jobs) as executor:
        futures = [executor.submit(clone_task, item) for item in nodes]
        for future in concurrent.futures.as_completed(futures):
            node_id, rc = future.result()
            if rc:
                clone_failures.append(node_id)

    install_failures: list[str] = []
    for item in nodes:
        node_id = item[0]
        state = by_id[node_id]
        if state["clone"] != "ok":
            continue
        state["install"] = "running"
        state["install_started_at"] = base.utc_now()
        _write_status(status_path, report)
        rc, detail = base.install_node(item, custom_dir, log_dir, dry_run=args.dry_run)
        state["install"] = detail if rc == 0 else "failed"
        state["install_finished_at"] = base.utc_now()
        if rc:
            state["detail"] = detail
            install_failures.append(node_id)
        _write_status(status_path, report)

    report["finished_at"] = base.utc_now()
    _write_status(status_path, report)
    print()
    base.print_status_report(report, status_path)

    if clone_failures:
        print("Clone failures: " + ", ".join(clone_failures), file=sys.stderr)
    if install_failures:
        print("Install failures: " + ", ".join(install_failures), file=sys.stderr)
    return 1 if clone_failures or install_failures else 0


def print_status(report: dict, status_path: Path) -> None:
    _ORIGINAL_STATUS_PRINTER(report, status_path)
    summary = report.get("summary", {})
    if "running" in summary:
        print(f"Running now: {summary.get('running', 0)}")


# Keep the profiling layer, but replace the raw command runner and the base
# installation state machine underneath it.
profiled._ORIGINAL_RUN_COMMAND = hardened_raw_run_command
profiled._ORIGINAL_INSTALL = hardened_install
base.recompute_summary = recompute_summary
profiled._ORIGINAL_PRINT_STATUS = print_status


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
