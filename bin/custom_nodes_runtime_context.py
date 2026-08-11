#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
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


runtime.telemetry._quality_profile = quality_profile_with_context_semantics


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
