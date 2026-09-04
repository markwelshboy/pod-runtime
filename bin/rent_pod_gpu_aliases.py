#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod GPU aliases require Python 3.11+ (tomllib)") from exc

import rent_pod as core
from rent_pod_config import config_root

GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

GPU_TYPES_QUERY = """
query rentPodGpuAliases {
  gpuTypes {
    id
    displayName
  }
}
"""


@dataclass(frozen=True)
class GpuAliasConfig:
    path: Path
    aliases: dict[str, str]
    file_exists: bool


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    explicit = (env.get("RENT_POD_GPU_ALIASES_FILE") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return config_root(env) / "gpu-aliases.toml"


def load_aliases(
    environ: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> GpuAliasConfig:
    env = environ if environ is not None else os.environ
    cfg = (path or config_path(env)).expanduser()
    if not cfg.is_file():
        return GpuAliasConfig(cfg, {}, False)

    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read GPU alias file {cfg}: {exc}") from exc

    raw_aliases = data.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        raise ValueError(f"aliases must be a TOML table in {cfg}")

    aliases: dict[str, str] = {}
    for raw_name, raw_target in raw_aliases.items():
        name = str(raw_name).strip()
        if not ALIAS_RE.match(name):
            raise ValueError(
                f"invalid GPU alias {name!r} in {cfg}; use letters, numbers, '.', '_' or '-'"
            )
        if not isinstance(raw_target, str) or not raw_target.strip():
            raise ValueError(f"aliases.{name} must be a non-empty string in {cfg}")
        key = name.casefold()
        if key in aliases:
            raise ValueError(f"duplicate GPU alias {name!r} in {cfg}")
        aliases[key] = raw_target.strip()

    return GpuAliasConfig(cfg, aliases, True)


def graphql_gpu_types(api_key: str) -> list[dict[str, str]]:
    payload = json.dumps({"query": GPU_TYPES_QUERY, "variables": {}}).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise core.RunPodError(
            f"RunPod GraphQL GPU-name lookup failed: HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(
            f"RunPod GraphQL GPU-name lookup failed: {exc.reason}"
        ) from exc

    errors = result.get("errors")
    if errors:
        raise core.RunPodError(
            f"RunPod GraphQL GPU-name lookup errors: {json.dumps(errors)}"
        )
    data = result.get("data")
    rows = data.get("gpuTypes") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise core.RunPodError(f"unexpected RunPod GPU-name response: {result!r}")

    cleaned: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        gpu_id = str(row.get("id") or "").strip()
        display = str(row.get("displayName") or "").strip()
        if gpu_id:
            cleaned.append({"id": gpu_id, "displayName": display})
    return cleaned


def install_core_gpu_resolver(
    api_key: str,
    environ: Mapping[str, str] | None = None,
) -> GpuAliasConfig:
    """Teach core.resolve_gpu about local aliases and live RunPod display names.

    Resolution order is local aliases -> built-in aliases -> exact live display
    name / exact live GPU ID. Unknown values continue to pass through unchanged,
    preserving the historical ability to supply a raw RunPod GPU ID even if a
    lookup is unavailable or the API adds a new type before this client knows it.
    """
    config = load_aliases(environ)
    original_resolve = core.resolve_gpu
    cached_rows: list[dict[str, str]] | None = None

    def resolve_gpu(value: str) -> str:
        nonlocal cached_rows
        raw = value.strip()
        target = config.aliases.get(raw.casefold(), raw)

        built_in = original_resolve(target)
        if built_in != target:
            return built_in

        if not api_key:
            return target

        if cached_rows is None:
            cached_rows = graphql_gpu_types(api_key)

        wanted = target.casefold()
        for row in cached_rows:
            gpu_id = row["id"]
            display = row.get("displayName", "")
            if gpu_id.casefold() == wanted or (display and display.casefold() == wanted):
                return gpu_id
        return target

    core.resolve_gpu = resolve_gpu
    return config
