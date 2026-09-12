#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_state_dir() -> Path:
    return Path(
        os.environ.get("COMFY_WORKSTATION_STATE_DIR", "/workspace/.pod-state/comfy")
    ).expanduser()


def default_comfy_root() -> Path:
    return Path(
        os.environ.get("COMFYUI_ROOT")
        or os.environ.get("COMFY_HOME")
        or "/workspace/ComfyUI"
    ).expanduser()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def append_event(state_dir: Path, event: dict[str, Any]) -> Path:
    state_dir = resolved(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    journal = state_dir / "events.jsonl"
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with journal.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return journal


def acquire(args: argparse.Namespace) -> int:
    destination = resolved(Path(args.destination))
    comfy_root = resolved(args.comfy_root)

    if args.comfy_only and not is_within(destination, comfy_root):
        return 0

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "time": utc_now(),
        "event": "asset_acquired",
        "source": args.source,
        "destination": str(destination),
    }

    optional = {
        "source_tool": args.tool,
        "mode": args.mode,
        "repo": args.repo,
        "repo_type": args.repo_type,
        "remote_path": args.remote_path,
        "remote_request": args.remote_request,
        "revision": args.revision,
        "url": args.url,
        "section": args.section,
    }
    event.update({key: value for key, value in optional.items() if value not in (None, "")})
    if args.bytes is not None:
        event["bytes"] = max(0, args.bytes)

    append_event(args.state_dir, event)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfy-state-event",
        description="Append-only event recorder for portable ComfyUI workstation state",
    )
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument("--comfy-root", type=Path, default=default_comfy_root())

    sub = parser.add_subparsers(dest="command", required=True)
    acquire_parser = sub.add_parser("acquire", help="record a successfully materialized asset")
    acquire_parser.add_argument("--source", required=True)
    acquire_parser.add_argument("--destination", required=True)
    acquire_parser.add_argument("--tool")
    acquire_parser.add_argument("--mode")
    acquire_parser.add_argument("--repo")
    acquire_parser.add_argument("--repo-type")
    acquire_parser.add_argument("--remote-path")
    acquire_parser.add_argument("--remote-request")
    acquire_parser.add_argument("--revision")
    acquire_parser.add_argument("--url")
    acquire_parser.add_argument("--section")
    acquire_parser.add_argument("--bytes", type=int)
    acquire_parser.add_argument(
        "--comfy-only",
        action="store_true",
        help="silently ignore destinations outside the configured ComfyUI root",
    )
    acquire_parser.set_defaults(func=acquire)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"[comfy-state-event] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
