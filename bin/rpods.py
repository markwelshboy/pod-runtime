#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

USER_AGENT = os.environ.get(
    "RUNPOD_USER_AGENT",
    "pod-runtime-rpods/1.0 (Linux; Python)",
)

# Match rent-pod's explicit HTTP identity so Cloudflare sees these management
# requests as the same client family rather than Python-urllib's default agent.
opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", USER_AGENT)]
urllib.request.install_opener(opener)

import rent_pod as core  # noqa: E402
import rent_pod_api_v2 as api_v2  # noqa: E402

# rent-pod_entry installs this REST v2 bridge, but rpods is a standalone entry
# point. Without this hook, core.api_request still targets the retired REST v1
# host (rest.runpod.io), which now fails DNS resolution.
api_v2.install_core_hooks()

import rent_pod_lifecycle as lifecycle  # noqa: E402
import rent_pod_manage as manage  # noqa: E402
import rpods_pixlstash as pixlstash_tunnel  # noqa: E402
import rpods_vlm as vlm_tunnel  # noqa: E402


@dataclass(frozen=True)
class PodChoice:
    pod_id: str
    name: str
    stage: str
    gpu: str
    machine: str
    datacenter: str
    public_ip: str | None
    ssh_port: int | None
    uptime_seconds: float | None
    started_at: datetime | None

    @property
    def connectable(self) -> bool:
        if not self.public_ip or not self.ssh_port:
            return False
        return self.stage.upper() not in {"EXITED", "STOPPED", "TERMINATED", "ERROR", "FAILED"}


def format_age(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_started(value: datetime | None) -> str:
    if value is None:
        return "?"
    local = value.astimezone()
    now = datetime.now().astimezone()
    if local.date() == now.date():
        return local.strftime("%H:%M")
    return local.strftime("%b %d %H:%M")


def _gpu_runtime_uptime(gql_pod: dict[str, Any] | None) -> float | None:
    runtime = (gql_pod or {}).get("runtime")
    if not isinstance(runtime, dict):
        return None
    value = runtime.get("uptime", runtime.get("uptimeInSeconds"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def choice_from_pod(
    pod: dict[str, Any],
    gql_pod: dict[str, Any] | None = None,
) -> PodChoice:
    row = manage.pod_row(pod, gql_pod)
    snapshot = lifecycle.build_snapshot(pod, gql_pod)
    identity = core.pod_identity(pod)

    port_value = snapshot.get("ssh_port")
    try:
        ssh_port = int(port_value) if port_value not in {None, ""} else None
    except (TypeError, ValueError):
        ssh_port = None

    # REST v2 exposes live uptime directly; keep GraphQL as an optional fallback.
    uptime = _gpu_runtime_uptime(pod)
    if uptime is None:
        uptime = _gpu_runtime_uptime(gql_pod)
    if uptime is None:
        uptime = lifecycle.pod_age_seconds(pod)

    return PodChoice(
        pod_id=str(pod.get("id") or row.get("id") or ""),
        name=str(pod.get("name") or row.get("name") or "-"),
        stage=str(row.get("status") or snapshot.get("stage") or "-"),
        gpu=str(row.get("gpu") or "-"),
        machine=str(snapshot.get("machine_id") or identity.get("machine_id") or "-"),
        datacenter=str(row.get("dc") or snapshot.get("data_center_id") or "-"),
        public_ip=(str(snapshot["public_ip"]) if snapshot.get("public_ip") else None),
        ssh_port=ssh_port,
        uptime_seconds=uptime,
        started_at=lifecycle.pod_started_at(pod),
    )


def collect_choices(api_key: str) -> list[PodChoice]:
    pods = manage.list_pods(api_key)
    if not pods:
        return []

    gql_by_id: dict[str, dict[str, Any]] = {}
    try:
        gql_by_id = {
            str(pod.get("id") or ""): pod
            for pod in lifecycle.graphql_pods(api_key)
            if pod.get("id")
        }
    except core.RunPodError as exc:
        print(
            f"[rpods] WARNING: live runtime probe unavailable; using REST mappings: {exc}",
            file=sys.stderr,
        )

    choices: list[PodChoice] = []
    for pod in pods:
        detailed = manage.enriched_pod(api_key, pod)
        pod_id = str(detailed.get("id") or pod.get("id") or "")
        choices.append(choice_from_pod(detailed, gql_by_id.get(pod_id)))

    # Most recently started pods first. Unknown ages go last.
    choices.sort(
        key=lambda item: (
            item.uptime_seconds is None,
            item.uptime_seconds if item.uptime_seconds is not None else float("inf"),
            item.name.lower(),
        )
    )
    return choices


def print_choices(choices: list[PodChoice], *, show_all: bool = False) -> list[PodChoice]:
    connectable = [choice for choice in choices if choice.connectable]
    visible = choices if show_all else connectable

    if not choices:
        print("[rpods] No RunPod pods found.")
        return []

    if show_all:
        print(
            f"[rpods] RunPod pods: {len(choices)} "
            f"({len(connectable)} SSH-connectable)"
        )
    else:
        print(f"[rpods] SSH-connectable RunPod pods: {len(connectable)}")
    print()

    numbered: list[PodChoice] = []
    for choice in visible:
        if choice.connectable:
            numbered.append(choice)
            marker = f"{len(numbered):>2})"
        else:
            marker = " --)"

        print(f"{marker} {choice.name}")
        detail = (
            f"     started {format_started(choice.started_at)} | "
            f"up {format_age(choice.uptime_seconds)} | {choice.stage}"
        )
        print(detail)
        print(
            f"     {choice.gpu} | machine {choice.machine} | {choice.datacenter}"
        )
        if choice.connectable:
            print(f"     root@{choice.public_ip}:{choice.ssh_port}")
        else:
            print("     SSH mapping pending")
        print()

    hidden = len(choices) - len(connectable)
    if hidden and not show_all:
        plural = "pod" if hidden == 1 else "pods"
        print(
            f"[rpods] {hidden} other {plural} not SSH-connectable yet "
            "(--all to show)."
        )
    return numbered


def select_choice(
    selector: str,
    all_choices: list[PodChoice],
    numbered: list[PodChoice],
) -> PodChoice:
    value = selector.strip()
    if not value:
        raise ValueError("empty pod selector")

    id_matches = [choice for choice in all_choices if choice.pod_id == value]
    if len(id_matches) == 1:
        return id_matches[0]

    name_matches = [choice for choice in all_choices if choice.name == value]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        ids = ", ".join(choice.pod_id for choice in name_matches)
        raise ValueError(f"pod name {value!r} is ambiguous; matching IDs: {ids}")

    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(numbered):
            return numbered[index - 1]

    raise ValueError(f"pod not found by number, ID, or exact name: {value}")


def ssh_argv(choice: PodChoice, ssh_key: str) -> list[str]:
    if not choice.connectable:
        raise ValueError(f"pod {choice.name!r} does not currently have a live SSH mapping")
    identity = {
        "public_ip": choice.public_ip,
        "ssh_port": choice.ssh_port,
    }
    return core.ssh_command(identity, ssh_key)


def connect(choice: PodChoice, ssh_key: str) -> None:
    argv = ssh_argv(choice, ssh_key)
    print(f"[rpods] Connecting to {choice.name} ({choice.pod_id})...")
    print(f"[rpods] {shlex.join(argv)}")
    sys.stdout.flush()
    os.execvp(argv[0], argv)


def _tcp_port(value: str) -> int:
    try:
        return pixlstash_tunnel.valid_port(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def connect_or_tunnel(choice: PodChoice, ssh_key: str, args: argparse.Namespace) -> int:
    ssh = ssh_argv(choice, ssh_key)
    if args.skills_zip:
        vlm_tunnel.push_skills_zip(ssh, args.skills_zip)
    selected = set(args.tunnel or [])
    if selected == {"pixlstash", "vlm"}:
        return pixlstash_tunnel.run_tunnel(
            ssh,
            local_comfy_port=args.local_port,
            remote_comfy_port=args.comfy_port,
            pixlstash_port=args.pixlstash_port,
            remote_pixlstash_port=args.pixlstash_remote_port,
            ollama_local_port=args.ollama_local_port,
            ollama_remote_port=args.ollama_port,
            worker_local_port=args.worker_local_port,
            worker_remote_port=args.worker_port,
        )
    if selected == {"pixlstash"}:
        return pixlstash_tunnel.run_tunnel(
            ssh,
            local_comfy_port=args.local_port,
            remote_comfy_port=args.comfy_port,
            pixlstash_port=args.pixlstash_port,
            remote_pixlstash_port=args.pixlstash_remote_port,
        )
    if selected == {"vlm"}:
        return vlm_tunnel.run_tunnel(
            ssh,
            local_ollama_port=args.ollama_local_port,
            remote_ollama_port=args.ollama_port,
            local_worker_port=args.worker_local_port,
            remote_worker_port=args.worker_port,
        )
    if args.skills_zip:
        return 0
    connect(choice, ssh_key)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quickly reconnect to SSH-ready rent-pod/RunPod machines."
    )
    parser.add_argument(
        "selector",
        nargs="?",
        help="pod number from the displayed list, exact pod name, or pod ID",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="show pods without prompting or connecting",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="also show pods whose SSH mapping is not ready yet",
    )
    parser.add_argument(
        "--ssh-key",
        default=manage.management_ssh_key(),
        help="SSH private key (default: RENT_POD_SSH_KEY/RUNPOD_SSH_KEY/rent-pod default)",
    )
    parser.add_argument(
        "--tunnel", nargs="+", choices=["pixlstash", "vlm"], metavar="MODE",
        help="one or more SSH tunnels: pixlstash, vlm, or both; "
             "example: --tunnel pixlstash vlm",
    )
    parser.add_argument(
        "--ollama-local-port", type=_tcp_port, default=47961, metavar="PORT",
        help="local WSL Ollama port, loopback only (default: 47961)",
    )
    parser.add_argument(
        "--ollama-port", type=_tcp_port, default=11434, metavar="PORT",
        help="remote Ollama port on the pod (default: 11434)",
    )
    parser.add_argument(
        "--worker-local-port", type=_tcp_port, default=47962, metavar="PORT",
        help="local VLM worker port (default: 47962, loopback only)",
    )
    parser.add_argument(
        "--worker-port", type=_tcp_port, default=8765, metavar="PORT",
        help="VLM worker port on the pod (default: 8765)",
    )
    parser.add_argument(
        "--skills-zip", type=str, metavar="ZIP",
        help="upload an Image Playground analysis ZIP into /workspace/vlm-skills "
             "via the selected pod's SSH credentials; without --tunnel, upload and exit",
    )
    parser.add_argument(
        "--local-port", type=_tcp_port, default=47960, metavar="PORT",
        help="local ComfyUI port for PixlStash (default: 47960, preserves your saved URL)",
    )
    parser.add_argument(
        "--comfy-port", type=_tcp_port, default=8288, metavar="PORT",
        help="ComfyUI port on RunPod (default: 8288, GPU0; use 8188 for primary)",
    )
    parser.add_argument(
        "--pixlstash-port", type=_tcp_port, metavar="PORT",
        help="local PixlStash API port (default: detect the running Electron API)",
    )
    parser.add_argument(
        "--pixlstash-remote-port", type=_tcp_port, default=64404, metavar="PORT",
        help="port saved in ComfyUI's PixlStash node settings (default: 64404)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list and (args.tunnel or args.skills_zip):
        parser.error("--list cannot be combined with --tunnel or --skills-zip")
    if args.tunnel and len(args.tunnel) != len(set(args.tunnel)):
        parser.error("duplicate tunnel modes are not allowed")
    if args.tunnel and "pixlstash" in args.tunnel and "vlm" in args.tunnel:
        if args.local_port == args.ollama_local_port:
            parser.error("local ComfyUI and Ollama tunnel ports must differ")
    if args.tunnel and "vlm" in args.tunnel:
        busy = {args.ollama_local_port, args.worker_local_port}
        if len(busy) != 2 or ("pixlstash" in args.tunnel and args.local_port in busy):
            parser.error("local ComfyUI, Ollama and worker ports must all differ")
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        print("ERROR: RUNPOD_API_KEY is required.", file=sys.stderr)
        return 2

    ssh_key = str(Path(args.ssh_key).expanduser())
    if not Path(ssh_key).is_file() and not args.list:
        print(f"ERROR: SSH key not found: {ssh_key}", file=sys.stderr)
        return 2

    while True:
        try:
            choices = collect_choices(api_key)
        except core.RunPodError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        numbered = print_choices(choices, show_all=args.all)

        if args.list:
            return 0

        if args.selector:
            try:
                selected = select_choice(args.selector, choices, numbered)
                return connect_or_tunnel(selected, ssh_key, args)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            return 0

        if not numbered:
            if not sys.stdin.isatty():
                return 1
            try:
                answer = input("Refresh [Enter/r] or quit [q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 130
            if answer in {"q", "quit", "exit"}:
                return 0
            continue

        if not sys.stdin.isatty():
            print("ERROR: interactive selection requires a TTY; use rpods <name-or-id>.", file=sys.stderr)
            return 2

        if len(numbered) == 1:
            prompt = "Connect [1, r=refresh, q=quit] (Enter=1): "
        else:
            prompt = f"Connect [1-{len(numbered)}, r=refresh, q=quit]: "

        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130

        if not answer and len(numbered) == 1:
            answer = "1"
        lower = answer.lower()
        if lower in {"q", "quit", "exit"}:
            return 0
        if lower in {"r", "refresh"}:
            print()
            continue

        try:
            selected = select_choice(answer, choices, numbered)
        except ValueError as exc:
            print(f"[rpods] {exc}", file=sys.stderr)
            print()
            continue

        try:
            return connect_or_tunnel(selected, ssh_key, args)
        except ValueError as exc:
            print(f"[rpods] {exc}", file=sys.stderr)
            print()
            continue


if __name__ == "__main__":
    raise SystemExit(main())
