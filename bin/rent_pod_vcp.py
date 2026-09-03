#!/usr/bin/env python3
from __future__ import annotations

import re
import shlex
import sys
from typing import Any

import rent_pod as core
import vcp_targets


_installed = False


def consume_vcp_args(argv: list[str]) -> tuple[list[str], bool]:
    """Strip the frontend-only --vcp switch from rental argv."""
    forwarded: list[str] = []
    enabled = False
    for arg in argv:
        if arg == "--vcp":
            enabled = True
            continue
        forwarded.append(arg)
    return forwarded, enabled


def requested_name(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--name" and i + 1 < len(argv):
            return argv[i + 1].strip() or None
        if arg.startswith("--name="):
            return arg.split("=", 1)[1].strip() or None
    return None


def vcp_ssh_args(identity: dict[str, Any], key: str) -> list[str]:
    ip = identity.get("public_ip")
    port = identity.get("ssh_port")
    if not ip or port in {None, ""}:
        raise ValueError("cannot configure VCP without a proven direct SSH endpoint")
    return ["-i", str(key), "-p", str(port), f"root@{ip}"]


def vcp_target_name(identity: dict[str, Any], rent_name: str | None = None) -> str:
    candidate = str(
        rent_name
        or identity.get("name")
        or identity.get("pod_id")
        or "runpod"
    ).strip()
    try:
        return vcp_targets.validate_target_name(candidate)
    except vcp_targets.VcpTargetError:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip("-._")
        return vcp_targets.validate_target_name(slug or "runpod")


def vcp_display_command(
    identity: dict[str, Any],
    key: str,
    rent_name: str | None = None,
) -> str:
    target = vcp_target_name(identity, rent_name)
    return shlex.join(["vcp", "config", target, "ssh", *vcp_ssh_args(identity, key)])


def print_vcp_handoff(
    identity: dict[str, Any],
    key: str,
    rent_name: str | None = None,
) -> None:
    target = vcp_target_name(identity, rent_name)
    print("[rent-pod] VCP target:")
    print(f"           {vcp_display_command(identity, key, rent_name)}")
    print(f"           vcp target {shlex.quote(target)}")


def configure_vcp(
    identity: dict[str, Any],
    key: str,
    rent_name: str | None = None,
) -> int:
    target = vcp_target_name(identity, rent_name)
    gpu = identity.get("gpu")
    description = f"RunPod {gpu}" if gpu else "RunPod pod"
    metadata = {
        "machine_id": identity.get("machine_id"),
        "runpod_name": rent_name or identity.get("name"),
    }
    print(f"[rent-pod] Configuring VCP target {target}...")
    try:
        vcp_targets.save_target(
            target,
            vcp_ssh_args(identity, key),
            pod_id=str(identity.get("pod_id") or "") or None,
            description=description,
            provider="runpod",
            metadata=metadata,
            make_active=True,
        )
    except Exception as exc:
        print(
            f"[rent-pod] WARNING: VCP target configuration failed: {exc}; "
            "pod remains accepted.",
            file=sys.stderr,
        )
        return 1
    print(f"[rent-pod] VCP target configured and active: {target}")
    return 0


def install_core_hooks(auto_configure: bool, rent_name: str | None = None) -> None:
    """Print named VCP handoff on SSH readiness and optionally save it.

    Manual output is emitted as soon as authenticated direct SSH is known, so it
    is also available for --no-provision and diagnostic provision failures.
    Mutating the local target registry is deliberately deferred until normal
    provision/network qualification succeeds, so a rejected pod never replaces
    the user's active VCP target.
    """
    global _installed
    if _installed:
        return

    original_wait = core.wait_for_ssh
    original_run_provision = core.run_provision

    def wait_for_ssh(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], str | None]:
        identity, reason = original_wait(*args, **kwargs)
        if reason is None and identity.get("public_ip") and identity.get("ssh_port"):
            # Core's third positional wait argument is the SSH key. Keep a
            # defensive keyword fallback for future call-site changes.
            key = kwargs.get("key")
            if key is None and len(args) >= 3:
                key = args[2]
            if key:
                print_vcp_handoff(identity, str(key), rent_name)
        return identity, reason

    def run_provision(identity: dict[str, Any], key: str) -> int:
        rc = original_run_provision(identity, key)
        if rc == 0 and auto_configure:
            # VCP configuration is a local convenience action, not an admission
            # gate. A failure must never cause a healthy paid pod to be deleted.
            configure_vcp(identity, key, rent_name)
        return rc

    core.wait_for_ssh = wait_for_ssh
    core.run_provision = run_provision
    _installed = True
