#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

ENV_SCHEMA_VERSION = 1
BASELINE_PATH = Path(
    os.environ.get(
        "POD_STATE_PROVISION_ENV_BASELINE",
        "/root/.cache/pod-runtime/provision-env.json",
    )
).expanduser()
CURRENT_ENV_PATH = Path(
    os.environ.get(
        "POD_STATE_CURRENT_ENV_FILE",
        "/workspace/.pod-state/env.current",
    )
).expanduser()
CURRENT_ENV_JSON_PATH = CURRENT_ENV_PATH.with_suffix(CURRENT_ENV_PATH.suffix + ".json")

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SENSITIVE_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL|ACCESS_KEY)",
    re.I,
)
SESSION_ENV_NAMES = {
    "_",
    "BASH_ENV",
    "HOSTNAME",
    "OLDPWD",
    "PROMPT_COMMAND",
    "PS1",
    "PS2",
    "PWD",
    "SHLVL",
    "SSH_CLIENT",
    "SSH_CONNECTION",
    "SSH_TTY",
    "TERM",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
}

_pending_overlay: dict[str, Any] | None = None
_installed = False


def _info(message: str) -> None:
    print(f"[pod-state] {message}")


def _warn(message: str) -> None:
    print(f"[pod-state] WARN: {message}", file=sys.stderr)


def _safe_env(environ: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in environ.items():
        name = str(raw_name)
        if not ENV_NAME_RE.match(name):
            continue
        if name in SESSION_ENV_NAMES or name.startswith("SSH_"):
            continue
        if SENSITIVE_ENV_RE.search(name):
            continue
        result[name] = str(raw_value)
    return result


def _pid1_environment() -> dict[str, str]:
    path = Path("/proc/1/environ")
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        try:
            name = key.decode("utf-8")
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            continue
        result[name] = text
    return result


def capture_provision_baseline(
    environ: Mapping[str, str] | None = None,
    *,
    path: Path | None = None,
) -> Path:
    """Persist the safe exported environment immediately after provisioning.

    PID 1 is used as the base so RunPod/container variables that an SSH session
    does not inherit are still represented. The provisioning shell wins for any
    duplicate key because it also contains runtime .env and provision changes.
    """
    target = path or BASELINE_PATH
    merged = _pid1_environment()
    merged.update(dict(os.environ if environ is None else environ))
    payload = {
        "schema_version": ENV_SCHEMA_VERSION,
        "env": _safe_env(merged),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def _load_baseline(path: Path | None = None) -> tuple[dict[str, str], str]:
    target = path or BASELINE_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        env = raw.get("env") if isinstance(raw, dict) else None
        if isinstance(env, dict):
            return _safe_env({str(k): str(v) for k, v in env.items()}), "diff-from-provision"
    except (OSError, json.JSONDecodeError):
        pass

    # Older pods may predate baseline capture. PID 1 still gives us a useful
    # approximation of the original container environment, allowing a RUN_DIR
    # or similar interactive export to be retained immediately.
    return _safe_env(_pid1_environment()), "diff-from-pid1-fallback"


def environment_overlay(
    environ: Mapping[str, str] | None = None,
    *,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    current = _safe_env(os.environ if environ is None else environ)
    baseline, mode = _load_baseline(baseline_path)
    changed = {
        key: value
        for key, value in sorted(current.items())
        if baseline.get(key) != value
    }
    return {
        "schema_version": ENV_SCHEMA_VERSION,
        "mode": mode,
        "set": changed,
    }


def _normalized_overlay(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"schema_version": ENV_SCHEMA_VERSION, "mode": "none", "set": {}}
    values = raw.get("set")
    if not isinstance(values, dict):
        values = {}
    safe = _safe_env({str(k): str(v) for k, v in values.items()})
    return {
        "schema_version": ENV_SCHEMA_VERSION,
        "mode": str(raw.get("mode") or "snapshot"),
        "set": safe,
    }


def _previous_overlay_names(path: Path | None = None) -> set[str]:
    target = path or CURRENT_ENV_JSON_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = raw.get("set") if isinstance(raw, dict) else None
    if not isinstance(values, dict):
        return set()
    return {str(key) for key in values if ENV_NAME_RE.match(str(key))}


def apply_environment_overlay(
    raw: Any,
    *,
    shell_path: Path | None = None,
    json_path: Path | None = None,
) -> dict[str, Any]:
    """Apply one snapshot overlay to this process and future SSH shells."""
    shell_target = shell_path or CURRENT_ENV_PATH
    json_target = json_path or CURRENT_ENV_JSON_PATH
    overlay = _normalized_overlay(raw)
    values: dict[str, str] = overlay["set"]

    for name in _previous_overlay_names(json_target) - set(values):
        os.environ.pop(name, None)
    os.environ.update(values)

    shell_target.parent.mkdir(parents=True, exist_ok=True)
    if values:
        lines = [
            "# Generated by configure-pod from snapshot environment state.",
            "# Safe exported values only; secrets are never stored here.",
        ]
        lines.extend(f"export {name}={shlex.quote(value)}" for name, value in sorted(values.items()))
        shell_target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        json_target.write_text(json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for target in (shell_target, json_target):
            try:
                target.chmod(0o600)
            except OSError:
                pass
    else:
        for target in (shell_target, json_target):
            try:
                target.unlink()
            except FileNotFoundError:
                pass
    return overlay


def clear_environment_overlay() -> None:
    apply_environment_overlay({"set": {}})


def _add_overlay_to_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"snapshot state manifest is not an object: {path}")
    overlay = environment_overlay()
    data["environment"] = overlay
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    count = len(overlay["set"])
    _info(f"environment delta: {count} exported variable(s) captured ({overlay['mode']})")
    return overlay


def install_core_hooks(core: Any) -> None:
    """Extend pod_state snapshot/configure without duplicating its state engine."""
    global _installed
    if _installed:
        return

    original_write_manifest = core.write_state_manifest
    original_find_manifest = core.find_staged_manifest
    original_hydrate = core.hydrate_staging
    original_cmd_snapshot = core.cmd_snapshot
    original_cmd_configure = core.cmd_configure

    def write_state_manifest(template: dict[str, Any], repo_states: list[dict[str, Any]], paths: list[str]) -> Path:
        path = original_write_manifest(template, repo_states, paths)
        _add_overlay_to_manifest(path)
        return path

    def find_staged_manifest(staging: Path, template_name: str) -> Path:
        global _pending_overlay
        path = original_find_manifest(staging, template_name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise core.PodStateError(f"could not read snapshot environment state: {exc}") from exc
        _pending_overlay = _normalized_overlay(data.get("environment") if isinstance(data, dict) else None)
        return path

    def hydrate_staging(staging: Path) -> None:
        original_hydrate(staging)
        overlay = apply_environment_overlay(_pending_overlay)
        _info(f"restored {len(overlay['set'])} exported environment variable(s)")

    def cmd_snapshot(args: Any) -> int:
        if getattr(args, "dry_run", False):
            overlay = environment_overlay()
            _info(
                f"would capture {len(overlay['set'])} exported environment variable(s) "
                f"({overlay['mode']})"
            )
        return original_cmd_snapshot(args)

    def cmd_configure(args: Any) -> int:
        global _pending_overlay
        _pending_overlay = None
        if not getattr(args, "snapshot", "") and not getattr(args, "dry_run", False):
            clear_environment_overlay()
        return original_cmd_configure(args)

    core.write_state_manifest = write_state_manifest
    core.find_staged_manifest = find_staged_manifest
    core.hydrate_staging = hydrate_staging
    core.cmd_snapshot = cmd_snapshot
    core.cmd_configure = cmd_configure
    _installed = True


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values == ["capture-baseline"]:
        path = capture_provision_baseline()
        _info(f"provision environment baseline: {path}")
        return 0
    print("usage: pod_env_state.py capture-baseline", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
