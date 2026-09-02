#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rent_pod as core

GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")

# Current Pod-create API enum. --cuda-min derives an allowed set from this so
# the REST API gets true >= semantics even though it accepts a list rather than
# a minCudaVersion field for Pods.
CUDA_VERSIONS = (
    "13.0",
    "12.9",
    "12.8",
    "12.7",
    "12.6",
    "12.5",
    "12.4",
    "12.3",
    "12.2",
    "12.1",
    "12.0",
    "11.8",
)


def version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise ValueError(f"invalid CUDA version: {value!r}") from exc


def allowed_cuda_versions(min_version: str | None) -> list[str]:
    if not min_version:
        return []
    minimum = version_key(min_version)
    allowed = [version for version in CUDA_VERSIONS if version_key(version) >= minimum]
    if not allowed:
        raise ValueError(
            f"CUDA >= {min_version} is not available in the current RunPod Pod API; "
            f"highest advertised version is {CUDA_VERSIONS[0]}"
        )
    return allowed


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
                raise ValueError("--cuda-min requires a version, e.g. --cuda-min 13.0")
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


def graphql_request(api_key: str, query: str) -> dict[str, Any]:
    payload = json.dumps({"query": query}).encode("utf-8")
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
        # GraphQL availability supports genuine minCudaVersion directly.
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
      minDownload
      minUpload
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
    print(f"{'GPU':<16} {'VRAM':>5} {'Pool':<7} {'Stock':<8} {'$/hr':>8} {'GPU counts':<18} {'Route floor'}")
    print("-" * 86)

    for row in selected:
        if row.get("missing"):
            print(f"{row['id']:<16} {'-':>5} {'-':<7} {'UNKNOWN':<8} {'-':>8} {'-':<18} -")
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
        route = "-"
        if lowest:
            route = f"{lowest.get('minDownload', '-')}↓/{lowest.get('minUpload', '-')}↑"
        display = str(row.get("displayName") or row.get("id") or "?")
        print(
            f"{display:<16} {str(row.get('memoryInGb') or '-'):>5} "
            f"{('yes' if pool_supported else 'no'):<7} {stock:<8} {price_text:>8} "
            f"{counts_text:<18} {route}"
        )
    return 0


def patch_create_for_cuda(cuda_min: str | None) -> None:
    allowed = allowed_cuda_versions(cuda_min)
    if not allowed:
        return

    def create_pod(api_key: str, args: Any, attempt: int) -> dict[str, Any]:
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
            "allowedCudaVersions": allowed,
        }
        if args.min_disk is not None:
            payload["minDiskBandwidthMBps"] = args.min_disk
        result = core.api_request(api_key, "POST", "/pods", payload)
        if not isinstance(result, dict):
            raise core.RunPodError(f"unexpected create response: {result!r}")
        return result

    core.create_pod = create_pod


def dry_run(forwarded: list[str], cuda_min: str | None) -> int:
    args = core.build_parser().parse_args(forwarded)
    args.gpu = core.resolve_gpu(args.gpu_alias)
    preview: dict[str, Any] = {
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
    allowed = allowed_cuda_versions(cuda_min)
    if allowed:
        preview["allowedCudaVersions"] = allowed
    print(json.dumps(preview, indent=2, sort_keys=True))
    return 0


def main() -> int:
    try:
        forwarded, options = split_frontend_args(sys.argv[1:])
        cloud, forwarded = cloud_from_args(forwarded, bool(options["community"]))
        cuda_min = options["cuda_min"]
        # Validate early, including list/dry-run.
        allowed_cuda_versions(cuda_min)
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
        return dry_run(forwarded, cuda_min)

    patch_create_for_cuda(cuda_min)
    sys.argv = [sys.argv[0], *forwarded]
    if cuda_min:
        print(
            f"[rent-pod] CUDA minimum:        {cuda_min} "
            f"(allowed: {', '.join(allowed_cuda_versions(cuda_min))})"
        )
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
