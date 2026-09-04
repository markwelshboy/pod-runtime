#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# OpenSSH options that consume the following argv item when written as a
# separate token. VCP stores only connection arguments plus one destination;
# remote commands are supplied by the transfer engine itself.
SSH_OPTIONS_WITH_VALUE = {
    "-B",
    "-b",
    "-c",
    "-D",
    "-E",
    "-e",
    "-F",
    "-I",
    "-i",
    "-J",
    "-L",
    "-l",
    "-m",
    "-O",
    "-o",
    "-p",
    "-Q",
    "-R",
    "-S",
    "-W",
    "-w",
}


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


def split_ssh_args(ssh_args: Any) -> tuple[list[str], str]:
    """Return (connection options, destination) from stored SSH argv.

    Historically VCP accepted arbitrary SSH argv and some configs therefore
    have the destination first (``root@host -p 123 -i key``). OpenSSH requires
    connection options before the destination when VCP later appends its remote
    command, so parse either spelling and canonicalize to options + destination.
    """
    if not _valid_ssh(ssh_args):
        raise VcpTargetError("SSH arguments must be a non-empty list of strings")

    args = list(ssh_args)
    options: list[str] = []
    destination: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            if i + 1 >= len(args):
                raise VcpTargetError("SSH '--' must be followed by a destination")
            if destination is not None or i + 2 != len(args):
                raise VcpTargetError("VCP SSH configuration must contain exactly one destination")
            destination = args[i + 1]
            i += 2
            continue

        if arg.startswith("-") and arg != "-":
            options.append(arg)
            if arg in SSH_OPTIONS_WITH_VALUE:
                if i + 1 >= len(args):
                    raise VcpTargetError(f"SSH option {arg} requires a value")
                options.append(args[i + 1])
                i += 2
            else:
                # Attached-value forms such as -p2222/-i/path and flag options
                # are already self-contained. Unknown flags remain untouched.
                i += 1
            continue

        if destination is not None:
            raise VcpTargetError(
                "VCP SSH configuration must contain one destination and no remote command"
            )
        destination = arg
        i += 1

    if not destination:
        raise VcpTargetError("SSH configuration has no destination")
    return options, destination


def normalize_ssh_args(ssh_args: Any) -> list[str]:
    options, destination = split_ssh_args(ssh_args)
    return [*options, destination]


def _ssh_port(options: list[str]) -> int | None:
    port: str | None = None
    i = 0
    while i < len(options):
        arg = options[i]
        if arg == "-p" and i + 1 < len(options):
            port = options[i + 1]
            i += 2
            continue
        if arg.startswith("-p") and len(arg) > 2:
            port = arg[2:]
        i += 1
    if port is None:
        return None
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def ssh_endpoint_key(ssh_args: Any) -> tuple[str, int | None] | None:
    """Return a comparison key (host, port), ignoring SSH username."""
    try:
        options, destination = split_ssh_args(ssh_args)
    except VcpTargetError:
        return None
    host = destination.rsplit("@", 1)[-1]
    # Bracketed IPv6 literals are kept comparable without the presentation []
    # when they arrive in the usual user@[addr] form.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.casefold(), _ssh_port(options)


def resolve_ssh(
    cfg: dict[str, Any],
    target: str | None = None,
) -> tuple[list[str], str | None]:
    """Resolve canonical SSH argv and the named target used.

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
        return normalize_ssh_args(ssh), selected

    legacy = cfg.get("ssh")
    if _valid_ssh(legacy):
        return normalize_ssh_args(legacy), None
    raise VcpTargetError(
        "SSH remote is not configured; run 'vcp config NAME ssh ...' or 'vcp config ssh ...'"
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
    normalized_ssh = normalize_ssh_args(ssh_args)

    cfg = read_config(environ)
    raw_targets = cfg.get("targets")
    if raw_targets is None:
        raw_targets = {}
    if not isinstance(raw_targets, dict):
        raise VcpTargetError("invalid VCP config: targets must be an object")

    old = raw_targets.get(name)
    entry: dict[str, Any] = dict(old) if isinstance(old, dict) else {}
    entry["ssh"] = normalized_ssh
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


def save_legacy_ssh(
    ssh_args: list[str],
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    normalized = normalize_ssh_args(ssh_args)
    cfg = read_config(environ)
    cfg["ssh"] = normalized
    write_config(cfg, environ)
    return normalized


def clear_matching_legacy_ssh(
    ssh_args: Any,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Clear the legacy/default SSH fallback when it duplicates an endpoint."""
    wanted = ssh_endpoint_key(ssh_args)
    if wanted is None:
        return False
    cfg = read_config(environ)
    if ssh_endpoint_key(cfg.get("ssh")) != wanted:
        return False
    cfg.pop("ssh", None)
    write_config(cfg, environ)
    return True


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


def remove_matching_targets(
    *,
    pod_id: str | None = None,
    endpoints: Iterable[tuple[str, int | None]] = (),
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Remove VCP references to a deleted Pod.

    Named targets match by saved RunPod pod_id first and by SSH host/port as a
    fallback for manually-created targets. The legacy top-level SSH setting has
    no pod metadata, so it is cleared only on an endpoint match.
    """
    cfg = read_config(environ)
    wanted_pod = str(pod_id or "").strip()
    wanted_endpoints = {
        (str(host).casefold(), int(port) if port is not None else None)
        for host, port in endpoints
        if str(host).strip()
    }
    removed: list[str] = []
    raw_targets = cfg.get("targets")
    changed = False

    if isinstance(raw_targets, dict):
        for name, entry in list(raw_targets.items()):
            if not isinstance(entry, dict):
                continue
            entry_pod = str(entry.get("pod_id") or "").strip()
            endpoint = ssh_endpoint_key(entry.get("ssh"))
            if (wanted_pod and entry_pod == wanted_pod) or (
                wanted_endpoints and endpoint in wanted_endpoints
            ):
                del raw_targets[name]
                removed.append(name)
                changed = True
                if cfg.get("active_target") == name:
                    cfg.pop("active_target", None)

    legacy_cleared = False
    if wanted_endpoints and ssh_endpoint_key(cfg.get("ssh")) in wanted_endpoints:
        cfg.pop("ssh", None)
        legacy_cleared = True
        changed = True

    if changed:
        write_config(cfg, environ)
    return {"targets": removed, "legacy": legacy_cleared}


def endpoint_from_ssh(ssh_args: Any) -> str:
    if not _valid_ssh(ssh_args):
        return "-"
    try:
        options, destination = split_ssh_args(ssh_args)
    except VcpTargetError:
        return "<invalid ssh>"
    port = _ssh_port(options)
    return f"{destination}:{port}" if port is not None else destination


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
