#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from typing import Any, Sequence

import rent_pod as rent_pod_core
import rent_pod_lifecycle
import vcp
import vcp_targets


RUNPOD_ID_MARKER = "__VCP_RUNPOD_POD_ID__="


def _die(message: str, code: int = 1) -> int:
    print(f"[vcp] ERROR: {message}", file=sys.stderr)
    return code


def _usage() -> str:
    base = vcp._usage().rstrip()
    return (
        base
        + "\n\nNamed targets:\n"
        + "  vcp targets\n"
        + "  vcp target [NAME]\n"
        + "  vcp target remove NAME\n"
        + "  vcp config ssh [ssh options] user@host   # discovers/creates a named RunPod target\n"
        + "  vcp config NAME ssh [ssh options] user@host\n"
        + "  vcp config NAME show\n"
        + "  vcp config NAME remove\n"
        + "  vcp config prune-legacy\n"
        + "  vcp --target NAME <source...> <destination>\n"
    )


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

    print(f"config:         {vcp_targets.config_path()}")
    print(f"active target:  {active or '<none>'}")

    if not rows:
        print("targets:        <none>")
        return 0

    print()
    print(
        f"{'NAME':<32} {'ACTIVE':<7} {'POD ID':<20} {'PROVIDER':<10} "
        f"{'ENDPOINT':<36} DESCRIPTION"
    )
    print("-" * 128)
    for row in rows:
        print(
            f"{row['name']:<32.32} {row['active']:<7.7} {row['pod_id']:<20.20} "
            f"{row['provider']:<10.10} {row['endpoint']:<36.36} {row['description']}"
        )
    return 0


def _target_command(argv: list[str]) -> int:
    if len(argv) == 1:
        active = vcp_targets.active_target_name(vcp_targets.read_config())
        print(active or "<none>")
        return 0

    if len(argv) == 3 and argv[1] in {"remove", "delete", "rm"}:
        name = vcp_targets.validate_target_name(argv[2])
        cfg = vcp_targets.read_config()
        was_active = vcp_targets.active_target_name(cfg) == name
        vcp_targets.remove_target(name)
        suffix = " (was active; active target cleared)" if was_active else ""
        print(f"[vcp] Removed target: {name}{suffix}")
        return 0

    if len(argv) != 2:
        raise vcp_targets.VcpTargetError(
            "usage: vcp target [NAME] | vcp target remove NAME"
        )
    name = vcp_targets.validate_target_name(argv[1])
    entry = vcp_targets.set_active_target(name)
    print(f"[vcp] Active target: {name} ({vcp_targets.endpoint_from_ssh(entry.get('ssh'))})")
    return 0


def _ssh_config_args(argv: list[str], start: int, usage: str) -> list[str]:
    ssh_args = list(argv[start:])
    if ssh_args and ssh_args[0] == "--":
        ssh_args = ssh_args[1:]
    if not ssh_args:
        raise vcp_targets.VcpTargetError(usage)
    return ssh_args


def _discover_runpod_from_api(ssh_args: list[str]) -> dict[str, str] | None:
    """Match an SSH endpoint to one of the caller's live RunPod Pods.

    Direct REST-created Pods do not reliably receive RunPod's documented
    RUNPOD_* environment variables. The local controller already has a stronger
    source of truth: the RunPod account API plus the same live GraphQL runtime
    port mapping used by rent-pod itself. Match public IP + SSH port exactly.
    """
    api_key = os.environ.get("RUNPOD_API_KEY")
    endpoint = vcp_targets.ssh_endpoint_key(ssh_args)
    if not api_key or endpoint is None or endpoint[1] is None:
        return None
    wanted_host, wanted_port = endpoint

    try:
        pods = rent_pod_core.api_request(api_key, "GET", "/pods")
    except rent_pod_core.RunPodError:
        return None
    if not isinstance(pods, list):
        return None
    rest_pods = [pod for pod in pods if isinstance(pod, dict) and pod.get("id")]

    gql_by_id: dict[str, dict[str, Any]] = {}
    try:
        gql_by_id = {
            str(pod.get("id")): pod
            for pod in rent_pod_lifecycle.graphql_pods(api_key)
            if isinstance(pod, dict) and pod.get("id")
        }
    except rent_pod_core.RunPodError:
        pass

    def match(rest_pod: dict[str, Any]) -> dict[str, str] | None:
        pod_id = str(rest_pod.get("id") or "").strip()
        if not pod_id:
            return None
        snapshot = rent_pod_lifecycle.build_snapshot(
            rest_pod,
            gql_by_id.get(pod_id),
        )
        host = str(snapshot.get("public_ip") or "").strip().casefold()
        port = snapshot.get("ssh_port")
        try:
            port_int = int(port) if port is not None else None
        except (TypeError, ValueError):
            port_int = None
        if host != wanted_host or port_int != wanted_port:
            return None
        name = str(rest_pod.get("name") or "").strip()
        return {"pod_id": pod_id, "name": name}

    matches = [found for pod in rest_pods if (found := match(pod)) is not None]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None

    # REST list metadata can lag or omit connection details. If the account-wide
    # live snapshot did not find a unique match, enrich each Pod once and retry.
    enriched_matches: list[dict[str, str]] = []
    for pod in rest_pods:
        pod_id = str(pod.get("id") or "").strip()
        try:
            detailed = rent_pod_core.get_pod(api_key, pod_id)
        except rent_pod_core.RunPodError:
            continue
        found = match(detailed)
        if found is not None:
            enriched_matches.append(found)
    return enriched_matches[0] if len(enriched_matches) == 1 else None


def _discover_runpod_pod_id(ssh_args: list[str]) -> str | None:
    """Fallback: probe a reachable SSH target for RunPod's injected Pod ID."""
    try:
        options, destination = vcp_targets.split_ssh_args(ssh_args)
    except vcp_targets.VcpTargetError:
        return None

    script = f"""
source_if_exists() {{
  if [[ -f \"$1\" ]]; then
    source \"$1\" >/dev/null 2>&1 || true
  fi
}}
source_if_exists /etc/rp_environment
source_if_exists /root/.secrets/env.current
printf '{RUNPOD_ID_MARKER}%s\\n' \"${{RUNPOD_POD_ID:-}}\"
"""
    cmd = [
        "ssh",
        *options,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
        destination,
        "bash",
        "-s",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        if line.startswith(RUNPOD_ID_MARKER):
            pod_id = line[len(RUNPOD_ID_MARKER) :].strip()
            return pod_id or None
    return None


def _runpod_name_for_id(pod_id: str) -> str | None:
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        return None
    try:
        pod = rent_pod_core.get_pod(api_key, pod_id)
    except rent_pod_core.RunPodError:
        return None
    name = str(pod.get("name") or "").strip()
    return name or None


def _safe_discovered_target_name(label: str | None, pod_id: str) -> str:
    candidate = str(label or pod_id).strip()
    try:
        return vcp_targets.validate_target_name(candidate)
    except vcp_targets.VcpTargetError:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip("-._")
        if slug:
            try:
                return vcp_targets.validate_target_name(slug)
            except vcp_targets.VcpTargetError:
                pass
        return vcp_targets.validate_target_name(pod_id)


def _default_ssh_config(argv: list[str]) -> int | None:
    """Handle bare `vcp config ssh ...` by discovering a named RunPod target.

    Discovery order:
      1. Match the supplied public SSH endpoint against the caller's RunPod API.
      2. Fall back to RUNPOD_POD_ID discovered over SSH for GUI/template Pods.
      3. If neither identifies the remote, require the caller to provide a name.
    """
    if len(argv) < 2 or argv[:2] != ["config", "ssh"]:
        return None
    ssh_args = _ssh_config_args(
        argv,
        2,
        "usage: vcp config ssh [ssh options] user@host",
    )
    normalized = vcp_targets.normalize_ssh_args(ssh_args)

    api_match = _discover_runpod_from_api(normalized)
    discovery = "api"
    if api_match is not None:
        pod_id = api_match["pod_id"]
        runpod_name = api_match.get("name") or None
    else:
        discovery = "ssh"
        pod_id = _discover_runpod_pod_id(normalized)
        runpod_name = _runpod_name_for_id(pod_id) if pod_id else None

    if not pod_id:
        endpoint = vcp_targets.endpoint_from_ssh(normalized)
        raise vcp_targets.VcpTargetError(
            f"could not identify {endpoint} as a RunPod Pod; persistent unnamed/default "
            "SSH mappings are no longer supported. Give it a name, for example: "
            f"vcp config my-target ssh {shlex.join(normalized)}"
        )

    target = _safe_discovered_target_name(runpod_name, pod_id)
    metadata = {"runpod_name": runpod_name} if runpod_name else None
    description = (
        "RunPod pod (matched from SSH endpoint)"
        if discovery == "api"
        else "RunPod pod (discovered via SSH)"
    )
    had_legacy = "ssh" in vcp_targets.read_config()
    entry = vcp_targets.save_target(
        target,
        normalized,
        pod_id=pod_id,
        provider="runpod",
        description=description,
        metadata=metadata,
        make_active=True,
    )
    if runpod_name:
        if discovery == "api":
            print(
                f"[vcp] Matched RunPod target {target} (pod {pod_id}) "
                "from SSH endpoint."
            )
        else:
            print(f"[vcp] Discovered RunPod target {target} (pod {pod_id}) via SSH.")
    else:
        print(
            f"[vcp] Identified RunPod pod {pod_id}; friendly name unavailable, "
            f"using pod ID as target name."
        )
    print(f"[vcp] Saved and activated target {target}: {shlex.join(entry.get('ssh') or [])}")
    if had_legacy:
        print("[vcp] Removed obsolete legacy/default SSH mapping.")
    return 0


def _maintenance_config(argv: list[str]) -> int | None:
    if argv != ["config", "prune-legacy"]:
        return None
    if vcp_targets.prune_legacy_ssh():
        print("[vcp] Removed obsolete legacy/default SSH mapping.")
    else:
        print("[vcp] No legacy/default SSH mapping present.")
    return 0


def _named_config(argv: list[str]) -> int | None:
    # vcp config NAME ssh [ssh args...]
    # vcp config NAME show
    # vcp config NAME remove
    if len(argv) < 2 or argv[0] != "config":
        return None
    if argv[1] in {"ssh", "show", "list", "hf-repo", "repo", "clear", "prune-legacy"}:
        return None
    name = vcp_targets.validate_target_name(argv[1])
    if len(argv) < 3:
        raise vcp_targets.VcpTargetError(
            "usage: vcp config NAME ssh [ssh options] user@host"
        )
    action = argv[2]
    if action == "ssh":
        ssh_args = _ssh_config_args(
            argv,
            3,
            "usage: vcp config NAME ssh [ssh options] user@host",
        )
        entry = vcp_targets.save_target(name, ssh_args)
        print(f"[vcp] Saved SSH target {name}: {shlex.join(entry.get('ssh') or [])}")
        return 0
    if action in {"show", "list"} and len(argv) == 3:
        cfg = vcp_targets.read_config()
        entry = vcp_targets.target_entry(cfg, name)
        marker = " (active)" if vcp_targets.active_target_name(cfg) == name else ""
        try:
            normalized = vcp_targets.normalize_ssh_args(entry.get("ssh"))
        except vcp_targets.VcpTargetError:
            normalized = entry.get("ssh") or []
        print(f"target:       {name}{marker}")
        print(f"ssh:          {shlex.join(normalized) if normalized else '<not configured>'}")
        print(f"endpoint:     {vcp_targets.endpoint_from_ssh(entry.get('ssh'))}")
        print(f"pod id:       {entry.get('pod_id') or '-'}")
        print(f"provider:     {entry.get('provider') or '-'}")
        print(f"description:  {entry.get('description') or '-'}")
        return 0
    if action in {"remove", "delete", "rm"} and len(argv) == 3:
        vcp_targets.remove_target(name)
        print(f"[vcp] Removed target: {name}")
        return 0
    raise vcp_targets.VcpTargetError(f"unknown target config action: {action}")


def _call_vcp(argv: list[str], selected: str | None) -> int:
    cfg = vcp_targets.read_config()
    # Transfers expose the selected named target as the top-level `ssh` field
    # expected by the existing engine. That projection exists only in memory.
    needs_remote = bool(argv) and argv[0] not in {"config", "-h", "--help", "help"}
    original_read = vcp._read_config
    if needs_remote:
        effective, _used = vcp_targets.effective_config(cfg, selected)
        vcp._read_config = lambda: dict(effective)
    elif selected is not None:
        raise vcp_targets.VcpTargetError("--target requires a transfer command")
    try:
        result = vcp.main(argv)
        return int(result or 0)
    finally:
        vcp._read_config = original_read


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args or args[0] in {"-h", "--help", "help"}:
            print(_usage())
            return 0
        if args[0] in {"targets", "list-targets"}:
            if len(args) != 1:
                raise vcp_targets.VcpTargetError("usage: vcp targets")
            return _show_targets()
        if args[0] == "target":
            return _target_command(args)

        maintenance = _maintenance_config(args)
        if maintenance is not None:
            return maintenance

        default_ssh = _default_ssh_config(args)
        if default_ssh is not None:
            return default_ssh

        named = _named_config(args)
        if named is not None:
            return named

        forwarded, selected = _extract_target(args)
        if forwarded[:2] in (["config", "show"], ["config", "list"]):
            _show_targets()
            print()
            # Retain established HF scratch/settings output, but never expose an
            # obsolete persistent top-level SSH mapping as a default target.
            cfg = vcp_targets.read_config()
            try:
                effective, _used = vcp_targets.effective_config(cfg, selected)
            except vcp_targets.VcpTargetError:
                effective = dict(cfg)
                effective.pop("ssh", None)
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
