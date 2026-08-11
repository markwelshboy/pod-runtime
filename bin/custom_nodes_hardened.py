#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import copy
import importlib.util
import os
import re
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
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


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


def _git_depth() -> int:
    try:
        return max(0, int(os.environ.get("GIT_DEPTH", "1")))
    except (TypeError, ValueError):
        return 1


def _option_present(options: list[str], name: str) -> bool:
    return any(value == name or value.startswith(name + "=") for value in options)


def _clone_options(node: dict) -> list[str]:
    options = [str(value) for value in node.get("clone_options", [])]
    depth = _git_depth()
    ref = str(node.get("ref") or "").strip()
    sha_ref = bool(ref and _SHA_RE.fullmatch(ref))

    # GIT_DEPTH has always been part of pod-runtime's public configuration, but
    # the manifest installer historically ignored it. Honour it for fresh clones.
    # Explicit clone options win, and raw commit refs stay full-depth because an
    # arbitrary SHA may not be reachable from a depth-1 clone.
    if depth > 0 and not sha_ref and not _option_present(options, "--depth"):
        options = ["--depth", str(depth), *options]

    # A non-SHA ref is a branch/tag. Ask clone for it directly so shallow clones
    # can still resolve manifests that select a non-default branch.
    if ref and not sha_ref and not _option_present(options, "--branch"):
        options.extend(["--branch", ref])

    recursive = any(
        value in {"--recursive", "--recurse-submodules"}
        or value.startswith("--recurse-submodules=")
        for value in options
    )
    if depth > 0 and recursive and "--shallow-submodules" not in options:
        options.append("--shallow-submodules")
    return options


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

    # Apply these to every command, not only top-level git invocations. Pip may
    # spawn git itself for VCS requirements, and those children inherit this
    # environment.
    environment.setdefault("GIT_TERMINAL_PROMPT", "0")
    environment.setdefault("GCM_INTERACTIVE", "never")
    environment.setdefault("PIP_NO_INPUT", "1")

    # Impact Pack pulls facebookresearch/sam2 as a VCS requirement. SAM2's
    # optional CUDA extension is not required for the normal Impact Pack path and
    # can turn a disposable-pod bootstrap into a long native build.
    node_id = getattr(profiled._CONTEXT, "node_id", "")
    if node_id == "comfyui-impact-pack":
        environment.setdefault("SAM2_BUILD_CUDA", "0")

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
    except KeyboardInterrupt:
        _terminate_process_group(process, log)
        raise


def hardened_clone_node(item, custom_dir: Path, log_dir: Path):
    node_id, node = item
    destination = custom_dir / base.local_name(node)
    log_path = log_dir / f"{base.local_name(node)}.log"
    depth = _git_depth()
    with log_path.open("a") as log:
        print(f"\n== clone/update {node_id} at {base.utc_now()} ==", file=log, flush=True)
        options = _clone_options(node)
        if (destination / ".git").exists():
            fetch = ["git", "-C", str(destination), "fetch", "--all", "--prune"]
            if depth > 0:
                fetch.extend(["--depth", str(depth)])
            rc = base.run_command(fetch, log=log)
            if rc == 0:
                rc = base.run_command(["git", "-C", str(destination), "pull", "--ff-only"], log=log)
        elif destination.exists():
            print(f"ERROR: destination exists but is not a git checkout: {destination}", file=log)
            rc = 1
        else:
            rc = base.run_command(
                ["git", "clone", *options, node["remote"], str(destination)],
                log=log,
            )
        if rc == 0 and node.get("ref"):
            rc = base.run_command(
                ["git", "-C", str(destination), "checkout", str(node["ref"])],
                log=log,
            )
        return node_id, rc, base.git_commit(destination) if rc == 0 else ""


def _apply_runtime_policies(manifest: dict) -> dict:
    """Apply safe pod-runtime policies even to image-baked manifests."""
    effective = copy.deepcopy(manifest)
    nodes = effective.get("nodes", {})

    impact = nodes.get("comfyui-impact-pack")
    if isinstance(impact, dict):
        pip_config = impact.setdefault("pip", {})
        options = list(
            pip_config.get("options")
            or effective.get("defaults", {}).get(
                "pip_options", ["--upgrade-strategy", "only-if-needed"]
            )
        )
        if "--no-build-isolation" not in options:
            options.append("--no-build-isolation")
        pip_config["options"] = options

    return effective


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
    manifest = _apply_runtime_policies(manifest)
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
        "git_depth": _git_depth(),
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
        try:
            result_id, rc, commit = base.clone_node(item, custom_dir, log_dir)
        except Exception as error:
            result_id, rc, commit = node_id, 1, ""
            log_path = log_dir / f"{base.local_name(item[1])}.log"
            with log_path.open("a") as log:
                print(f"ERROR: clone task raised: {error}", file=log, flush=True)
        state = by_id[result_id]
        state["clone"] = "ok" if rc == 0 else "failed"
        state["clone_finished_at"] = base.utc_now()
        state["commit"] = commit
        if rc:
            state["install"] = "skipped-clone-failed"
        _write_status(status_path, report)
        return result_id, rc

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


# Keep the profiling layer, but replace the raw command runner, clone implementation,
# and base installation state machine underneath it.
profiled._ORIGINAL_RUN_COMMAND = hardened_raw_run_command
profiled._ORIGINAL_CLONE_NODE = hardened_clone_node
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
