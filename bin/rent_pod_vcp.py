#!/usr/bin/env python3
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import rent_pod as core


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


def vcp_ssh_args(identity: dict[str, Any], key: str) -> list[str]:
    ip = identity.get("public_ip")
    port = identity.get("ssh_port")
    if not ip or port in {None, ""}:
        raise ValueError("cannot configure VCP without a proven direct SSH endpoint")
    return ["-i", str(key), "-p", str(port), f"root@{ip}"]


def vcp_display_command(identity: dict[str, Any], key: str) -> str:
    return shlex.join(["vcp", "config", "ssh", *vcp_ssh_args(identity, key)])


def print_vcp_handoff(identity: dict[str, Any], key: str) -> None:
    print("[rent-pod] VCP remote:")
    print(f"           {vcp_display_command(identity, key)}")


def configure_vcp(identity: dict[str, Any], key: str) -> int:
    # Config-only VCP operations need no Hugging Face packages. Invoke the
    # Python implementation directly instead of the root vcp wrapper, whose
    # normal transfer path intentionally initializes the HFF virtualenv.
    vcp_py = Path(__file__).resolve().parent / "vcp.py"
    if not vcp_py.is_file():
        print(f"[rent-pod] WARNING: VCP command not found: {vcp_py}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(vcp_py), "config", "ssh", *vcp_ssh_args(identity, key)]
    print("[rent-pod] Configuring VCP remote...")
    try:
        result = subprocess.run(cmd, check=False)
    except OSError as exc:
        print(f"[rent-pod] WARNING: could not run VCP configuration: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            f"[rent-pod] WARNING: VCP configuration failed with rc={result.returncode}; "
            "pod remains accepted.",
            file=sys.stderr,
        )
        return result.returncode
    print("[rent-pod] VCP remote configured.")
    return 0


def install_core_hooks(auto_configure: bool) -> None:
    """Print the VCP handoff on SSH readiness; optionally configure after acceptance.

    Manual output is emitted as soon as authenticated direct SSH is known, so it
    is also available for --no-provision and diagnostic provision failures.
    The mutating `vcp config ssh` operation is deliberately deferred until the
    normal provision/network qualification succeeds, so a rejected pod never
    replaces the user's existing VCP target.
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
                print_vcp_handoff(identity, str(key))
        return identity, reason

    def run_provision(identity: dict[str, Any], key: str) -> int:
        rc = original_run_provision(identity, key)
        if rc == 0 and auto_configure:
            # VCP configuration is a local convenience action, not an admission
            # gate. A failure must never cause a healthy paid pod to be deleted.
            configure_vcp(identity, key)
        return rc

    core.wait_for_ssh = wait_for_ssh
    core.run_provision = run_provision
    _installed = True
