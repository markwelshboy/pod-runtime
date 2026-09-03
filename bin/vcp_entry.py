#!/usr/bin/env python3
from __future__ import annotations

import shlex
import sys
from typing import Sequence

import vcp
import vcp_targets


def _die(message: str, code: int = 1) -> int:
    print(f"[vcp] ERROR: {message}", file=sys.stderr)
    return code


def _extract_target(argv: list[str]) -> tuple[list[str], str | None]:
    forwarded: list[str] = []
    selected: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--target":
            if selected is not None:
                raise vcp_targets.VcpTargetError("--target may only be specified once")
            if i + 1 >= len(argv):
                raise vcp_targets.VcpTargetError("--target requires a target name")
            selected = vcp_targets.validate_target_name(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--target="):
            if selected is not None:
                raise vcp_targets.VcpTargetError("--target may only be specified once")
            selected = vcp_targets.validate_target_name(arg.split("=", 1)[1])
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, selected


def _show_targets() -> int:
    cfg = vcp_targets.read_config()
    rows = vcp_targets.rows(cfg)
    active = vcp_targets.active_target_name(cfg)
    legacy = cfg.get("ssh")
    print(f"config:        {vcp_targets.config_path()}")
    print(f"active target: {active or '<legacy/default>' if legacy else active or '<none>'}")
    if not rows:
        print("targets:       <none>")
        if isinstance(legacy, list) and legacy:
            print(f"legacy ssh:    {shlex.join(legacy)}")
        return 0
    print()
    print(f"{'NAME':<24} {'ACTIVE':<7} {'POD ID':<20} {'PROVIDER':<10} {'ENDPOINT':<34} DESCRIPTION")
    print("-" * 116)
    for row in rows:
        print(
            f"{row['name']:<24.24} {row['active']:<7.7} {row['pod_id']:<20.20} "
            f"{row['provider']:<10.10} {row['endpoint']:<34.34} {row['description']}"
        )
    return 0


def _target_command(argv: list[str]) -> int:
    if len(argv) == 1:
        cfg = vcp_targets.read_config()
        active = vcp_targets.active_target_name(cfg)
        if active:
            print(active)
            return 0
        if isinstance(cfg.get("ssh"), list) and cfg.get("ssh"):
            print("<legacy/default>")
            return 0
        print("<none>")
        return 0
    if len(argv) != 2:
        raise vcp_targets.VcpTargetError("usage: vcp target [NAME]")
    name = vcp_targets.validate_target_name(argv[1])
    entry = vcp_targets.set_active_target(name)
    print(f"[vcp] Active target: {name} ({vcp_targets.endpoint_from_ssh(entry.get('ssh'))})")
    return 0


def _named_config(argv: list[str]) -> int | None:
    # vcp config NAME ssh [ssh args...]
    # vcp config NAME show
    # vcp config NAME remove
    if len(argv) < 2 or argv[0] != "config":
        return None
    if argv[1] in {"ssh", "show", "list", "hf-repo", "repo", "clear"}:
        return None
    name = vcp_targets.validate_target_name(argv[1])
    if len(argv) < 3:
        raise vcp_targets.VcpTargetError(
            "usage: vcp config NAME ssh [ssh options] user@host"
        )
    action = argv[2]
    if action == "ssh":
        ssh_args = list(argv[3:])
        if ssh_args and ssh_args[0] == "--":
            ssh_args = ssh_args[1:]
        if not ssh_args:
            raise vcp_targets.VcpTargetError(
                "usage: vcp config NAME ssh [ssh options] user@host"
            )
        vcp_targets.save_target(name, ssh_args)
        print(f"saved SSH target {name}: {shlex.join(ssh_args)}")
        return 0
    if action in {"show", "list"} and len(argv) == 3:
        cfg = vcp_targets.read_config()
        entry = vcp_targets.target_entry(cfg, name)
        marker = " (active)" if vcp_targets.active_target_name(cfg) == name else ""
        print(f"target:       {name}{marker}")
        print(f"ssh:          {shlex.join(entry.get('ssh') or []) if entry.get('ssh') else '<not configured>'}")
        print(f"pod id:       {entry.get('pod_id') or '-'}")
        print(f"provider:     {entry.get('provider') or '-'}")
        print(f"description:  {entry.get('description') or '-'}")
        return 0
    if action in {"remove", "delete", "rm"} and len(argv) == 3:
        vcp_targets.remove_target(name)
        print(f"removed VCP target: {name}")
        return 0
    raise vcp_targets.VcpTargetError(f"unknown target config action: {action}")


def _call_vcp(argv: list[str], selected: str | None) -> int:
    cfg = vcp_targets.read_config()
    # Config mutations keep using vcp.py's legacy implementation unless this
    # entrypoint handled them above. For transfers/show, expose the selected
    # target as the top-level `ssh` field expected by the existing engine.
    needs_remote = not argv or argv[0] not in {"config"}
    original_read = vcp._read_config
    if needs_remote:
        effective, _used = vcp_targets.effective_config(cfg, selected)
        vcp._read_config = lambda: dict(effective)
    elif selected is not None:
        raise vcp_targets.VcpTargetError("--target is not valid with legacy vcp config commands")
    try:
        result = vcp.main(argv)
        return int(result or 0)
    finally:
        vcp._read_config = original_read


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] in {"targets", "list-targets"}:
            if len(args) != 1:
                raise vcp_targets.VcpTargetError("usage: vcp targets")
            return _show_targets()
        if args and args[0] == "target":
            return _target_command(args)

        named = _named_config(args)
        if named is not None:
            return named

        forwarded, selected = _extract_target(args)
        if forwarded[:2] in (["config", "show"], ["config", "list"]):
            _show_targets()
            print()
            # Also retain the established config output for HF scratch settings.
            cfg = vcp_targets.read_config()
            try:
                effective, _used = vcp_targets.effective_config(cfg, selected)
            except vcp_targets.VcpTargetError:
                effective = cfg
            original_read = vcp._read_config
            vcp._read_config = lambda: dict(effective)
            try:
                vcp._config_command(["show"])
            finally:
                vcp._read_config = original_read
            return 0
        return _call_vcp(forwarded, selected)
    except vcp_targets.VcpTargetError as exc:
        return _die(str(exc))
    except vcp.VcpError as exc:
        return _die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
