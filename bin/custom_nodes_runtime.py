#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_TELEMETRY_PATH = Path(__file__).with_name("custom_nodes_telemetry.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_telemetry", _TELEMETRY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load custom-node telemetry installer: {_TELEMETRY_PATH}")
telemetry = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(telemetry)

base = telemetry.base
_ORIGINAL_QUALITY_PROFILE = telemetry._quality_profile


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def quality_profile_with_git_evidence(report: dict) -> dict:
    quality = _ORIGINAL_QUALITY_PROFILE(report)
    network = quality.setdefault("network", {})

    longest_git_seconds = 0.0
    for node in report.get("nodes", []):
        try:
            seconds = float(node.get("source_profile", {}).get("git", {}).get("seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        longest_git_seconds = max(longest_git_seconds, seconds)
    network["longest_git_seconds"] = round(longest_git_seconds, 3)

    slow_rate_limit = _float_env("CUSTOM_NODE_QUALITY_SLOW_TRANSFER_BPS", 5_000_000.0)
    long_git_limit = _float_env("CUSTOM_NODE_QUALITY_LONG_GIT_SECONDS", 60.0)
    median_rate = float(network.get("transfer_rate_median_bytes_per_second", 0.0) or 0.0)

    slow_git = (
        longest_git_seconds >= long_git_limit
        and median_rate > 0
        and median_rate < slow_rate_limit
    )
    reasons = quality.setdefault("reasons", [])
    if slow_git and "slow_observed_git_transfer" not in reasons:
        reasons.append("slow_observed_git_transfer")
        # Preserve dry-run/failed as non-comparable; otherwise classify the host/run
        # as degraded and exclude it from performance medians.
        if quality.get("classification") not in {"non-comparable", "unknown"}:
            quality["classification"] = "degraded"
        quality["include_in_performance_baseline"] = False

    quality.setdefault("thresholds", {})["long_git_seconds"] = long_git_limit
    return quality


telemetry._quality_profile = quality_profile_with_git_evidence


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
