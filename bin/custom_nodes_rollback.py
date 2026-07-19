#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERBOSE = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    quiet: bool = False,
) -> subprocess.CompletedProcess:
    if VERBOSE:
        print("+", " ".join(cmd), file=sys.stderr, flush=True)
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "check": False,
    }
    if capture or quiet:
        kwargs["capture_output"] = True
    return subprocess.run(cmd, **kwargs)


def git_value(path: Path, *args: str) -> str:
    result = run(["git", "-C", str(path), *args], capture=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def package_state(python: str) -> tuple[list[dict[str, Any]], list[str]]:
    listed = run([python, "-m", "pip", "list", "--format=json"], capture=True)
    if listed.returncode:
        raise RuntimeError("pip list failed")
    frozen = run([python, "-m", "pip", "freeze", "--all"], capture=True)
    if frozen.returncode:
        raise RuntimeError("pip freeze failed")
    return json.loads(listed.stdout), [line for line in frozen.stdout.splitlines() if line.strip()]


def classify_dirty(lines: list[str]) -> str:
    if not lines:
        return "clean"
    tracked = any(line[:2].strip() and not line.startswith("??") for line in lines)
    untracked = any(line.startswith("??") for line in lines)
    cache_markers = ("__pycache__", ".pyc", ".pyo", ".cache/", "/cache/", ".DS_Store")
    cache_only = all(any(marker in line for marker in cache_markers) for line in lines)
    if cache_only:
        return "generated/cache only"
    if tracked and untracked:
        return "tracked and untracked changes"
    if tracked:
        return "tracked changes"
    return "untracked files"


def scan_nodes(custom_dir: Path) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if not custom_dir.is_dir():
        return nodes
    for path in sorted(custom_dir.iterdir(), key=lambda p: p.name.casefold()):
        if path.name.startswith(".") or path.name == "__pycache__":
            continue
        item: dict[str, Any] = {"name": path.name, "path": str(path), "kind": "other"}
        if path.is_symlink():
            item.update(kind="symlink", target=os.readlink(path))
        elif (path / ".git").exists():
            status_lines = git_value(path, "status", "--porcelain").splitlines()
            item.update(
                kind="git",
                commit=git_value(path, "rev-parse", "HEAD"),
                branch=git_value(path, "branch", "--show-current"),
                remote=git_value(path, "remote", "get-url", "origin"),
                dirty=bool(status_lines),
                dirty_class=classify_dirty(status_lines),
                dirty_summary=status_lines[:50],
            )
        nodes.append(item)
    return nodes


def print_dirty_summary(dirty: list[dict[str, Any]], *, details: bool) -> None:
    if not dirty:
        return
    print("\nDirty repositories:")
    for item in dirty:
        print(f"  {item['name']:<36} {item.get('dirty_class', 'dirty')}")
        if details:
            for line in item.get("dirty_summary", []):
                print(f"      {line}")


def confirm_dirty(args: argparse.Namespace, dirty: list[dict[str, Any]]) -> None:
    if not dirty:
        return
    print_dirty_summary(dirty, details=args.verbose)
    print(
        "\nWARNING: uncommitted contents are recorded for diagnosis but are not backed up.\n"
        "A rollback will restore these repositories to their recorded commits and discard\n"
        "those local modifications."
    )
    if args.strict_dirty:
        raise RuntimeError("dirty repositories found and --strict-dirty was requested")
    if args.accept_default or args.allow_dirty:
        print("Proceeding with dirty repository snapshot.")
        return
    if not sys.stdin.isatty():
        raise RuntimeError(
            "dirty repositories require confirmation; rerun with --accept-default "
            "or --allow-dirty, or use --strict-dirty to fail explicitly"
        )
    answer = input("Continue and create rollback snapshot? [Y/n]: ").strip().lower()
    if answer not in {"", "y", "yes"}:
        raise RuntimeError("rollback snapshot cancelled")


def create_snapshot(args: argparse.Namespace) -> int:
    global VERBOSE
    VERBOSE = args.verbose
    custom_dir = Path(args.custom_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    print("Creating rollback snapshot...")
    packages, freeze = package_state(args.python)
    print(f"  Python environment .............. OK ({len(packages)} packages)")
    nodes = scan_nodes(custom_dir)
    git_nodes = [item for item in nodes if item.get("kind") == "git"]
    dirty = [item for item in git_nodes if item.get("dirty")]
    print(f"  Custom-node items ............... {len(nodes)}")
    print(f"  Git repositories ................ {len(git_nodes)}")
    print(f"  Clean repositories .............. {len(git_nodes) - len(dirty)}")
    print(f"  Dirty repositories .............. {len(dirty)}")

    confirm_dirty(args, dirty)

    report = {
        "schema_version": 2,
        "type": "custom-node-rollback",
        "created_at": now(),
        "python": args.python,
        "custom_dir": str(custom_dir),
        "packages": packages,
        "pip_freeze": freeze,
        "custom_nodes": nodes,
        "summary": {
            "package_count": len(packages),
            "custom_node_count": len(nodes),
            "git_repository_count": len(git_nodes),
            "clean_repository_count": len(git_nodes) - len(dirty),
            "dirty_repository_count": len(dirty),
        },
        "rollback_policy": {
            "dirty_repositories_reset_to_recorded_commit": True,
            "new_custom_node_directories_removed": True,
            "new_python_packages_removed": True,
        },
        "limitations": [
            "Dirty/uncommitted repository contents are not backed up.",
            "Arbitrary install.py changes outside custom_dir and the Python environment are not reversible.",
            "Downloaded models and caches outside custom_dir are not removed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(output)
    print(f"  Rollback file ................... {output}")
    print("Rollback snapshot created successfully.")
    return 0


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def restore_nodes(snapshot: dict, *, keep_added: bool, preserve_dirty: bool) -> list[str]:
    custom_dir = Path(snapshot["custom_dir"])
    expected = {item["name"]: item for item in snapshot.get("custom_nodes", [])}
    errors: list[str] = []
    custom_dir.mkdir(parents=True, exist_ok=True)

    if not keep_added:
        for path in custom_dir.iterdir():
            if path.name.startswith(".") or path.name == "__pycache__":
                continue
            if path.name not in expected:
                print(f"  Removing added custom node ...... {path.name}")
                remove_path(path)

    for name, item in expected.items():
        path = custom_dir / name
        kind = item.get("kind")
        if kind == "git":
            if not (path / ".git").exists():
                remote = item.get("remote")
                if not remote:
                    errors.append(f"{name}: missing checkout and no remote recorded")
                    continue
                if run(["git", "clone", remote, str(path)], quiet=not VERBOSE).returncode:
                    errors.append(f"{name}: clone failed")
                    continue
            dirty_now = bool(git_value(path, "status", "--porcelain"))
            if dirty_now and preserve_dirty:
                errors.append(f"{name}: checkout is dirty and --preserve-dirty was requested")
                continue
            commit = item.get("commit")
            if not commit:
                errors.append(f"{name}: no commit recorded")
                continue
            run(["git", "-C", str(path), "fetch", "--all", "--tags", "--prune"], quiet=not VERBOSE)
            if run(["git", "-C", str(path), "reset", "--hard", commit], quiet=not VERBOSE).returncode:
                errors.append(f"{name}: reset to {commit} failed")
                continue
            # Remove files introduced after the snapshot while preserving ignored caches.
            run(["git", "-C", str(path), "clean", "-fd"], quiet=not VERBOSE)
        elif kind == "symlink":
            target = item.get("target")
            if not target:
                continue
            if path.exists() or path.is_symlink():
                remove_path(path)
            path.symlink_to(target)
        elif not path.exists():
            errors.append(f"{name}: prior non-git item is missing and cannot be reconstructed")
    return errors


def restore_packages(snapshot: dict, python: str) -> list[str]:
    errors: list[str] = []
    freeze = snapshot.get("pip_freeze", [])
    print("  Restoring Python packages .......", end=" ", flush=True)
    with tempfile.TemporaryDirectory(prefix="custom-node-rollback-") as temp:
        req = Path(temp) / "requirements.txt"
        req.write_text("\n".join(freeze) + "\n")
        rc = run(
            [python, "-m", "pip", "install", "--upgrade-strategy", "only-if-needed", "-r", str(req)],
            quiet=not VERBOSE,
        ).returncode
        if rc:
            print("FAILED")
            errors.append("restoring frozen Python requirements failed")
        else:
            print("OK")

    current, _ = package_state(python)
    wanted = {str(item["name"]).lower().replace("_", "-") for item in snapshot.get("packages", [])}
    extras = [
        str(item["name"])
        for item in current
        if str(item["name"]).lower().replace("_", "-") not in wanted
    ]
    if extras:
        print(f"  Removing introduced packages .... {len(extras)}")
        if run([python, "-m", "pip", "uninstall", "-y", *extras], quiet=not VERBOSE).returncode:
            errors.append("uninstalling newly introduced Python packages failed")
    else:
        print("  Introduced Python packages ...... 0")
    return errors


def perform_rollback(args: argparse.Namespace) -> int:
    global VERBOSE
    VERBOSE = args.verbose
    path = Path(args.snapshot).expanduser().resolve()
    data = json.loads(path.read_text())
    if data.get("type") != "custom-node-rollback" or data.get("schema_version") not in {1, 2}:
        raise RuntimeError("unsupported rollback manifest")
    python = args.python or data.get("python") or sys.executable
    print(f"Rollback snapshot : {path}")
    print(f"Snapshot created  : {data.get('created_at', '-')}")
    print(f"Custom-node root  : {data.get('custom_dir', '-')}")
    print(f"Python executable : {python}")
    print("\nRestoring custom-node state...")

    errors = restore_nodes(
        data,
        keep_added=args.keep_added_nodes,
        preserve_dirty=args.preserve_dirty,
    )
    errors.extend(restore_packages(data, python))
    print("  Running pip check ...............", end=" ", flush=True)
    check = run([python, "-m", "pip", "check"], quiet=not VERBOSE)
    if check.returncode:
        print("WARN")
        if check.stdout:
            print(check.stdout.rstrip())
        if check.stderr:
            print(check.stderr.rstrip())
        errors.append("pip check reports dependency problems after rollback")
    else:
        print("OK")

    if errors:
        print("\nRollback completed with errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("\nRollback completed successfully.")
    print("Restart ComfyUI before testing the restored environment.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot and restore custom-node/Python state")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--output", required=True)
    create.add_argument("--custom-dir", required=True)
    create.add_argument("--python", required=True)
    create.add_argument("--allow-dirty", action="store_true", help="proceed without prompting")
    create.add_argument("--accept-default", action="store_true", help="accept dirty snapshot warning")
    create.add_argument("--strict-dirty", action="store_true", help="abort if any repository is dirty")
    create.add_argument("--verbose", action="store_true")

    restore = sub.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--python")
    restore.add_argument("--keep-added-nodes", action="store_true")
    restore.add_argument("--preserve-dirty", action="store_true", help="refuse to reset currently dirty checkouts")
    restore.add_argument("--force-dirty", action="store_true", help=argparse.SUPPRESS)
    restore.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    if args.command == "create":
        return create_snapshot(args)
    return perform_rollback(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"custom-node rollback: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
