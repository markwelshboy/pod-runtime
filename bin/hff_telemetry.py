#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi


def die(message: str, code: int = 1) -> None:
    print(f"[hff] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def normalize_path(value: str) -> str:
    path = (value or "").strip().replace("\\", "/").lstrip("/")
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip(".-")
    return cleaned[:160] or fallback


def profile_metadata(path: Path) -> tuple[str, str]:
    run_id = ""
    hostname = ""
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if isinstance(payload, dict):
            run_id = str(payload.get("run_id") or "").strip()
            environment = payload.get("environment")
            if isinstance(environment, dict):
                hostname = str(environment.get("hostname") or "").strip()
    return run_id, hostname


def dated_target(path: Path, prefix: str) -> str:
    run_id, profile_host = profile_metadata(path)
    now = datetime.now(timezone.utc)
    if not run_id:
        run_id = now.strftime("%Y%m%dT%H%M%S.%fZ")

    date_match = re.match(r"(\d{4})(\d{2})(\d{2})", run_id)
    if date_match:
        year, month, day = date_match.groups()
    else:
        year, month, day = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")

    hostname = safe_component(profile_host or socket.gethostname(), "unknown-host")
    run_component = safe_component(run_id, now.strftime("%Y%m%dT%H%M%S.%fZ"))
    basename = safe_component(path.name, "telemetry.json")
    root = normalize_path(prefix) or "telemetry/custom_nodes/v1"
    return f"{root}/{year}/{month}/{day}/{hostname}__{run_component}__{basename}"


def make_uri(repo: str, repo_type: str, remote_path: str) -> str:
    prefix = "hf://datasets/" if repo_type == "dataset" else "hf://"
    return f"{prefix}{repo}/{remote_path}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Direct immutable-style telemetry upload to the configured Hugging Face repository"
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--repo",
        default=os.environ.get("HFF_REPO") or os.environ.get("HF_MY_REPO_ID") or "",
        help="destination owner/repo; defaults to HFF_REPO or HF_MY_REPO_ID",
    )
    parser.add_argument(
        "--type",
        dest="repo_type",
        choices=["model", "dataset"],
        default=os.environ.get("HFF_REPO_TYPE") or os.environ.get("HF_MY_REPO_TYPE") or "model",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("HFF_TELEMETRY_PREFIX") or "telemetry/custom_nodes/v1",
        help="repo-relative telemetry prefix",
    )
    parser.add_argument("-m", "--message", default="")
    args = parser.parse_args()

    local = args.file.expanduser()
    if not local.is_file():
        die(f"telemetry: local file not found: {local}")
    repo = (args.repo or "").strip()
    if not repo:
        die("telemetry: destination repo is not configured")
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        die("HF_TOKEN is not set")

    remote_path = dated_target(local, args.prefix)
    try:
        HfApi(token=token).upload_file(
            path_or_fileobj=str(local),
            path_in_repo=remote_path,
            repo_id=repo,
            repo_type=args.repo_type,
            commit_message=args.message or f"telemetry {remote_path}",
        )
    except Exception as error:
        die(f"telemetry: upload failed: {error}")

    print(make_uri(repo, args.repo_type, remote_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
