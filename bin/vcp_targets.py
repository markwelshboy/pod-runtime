#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class VcpTargetError(RuntimeError):
    pass


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = environ or os.environ
    return Path(env.get("VCP_CONFIG", "~/.config/vcp/config.json")).expanduser()


def read_config(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    path = config_path(environ)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VcpTargetError(f"could not read config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VcpTargetError(f"invalid config {path}: expected JSON object")
    return value


def write_config(cfg: dict[str, Any], environ: Mapping[str, str] | None = None) -> None:
    path = config_path(environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def validate_target_name(name: str) -> str:
    value = name.strip()
    if not value or not TARGET_RE.fullmatch(value):
        raise VcpTargetError(
            "target names may contain letters, numbers, dot, underscore, and hyphen"
        )
    return value


def targets(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = cfg.get("targets")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise VcpTargetError("invalid VCP config: targets must be an object")
    result: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if isinstance(name, str) and isinstance(value, dict):
            result[name] = value
    return result


def active_target_name(cfg: dict[str, Any]) -> str | None:
    value = cfg.get("active_target")
    return value if isinstance(value, str) and value else None


def target_entry(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    name = validate_target_name(name)
    entry = targets(cfg).get(name)
    if not isinstance(entry, dict):
        raise VcpTargetError(f"unknown VCP target: {name}")
    return entry


def _valid_ssh(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item for item in value
    )


def resolve_ssh(
    cfg: dict[str, Any],
    target: str | None = None,
) -> tuple[list[str], str | None]:
    """Resolve SSH argv and the named target used.

    Compatibility order when no explicit target is supplied:
      1. active_target from the multi-target registry
      2. legacy top-level `ssh`
    """
    selected = validate_target_name(target) if target else active_target_name(cfg)
    if selected:
        entry = target_entry(cfg, selected)
        ssh = entry.get("ssh")
        if not _valid_ssh(ssh):
            raise VcpTargetError(f"VCP target {selected!r} has no valid SSH configuration")
        return list(ssh), selected

    legacy = cfg.get("ssh")
    if _valid_ssh(legacy):
        return list(legacy), None
    raise VcpTargetError(
        "SSH remote is not configured; run 'vcp config NAME ssh ...' or legacy 'vcp config ssh ...'"
    )


def effective_config(cfg: dict[str, Any], target: str | None = None) -> tuple[dict[str, Any], str | None]:
    ssh, selected = resolve_ssh(cfg, target)
    result = dict(cfg)
    result["ssh"] = ssh
    return result, selected


def save_target(
    name: str,
    ssh_args: list[str],
    *,
    pod_id: str | None = None,
    description: str | None = None,
    provider: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    make_active: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    name = validate_target_name(name)
    if not _valid_ssh(ssh_args):
        raise VcpTargetError("SSH arguments must be a non-empty list of strings")

    cfg = read_config(environ)
    raw_targets = cfg.get("targets")
    if raw_targets is None:
        raw_targets = {}
    if not isinstance(raw_targets, dict):
        raise VcpTargetError("invalid VCP config: targets must be an object")

    old = raw_targets.get(name)
    entry: dict[str, Any] = dict(old) if isinstance(old, dict) else {}
    entry["ssh"] = list(ssh_args)
    if pod_id:
        entry["pod_id"] = str(pod_id)
    elif pod_id == "":
        entry.pop("pod_id", None)
    if description:
        entry["description"] = str(description)
    if provider:
        entry["provider"] = str(provider)
    if metadata:
        for key, value in metadata.items():
            if value is not None and value != "":
                entry[str(key)] = value

    raw_targets[name] = entry
    cfg["targets"] = raw_targets
    cfg["version"] = max(int(cfg.get("version") or 1), 2)
    if make_active:
        cfg["active_target"] = name
    write_config(cfg, environ)
    return entry


def set_active_target(
    name: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cfg = read_config(environ)
    name = validate_target_name(name)
    entry = target_entry(cfg, name)
    if not _valid_ssh(entry.get("ssh")):
        raise VcpTargetError(f"VCP target {name!r} has no valid SSH configuration")
    cfg["active_target"] = name
    cfg["version"] = max(int(cfg.get("version") or 1), 2)
    write_config(cfg, environ)
    return entry


def remove_target(name: str, environ: Mapping[str, str] | None = None) -> None:
    cfg = read_config(environ)
    name = validate_target_name(name)
    raw_targets = cfg.get("targets")
    if not isinstance(raw_targets, dict) or name not in raw_targets:
        raise VcpTargetError(f"unknown VCP target: {name}")
    del raw_targets[name]
    if cfg.get("active_target") == name:
        cfg.pop("active_target", None)
    write_config(cfg, environ)


def endpoint_from_ssh(ssh_args: Any) -> str:
    if not _valid_ssh(ssh_args):
        return "-"
    args = list(ssh_args)
    host = args[-1] if args else "-"
    port = None
    for i, arg in enumerate(args[:-1]):
        if arg == "-p" and i + 1 < len(args):
            port = args[i + 1]
    return f"{host}:{port}" if port else host


def rows(cfg: dict[str, Any]) -> list[dict[str, str]]:
    active = active_target_name(cfg)
    result: list[dict[str, str]] = []
    for name, entry in sorted(targets(cfg).items()):
        result.append(
            {
                "name": name,
                "active": "yes" if name == active else "",
                "pod_id": str(entry.get("pod_id") or "-"),
                "provider": str(entry.get("provider") or "-"),
                "endpoint": endpoint_from_ssh(entry.get("ssh")),
                "description": str(entry.get("description") or ""),
            }
        )
    return result
