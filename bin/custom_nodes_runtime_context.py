#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUNTIME_PATH = Path(__file__).with_name("custom_nodes_runtime.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_runtime", _RUNTIME_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load custom-node runtime installer: {_RUNTIME_PATH}")
runtime = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runtime)

base = runtime.base
_ORIGINAL_QUALITY_PROFILE = runtime.telemetry._quality_profile
_ORIGINAL_INSTALL = base.install


def _observed_build_count(report: dict[str, Any]) -> int:
    total = 0
    for node in report.get("nodes", []):
        install_profile = node.get("install_profile", {})
        for phase in ("pip", "install_py"):
            profile = install_profile.get(phase, {})
            try:
                total += int(profile.get("wheel_build_count", 0) or 0)
            except (TypeError, ValueError):
                pass
    return total


def quality_profile_with_context_semantics(report: dict[str, Any]) -> dict[str, Any]:
    quality = _ORIGINAL_QUALITY_PROFILE(report)
    context = quality.setdefault("measurement_context", {})
    flags = context.setdefault("flags", [])

    build_count = _observed_build_count(report)
    context["observed_build_count"] = build_count
    if build_count > 0 and "native_or_wheel_build_activity" not in flags:
        flags.append("native_or_wheel_build_activity")

    reasons = quality.setdefault("reasons", [])
    hf_concurrent = "concurrent_model_provisioning" in flags

    # Cgroup-local IO pressure is real, but when it coincides with our own model
    # provisioner it is expected startup contention rather than evidence that the
    # provider host itself is unhealthy. Keep the run out of intrinsic node timing
    # medians while preserving it as a valid real-world cold-start sample.
    if hf_concurrent and "high_io_pressure" in reasons:
        reasons.remove("high_io_pressure")
        if "concurrent_model_io_contention" not in reasons:
            reasons.append("concurrent_model_io_contention")
        quality.setdefault("observations", []).append(
            "cgroup_io_pressure_observed_during_concurrent_model_provisioning"
        )
        context["contention_attribution"] = "model_provisioning"
        if quality.get("classification") == "degraded":
            quality["classification"] = "context-contended"
        quality["include_in_performance_baseline"] = False

    return quality


def _quarantine_disabled_nodes(args: Any, manifest: dict[str, Any]) -> list[tuple[str, Path, Path]]:
    """Move already-present runtime-disabled nodes out of ComfyUI's load path.

    Filtering a disabled ID out of the install plan is not enough when a persistent
    workspace already contains that checkout. ComfyUI ignores directories whose
    names end in ``.disabled``, so keep the checkout recoverable but inert.
    """
    disabled = sorted(runtime._disabled_node_ids())
    if not disabled:
        return []

    custom_dir = Path(
        getattr(args, "custom_dir", None)
        or runtime.os.environ.get(
            "CUSTOM_DIR",
            runtime.os.environ.get("COMFY_HOME", "/workspace/ComfyUI") + "/custom_nodes",
        )
    )
    nodes = manifest.get("nodes", {})
    if not isinstance(nodes, dict):
        return []

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantined: list[tuple[str, Path, Path]] = []
    for node_id in disabled:
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        active = custom_dir / base.local_name(node)
        if not (active.exists() or active.is_symlink()):
            continue

        target = custom_dir / f"{active.name}.{stamp}.disabled"
        sequence = 1
        while target.exists() or target.is_symlink():
            target = custom_dir / f"{active.name}.{stamp}.{sequence}.disabled"
            sequence += 1

        active.rename(target)
        quarantined.append((node_id, active, target))
        print(
            f"[custom-nodes] quarantined runtime-disabled node {node_id}: "
            f"{active} -> {target}",
            file=sys.stderr,
            flush=True,
        )

    return quarantined


def install_with_disabled_node_quarantine(args: Any, manifest: dict[str, Any]) -> int:
    _quarantine_disabled_nodes(args, manifest)
    return _ORIGINAL_INSTALL(args, manifest)


runtime.telemetry._quality_profile = quality_profile_with_context_semantics
base.install = install_with_disabled_node_quarantine


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
