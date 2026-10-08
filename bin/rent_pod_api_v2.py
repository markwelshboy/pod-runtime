#!/usr/bin/env python3
"""RunPod API v2 compatibility layer for rent-pod.

REST reads/deletes/listing use API v2. Pod creation intentionally remains on
RunPod's GraphQL scheduler for now because rent-pod relies on placement floors
(min download/upload/disk) that API v2's create schema does not currently expose.
The GraphQL path is isolated here so it can be removed without touching the
public CLI when v2 reaches feature parity.
"""
from __future__ import annotations

import json
import os
import shlex
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import rent_pod as core

V2_BASE = os.environ.get("RUNPOD_API_V2_BASE", "https://api.runpod.io/v2").rstrip("/")
GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")

_CREATE_POD_MUTATION = """
mutation rentPodCreate($input: PodFindAndDeployOnDemandInput!) {
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

_installed = False
_original_api_request: Callable[..., Any] | None = None
_cuda_min: str | None = None


def _decode_error(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", "replace")
    try:
        obj = json.loads(body)
    except Exception:
        return body.strip() or str(exc.reason)
    if isinstance(obj, dict):
        detail = str(obj.get("detail") or obj.get("title") or "").strip()
        errors = obj.get("errors")
        if errors:
            return f"{detail}: {errors}" if detail else str(errors)
        if detail:
            return detail
    return json.dumps(obj, sort_keys=True)


def v2_request(
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = core.DEFAULT_API_TIMEOUT,
) -> Any:
    url = f"{V2_BASE}{path}"
    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        raise core.RunPodError(
            f"RunPod API v2 {method} {path} failed: HTTP {exc.code}: {_decode_error(exc)}",
            status_code=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(f"RunPod API v2 {method} {path} failed: {exc.reason}") from exc


def _graphql_request(api_key: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
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
        raise core.RunPodError(
            f"RunPod GraphQL create failed: HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(f"RunPod GraphQL create failed: {exc.reason}") from exc

    if result.get("errors"):
        raise core.RunPodError(f"RunPod GraphQL create errors: {json.dumps(result['errors'])}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise core.RunPodError(f"unexpected GraphQL create response: {result!r}")
    return data


def _docker_args(payload: dict[str, Any]) -> str | None:
    entrypoint = payload.get("dockerEntrypoint")
    start_cmd = payload.get("dockerStartCmd")
    if entrypoint:
        raise ValueError(
            "RunPod's GraphQL compatibility create path cannot preserve a "
            "dockerEntrypoint override; use the image ENTRYPOINT or omit "
            "docker_entrypoint from the local rent-pod template"
        )
    if not start_cmd:
        return None
    if not isinstance(start_cmd, list) or not all(isinstance(item, str) for item in start_cmd):
        raise ValueError("dockerStartCmd must be a list of strings")
    return shlex.join(start_cmd)


def graphql_create_input(payload: dict[str, Any], cuda_min: str | None = None) -> dict[str, Any]:
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
            "GraphQL compatibility create cannot translate Pod field(s): "
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
    }
    if cuda_min:
        result["minCudaVersion"] = cuda_min
    if len(gpu_ids) == 1:
        result["gpuTypeId"] = str(gpu_ids[0])
    else:
        result["gpuTypeIdList"] = [str(value) for value in gpu_ids]

    for field in (
        "templateId",
        "imageName",
        "containerDiskInGb",
        "volumeInGb",
        "volumeMountPath",
        "networkVolumeId",
        "containerRegistryAuthId",
    ):
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
        result["ports"] = (
            ",".join(str(value) for value in ports)
            if isinstance(ports, list)
            else str(ports)
        )

    docker_args = _docker_args(payload)
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


def _create_pod(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = _graphql_request(
        api_key,
        _CREATE_POD_MUTATION,
        {"input": graphql_create_input(payload, _cuda_min)},
    )
    result = data.get("podFindAndDeployOnDemand")
    if not isinstance(result, dict):
        raise core.RunPodError(f"unexpected GraphQL create response: {data!r}")
    return result


def normalize_v2_pod(pod: dict[str, Any]) -> dict[str, Any]:
    """Add the legacy aliases still consumed by rent-pod lifecycle helpers."""
    result = dict(pod)
    gpu = dict(result.get("gpu") or {})
    gpu_id = gpu.get("id")
    if gpu_id and not gpu.get("displayName"):
        gpu["displayName"] = gpu_id
    if gpu:
        result["gpu"] = gpu

    ssh = result.get("ssh") or {}
    direct = ssh.get("direct") or {}
    host = direct.get("host")
    port = direct.get("port")
    if host:
        result.setdefault("publicIp", host)
    if port is not None:
        result.setdefault("portMappings", {"22": port})

    status = result.get("status")
    if status:
        result.setdefault("desiredStatus", status)
    cost = result.get("cost")
    if cost is not None:
        result.setdefault("costPerHr", cost)
        result.setdefault("adjustedCostPerHr", cost)
    if gpu.get("count") is not None:
        result.setdefault("gpuCount", gpu.get("count"))
    if gpu_id:
        result.setdefault("gpuTypeId", gpu_id)

    dc = result.get("dataCenterId")
    machine = dict(result.get("machine") or {})
    if dc:
        machine.setdefault("dataCenterId", dc)
        machine.setdefault("location", dc)
    if gpu_id:
        machine.setdefault("gpuDisplayName", gpu_id)
        machine.setdefault("gpuTypeId", gpu_id)
    if machine:
        result["machine"] = machine
    return result


def _legacy_path(path: str) -> tuple[str, str | None] | None:
    parsed = urllib.parse.urlsplit(path)
    clean = parsed.path
    if clean == "/pods":
        return clean, None
    if clean.startswith("/pods/"):
        return clean, clean.split("/", 2)[2]
    return None


def install_core_hooks() -> None:
    global _installed, _original_api_request
    if _installed:
        return
    _installed = True
    _original_api_request = core.api_request

    def api_request(
        api_key: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = core.DEFAULT_API_TIMEOUT,
    ) -> Any:
        match = _legacy_path(path)
        if match is None:
            assert _original_api_request is not None
            return _original_api_request(api_key, method, path, payload, timeout=timeout)

        _clean, pod_id = match
        verb = method.upper()
        if verb == "POST" and pod_id is None:
            if not isinstance(payload, dict):
                raise core.RunPodError("Pod create payload must be an object")
            return _create_pod(api_key, payload)
        if verb == "GET" and pod_id is None:
            obj = v2_request(api_key, "GET", "/pods", timeout=timeout)
            rows = obj.get("pods") if isinstance(obj, dict) else None
            if not isinstance(rows, list):
                raise core.RunPodError(f"unexpected API v2 pods response: {obj!r}")
            return [normalize_v2_pod(row) for row in rows if isinstance(row, dict)]
        if verb == "GET" and pod_id:
            obj = v2_request(
                api_key,
                "GET",
                f"/pods/{urllib.parse.quote(pod_id)}",
                timeout=timeout,
            )
            if not isinstance(obj, dict):
                raise core.RunPodError(f"unexpected API v2 pod response: {obj!r}")
            return normalize_v2_pod(obj)
        if verb == "DELETE" and pod_id:
            return v2_request(
                api_key,
                "DELETE",
                f"/pods/{urllib.parse.quote(pod_id)}",
                timeout=timeout,
            )

        assert _original_api_request is not None
        return _original_api_request(api_key, method, path, payload, timeout=timeout)

    core.api_request = api_request


def install_frontend_hooks(frontend: Any) -> None:
    """Make the frontend's CUDA switch configure this single create transport."""
    def patch_create_for_cuda(cuda_min: str | None) -> None:
        global _cuda_min
        _cuda_min = frontend.validate_cuda_version(cuda_min)

    frontend.patch_create_for_cuda = patch_create_for_cuda

    def dry_run(forwarded: list[str], cuda_min: str | None) -> int:
        args = core.build_parser().parse_args(forwarded)
        args.gpu = core.resolve_gpu(args.gpu_alias)
        payload = frontend.base_create_payload(args, 1)
        preview = graphql_create_input(payload, frontend.validate_cuda_version(cuda_min))
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    frontend.dry_run = dry_run
