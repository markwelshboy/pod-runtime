#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), file=sys.stderr, flush=True)
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, check=False)


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
            status = git_value(path, "status", "--porcelain")
            item.update(
                kind="git",
                commit=git_value(path, "rev-parse", "HEAD"),
                branch=git_value(path, "branch", "--show-current"),
                remote=git_value(path, "remote", "get-url", "origin"),
                dirty=bool(status),
                dirty_summary=status.splitlines()[:20],
            )
        nodes.append(item)
    return nodes


def create_snapshot(args: argparse.Namespace) -> int:
    custom_dir = Path(args.custom_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    packages, freeze = package_state(args.python)
    nodes = scan_nodes(custom_dir)
    dirty = [item["name"] for item in nodes if item.get("dirty")]
    if dirty and not args.allow_dirty:
        raise RuntimeError(
            "dirty git custom nodes cannot be reproduced from a manifest: "
            + ", ".join(dirty)
            + ". Commit/stash them or use --allow-dirty."
        )
    report = {
        "schema_version": 1,
        "type": "custom-node-rollback",
        "created_at": now(),
        "python": args.python,
        "custom_dir": str(custom_dir),
        "packages": packages,
        "pip_freeze": freeze,
        "custom_nodes": nodes,
        "limitations": [
            "Dirty/uncommitted repository contents are not backed up.",
            "Arbitrary install.py changes outside custom_dir and the Python environment are not reversible.",
            "Downloaded models and caches are not removed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(output)
    print(f"Rollback snapshot: {output}")
    print(f"Python packages  : {len(packages)}")
    print(f"Custom-node items: {len(nodes)}")
    if dirty:
        print("WARNING: dirty repositories recorded but their uncommitted content is not backed up:")
        for name in dirty:
            print(f"  - {name}")
    return 0


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def restore_nodes(snapshot: dict, *, keep_added: bool, force_dirty: bool) -> list[str]:
    custom_dir = Path(snapshot["custom_dir"])
    expected = {item["name"]: item for item in snapshot.get("custom_nodes", [])}
    errors: list[str] = []
    custom_dir.mkdir(parents=True, exist_ok=True)

    if not keep_added:
        for path in custom_dir.iterdir():
            if path.name.startswith(".") or path.name == "__pycache__":
                continue
            if path.name not in expected:
                print(f"Removing added custom node: {path}")
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
                rc = run(["git", "clone", remote, str(path)]).returncode
                if rc:
                    errors.append(f"{name}: clone failed")
                    continue
            dirty_now = bool(git_value(path, "status", "--porcelain"))
            if dirty_now and not force_dirty:
                errors.append(f"{name}: checkout is dirty; rerun with --force-dirty")
                continue
            commit = item.get("commit")
            if not commit:
                errors.append(f"{name}: no commit recorded")
                continue
            run(["git", "-C", str(path), "fetch", "--all", "--tags", "--prune"])
            if run(["git", "-C", str(path), "reset", "--hard", commit]).returncode:
                errors.append(f"{name}: reset to {commit} failed")
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
    with __import__("tempfile").TemporaryDirectory(prefix="custom-node-rollback-") as temp:
        req = Path(temp) / "requirements.txt"
        req.write_text("\n".join(freeze) + "\n")
        if run([python, "-m", "pip", "install", "--upgrade-strategy", "only-if-needed", "-r", str(req)]).returncode:
            errors.append("restoring frozen Python requirements failed")

    current, _ = package_state(python)
    wanted = {str(item["name"]).lower().replace("_", "-") for item in snapshot.get("packages", [])}
    extras = [
        str(item["name"])
        for item in current
        if str(item["name"]).lower().replace("_", "-") not in wanted
    ]
    if extras:
        print("Removing packages introduced after snapshot:")
        for name in extras:
            print(f"  - {name}")
        if run([python, "-m", "pip", "uninstall", "-y", *extras]).returncode:
            errors.append("uninstalling newly introduced Python packages failed")
    return errors


def perform_rollback(args: argparse.Namespace) -> int:
    path = Path(args.snapshot).expanduser().resolve()
    data = json.loads(path.read_text())
    if data.get("type") != "custom-node-rollback" or data.get("schema_version") != 1:
        raise RuntimeError("unsupported rollback manifest")
    python = args.python or data.get("python") or sys.executable
    print(f"Rollback snapshot : {path}")
    print(f"Snapshot created  : {data.get('created_at', '-')}")
    print(f"Custom-node root  : {data.get('custom_dir', '-')}")
    print(f"Python executable : {python}")

    errors = restore_nodes(data, keep_added=args.keep_added_nodes, force_dirty=args.force_dirty)
    errors.extend(restore_packages(data, python))
    check = run([python, "-m", "pip", "check"])
    if check.returncode:
        errors.append("pip check reports dependency problems after rollback")

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
    create.add_argument("--allow-dirty", action="store_true")

    restore = sub.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--python")
    restore.add_argument("--keep-added-nodes", action="store_true")
    restore.add_argument("--force-dirty", action="store_true")

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
