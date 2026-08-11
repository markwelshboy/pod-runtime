#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

_TELEMETRY_PATH = Path(__file__).with_name("custom_nodes_telemetry.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_telemetry", _TELEMETRY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load custom-node telemetry installer: {_TELEMETRY_PATH}")
telemetry = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(telemetry)

base = telemetry.base
_ORIGINAL_QUALITY_PROFILE = telemetry._quality_profile
_ORIGINAL_READ_PRESSURE = telemetry._read_pressure
_ORIGINAL_EFFECTIVE_CPUS = telemetry._effective_cpus
_ORIGINAL_INSTALL_WITH_QUALITY = base.install
_ORIGINAL_RUNTIME_POLICIES = telemetry.hardened._apply_runtime_policies
_CONTEXT_START: dict[str, Any] = {}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _parse_pressure_text(text: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        values: dict[str, float] = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            key, raw = token.split("=", 1)
            try:
                values[key] = float(raw)
            except ValueError:
                continue
        result[parts[0]] = values
    return result


def _pressure_path(kind: str) -> Path:
    return Path("/sys/fs/cgroup") / f"{kind}.pressure"


def cgroup_aware_pressure(kind: str) -> dict[str, dict[str, float]]:
    """Prefer this container/cgroup's PSI over host-global /proc/pressure."""
    path = _pressure_path(kind)
    try:
        if path.is_file():
            return _parse_pressure_text(path.read_text(errors="replace"))
    except OSError:
        pass
    return _ORIGINAL_READ_PRESSURE(kind)


def _cpuset_count() -> int | None:
    path = Path("/sys/fs/cgroup/cpuset.cpus.effective")
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    if not text:
        return None
    count = 0
    try:
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                start_raw, end_raw = token.split("-", 1)
                start = int(start_raw)
                end = int(end_raw)
                if end >= start:
                    count += end - start + 1
            else:
                int(token)
                count += 1
    except ValueError:
        return None
    return count or None


def effective_cpus_with_cpuset() -> float:
    effective = float(_ORIGINAL_EFFECTIVE_CPUS())
    cpuset = _cpuset_count()
    if cpuset is not None:
        effective = min(effective, float(cpuset))
    return max(0.01, effective)


def _hf_manifest_context() -> dict[str, Any]:
    state = Path(
        os.environ.get(
            "HF_MANIFEST_STATE_DIR",
            str(Path(os.environ.get("COMFY_LOGS", "/workspace/logs")) / "hf_manifest"),
        )
    )
    result: dict[str, Any] = {
        "state_dir": str(state),
        "exists": state.is_dir(),
        "active": False,
        "controller_pid": 0,
        "controller_status": "",
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "known_total_bytes": 0,
    }
    if not state.is_dir():
        return result

    controller: dict[str, Any] = {}
    try:
        controller = json.loads((state / "controller.json").read_text())
    except Exception:
        pass
    try:
        pid = int((state / "controller.pid").read_text().strip())
    except Exception:
        pid = int(controller.get("pid") or 0)

    status = str(controller.get("status") or "")
    active = False
    if pid > 0 and status in {"prepared", "running"}:
        try:
            os.kill(pid, 0)
            active = True
        except OSError:
            pass

    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    known_total = 0
    try:
        for item_path in (state / "items").glob("*.json"):
            try:
                item = json.loads(item_path.read_text())
            except Exception:
                continue
            item_status = str(item.get("status") or "")
            if item_status in counts:
                counts[item_status] += 1
            try:
                known_total += max(0, int(item.get("total_bytes") or 0))
            except (TypeError, ValueError):
                pass
    except OSError:
        pass

    result.update(
        {
            "active": active,
            "controller_pid": pid,
            "controller_status": status,
            "pending": counts["pending"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "known_total_bytes": known_total,
        }
    )
    return result


def _disabled_node_ids() -> set[str]:
    raw = os.environ.get("CUSTOM_NODE_DISABLED_IDS", "")
    return {token.strip() for token in raw.replace(",", " ").split() if token.strip()}


def runtime_policies_with_disabled_nodes(manifest: dict) -> dict:
    effective = _ORIGINAL_RUNTIME_POLICIES(manifest)
    disabled = _disabled_node_ids()
    if not disabled:
        return effective

    nodes = effective.get("nodes", {})
    if isinstance(nodes, dict):
        for node_id in disabled:
            nodes.pop(node_id, None)

    sets = effective.get("sets", {})
    if isinstance(sets, dict):
        for set_name, members in list(sets.items()):
            if isinstance(members, list):
                sets[set_name] = [member for member in members if member not in disabled]
    return effective


def quality_profile_with_runtime_context(report: dict) -> dict:
    quality = _ORIGINAL_QUALITY_PROFILE(report)
    network = quality.setdefault("network", {})
    host = quality.setdefault("host", {})

    longest_git_seconds = 0.0
    build_count = 0
    for node in report.get("nodes", []):
        try:
            seconds = float(node.get("source_profile", {}).get("git", {}).get("seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        longest_git_seconds = max(longest_git_seconds, seconds)
        install_profile = node.get("install_profile", {})
        for phase in ("pip", "install_py"):
            try:
                build_count += int(install_profile.get(phase, {}).get("build_count", 0) or 0)
            except (TypeError, ValueError):
                pass
    network["longest_git_seconds"] = round(longest_git_seconds, 3)

    pressure_sources = {
        kind: ("cgroup" if _pressure_path(kind).is_file() else "host")
        for kind in ("cpu", "io", "memory")
    }
    host["pressure_sources"] = pressure_sources
    host["cpuset_effective_cpus"] = _cpuset_count()

    context_end = _hf_manifest_context()
    hf_concurrent = bool(_CONTEXT_START.get("active") or context_end.get("active"))
    context_flags: list[str] = []
    if hf_concurrent:
        context_flags.append("concurrent_model_provisioning")
    if build_count > 0:
        context_flags.append("native_or_wheel_build_activity")
    quality["measurement_context"] = {
        "comparison_group": "startup-with-hf-downloads" if hf_concurrent else "custom-nodes-only",
        "flags": context_flags,
        "hf_manifest_start": dict(_CONTEXT_START),
        "hf_manifest_end": context_end,
        "observed_build_count": build_count,
    }

    # Host-global /proc/pressure is useful evidence but should not by itself mark a
    # container as degraded. On shared GPU hosts it can reflect unrelated tenants.
    # Prefer cgroup PSI; if unavailable, require corroborating saturation/throttling.
    reasons = quality.setdefault("reasons", [])
    if "high_cpu_pressure" in reasons and pressure_sources["cpu"] == "host":
        load_limit = _float_env("CUSTOM_NODE_QUALITY_CPU_LOAD_LIMIT", 0.8)
        load_ratio = float(host.get("load1_per_effective_cpu_peak", 0.0) or 0.0)
        throttle_ratio = float(host.get("cpu_throttled_time_vs_wall_ratio", 0.0) or 0.0)
        throttle_limit = _float_env("CUSTOM_NODE_QUALITY_CPU_THROTTLE_LIMIT", 0.15)
        if load_ratio < load_limit and throttle_ratio < throttle_limit:
            reasons.remove("high_cpu_pressure")
            quality.setdefault("observations", []).append("host_global_cpu_pressure_not_used_for_gating")
            if quality.get("classification") == "degraded" and not reasons:
                quality["classification"] = "healthy"
                quality["include_in_performance_baseline"] = True

    slow_rate_limit = _float_env("CUSTOM_NODE_QUALITY_SLOW_TRANSFER_BPS", 5_000_000.0)
    long_git_limit = _float_env("CUSTOM_NODE_QUALITY_LONG_GIT_SECONDS", 60.0)
    median_rate = float(network.get("transfer_rate_median_bytes_per_second", 0.0) or 0.0)
    slow_git = (
        longest_git_seconds >= long_git_limit
        and median_rate > 0
        and median_rate < slow_rate_limit
    )
    if slow_git and "slow_observed_git_transfer" not in reasons:
        reasons.append("slow_observed_git_transfer")
        if quality.get("classification") not in {"non-comparable", "unknown"}:
            quality["classification"] = "degraded"
        quality["include_in_performance_baseline"] = False

    quality.setdefault("thresholds", {})["long_git_seconds"] = long_git_limit
    quality.setdefault("thresholds", {})["host_cpu_load_per_effective_cpu"] = _float_env(
        "CUSTOM_NODE_QUALITY_CPU_LOAD_LIMIT", 0.8
    )
    return quality


def install_with_runtime_context(args, manifest: dict) -> int:
    global _CONTEXT_START
    _CONTEXT_START = _hf_manifest_context()
    disabled = sorted(_disabled_node_ids())
    if disabled:
        print(
            "[custom-nodes] runtime-disabled nodes: " + ", ".join(disabled),
            file=sys.stderr,
            flush=True,
        )
    return _ORIGINAL_INSTALL_WITH_QUALITY(args, manifest)


# Patch the telemetry sampler before a HostQualitySampler is instantiated.
telemetry._read_pressure = cgroup_aware_pressure
telemetry._effective_cpus = effective_cpus_with_cpuset
telemetry.hardened._apply_runtime_policies = runtime_policies_with_disabled_nodes
telemetry._quality_profile = quality_profile_with_runtime_context
base.install = install_with_runtime_context


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
