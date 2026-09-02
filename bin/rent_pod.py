#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

API_BASE = os.environ.get("RUNPOD_API_BASE", "https://rest.runpod.io/v1").rstrip("/")
DEFAULT_TEMPLATE_ID = os.environ.get("RUNPOD_TEMPLATE_ID", "86n5dpgf7h")
DEFAULT_SSH_KEY = os.environ.get("RUNPOD_SSH_KEY", "~/.ssh/id_ed25519_runpod")
DEFAULT_CLOUD = os.environ.get("RUNPOD_CLOUD_TYPE", "COMMUNITY").upper()
DEFAULT_STATE_FILE = Path(
    os.environ.get(
        "RUNPOD_RENT_STATE_FILE",
        "~/.cache/pod-runtime/rent-pod-rejections.json",
    )
).expanduser()

GPU_ALIASES = {
    "4090": "NVIDIA GeForce RTX 4090",
    "5090": "NVIDIA GeForce RTX 5090",
    "l40s": "NVIDIA L40S",
    "l40": "NVIDIA L40",
    "5080": "NVIDIA GeForce RTX 5080",
    "3090": "NVIDIA GeForce RTX 3090",
}


class RunPodError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def resolve_gpu(value: str) -> str:
    return GPU_ALIASES.get(value.strip().lower(), value.strip())


def api_request(
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"{API_BASE}{path}"
    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.dumps(json.loads(body), sort_keys=True)
        except Exception:
            detail = body.strip() or str(exc.reason)
        raise RunPodError(
            f"RunPod API {method} {path} failed: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RunPodError(
            f"RunPod API {method} {path} failed: {exc.reason}"
        ) from exc


def create_pod(api_key: str, args: argparse.Namespace, attempt: int) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", args.gpu_alias.lower()).strip("-") or "gpu"
    payload: dict[str, Any] = {
        "name": args.name or f"podlet-{slug}-{int(time.time())}-a{attempt}",
        "templateId": args.template,
        "gpuTypeIds": [args.gpu],
        "gpuCount": 1,
        "gpuTypePriority": "availability",
        "supportPublicIp": True,
        "minDownloadMbps": args.min_download,
        "minUploadMbps": args.min_upload,
        "cloudType": args.cloud,
    }
    if args.min_disk is not None:
        payload["minDiskBandwidthMBps"] = args.min_disk
    result = api_request(api_key, "POST", "/pods", payload)
    if not isinstance(result, dict):
        raise RunPodError(f"unexpected create response: {result!r}")
    return result


def get_pod(api_key: str, pod_id: str) -> dict[str, Any]:
    result = api_request(
        api_key,
        "GET",
        f"/pods/{urllib.parse.quote(pod_id)}?includeMachine=true",
    )
    if not isinstance(result, dict):
        raise RunPodError(f"unexpected pod response: {result!r}")
    return result


def delete_pod(api_key: str, pod_id: str) -> None:
    api_request(api_key, "DELETE", f"/pods/{urllib.parse.quote(pod_id)}")


def pod_identity(pod: dict[str, Any]) -> dict[str, Any]:
    machine = pod.get("machine") or {}
    mappings = pod.get("portMappings") or {}
    ssh_port = mappings.get("22")
    if ssh_port is None:
        ssh_port = mappings.get(22)
    return {
        "pod_id": pod.get("id"),
        "machine_id": pod.get("machineId"),
        "data_center_id": machine.get("dataCenterId"),
        "location": machine.get("location"),
        "public_ip": pod.get("publicIp"),
        "ssh_port": ssh_port,
        "gpu": (
            (pod.get("gpu") or {}).get("displayName")
            or machine.get("gpuDisplayName")
            or machine.get("gpuTypeId")
        ),
        "cost_per_hr": pod.get("adjustedCostPerHr") or pod.get("costPerHr"),
        "max_download_mbps": machine.get("maxDownloadSpeedMbps"),
        "max_upload_mbps": machine.get("maxUploadSpeedMbps"),
        "disk_throughput_mbps": machine.get("diskThroughputMBps"),
        "desired_status": pod.get("desiredStatus"),
    }


def print_identity(identity: dict[str, Any]) -> None:
    labels = (
        ("pod_id", "Pod"),
        ("gpu", "GPU"),
        ("machine_id", "Machine"),
        ("data_center_id", "Datacenter"),
        ("location", "Location"),
        ("cost_per_hr", "Cost/hr"),
        ("max_download_mbps", "Advertised down Mbps"),
        ("max_upload_mbps", "Advertised up Mbps"),
        ("disk_throughput_mbps", "Disk throughput MB/s"),
        ("public_ip", "Public IP"),
        ("ssh_port", "SSH port"),
    )
    for key, label in labels:
        value = identity.get(key)
        if value is not None and value != "":
            print(f"[rent-pod] {label:<22} {value}")


def load_rejections(path: Path) -> list[dict[str, Any]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            obj = obj.get("rejections", [])
        return obj if isinstance(obj, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_rejections(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {"schema_version": 1, "rejections": records[-100:]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def recent_rejections(path: Path, ttl_hours: float) -> list[dict[str, Any]]:
    cutoff = now_utc() - timedelta(hours=ttl_hours)
    result = []
    for record in load_rejections(path):
        stamp = parse_time(str(record.get("timestamp", "")))
        if stamp is not None and stamp >= cutoff:
            result.append(record)
    return result


def rejection_match(
    identity: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    for field in ("machine_id", "public_ip"):
        value = identity.get(field)
        if not value:
            continue
        for record in reversed(records):
            if record.get(field) == value:
                return field, record
    return None


def record_rejection(
    path: Path,
    identity: dict[str, Any],
    reason: str,
    provision_rc: int | None = None,
) -> None:
    records = load_rejections(path)
    record = dict(identity)
    record.update({"timestamp": now_utc().isoformat(), "reason": reason})
    if provision_rc is not None:
        record["provision_rc"] = provision_rc
    records.append(record)
    save_rejections(path, records)


def ssh_command(identity: dict[str, Any], key: str, command: str | None = None) -> list[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-i",
        key,
        "-p",
        str(identity["ssh_port"]),
        f"root@{identity['public_ip']}",
    ]
    if command is not None:
        cmd.append(command)
    return cmd


def ssh_ready(identity: dict[str, Any], key: str) -> bool:
    if not identity.get("public_ip") or not identity.get("ssh_port"):
        return False
    return (
        subprocess.run(
            ssh_command(identity, key, "true"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def run_provision(identity: dict[str, Any], key: str) -> int:
    provision = Path(__file__).resolve().parent / "provision"
    cmd = [
        str(provision),
        "ssh",
        f"root@{identity['public_ip']}",
        "-p",
        str(identity["ssh_port"]),
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    print("[rent-pod] Running provision + real HF/PyPI qualification...")
    return subprocess.run(cmd).returncode


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
    deadline = time.monotonic() + timeout_s
    identity: dict[str, Any] = {"pod_id": pod_id}
    last_signature = None
    next_status = 0.0
    records = recent_rejections(state_file, ttl_hours)

    while time.monotonic() < deadline:
        identity = pod_identity(get_pod(api_key, pod_id))
        signature = (
            identity.get("machine_id"),
            identity.get("data_center_id"),
            identity.get("public_ip"),
            identity.get("ssh_port"),
        )
        if signature != last_signature:
            print_identity(identity)
            dc = identity.get("data_center_id")
            if dc:
                count = sum(1 for record in records if record.get("data_center_id") == dc)
                if count:
                    print(
                        f"[rent-pod] Recent rejected pods in datacenter {dc}: {count} "
                        "(informational; datacenter is not auto-blocked)"
                    )
            last_signature = signature

        if not allow_seen:
            match = rejection_match(identity, records)
            if match:
                field, record = match
                print(
                    f"[rent-pod] Previously rejected {field}={identity.get(field)}: "
                    f"{record.get('reason', 'previous rejection')}"
                )
                return identity, "previously-rejected-host"

        if identity.get("public_ip") and identity.get("ssh_port") and ssh_ready(identity, key):
            print("[rent-pod] SSH is ready.")
            return identity, None

        now = time.monotonic()
        if now >= next_status:
            remaining = max(0, int(deadline - now))
            print(
                "[rent-pod] Waiting for image/container + SSH mapping... "
                f"{remaining}s remaining"
            )
            next_status = now + 15
        time.sleep(poll_s)

    return identity, "startup-timeout"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rent, qualify, and provision a disposable RunPod GPU pod."
    )
    parser.add_argument(
        "gpu_alias",
        nargs="?",
        default="4090",
        help="GPU alias (4090, 5090, l40s...) or exact RunPod GPU type",
    )
    parser.add_argument("--template", default=DEFAULT_TEMPLATE_ID)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--min-download", type=float, default=500)
    parser.add_argument("--min-upload", type=float, default=100)
    parser.add_argument("--min-disk", type=float, default=None)
    parser.add_argument(
        "--cloud",
        choices=["SECURE", "COMMUNITY"],
        default=DEFAULT_CLOUD,
    )
    parser.add_argument("--name", default=None)
    parser.add_argument("--ssh-key", default=DEFAULT_SSH_KEY)
    parser.add_argument("--startup-timeout", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--retry-delay", type=int, default=5)
    parser.add_argument("--rejection-ttl-hours", type=float, default=24)
    parser.add_argument("--allow-seen-machine", action="store_true")
    parser.add_argument("--keep-failed", action="store_true")
    parser.add_argument("--no-provision", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.attempts < 1:
        print("ERROR: --attempts must be >= 1", file=sys.stderr)
        return 2

    args.gpu = resolve_gpu(args.gpu_alias)
    args.ssh_key = str(Path(args.ssh_key).expanduser())
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()

    if not api_key and not args.dry_run:
        print("ERROR: RUNPOD_API_KEY is not set in the local environment.", file=sys.stderr)
        return 2
    if not Path(args.ssh_key).is_file() and not args.dry_run:
        print(f"ERROR: SSH key not found: {args.ssh_key}", file=sys.stderr)
        return 2

    print(f"[rent-pod] Template:            {args.template}")
    print(f"[rent-pod] GPU:                 {args.gpu}")
    print(f"[rent-pod] Cloud:               {args.cloud}")
    print(f"[rent-pod] Min advertised down: {args.min_download} Mbps")
    print(f"[rent-pod] Min advertised up:   {args.min_upload} Mbps")
    print(f"[rent-pod] Attempts:            {args.attempts}")

    if args.dry_run:
        preview = {
            "name": args.name or "podlet-<gpu>-<timestamp>-a1",
            "templateId": args.template,
            "gpuTypeIds": [args.gpu],
            "gpuCount": 1,
            "gpuTypePriority": "availability",
            "supportPublicIp": True,
            "minDownloadMbps": args.min_download,
            "minUploadMbps": args.min_upload,
            "cloudType": args.cloud,
        }
        if args.min_disk is not None:
            preview["minDiskBandwidthMBps"] = args.min_disk
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    for attempt in range(1, args.attempts + 1):
        pod_id: str | None = None
        identity: dict[str, Any] = {}
        print(f"\n[rent-pod] === Attempt {attempt}/{args.attempts} ===")
        try:
            pod = create_pod(api_key, args, attempt)
            pod_id = str(pod.get("id") or "")
            if not pod_id:
                raise RunPodError("create response did not include a pod ID")
            identity = pod_identity(pod)
            print("[rent-pod] Pod rented.")
            print_identity(identity)

            identity, reject_reason = wait_for_ssh(
                api_key,
                pod_id,
                args.ssh_key,
                args.startup_timeout,
                args.poll_seconds,
                DEFAULT_STATE_FILE,
                args.rejection_ttl_hours,
                args.allow_seen_machine,
            )
            if reject_reason:
                record_rejection(DEFAULT_STATE_FILE, identity, reject_reason)
                if args.keep_failed:
                    print(f"[rent-pod] Keeping rejected pod {pod_id} (--keep-failed).")
                    return 1
                print(f"[rent-pod] Destroying rejected pod {pod_id}: {reject_reason}")
                delete_pod(api_key, pod_id)
                pod_id = None
                if attempt < args.attempts:
                    time.sleep(args.retry_delay)
                continue

            if args.no_provision:
                print("[rent-pod] SSH ready; --no-provision supplied, leaving pod running.")
                print(
                    f"ssh root@{identity['public_ip']} -p {identity['ssh_port']} "
                    f"-i {args.ssh_key}"
                )
                return 0

            rc = run_provision(identity, args.ssh_key)
            if rc == 0:
                print("\n[rent-pod] ACCEPTED: provision and real HF/PyPI qualification passed.")
                print_identity(identity)
                print(
                    f"[rent-pod] Connect: ssh root@{identity['public_ip']} "
                    f"-p {identity['ssh_port']} -i {args.ssh_key}"
                )
                return 0

            if rc == 78:
                record_rejection(
                    DEFAULT_STATE_FILE,
                    identity,
                    "provision-network-rejected",
                    provision_rc=rc,
                )
                if args.keep_failed:
                    print(f"[rent-pod] Network rejected; keeping pod {pod_id} (--keep-failed).")
                    return rc
                print(f"[rent-pod] Network rejected; destroying pod {pod_id}.")
                delete_pod(api_key, pod_id)
                pod_id = None
                if attempt < args.attempts:
                    time.sleep(args.retry_delay)
                continue

            print(
                f"[rent-pod] Provision failed rc={rc}; leaving pod running for diagnosis.",
                file=sys.stderr,
            )
            print(f"[rent-pod] Pod ID: {pod_id}", file=sys.stderr)
            return rc

        except KeyboardInterrupt:
            print("\n[rent-pod] Interrupted.", file=sys.stderr)
            if pod_id and not args.keep_failed:
                print(f"[rent-pod] Destroying in-flight pod {pod_id}...", file=sys.stderr)
                try:
                    delete_pod(api_key, pod_id)
                except Exception as exc:
                    print(f"[rent-pod] WARNING: cleanup failed: {exc}", file=sys.stderr)
            return 130
        except RunPodError as exc:
            print(f"[rent-pod] ERROR: {exc}", file=sys.stderr)
            if pod_id and not args.keep_failed:
                print(f"[rent-pod] Destroying in-flight pod {pod_id}...", file=sys.stderr)
                try:
                    delete_pod(api_key, pod_id)
                except Exception as cleanup_exc:
                    print(f"[rent-pod] WARNING: cleanup failed: {cleanup_exc}", file=sys.stderr)
            if attempt == args.attempts:
                return 1
            time.sleep(args.retry_delay)

    print(
        f"[rent-pod] No acceptable pod found after {args.attempts} attempt(s).",
        file=sys.stderr,
    )
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
