#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rent_pod as core

GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")

# Template/profile handling is installed by rent_pod_entry before main() runs.
# Keeping this hook in the frontend lets the CUDA/GraphQL create path reuse the
# exact same profile expansion as the normal REST create path without coupling
# this module back to rent_pod_templates.
_create_context_hook: Callable[[dict[str, Any]], dict[str, Any]] | None = None

CREATE_POD_MUTATION = """
mutation createPod($input: PodFindAndDeployOnDemandInput!) {
  podFindAndDeployOnDemand(input: $input) {
    id
    name
    imageName
    desiredStatus
    costPerHr
    adjustedCostPerHr
    containerDiskInGb
    volumeInGb
    volumeMountPath
    gpuCount
    memoryInGb
    vcpuCount
    ports
    lastStatusChange
    machineId
    machine {
      gpuDisplayName
      location
    }
  }
}
"""


def version_key(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not text:
        raise ValueError("CUDA version cannot be empty")
    try:
        parts = tuple(int(part) for part in text.split("."))
    except ValueError as exc:
        raise ValueError(f"invalid CUDA version: {value!r}") from exc
    if not parts or any(part < 0 for part in parts):
        raise ValueError(f"invalid CUDA version: {value!r}")
    return parts


def validate_cuda_version(value: str | None) -> str | None:
    """Validate syntax without imposing a client-side maximum CUDA version.

    RunPod's GraphQL Pod scheduler accepts minCudaVersion directly.  Keeping a
    local enum here would make rent-pod stale every time RunPod adds a host CUDA
    version, which is exactly what happened when 13.1+ appeared.
    """
    if value is None:
        return None
    text = value.strip()
    version_key(text)
    return text


def set_create_context_hook(
    hook: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> None:
    global _create_context_hook
    _create_context_hook = hook


def apply_create_context(payload: dict[str, Any]) -> dict[str, Any]:
    if _create_context_hook is None:
        return dict(payload)
    return _create_context_hook(dict(payload))


def split_frontend_args(argv: list[str]) -> tuple[list[str], dict[str, Any]]:
    forwarded: list[str] = []
    options: dict[str, Any] = {
        "community": False,
        "cuda_min": None,
        "list_spec": None,
        "list_requested": False,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--community":
            options["community"] = True
            i += 1
            continue
        if arg == "--cuda-min":
            if i + 1 >= len(argv):
                raise ValueError("--cuda-min requires a version, e.g. --cuda-min 13.3")
            options["cuda_min"] = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--cuda-min="):
            options["cuda_min"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--list":
            options["list_requested"] = True
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                options["list_spec"] = argv[i + 1]
                i += 2
            else:
                options["list_spec"] = ""
                i += 1
            continue
        if arg.startswith("--list="):
            options["list_requested"] = True
            options["list_spec"] = arg.split("=", 1)[1]
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, options


def cloud_from_args(forwarded: list[str], community: bool) -> tuple[str, list[str]]:
    explicit: str | None = None
    i = 0
    while i < len(forwarded):
        arg = forwarded[i]
        if arg == "--cloud":
            if i + 1 >= len(forwarded):
                raise ValueError("--cloud requires SECURE or COMMUNITY")
            explicit = forwarded[i + 1].upper()
            i += 2
            continue
        if arg.startswith("--cloud="):
            explicit = arg.split("=", 1)[1].upper()
        i += 1

    if community and explicit and explicit != "COMMUNITY":
        raise ValueError("--community conflicts with --cloud SECURE")

    cloud = "COMMUNITY" if community else (explicit or "SECURE")
    if cloud not in {"SECURE", "COMMUNITY"}:
        raise ValueError(f"invalid cloud pool: {cloud}")

    if explicit is None:
        forwarded = [*forwarded, "--cloud", cloud]
    return cloud, forwarded


def option_value(argv: list[str], name: str, default: float) -> float:
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == name and i + 1 < len(argv):
            return float(argv[i + 1])
        if arg.startswith(name + "="):
            return float(arg.split("=", 1)[1])
        i += 1
    return default


def graphql_request(
    api_key: str,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {"query": query}
    if variables is not None:
        request_payload["variables"] = variables
    payload = json.dumps(request_payload).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise core.RunPodError(f"RunPod GraphQL failed: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(f"RunPod GraphQL failed: {exc.reason}") from exc

    if result.get("errors"):
        raise core.RunPodError(f"RunPod GraphQL errors: {json.dumps(result['errors'])}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise core.RunPodError(f"unexpected GraphQL response: {result!r}")
    return data


def parse_gpu_list(spec: str | None) -> list[str]:
    if spec is None or not spec.strip():
        return []
    tokens = [token for token in re.split(r"[\s,]+", spec.strip()) if token]
    return [core.resolve_gpu(token) for token in tokens]


def list_gpus(
    api_key: str,
    spec: str | None,
    cloud: str,
    cuda_min: str | None,
    min_download: float,
    min_upload: float,
) -> int:
    secure = "true" if cloud == "SECURE" else "false"
    price_args = [
        "gpuCount: 1",
        f"secureCloud: {secure}",
        "supportPublicIp: true",
        f"minDownload: {int(min_download)}",
        f"minUpload: {int(min_upload)}",
    ]
    if cuda_min:
        price_args.append(f"minCudaVersion: {json.dumps(cuda_min)}")

    query = f"""
query {{
  gpuTypes {{
    id
    displayName
    memoryInGb
    secureCloud
    communityCloud
    securePrice
    communityPrice
    maxGpuCountSecureCloud
    maxGpuCountCommunityCloud
    lowestPrice(input: {{ {', '.join(price_args)} }}) {{
      stockStatus
      uninterruptablePrice
      minimumBidPrice
      availableGpuCounts
      countryCode
    }}
  }}
}}
"""
    data = graphql_request(api_key, query)
    rows = data.get("gpuTypes") or []
    if not isinstance(rows, list):
        raise core.RunPodError("gpuTypes response was not a list")

    requested = parse_gpu_list(spec)
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    if requested:
        selected = [by_id.get(gpu_id, {"id": gpu_id, "missing": True}) for gpu_id in requested]
    else:
        selected = sorted(
            (row for row in rows if isinstance(row, dict)),
            key=lambda row: str(row.get("displayName") or row.get("id") or ""),
        )

    filter_text = f"{cloud} | >= {int(min_download)} Mbps down | >= {int(min_upload)} Mbps up"
    if cuda_min:
        filter_text += f" | CUDA >= {cuda_min}"
    print(f"[rent-pod] Live RunPod availability: {filter_text}")
    print()
    print(f"{'GPU':<22} {'VRAM':>5} {'Pool':<7} {'Stock':<8} {'$/hr':>8} {'GPU counts':<18}")
    print("-" * 72)

    for row in selected:
        if row.get("missing"):
            print(f"{row['id']:<22} {'-':>5} {'-':<7} {'UNKNOWN':<8} {'-':>8} {'-':<18}")
            continue
        pool_supported = bool(row.get("secureCloud" if cloud == "SECURE" else "communityCloud"))
        lowest = row.get("lowestPrice") or {}
        stock = str(lowest.get("stockStatus") or ("None" if pool_supported else "N/A"))
        price = lowest.get("uninterruptablePrice")
        if price is None and pool_supported:
            price = row.get("securePrice" if cloud == "SECURE" else "communityPrice")
        price_text = f"${float(price):.3f}" if price is not None else "-"
        counts = lowest.get("availableGpuCounts") or []
        counts_text = ",".join(str(value) for value in counts) if counts else "-"
        display = str(row.get("displayName") or row.get("id") or "?")
        print(
            f"{display:<22} {str(row.get('memoryInGb') or '-'):>5} "
            f"{('yes' if pool_supported else 'no'):<7} {stock:<8} {price_text:>8} "
            f"{counts_text:<18}"
        )
    return 0


def base_create_payload(args: Any, attempt: int) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", args.gpu_alias.lower()).strip("-") or "gpu"
    payload: dict[str, Any] = {
        "name": args.name or f"podlet-{slug}-{int(core.time.time())}-a{attempt}",
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
    return apply_create_context(payload)


def _docker_args_from_rest_payload(payload: dict[str, Any]) -> str | None:
    entrypoint = payload.get("dockerEntrypoint")
    start_cmd = payload.get("dockerStartCmd")
    if entrypoint:
        raise ValueError(
            "--min-cuda uses RunPod GraphQL Pod creation, which cannot preserve a "
            "dockerEntrypoint override from a local template; use the image's "
            "ENTRYPOINT, a remote RunPod template, or omit --min-cuda"
        )
    if not start_cmd:
        return None
    if not isinstance(start_cmd, list) or not all(isinstance(item, str) for item in start_cmd):
        raise ValueError("dockerStartCmd must be a list of strings")
    return shlex.join(start_cmd)


def graphql_create_input(payload: dict[str, Any], cuda_min: str) -> dict[str, Any]:
    """Translate the existing REST-shaped create/profile payload to GraphQL."""
    cuda_min = validate_cuda_version(cuda_min) or ""
    supported = {
        "name",
        "templateId",
        "gpuTypeIds",
        "gpuCount",
        "gpuTypePriority",
        "supportPublicIp",
        "minDownloadMbps",
        "minUploadMbps",
        "minDiskBandwidthMBps",
        "cloudType",
        "imageName",
        "containerDiskInGb",
        "volumeInGb",
        "volumeMountPath",
        "ports",
        "dockerEntrypoint",
        "dockerStartCmd",
        "minVCPUPerGPU",
        "minRAMPerGPU",
        "networkVolumeId",
        "containerRegistryAuthId",
        "globalNetworking",
        "env",
    }
    unknown = sorted(set(payload) - supported)
    if unknown:
        raise ValueError(
            "--min-cuda GraphQL create cannot translate Pod field(s): "
            + ", ".join(unknown)
        )

    gpu_ids = payload.get("gpuTypeIds") or []
    if not isinstance(gpu_ids, list) or not gpu_ids:
        raise ValueError("Pod creation requires at least one GPU type")

    result: dict[str, Any] = {
        "name": payload.get("name"),
        "gpuCount": int(payload.get("gpuCount") or 1),
        "cloudType": payload.get("cloudType"),
        "supportPublicIp": bool(payload.get("supportPublicIp")),
        "startSsh": True,
        "minCudaVersion": cuda_min,
    }
    if len(gpu_ids) == 1:
        result["gpuTypeId"] = str(gpu_ids[0])
    else:
        result["gpuTypeIdList"] = [str(value) for value in gpu_ids]

    direct_fields = (
        "templateId",
        "imageName",
        "containerDiskInGb",
        "volumeInGb",
        "volumeMountPath",
        "networkVolumeId",
        "containerRegistryAuthId",
    )
    for field in direct_fields:
        value = payload.get(field)
        if value is not None and value != "":
            result[field] = value

    if payload.get("minDownloadMbps") is not None:
        result["minDownload"] = int(float(payload["minDownloadMbps"]))
    if payload.get("minUploadMbps") is not None:
        result["minUpload"] = int(float(payload["minUploadMbps"]))
    if payload.get("minDiskBandwidthMBps") is not None:
        result["minDisk"] = int(float(payload["minDiskBandwidthMBps"]))
    if payload.get("minVCPUPerGPU") is not None:
        result["minVcpuCount"] = int(payload["minVCPUPerGPU"])
    if payload.get("minRAMPerGPU") is not None:
        result["minMemoryInGb"] = int(payload["minRAMPerGPU"])
    if payload.get("globalNetworking") is not None:
        result["globalNetwork"] = bool(payload["globalNetworking"])

    ports = payload.get("ports")
    if ports:
        if isinstance(ports, list):
            result["ports"] = ",".join(str(value) for value in ports)
        else:
            result["ports"] = str(ports)

    docker_args = _docker_args_from_rest_payload(payload)
    if docker_args is not None:
        result["dockerArgs"] = docker_args

    env = payload.get("env")
    if env:
        if not isinstance(env, dict):
            raise ValueError("Pod env must be a mapping for GraphQL creation")
        result["env"] = [
            {"key": str(key), "value": str(value)}
            for key, value in sorted(env.items())
        ]

    return {key: value for key, value in result.items() if value is not None}


def graphql_create_pod(
    api_key: str,
    payload: dict[str, Any],
    cuda_min: str,
) -> dict[str, Any]:
    input_payload = graphql_create_input(payload, cuda_min)
    data = graphql_request(
        api_key,
        CREATE_POD_MUTATION,
        {"input": input_payload},
    )
    result = data.get("podFindAndDeployOnDemand")
    if not isinstance(result, dict):
        raise core.RunPodError(f"unexpected GraphQL create response: {data!r}")
    return result


def patch_create_for_cuda(cuda_min: str | None) -> None:
    cuda_min = validate_cuda_version(cuda_min)
    if not cuda_min:
        return

    def create_pod(api_key: str, args: Any, attempt: int) -> dict[str, Any]:
        return graphql_create_pod(api_key, base_create_payload(args, attempt), cuda_min)

    core.create_pod = create_pod


def dry_run(forwarded: list[str], cuda_min: str | None) -> int:
    args = core.build_parser().parse_args(forwarded)
    args.gpu = core.resolve_gpu(args.gpu_alias)
    payload = base_create_payload(args, 1)
    if cuda_min:
        preview = graphql_create_input(payload, cuda_min)
    else:
        preview = payload
    print(json.dumps(preview, indent=2, sort_keys=True))
    return 0


def main() -> int:
    try:
        forwarded, options = split_frontend_args(sys.argv[1:])
        cloud, forwarded = cloud_from_args(forwarded, bool(options["community"]))
        cuda_min = validate_cuda_version(options["cuda_min"])
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()

    if options["list_requested"]:
        if not api_key:
            print("ERROR: RUNPOD_API_KEY is required for live --list output.", file=sys.stderr)
            return 2
        try:
            return list_gpus(
                api_key,
                options["list_spec"],
                cloud,
                cuda_min,
                option_value(forwarded, "--min-download", 500),
                option_value(forwarded, "--min-upload", 100),
            )
        except (ValueError, core.RunPodError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if "--dry-run" in forwarded:
        try:
            return dry_run(forwarded, cuda_min)
        except (ValueError, core.RunPodError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    patch_create_for_cuda(cuda_min)
    sys.argv = [sys.argv[0], *forwarded]
    if cuda_min:
        print(f"[rent-pod] CUDA minimum:        {cuda_min} (GraphQL minCudaVersion)")
    try:
        return core.main()
    except (ValueError, core.RunPodError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
