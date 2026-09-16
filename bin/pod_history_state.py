#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SOURCE_HISTORY_PATH = Path(
    os.environ.get("POD_STATE_BASH_HISTORY", str(Path.home() / ".bash_history"))
).expanduser()
RESTORE_HISTORY_PATH = Path(
    os.environ.get("POD_STATE_RESTORE_BASH_HISTORY", str(Path.home() / ".bash_history"))
).expanduser()

SENSITIVE_HISTORY_RE = re.compile(
    r"(?:"
    r"(?:^|[\s;])(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*"
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL|ACCESS_KEY)"
    r"[A-Za-z0-9_]*\s*="
    r"|--(?:token|password|passwd|api-key|secret|credential|access-key)(?:=|\s)"
    r"|authorization\s*:"
    r")",
    re.IGNORECASE,
)
REDACTED_LINE = "# [pod-state redacted sensitive history line]"

_installed = False
_pending_template: str | None = None


def _info(message: str) -> None:
    print(f"[pod-state] {message}")


def _warn(message: str) -> None:
    print(f"[pod-state] WARN: {message}", file=sys.stderr)


def history_state_path(template_name: str) -> Path:
    return Path("/workspace/.pod-state") / template_name / "bash_history"


def redact_history_text(text: str) -> tuple[str, int]:
    """Return shell history with obvious credential-bearing lines removed."""
    out: list[str] = []
    redacted = 0
    for line in text.splitlines():
        if SENSITIVE_HISTORY_RE.search(line):
            out.append(REDACTED_LINE)
            redacted += 1
        else:
            out.append(line)
    rendered = "\n".join(out)
    if text.endswith("\n") or rendered:
        rendered += "\n"
    return rendered, redacted


def capture_history(template_name: str, *, source: Path | None = None) -> Path | None:
    src = source or SOURCE_HISTORY_PATH
    target = history_state_path(template_name)
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        _warn(f"shell history not found; skipping: {src}")
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return None
    except OSError as exc:
        _warn(f"could not read shell history {src}: {exc}")
        return None

    safe_text, redacted = redact_history_text(text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(safe_text, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass

    lines = len(safe_text.splitlines())
    suffix = f", {redacted} sensitive line(s) redacted" if redacted else ""
    _info(f"shell history: captured {lines} line(s){suffix}")
    return target


def restore_history(template_name: str, *, destination: Path | None = None) -> bool:
    source = history_state_path(template_name)
    target = destination or RESTORE_HISTORY_PATH
    if not source.is_file():
        _info("shell history: snapshot has no saved history")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    _info(f"shell history: restored to {target}")
    return True


def _append_history_snapshot_path(template: dict[str, Any]) -> dict[str, Any]:
    name = str(template.get("name") or "").strip()
    if not name:
        return template
    path = history_state_path(name)
    if not path.is_file():
        return template

    snapshot = template.get("snapshot")
    if not isinstance(snapshot, dict):
        return template
    paths = snapshot.get("paths")
    if not isinstance(paths, list):
        return template

    rendered = str(path)
    if rendered not in paths:
        paths.append(rendered)
    return template


def install_core_hooks(core: Any) -> None:
    """Capture sanitized Bash history into snapshots and restore it on hydrate."""
    global _installed
    if _installed:
        return

    original_load_template = core.load_template
    original_find_manifest = core.find_staged_manifest
    original_hydrate = core.hydrate_staging
    original_cmd_snapshot = core.cmd_snapshot

    def load_template(name_or_path: str) -> dict[str, Any]:
        return _append_history_snapshot_path(original_load_template(name_or_path))

    def find_staged_manifest(staging: Path, template_name: str) -> Path:
        global _pending_template
        path = original_find_manifest(staging, template_name)
        _pending_template = template_name
        return path

    def hydrate_staging(staging: Path) -> None:
        original_hydrate(staging)
        if _pending_template:
            restore_history(_pending_template)

    def cmd_snapshot(args: Any) -> int:
        if not getattr(args, "dry_run", False):
            template = original_load_template(args.template)
            capture_history(str(template["name"]))
        else:
            _info("would capture sanitized shell history")
        return original_cmd_snapshot(args)

    core.load_template = load_template
    core.find_staged_manifest = find_staged_manifest
    core.hydrate_staging = hydrate_staging
    core.cmd_snapshot = cmd_snapshot
    _installed = True


if __name__ == "__main__":
    print("pod_history_state.py is loaded by snapshot-pod/configure-pod", file=sys.stderr)
    raise SystemExit(2)
