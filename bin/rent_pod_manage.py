#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import Any

import rent_pod as core


def parse_management_args(argv: list[str]) -> dict[str, Any] | None:
    """Return a management request or None when argv is a rental/list command."""
    action: str | None = None
    pod_id: str | None = None
    assume_yes = False
    extras: list[str] = []

    def set_action(value: str) -> None:
        nonlocal action
        if action is not None:
            raise ValueError("use only one of --show, --kill, or --kill-all")
        action = value

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--show":
            set_action("show")
            i += 1
            continue
        if arg == "--kill":
            set_action("kill")
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--kill requires a pod ID")
            pod_id = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--kill="):
            set_action("kill")
            pod_id = arg.split("=", 1)[1].strip()
            if not pod_id:
                raise ValueError("--kill requires a pod ID")
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
    return {"action": action, "pod_id": pod_id, "assume_yes": assume_yes}


def list_pods(api_key: str) -> list[dict[str, Any]]:
    result = core.api_request(api_key, "GET", "/pods")
    if not isinstance(result, list):
        raise core.RunPodError(f"unexpected pods response: {result!r}")
    return [pod for pod in result if isinstance(pod, dict)]


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


def pod_row(pod: dict[str, Any]) -> dict[str, str]:
    identity = core.pod_identity(pod)
    machine = pod.get("machine") or {}
    runtime = pod.get("runtime") or {}
    mappings = pod.get("portMappings") or {}

    ssh_port = identity.get("ssh_port")
    if ssh_port is None:
        ssh_port = mappings.get("22") or mappings.get(22)

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

    public_ip = _first(identity.get("public_ip"), pod.get("publicIp"))
    endpoint = "-"
    if public_ip and ssh_port:
        endpoint = f"{public_ip}:{ssh_port}"
    elif public_ip:
        endpoint = str(public_ip)

    return {
        "id": str(pod.get("id") or "-"),
        "name": str(pod.get("name") or "-"),
        "status": str(pod.get("desiredStatus") or pod.get("status") or "-"),
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

    rows = [pod_row(enriched_pod(api_key, pod)) for pod in pods]
    print(f"[rent-pod] Your RunPod pods: {len(rows)}")
    print()
    print(
        f"{'ID':<18} {'NAME':<28} {'STATUS':<10} {'GPU':<28} "
        f"{'$/hr':>8} {'DATACENTER':<16} SSH"
    )
    print("-" * 126)
    for row in rows:
        print(
            f"{row['id']:<18.18} {row['name']:<28.28} {row['status']:<10.10} "
            f"{row['gpu']:<28.28} {row['cost']:>8} {row['dc']:<16.16} {row['ssh']}"
        )
    return 0


def kill_pod(api_key: str, pod_id: str) -> int:
    pod_id = pod_id.strip()
    if not pod_id:
        print("ERROR: --kill requires a pod ID", file=sys.stderr)
        return 2

    # Read first so a typo does not produce a misleading success message.
    pod = core.get_pod(api_key, pod_id)
    name = str(pod.get("name") or "")
    core.delete_pod(api_key, pod_id)
    suffix = f" ({name})" if name else ""
    print(f"[rent-pod] Deleted pod {pod_id}{suffix}.")
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
    if action == "kill":
        return kill_pod(api_key, str(request.get("pod_id") or ""))
    if action == "kill-all":
        return kill_all(api_key, bool(request.get("assume_yes")))
    raise ValueError(f"unknown pod management action: {action}")
