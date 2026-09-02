#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rent_pod as core

GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")
HEARTBEAT_SECONDS = 60

_original_print_identity = core.print_identity
_original_run_provision = core.run_provision
_installed = False
_identity_print_count: dict[str, int] = {}


MY_PODS_QUERY = """
query rentPodLifecycle {
  myself {
    pods {
      id
      desiredStatus
      lastStatusChange
      runtime {
        uptimeInSeconds
        ports {
          ip
          isIpPublic
          privatePort
          publicPort
          type
        }
      }
    }
  }
}
"""


def _graphql_request(api_key: str) -> dict[str, Any]:
    payload = json.dumps({"query": MY_PODS_QUERY, "variables": {}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise core.RunPodError(
            f"RunPod GraphQL lifecycle probe failed: HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(
            f"RunPod GraphQL lifecycle probe failed: {exc.reason}"
        ) from exc

    errors = result.get("errors")
    if errors:
        raise core.RunPodError(
            f"RunPod GraphQL lifecycle probe errors: {json.dumps(errors)}"
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise core.RunPodError(f"unexpected GraphQL lifecycle response: {result!r}")
    return data


def graphql_pod(api_key: str, pod_id: str) -> dict[str, Any] | None:
    data = _graphql_request(api_key)
    myself = data.get("myself") or {}
    pods = myself.get("pods") or []
    for pod in pods:
        if isinstance(pod, dict) and str(pod.get("id") or "") == pod_id:
            return pod
    return None


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _event_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return " ".join(value.split())
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _runtime_ssh(runtime: Any) -> tuple[str | None, int | None]:
    if not isinstance(runtime, dict):
        return None, None
    ports = runtime.get("ports") or []
    for port in ports:
        if not isinstance(port, dict):
            continue
        private = port.get("privatePort")
        public = port.get("publicPort")
        ip = port.get("ip")
        public_ip = port.get("isIpPublic")
        port_type = str(port.get("type") or "tcp").lower()
        if private == 22 and public and ip and public_ip is not False and port_type == "tcp":
            try:
                return str(ip), int(public)
            except (TypeError, ValueError):
                return str(ip), None
    return None, None


def _runtime_public_ip(runtime: Any) -> str | None:
    if not isinstance(runtime, dict):
        return None
    for port in runtime.get("ports") or []:
        if not isinstance(port, dict):
            continue
        if port.get("isIpPublic") is False:
            continue
        ip = port.get("ip")
        if ip:
            return str(ip)
    return None


def build_snapshot(
    rest_pod: dict[str, Any],
    gql_pod: dict[str, Any] | None,
    probe_error: str | None = None,
) -> dict[str, Any]:
    identity = core.pod_identity(rest_pod)
    gql_pod = gql_pod or {}
    runtime = gql_pod.get("runtime")
    runtime_present = isinstance(runtime, dict)
    gql_ip, gql_ssh_port = _runtime_ssh(runtime)

    public_ip = _first(identity.get("public_ip"), gql_ip, _runtime_public_ip(runtime))
    ssh_port = _first(identity.get("ssh_port"), gql_ssh_port)
    desired = str(
        _first(gql_pod.get("desiredStatus"), rest_pod.get("desiredStatus"), "UNKNOWN")
    )
    last_event = _event_text(
        _first(gql_pod.get("lastStatusChange"), rest_pod.get("lastStatusChange"))
    )
    uptime = runtime.get("uptimeInSeconds") if runtime_present else None

    desired_upper = desired.upper()
    if desired_upper in {"EXITED", "STOPPED", "TERMINATED"}:
        stage = desired_upper
    elif runtime_present and public_ip and ssh_port:
        stage = "NETWORK"
    elif runtime_present:
        stage = "CONTAINER"
    else:
        stage = "STARTING"

    return {
        "stage": stage,
        "desired_status": desired,
        "last_event": last_event,
        "runtime_present": runtime_present,
        "uptime": uptime,
        "public_ip": public_ip,
        "ssh_port": ssh_port,
        "machine_id": identity.get("machine_id"),
        "data_center_id": identity.get("data_center_id"),
        "probe_error": probe_error,
    }


def _parse_created_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return _parse_created_at(float(text))
            except ValueError:
                return None
    return None


def pod_age_seconds(rest_pod: dict[str, Any]) -> float | None:
    created = _parse_created_at(rest_pod.get("createdAt"))
    if created is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())


def format_elapsed(seconds: float | int | None) -> str:
    if seconds is None:
        return "--:--"
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def snapshot_signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    # Deliberately omit uptime: otherwise a live container would print every poll.
    return (
        snapshot.get("stage"),
        snapshot.get("desired_status"),
        snapshot.get("last_event"),
        snapshot.get("public_ip"),
        snapshot.get("ssh_port"),
        snapshot.get("probe_error"),
    )


def print_snapshot(
    snapshot: dict[str, Any],
    elapsed_s: float | int | None,
    remaining_s: float | int | None = None,
    ssh_ready: bool | None = None,
) -> None:
    stage = str(snapshot.get("stage") or "UNKNOWN")
    line = f"[rent-pod] {stage:<10} {format_elapsed(elapsed_s)}"
    if remaining_s is not None:
        line += f"   ({format_elapsed(remaining_s)} remaining)"
    print(line)

    last_event = snapshot.get("last_event")
    if last_event:
        print(f"           last event: {last_event}")

    if stage == "STARTING":
        print("           image/container runtime: waiting")
    elif snapshot.get("runtime_present"):
        uptime = snapshot.get("uptime")
        if uptime is None:
            print("           runtime: present")
        else:
            print(f"           runtime uptime: {format_elapsed(uptime)}")

    public_ip = snapshot.get("public_ip")
    print(f"           public IP: {public_ip or 'pending'}")

    ssh_port = snapshot.get("ssh_port")
    if public_ip and ssh_port:
        state = "ready" if ssh_ready is True else "waiting for handshake"
        if ssh_ready is None:
            state = "mapped"
        print(f"           SSH: {public_ip}:{ssh_port} ({state})")
    else:
        print("           SSH mapping: pending")

    if snapshot.get("probe_error"):
        print(f"           runtime probe: unavailable ({snapshot['probe_error']})")


def print_allocated(identity: dict[str, Any]) -> None:
    print("[rent-pod] Pod allocated")
    if identity.get("pod_id"):
        print(f"           pod: {identity['pod_id']}")
    if identity.get("machine_id"):
        print(f"           machine: {identity['machine_id']}")
    down = identity.get("max_download_mbps")
    up = identity.get("max_upload_mbps")
    if down is not None or up is not None:
        print(f"           advertised: {down if down is not None else '-'}↓ / {up if up is not None else '-'}↑ Mbps")
    disk = identity.get("disk_throughput_mbps")
    if disk is not None:
        print(f"           disk: {disk} MB/s")
    cost = identity.get("cost_per_hr")
    if cost is not None:
        print(f"           cost: ${float(cost):.3f}/hr")


def lifecycle_print_identity(identity: dict[str, Any]) -> None:
    pod_id = str(identity.get("pod_id") or "")
    count = _identity_print_count.get(pod_id, 0)
    _identity_print_count[pod_id] = count + 1
    if count == 0:
        print_allocated(identity)
    else:
        _original_print_identity(identity)


def _fetch_snapshot(api_key: str, pod_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rest_pod = core.get_pod(api_key, pod_id)
    gql: dict[str, Any] | None = None
    probe_error: str | None = None
    try:
        gql = graphql_pod(api_key, pod_id)
    except core.RunPodError as exc:
        probe_error = str(exc)
    return rest_pod, build_snapshot(rest_pod, gql, probe_error)


def _identity_with_endpoint(rest_pod: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = core.pod_identity(rest_pod)
    if snapshot.get("public_ip"):
        identity["public_ip"] = snapshot["public_ip"]
    if snapshot.get("ssh_port"):
        identity["ssh_port"] = snapshot["ssh_port"]
    return identity


def wait_for_ssh(
    api_key: str,
    pod_id: str,
    key: str,
    timeout_s: int,
    poll_s: int,
    state_file: Path,
    ttl_hours: float,
    allow_seen: bool,
) -> tuple[dict[str, Any], str | None]:
    started = time.monotonic()
    deadline = started + timeout_s
    records = core.recent_rejections(state_file, ttl_hours)
    last_signature: tuple[Any, ...] | None = None
    next_heartbeat = started
    last_identity: dict[str, Any] = {"pod_id": pod_id}
    last_snapshot: dict[str, Any] = {"stage": "STARTING"}

    while time.monotonic() < deadline:
        rest_pod, snapshot = _fetch_snapshot(api_key, pod_id)
        last_snapshot = snapshot
        identity = _identity_with_endpoint(rest_pod, snapshot)
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

        now = time.monotonic()
        elapsed = pod_age_seconds(rest_pod)
        if elapsed is None:
            elapsed = now - started
        remaining = max(0.0, deadline - now)
        signature = snapshot_signature(snapshot)

        endpoint_ready = bool(identity.get("public_ip") and identity.get("ssh_port"))
        actual_ssh_ready = False
        if endpoint_ready:
            actual_ssh_ready = core.ssh_ready(identity, key)

        should_print = signature != last_signature or now >= next_heartbeat
        if actual_ssh_ready:
            print_snapshot(snapshot, elapsed, remaining, ssh_ready=True)
            print("[rent-pod] SSH is ready.")
            return identity, None
        if should_print:
            print_snapshot(
                snapshot,
                elapsed,
                remaining,
                ssh_ready=False if endpoint_ready else None,
            )
            last_signature = signature
            next_heartbeat = now + HEARTBEAT_SECONDS

        if str(snapshot.get("stage") or "").upper() in {"EXITED", "STOPPED", "TERMINATED"}:
            return identity, f"pod-{str(snapshot['stage']).lower()}"

        time.sleep(max(1, poll_s))

    elapsed = time.monotonic() - started
    print(f"[rent-pod] STARTUP TIMEOUT {format_elapsed(elapsed)}")
    print(f"           waited: {timeout_s}s")
    print(f"           last stage: {last_snapshot.get('stage', 'unknown')}")
    print("           pod will be rejected by rental policy")
    return last_identity, "startup-timeout"


def run_provision(identity: dict[str, Any], key: str) -> int:
    started = identity.get("_rent_started_monotonic")
    elapsed = None
    if isinstance(started, (int, float)):
        elapsed = time.monotonic() - float(started)
    print(f"[rent-pod] QUALIFYING {format_elapsed(elapsed)}")
    print("           HF/CDN: pending")
    print("           PyPI/CDN: pending")
    return _original_run_provision(identity, key)


def status_pod(api_key: str, pod_id: str, ssh_key: str | None = None) -> int:
    rest_pod, snapshot = _fetch_snapshot(api_key, pod_id)
    identity = _identity_with_endpoint(rest_pod, snapshot)
    ready: bool | None = None
    if identity.get("public_ip") and identity.get("ssh_port"):
        if ssh_key and Path(ssh_key).expanduser().is_file():
            ready = core.ssh_ready(identity, str(Path(ssh_key).expanduser()))
    print_snapshot(snapshot, pod_age_seconds(rest_pod), ssh_ready=ready)
    return 0


def watch_pod(
    api_key: str,
    pod_id: str,
    ssh_key: str | None = None,
    poll_s: int = 5,
) -> int:
    key_path = str(Path(ssh_key).expanduser()) if ssh_key else None
    key_available = bool(key_path and Path(key_path).is_file())
    started = time.monotonic()
    last_signature: tuple[Any, ...] | None = None
    next_heartbeat = started

    try:
        while True:
            rest_pod, snapshot = _fetch_snapshot(api_key, pod_id)
            identity = _identity_with_endpoint(rest_pod, snapshot)
            now = time.monotonic()
            elapsed = pod_age_seconds(rest_pod)
            if elapsed is None:
                elapsed = now - started
            signature = snapshot_signature(snapshot)
            endpoint = bool(identity.get("public_ip") and identity.get("ssh_port"))
            ready = False
            if endpoint and key_available:
                ready = core.ssh_ready(identity, key_path or "")

            if signature != last_signature or now >= next_heartbeat or ready:
                print_snapshot(
                    snapshot,
                    elapsed,
                    ssh_ready=(ready if endpoint and key_available else None),
                )
                last_signature = signature
                next_heartbeat = now + HEARTBEAT_SECONDS

            if ready:
                print("[rent-pod] SSH is ready.")
                return 0
            if endpoint and not key_available:
                print("[rent-pod] SSH endpoint is exposed; connectivity probe skipped (SSH key unavailable).")
                return 0
            if str(snapshot.get("stage") or "").upper() in {"EXITED", "STOPPED", "TERMINATED"}:
                return 1
            time.sleep(max(1, poll_s))
    except KeyboardInterrupt:
        print("\n[rent-pod] Watch stopped; pod was not modified.")
        return 130


def install_core_hooks() -> None:
    global _installed
    if _installed:
        return
    core.print_identity = lifecycle_print_identity
    core.wait_for_ssh = wait_for_ssh
    core.run_provision = run_provision
    _installed = True
