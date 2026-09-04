#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Any

import rent_pod as core
import rent_pod_lifecycle as lifecycle
import vcp_targets


def parse_management_args(argv: list[str]) -> dict[str, Any] | None:
    """Return a management request or None when argv is a rental/list command."""
    action: str | None = None
    pod_id: str | None = None
    assume_yes = False
    extras: list[str] = []

    def set_action(value: str) -> None:
        nonlocal action
        if action is not None:
            raise ValueError(
                "use only one of --show, --status, --watch, --kill, or --kill-all"
            )
        action = value

    def take_pod_id(flag: str, index: int) -> tuple[str, int]:
        if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
            raise ValueError(f"{flag} requires a pod ID or name")
        return argv[index + 1], index + 2

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--show":
            set_action("show")
            i += 1
            continue
        if arg in {"--status", "--watch", "--kill"}:
            action_name = arg[2:]
            set_action(action_name)
            pod_id, i = take_pod_id(arg, i)
            continue
        if arg.startswith("--status="):
            set_action("status")
            pod_id = arg.split("=", 1)[1].strip()
            if not pod_id:
                raise ValueError("--status requires a pod ID or name")
            i += 1
            continue
        if arg.startswith("--watch="):
            set_action("watch")
            pod_id = arg.split("=", 1)[1].strip()
            if not pod_id:
                raise ValueError("--watch requires a pod ID or name")
            i += 1
            continue
        if arg.startswith("--kill="):
            set_action("kill")
            pod_id = arg.split("=", 1)[1].strip()
            if not pod_id:
                raise ValueError("--kill requires a pod ID or name")
            i += 1
            continue
        if arg == "--kill-all":
            set_action("kill-all")
            i += 1
            continue
        if arg in {"--yes", "-y", "--force"}:
            assume_yes = True
            i += 1
            continue
        extras.append(arg)
        i += 1

    if action is None:
        return None
    if extras:
        raise ValueError(
            "pod management commands cannot be combined with rental/list options: "
            + " ".join(extras)
        )
    if assume_yes and action != "kill-all":
        raise ValueError("--yes/-y/--force is only valid with --kill-all")
    return {"action": action, "pod_id": pod_id, "assume_yes": assume_yes}


def list_pods(api_key: str) -> list[dict[str, Any]]:
    result = core.api_request(api_key, "GET", "/pods")
    if not isinstance(result, list):
        raise core.RunPodError(f"unexpected pods response: {result!r}")
    return [pod for pod in result if isinstance(pod, dict)]


def resolve_pod_selector(api_key: str, selector: str) -> tuple[str, dict[str, Any]]:
    """Resolve an exact Pod ID or exact Pod name to one account Pod.

    Names are convenient in human-facing management commands, but they are not
    guaranteed unique. Ambiguous names are rejected rather than guessing.
    """
    value = selector.strip()
    if not value:
        raise core.RunPodError("pod selector must be a pod ID or name")

    pods = list_pods(api_key)
    id_matches = [pod for pod in pods if str(pod.get("id") or "") == value]
    if len(id_matches) == 1:
        return value, id_matches[0]

    name_matches = [pod for pod in pods if str(pod.get("name") or "") == value]
    if len(name_matches) == 1:
        pod_id = str(name_matches[0].get("id") or "").strip()
        if pod_id:
            return pod_id, name_matches[0]

    if len(name_matches) > 1:
        ids = ", ".join(str(pod.get("id") or "?") for pod in name_matches)
        raise core.RunPodError(
            f"pod name {value!r} is ambiguous; matching IDs: {ids}. Use the pod ID."
        )
    raise core.RunPodError(f"pod not found by ID or name: {value}")


def enriched_pod(api_key: str, pod: dict[str, Any]) -> dict[str, Any]:
    pod_id = str(pod.get("id") or "")
    if not pod_id:
        return pod
    try:
        return core.get_pod(api_key, pod_id)
    except core.RunPodError:
        # The list response is still useful if a machine-detail read races with
        # deletion/startup or RunPod temporarily cannot enrich the resource.
        return pod


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def pod_row(
    pod: dict[str, Any],
    gql_pod: dict[str, Any] | None = None,
) -> dict[str, str]:
    identity = core.pod_identity(pod)
    machine = pod.get("machine") or {}
    runtime = pod.get("runtime") or {}
    mappings = pod.get("portMappings") or {}

    # The live GraphQL runtime ports are the authoritative connection surface
    # used by RunPod's own CLI. REST portMappings may lag/churn during startup.
    snapshot = lifecycle.build_snapshot(pod, gql_pod) if gql_pod else None
    public_ip = snapshot.get("public_ip") if snapshot else None
    ssh_port = snapshot.get("ssh_port") if snapshot else None
    public_ip = _first(public_ip, identity.get("public_ip"), pod.get("publicIp"))
    ssh_port = _first(ssh_port, identity.get("ssh_port"), mappings.get("22"), mappings.get(22))

    gpu = _first(
        identity.get("gpu"),
        pod.get("gpuTypeId"),
        machine.get("gpuDisplayName"),
        machine.get("gpuTypeId"),
    )
    gpu_count = _first(pod.get("gpuCount"), runtime.get("gpuCount"))
    if gpu_count and gpu_count != 1 and gpu:
        gpu = f"{gpu_count}x {gpu}"

    cost = _first(identity.get("cost_per_hr"), pod.get("costPerHr"))
    cost_text = f"${float(cost):.3f}" if cost is not None else "-"

    endpoint = "-"
    if public_ip and ssh_port:
        endpoint = f"{public_ip}:{ssh_port}"
    elif public_ip:
        endpoint = str(public_ip)

    status = str(pod.get("desiredStatus") or pod.get("status") or "-")
    if snapshot:
        status = str(snapshot.get("stage") or status)

    return {
        "id": str(pod.get("id") or "-"),
        "name": str(pod.get("name") or "-"),
        "status": status,
        "gpu": str(gpu or "-"),
        "cost": cost_text,
        "dc": str(identity.get("data_center_id") or machine.get("dataCenterId") or "-"),
        "ssh": endpoint,
    }


def show_pods(api_key: str) -> int:
    pods = list_pods(api_key)
    if not pods:
        print("[rent-pod] No pods found.")
        return 0

    # One account-wide GraphQL request gives us the same live runtime/SSH view
    # used by --status/--watch. If it fails, degrade to REST-only listing.
    gql_by_id: dict[str, dict[str, Any]] = {}
    try:
        gql_by_id = {
            str(pod.get("id") or ""): pod
            for pod in lifecycle.graphql_pods(api_key)
            if pod.get("id")
        }
    except core.RunPodError as exc:
        print(f"[rent-pod] WARNING: live runtime probe unavailable: {exc}", file=sys.stderr)

    rows: list[dict[str, str]] = []
    for pod in pods:
        detailed = enriched_pod(api_key, pod)
        pod_id = str(detailed.get("id") or pod.get("id") or "")
        rows.append(pod_row(detailed, gql_by_id.get(pod_id)))

    print(f"[rent-pod] Your RunPod pods: {len(rows)}")
    print()
    print(
        f"{'ID':<18} {'NAME':<28} {'STAGE':<10} {'GPU':<28} "
        f"{'$/hr':>8} {'DATACENTER':<16} SSH"
    )
    print("-" * 126)
    for row in rows:
        print(
            f"{row['id']:<18.18} {row['name']:<28.28} {row['status']:<10.10} "
            f"{row['gpu']:<28.28} {row['cost']:>8} {row['dc']:<16.16} {row['ssh']}"
        )
    return 0


def management_ssh_key() -> str:
    return (
        os.environ.get("RENT_POD_SSH_KEY")
        or os.environ.get("RUNPOD_SSH_KEY")
        or core.DEFAULT_SSH_KEY
    )


def status_pod(api_key: str, selector: str) -> int:
    pod_id, _pod = resolve_pod_selector(api_key, selector)
    return lifecycle.status_pod(api_key, pod_id, management_ssh_key())


def watch_pod(api_key: str, selector: str) -> int:
    pod_id, _pod = resolve_pod_selector(api_key, selector)
    return lifecycle.watch_pod(api_key, pod_id, management_ssh_key())


def pod_vcp_endpoints(pod: dict[str, Any]) -> set[tuple[str, int | None]]:
    """Return SSH host/port pairs visible in a REST Pod response."""
    result: set[tuple[str, int | None]] = set()
    identity = core.pod_identity(pod)
    mappings = pod.get("portMappings") or {}
    candidates = [
        (identity.get("public_ip"), identity.get("ssh_port")),
        (pod.get("publicIp"), mappings.get("22")),
        (pod.get("publicIp"), mappings.get(22)),
    ]
    for host, port in candidates:
        if not host or port in {None, ""}:
            continue
        try:
            result.add((str(host), int(port)))
        except (TypeError, ValueError):
            continue
    return result


def _reap_vcp_for_deleted_pod(pod_id: str, pod: dict[str, Any]) -> None:
    """Best-effort local VCP cleanup after RunPod confirms deletion."""
    try:
        cleanup = vcp_targets.remove_matching_targets(
            pod_id=pod_id,
            endpoints=pod_vcp_endpoints(pod),
        )
    except Exception as exc:
        # A local convenience registry must never turn a successful paid-resource
        # deletion into a failed management command.
        print(f"[rent-pod] WARNING: VCP cleanup failed: {exc}", file=sys.stderr)
        return

    removed = cleanup.get("targets") or []
    if removed:
        print(f"[rent-pod] Reaped VCP target(s): {', '.join(removed)}")
    if cleanup.get("legacy"):
        print("[rent-pod] Removed obsolete legacy/default VCP SSH mapping.")


def kill_pod(api_key: str, selector: str) -> int:
    selector = selector.strip()
    if not selector:
        print("ERROR: --kill requires a pod ID or name", file=sys.stderr)
        return 2

    pod_id, summary = resolve_pod_selector(api_key, selector)
    # Read the concrete ID before deletion so endpoint cleanup has the richest
    # available metadata and a typo/race cannot produce a misleading success.
    pod = core.get_pod(api_key, pod_id)
    name = str(pod.get("name") or summary.get("name") or "")
    core.delete_pod(api_key, pod_id)
    suffix = f" ({name})" if name else ""
    print(f"[rent-pod] Deleted pod {pod_id}{suffix}.")
    _reap_vcp_for_deleted_pod(pod_id, pod)
    return 0


def confirm_kill_all(count: int) -> bool:
    if not sys.stdin.isatty():
        print(
            "ERROR: --kill-all requires an interactive terminal or --yes/-y.",
            file=sys.stderr,
        )
        return False
    print(f"[rent-pod] About to permanently delete {count} pod(s).")
    try:
        answer = input("Type DELETE ALL to continue: ")
    except EOFError:
        return False
    return answer.strip() == "DELETE ALL"


def kill_all(api_key: str, assume_yes: bool = False) -> int:
    pods = list_pods(api_key)
    if not pods:
        print("[rent-pod] No pods to delete.")
        return 0

    if not assume_yes and not confirm_kill_all(len(pods)):
        print("[rent-pod] No pods deleted.")
        return 1

    failures: list[tuple[str, str]] = []
    deleted = 0
    for pod in pods:
        pod_id = str(pod.get("id") or "")
        if not pod_id:
            continue
        name = str(pod.get("name") or "")
        try:
            core.delete_pod(api_key, pod_id)
            deleted += 1
            suffix = f" ({name})" if name else ""
            print(f"[rent-pod] Deleted {pod_id}{suffix}")
            _reap_vcp_for_deleted_pod(pod_id, pod)
        except core.RunPodError as exc:
            failures.append((pod_id, str(exc)))
            print(f"[rent-pod] ERROR deleting {pod_id}: {exc}", file=sys.stderr)

    if failures:
        print(
            f"[rent-pod] Deleted {deleted}/{len(pods)} pods; {len(failures)} failed.",
            file=sys.stderr,
        )
        return 1

    print(f"[rent-pod] Deleted all {deleted} pods.")
    return 0


def run_management(api_key: str, request: dict[str, Any]) -> int:
    action = request["action"]
    if action == "show":
        return show_pods(api_key)
    if action == "status":
        return status_pod(api_key, str(request.get("pod_id") or ""))
    if action == "watch":
        return watch_pod(api_key, str(request.get("pod_id") or ""))
    if action == "kill":
        return kill_pod(api_key, str(request.get("pod_id") or ""))
    if action == "kill-all":
        return kill_all(api_key, bool(request.get("assume_yes")))
    raise ValueError(f"unknown pod management action: {action}")
