#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any, Mapping

import rent_pod as core
import rent_pod_lifecycle as lifecycle

DEFAULT_SSH_EXPOSURE_TIMEOUT = 180
ENDPOINT_GRACE_SECONDS = 90
TCP_BANNER_TIMEOUT = 2.0


def consume_ssh_phase_args(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], int]:
    """Strip the frontend-only SSH exposure timeout option from argv.

    The overall startup timeout governs allocation -> runtime. Once a runtime is
    visible we switch to this shorter direct-SSH exposure timeout instead.
    Command-line values override RENT_POD_SSH_EXPOSURE_TIMEOUT.
    """
    env = environ or os.environ
    raw_env = (env.get("RENT_POD_SSH_EXPOSURE_TIMEOUT") or "").strip()
    timeout = DEFAULT_SSH_EXPOSURE_TIMEOUT
    if raw_env:
        try:
            timeout = int(raw_env)
        except ValueError as exc:
            raise ValueError("RENT_POD_SSH_EXPOSURE_TIMEOUT must be an integer") from exc

    forwarded: list[str] = []
    cli_value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--ssh-exposure-timeout":
            if i + 1 >= len(argv):
                raise ValueError("--ssh-exposure-timeout requires seconds")
            cli_value = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--ssh-exposure-timeout="):
            cli_value = arg.split("=", 1)[1]
            i += 1
            continue
        forwarded.append(arg)
        i += 1

    if cli_value is not None:
        try:
            timeout = int(cli_value)
        except ValueError as exc:
            raise ValueError("--ssh-exposure-timeout must be an integer") from exc
    if timeout < 1:
        raise ValueError("SSH exposure timeout must be >= 1 second")
    return forwarded, timeout


def tcp_and_banner_ready(ip: str, port: int, timeout: float = TCP_BANNER_TIMEOUT) -> tuple[bool, bool]:
    """Probe a direct RunPod TCP mapping and the server-side SSH banner.

    OpenSSH sends its SSH identification string immediately after TCP connect,
    before authentication. A reachable TCP socket with no banner therefore
    distinguishes RunPod NAT/port exposure from an sshd that is actually ready.
    """
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout) as sock:
            tcp_ready = True
            sock.settimeout(timeout)
            try:
                data = sock.recv(512)
            except (socket.timeout, TimeoutError, OSError):
                data = b""
            banner_ready = any(line.startswith(b"SSH-") for line in data.splitlines())
            return tcp_ready, banner_ready
    except (OSError, ValueError):
        return False, False


def _endpoint(ip: Any, port: Any) -> tuple[str, int] | None:
    if not ip or port in {None, ""}:
        return None
    try:
        return str(ip), int(port)
    except (TypeError, ValueError):
        return None


def observed_endpoints(rest_pod: dict[str, Any], snapshot: dict[str, Any]) -> list[tuple[str, int]]:
    """Return current GraphQL-preferred and REST direct-SSH mappings.

    During startup RunPod can expose different port-22 mappings on the GraphQL
    runtime and REST surfaces. Keep both candidates rather than assuming either
    surface is instantly authoritative.
    """
    result: list[tuple[str, int]] = []

    selected = _endpoint(snapshot.get("public_ip"), snapshot.get("ssh_port"))
    if selected is not None:
        result.append(selected)

    rest_identity = core.pod_identity(rest_pod)
    rest = _endpoint(rest_identity.get("public_ip"), rest_identity.get("ssh_port"))
    if rest is not None and rest not in result:
        result.append(rest)
    return result


def retain_endpoints(
    recent: dict[tuple[str, int], float],
    current: list[tuple[str, int]],
    now: float,
    grace_seconds: float = ENDPOINT_GRACE_SECONDS,
) -> list[tuple[str, int]]:
    for endpoint in current:
        recent[endpoint] = now
    for endpoint, last_seen in list(recent.items()):
        if now - last_seen > grace_seconds:
            recent.pop(endpoint, None)

    ordered = list(current)
    for endpoint, _last_seen in sorted(recent.items(), key=lambda item: item[1], reverse=True):
        if endpoint not in ordered:
            ordered.append(endpoint)
    return ordered


def probe_endpoints(
    endpoints: list[tuple[str, int]],
    key: str | None,
) -> list[dict[str, Any]]:
    key_path = str(Path(key).expanduser()) if key else None
    key_available = bool(key_path and Path(key_path).is_file())
    probes: list[dict[str, Any]] = []

    for ip, port in endpoints:
        tcp_ready, banner_ready = tcp_and_banner_ready(ip, port)
        auth_ready: bool | None = None
        if banner_ready and key_available:
            identity = {"public_ip": ip, "ssh_port": port}
            auth_ready = core.ssh_ready(identity, key_path)
        probes.append(
            {
                "ip": ip,
                "port": port,
                "tcp_ready": tcp_ready,
                "banner_ready": banner_ready,
                "auth_ready": auth_ready,
            }
        )
    return probes


def best_probe(probes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not probes:
        return None

    def rank(probe: dict[str, Any]) -> int:
        if probe.get("auth_ready") is True:
            return 4
        if probe.get("banner_ready"):
            return 3
        if probe.get("tcp_ready"):
            return 2
        return 1

    return max(probes, key=rank)


def phase_for(snapshot: dict[str, Any], probe: dict[str, Any] | None) -> str:
    terminal = str(snapshot.get("stage") or "").upper()
    if terminal in {"EXITED", "STOPPED", "TERMINATED"}:
        return terminal
    if not snapshot.get("runtime_present"):
        return "STARTING"
    if probe and (probe.get("banner_ready") or probe.get("auth_ready") is True):
        return "SSH"
    if probe is not None:
        return "NETWORK"
    return "CONTAINER"


def probe_signature(snapshot: dict[str, Any], probe: dict[str, Any] | None) -> tuple[Any, ...]:
    return (
        phase_for(snapshot, probe),
        snapshot.get("desired_status"),
        snapshot.get("last_event"),
        probe.get("ip") if probe else None,
        probe.get("port") if probe else None,
        probe.get("tcp_ready") if probe else None,
        probe.get("banner_ready") if probe else None,
        probe.get("auth_ready") if probe else None,
        snapshot.get("probe_error"),
    )


def print_probe_snapshot(
    snapshot: dict[str, Any],
    probe: dict[str, Any] | None,
    elapsed_s: float | int | None,
    startup_remaining_s: float | int | None = None,
    ssh_remaining_s: float | int | None = None,
) -> None:
    stage = phase_for(snapshot, probe)
    line = f"[rent-pod] {stage:<10} {lifecycle.format_elapsed(elapsed_s)}"
    if not snapshot.get("runtime_present") and startup_remaining_s is not None:
        line += f"   ({lifecycle.format_elapsed(startup_remaining_s)} startup remaining)"
    elif snapshot.get("runtime_present") and ssh_remaining_s is not None:
        line += f"   ({lifecycle.format_elapsed(ssh_remaining_s)} SSH exposure remaining)"
    print(line)

    last_event = snapshot.get("last_event")
    if last_event:
        print(f"           last event: {last_event}")

    if not snapshot.get("runtime_present"):
        print("           image/container runtime: waiting")
    else:
        uptime = snapshot.get("uptime")
        if uptime is None:
            print("           runtime: present")
        else:
            print(f"           runtime uptime: {lifecycle.format_elapsed(uptime)}")

    if probe is None:
        public_ip = snapshot.get("public_ip")
        print(f"           public IP: {public_ip or 'pending'}")
        print("           SSH mapping: pending")
    else:
        ip = probe["ip"]
        port = probe["port"]
        print(f"           public IP: {ip}")
        print(f"           SSH mapping: {ip}:{port}")
        print(f"           TCP/{port}: {'reachable' if probe.get('tcp_ready') else 'pending'}")
        print(f"           SSH banner: {'ready' if probe.get('banner_ready') else 'pending'}")
        auth = probe.get("auth_ready")
        if auth is None:
            print("           SSH auth: not probed")
        else:
            print(f"           SSH auth: {'ready' if auth else 'pending'}")

    if snapshot.get("probe_error"):
        print(f"           runtime probe: unavailable ({snapshot['probe_error']})")


def _identity_for_probe(
    rest_pod: dict[str, Any],
    snapshot: dict[str, Any],
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    identity = lifecycle._identity_with_endpoint(rest_pod, snapshot)
    if probe is not None:
        identity["public_ip"] = probe["ip"]
        identity["ssh_port"] = probe["port"]
    return identity


def _runtime_deadline(now: float, snapshot: dict[str, Any], timeout_s: int) -> float:
    uptime = snapshot.get("uptime")
    try:
        uptime_s = max(0.0, float(uptime)) if uptime is not None else 0.0
    except (TypeError, ValueError):
        uptime_s = 0.0
    return (now - uptime_s) + timeout_s


def wait_for_ssh(
    api_key: str,
    pod_id: str,
    key: str,
    timeout_s: int,
    poll_s: int,
    state_file: Path,
    ttl_hours: float,
    allow_seen: bool,
    ssh_exposure_timeout_s: int = DEFAULT_SSH_EXPOSURE_TIMEOUT,
) -> tuple[dict[str, Any], str | None]:
    started = time.monotonic()
    startup_deadline = started + timeout_s
    records = core.recent_rejections(state_file, ttl_hours)
    recent_endpoints: dict[tuple[str, int], float] = {}
    last_signature: tuple[Any, ...] | None = None
    next_heartbeat = started
    runtime_deadline: float | None = None
    last_identity: dict[str, Any] = {"pod_id": pod_id}
    last_snapshot: dict[str, Any] = {"stage": "STARTING", "runtime_present": False}

    while True:
        now = time.monotonic()
        rest_pod, snapshot = lifecycle._fetch_snapshot(api_key, pod_id)
        last_snapshot = snapshot

        current = observed_endpoints(rest_pod, snapshot)
        candidates = retain_endpoints(recent_endpoints, current, now)
        probes = probe_endpoints(candidates, key)
        probe = best_probe(probes)

        identity = _identity_for_probe(rest_pod, snapshot, probe)
        identity["_rent_started_monotonic"] = started
        last_identity = identity

        if not allow_seen:
            match = core.rejection_match(identity, records)
            if match:
                field, record = match
                print(
                    f"[rent-pod] Previously rejected {field}={identity.get(field)}: "
                    f"{record.get('reason', 'previous rejection')}"
                )
                return identity, "previously-rejected-host"

        elapsed = lifecycle.pod_age_seconds(rest_pod)
        if elapsed is None:
            elapsed = now - started

        if snapshot.get("runtime_present"):
            # Compute from runtime uptime so a delayed API observation does not
            # accidentally grant a fresh three-minute window to an already-old
            # container. Recompute if uptime resets after a container restart.
            runtime_deadline = _runtime_deadline(now, snapshot, ssh_exposure_timeout_s)
            ssh_remaining = max(0.0, runtime_deadline - now)
            startup_remaining = None
        else:
            ssh_remaining = None
            startup_remaining = max(0.0, startup_deadline - now)

        signature = probe_signature(snapshot, probe)
        auth_ready = bool(probe and probe.get("auth_ready") is True)
        should_print = signature != last_signature or now >= next_heartbeat or auth_ready

        if should_print:
            print_probe_snapshot(
                snapshot,
                probe,
                elapsed,
                startup_remaining_s=startup_remaining,
                ssh_remaining_s=ssh_remaining,
            )
            last_signature = signature
            next_heartbeat = now + lifecycle.HEARTBEAT_SECONDS

        if auth_ready:
            if current and (probe["ip"], probe["port"]) not in current:
                print(
                    f"[rent-pod] SSH became ready on a recently seen mapping: "
                    f"{probe['ip']}:{probe['port']}"
                )
            print("[rent-pod] SSH is ready.")
            return identity, None

        terminal = str(snapshot.get("stage") or "").upper()
        if terminal in {"EXITED", "STOPPED", "TERMINATED"}:
            return identity, f"pod-{terminal.lower()}"

        if snapshot.get("runtime_present"):
            if runtime_deadline is not None and now >= runtime_deadline:
                print(f"[rent-pod] SSH EXPOSURE TIMEOUT {lifecycle.format_elapsed(elapsed)}")
                print(f"           runtime is alive but direct SSH did not become usable within {ssh_exposure_timeout_s}s")
                print("           rejection reason: ssh-exposure-timeout")
                return identity, "ssh-exposure-timeout"
        elif now >= startup_deadline:
            print(f"[rent-pod] STARTUP TIMEOUT {lifecycle.format_elapsed(elapsed)}")
            print(f"           runtime never appeared within {timeout_s}s")
            print("           rejection reason: startup-timeout")
            return identity, "startup-timeout"

        time.sleep(max(1, poll_s))


def status_pod(api_key: str, pod_id: str, ssh_key: str | None = None) -> int:
    rest_pod, snapshot = lifecycle._fetch_snapshot(api_key, pod_id)
    endpoints = observed_endpoints(rest_pod, snapshot)
    probe = best_probe(probe_endpoints(endpoints, ssh_key))
    print_probe_snapshot(snapshot, probe, lifecycle.pod_age_seconds(rest_pod))
    return 0


def watch_pod(
    api_key: str,
    pod_id: str,
    ssh_key: str | None = None,
    poll_s: int = 5,
) -> int:
    started = time.monotonic()
    recent_endpoints: dict[tuple[str, int], float] = {}
    last_signature: tuple[Any, ...] | None = None
    next_heartbeat = started

    try:
        while True:
            now = time.monotonic()
            rest_pod, snapshot = lifecycle._fetch_snapshot(api_key, pod_id)
            current = observed_endpoints(rest_pod, snapshot)
            candidates = retain_endpoints(recent_endpoints, current, now)
            probe = best_probe(probe_endpoints(candidates, ssh_key))
            elapsed = lifecycle.pod_age_seconds(rest_pod)
            if elapsed is None:
                elapsed = now - started

            signature = probe_signature(snapshot, probe)
            ready = bool(probe and probe.get("auth_ready") is True)
            if signature != last_signature or now >= next_heartbeat or ready:
                print_probe_snapshot(snapshot, probe, elapsed)
                last_signature = signature
                next_heartbeat = now + lifecycle.HEARTBEAT_SECONDS

            if ready:
                print("[rent-pod] SSH is ready; watch complete.")
                return 0
            terminal = str(snapshot.get("stage") or "").upper()
            if terminal in {"EXITED", "STOPPED", "TERMINATED"}:
                return 1
            time.sleep(max(1, poll_s))
    except KeyboardInterrupt:
        print("\n[rent-pod] Watch stopped; pod left untouched.")
        return 130


def install_management_hooks() -> None:
    # rent_pod_manage calls these lifecycle module attributes dynamically, so
    # replacing them before management dispatch upgrades --status/--watch too.
    lifecycle.status_pod = status_pod
    lifecycle.watch_pod = watch_pod


def install_core_hook(ssh_exposure_timeout_s: int) -> None:
    def hooked_wait_for_ssh(
        api_key: str,
        pod_id: str,
        key: str,
        timeout_s: int,
        poll_s: int,
        state_file: Path,
        ttl_hours: float,
        allow_seen: bool,
    ) -> tuple[dict[str, Any], str | None]:
        return wait_for_ssh(
            api_key,
            pod_id,
            key,
            timeout_s,
            poll_s,
            state_file,
            ttl_hours,
            allow_seen,
            ssh_exposure_timeout_s,
        )

    core.wait_for_ssh = hooked_wait_for_ssh
