#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_HARDENED_PATH = Path(__file__).with_name("custom_nodes_hardened.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_hardened", _HARDENED_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load hardened custom-node installer: {_HARDENED_PATH}")
hardened = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hardened)

profiled = hardened.profiled
base = hardened.base
_ORIGINAL_PERSIST_PROFILE = profiled.persist_profile
_ORIGINAL_BASE_INSTALL = base.install
_ACTIVE_SAMPLER: HostQualitySampler | None = None

_RATE_RE = re.compile(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)\s*([kKmMgGtT](?:i)?B|B)/s")
_PROGRESS_TOTAL_RE = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMgGtT])\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*\2"
)


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _read_pressure(kind: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    text = _read_text(Path("/proc/pressure") / kind)
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


def _read_cpu_stat() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in _read_text(Path("/sys/fs/cgroup/cpu.stat")).splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            result[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return result


def _effective_cpus() -> float:
    logical = float(os.cpu_count() or 1)
    text = _read_text(Path("/sys/fs/cgroup/cpu.max")).strip()
    if not text:
        return logical
    parts = text.split()
    if len(parts) != 2 or parts[0] == "max":
        return logical
    try:
        quota = float(parts[0])
        period = float(parts[1])
        if quota > 0 and period > 0:
            return max(0.01, min(logical, quota / period))
    except ValueError:
        pass
    return logical


def _loadavg() -> tuple[float, float, float]:
    try:
        first = Path("/proc/loadavg").read_text().split()[:3]
        return tuple(float(value) for value in first)  # type: ignore[return-value]
    except (OSError, ValueError):
        return 0.0, 0.0, 0.0


def _memory_value(name: str) -> int | None:
    text = _read_text(Path("/sys/fs/cgroup") / name).strip()
    if not text or text == "max":
        return None
    try:
        return int(text)
    except ValueError:
        return None


class HostQualitySampler:
    def __init__(self) -> None:
        self.interval = max(0.25, _float_env("CUSTOM_NODE_QUALITY_SAMPLE_INTERVAL", 1.0))
        self.samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started = time.monotonic()
        self.cpu_stat_start = _read_cpu_stat()
        self.cpu_stat_last = dict(self.cpu_stat_start)
        self.effective_cpus = _effective_cpus()

    def _sample(self) -> None:
        load1, load5, load15 = _loadavg()
        sample = {
            "monotonic": time.monotonic(),
            "load1": load1,
            "load5": load5,
            "load15": load15,
            "cpu": _read_pressure("cpu"),
            "io": _read_pressure("io"),
            "memory": _read_pressure("memory"),
            "memory_current": _memory_value("memory.current"),
            "memory_max": _memory_value("memory.max"),
        }
        cpu_stat = _read_cpu_stat()
        if cpu_stat:
            self.cpu_stat_last = cpu_stat
        with self._lock:
            self.samples.append(sample)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def start(self) -> None:
        self._sample()
        self._thread = threading.Thread(target=self._run, name="custom-node-quality", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 2))
        self._sample()

    def snapshot(self) -> dict[str, Any]:
        self._sample()
        with self._lock:
            samples = list(self.samples)

        def peak(kind: str, mode: str = "some", field: str = "avg10") -> float:
            values = [
                float(sample.get(kind, {}).get(mode, {}).get(field, 0.0) or 0.0)
                for sample in samples
            ]
            return round(max(values, default=0.0), 3)

        wall_seconds = max(0.001, time.monotonic() - self.started)
        start = self.cpu_stat_start
        end = self.cpu_stat_last
        throttled_usec = max(0, end.get("throttled_usec", 0) - start.get("throttled_usec", 0))
        periods = max(0, end.get("nr_periods", 0) - start.get("nr_periods", 0))
        throttled_periods = max(0, end.get("nr_throttled", 0) - start.get("nr_throttled", 0))
        throttled_vs_wall = throttled_usec / (wall_seconds * 1_000_000.0)
        throttled_period_fraction = throttled_periods / periods if periods else 0.0
        load1_peak = max((float(sample.get("load1", 0.0)) for sample in samples), default=0.0)

        memory_ratios = []
        for sample in samples:
            current = sample.get("memory_current")
            maximum = sample.get("memory_max")
            if isinstance(current, int) and isinstance(maximum, int) and maximum > 0:
                memory_ratios.append(current / maximum)

        return {
            "samples": len(samples),
            "sample_interval_seconds": self.interval,
            "wall_seconds_observed": round(wall_seconds, 3),
            "logical_cpus": os.cpu_count() or 1,
            "effective_cpus": round(self.effective_cpus, 3),
            "load1_peak": round(load1_peak, 3),
            "load1_per_effective_cpu_peak": round(load1_peak / max(self.effective_cpus, 0.01), 3),
            "cpu_psi_some_avg10_peak": peak("cpu"),
            "cpu_psi_full_avg10_peak": peak("cpu", "full"),
            "io_psi_some_avg10_peak": peak("io"),
            "io_psi_full_avg10_peak": peak("io", "full"),
            "memory_psi_some_avg10_peak": peak("memory"),
            "memory_psi_full_avg10_peak": peak("memory", "full"),
            "cpu_throttled_usec_delta": throttled_usec,
            "cpu_throttled_time_vs_wall_ratio": round(throttled_vs_wall, 4),
            "cpu_periods_delta": periods,
            "cpu_throttled_periods_delta": throttled_periods,
            "cpu_throttled_period_fraction": round(throttled_period_fraction, 4),
            "memory_cgroup_fraction_peak": round(max(memory_ratios, default=0.0), 4),
        }


def _rate_bytes_per_second(value: float, unit: str) -> float:
    normalized = unit.lower()
    binary = "i" in normalized
    prefix = normalized[0] if normalized != "b" else ""
    order = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}.get(prefix, 0)
    return value * ((1024 if binary else 1000) ** order)


def _progress_bytes(value: float, unit: str) -> float:
    order = {"k": 1, "m": 2, "g": 3, "t": 4}.get(unit.lower(), 0)
    return value * (1000**order)


def _current_run_log_section(node: dict) -> str:
    path = Path(str(node.get("log") or ""))
    text = _read_text(path)
    if not text:
        return ""
    node_id = str(node.get("id") or "")
    marker = f"== clone/update {node_id} at "
    index = text.rfind(marker)
    if index < 0:
        marker = f"== dependency install {node_id} at "
        index = text.rfind(marker)
    return text[index:] if index >= 0 else text


def _network_profile(report: dict) -> dict[str, Any]:
    rates: list[float] = []
    tqdm_bytes = 0.0
    for node in report.get("nodes", []):
        section = _current_run_log_section(node)
        if not section:
            continue
        node_rates = [
            _rate_bytes_per_second(float(value), unit)
            for value, unit in _RATE_RE.findall(section)
        ]
        if len(node_rates) > 500:
            node_rates = node_rates[-500:]
        rates.extend(node_rates)

        totals = [
            _progress_bytes(float(total), unit)
            for _done, unit, total in _PROGRESS_TOTAL_RE.findall(section)
        ]
        if totals:
            tqdm_bytes += max(totals)

    pip_bytes = 0
    for node in report.get("nodes", []):
        install = node.get("install_profile", {})
        pip_bytes += int(install.get("pip", {}).get("download_bytes_observed", 0) or 0)
        pip_bytes += int(install.get("install_py", {}).get("download_bytes_observed", 0) or 0)

    median_bps = statistics.median(rates) if rates else 0.0
    return {
        "transfer_rate_samples": len(rates),
        "transfer_rate_min_bytes_per_second": round(min(rates), 1) if rates else 0.0,
        "transfer_rate_median_bytes_per_second": round(median_bps, 1),
        "transfer_rate_max_bytes_per_second": round(max(rates), 1) if rates else 0.0,
        "pip_download_bytes_observed": pip_bytes,
        "progress_total_bytes_observed": int(tqdm_bytes),
        "large_transfer_bytes_evidence": max(pip_bytes, int(tqdm_bytes)),
    }


def _quality_profile(report: dict) -> dict[str, Any]:
    host = _ACTIVE_SAMPLER.snapshot() if _ACTIVE_SAMPLER is not None else {"samples": 0}
    network = _network_profile(report)

    cpu_psi_limit = _float_env("CUSTOM_NODE_QUALITY_CPU_PSI_LIMIT", 20.0)
    io_psi_limit = _float_env("CUSTOM_NODE_QUALITY_IO_PSI_LIMIT", 10.0)
    memory_psi_limit = _float_env("CUSTOM_NODE_QUALITY_MEMORY_PSI_LIMIT", 5.0)
    throttle_limit = _float_env("CUSTOM_NODE_QUALITY_CPU_THROTTLE_LIMIT", 0.15)
    slow_rate_limit = _float_env("CUSTOM_NODE_QUALITY_SLOW_TRANSFER_BPS", 5_000_000.0)
    large_transfer_limit = _float_env("CUSTOM_NODE_QUALITY_LARGE_TRANSFER_BYTES", 50_000_000.0)

    degraded: list[str] = []
    non_comparable: list[str] = []

    if bool(report.get("dry_run")):
        non_comparable.append("dry_run")
    if int(report.get("summary", {}).get("failed", 0) or 0) > 0:
        non_comparable.append("run_failed")

    if float(host.get("cpu_psi_some_avg10_peak", 0.0) or 0.0) >= cpu_psi_limit:
        degraded.append("high_cpu_pressure")
    if float(host.get("io_psi_some_avg10_peak", 0.0) or 0.0) >= io_psi_limit:
        degraded.append("high_io_pressure")
    if float(host.get("memory_psi_some_avg10_peak", 0.0) or 0.0) >= memory_psi_limit:
        degraded.append("high_memory_pressure")
    if float(host.get("cpu_throttled_time_vs_wall_ratio", 0.0) or 0.0) >= throttle_limit:
        degraded.append("cpu_throttling")

    large_bytes = float(network.get("large_transfer_bytes_evidence", 0.0) or 0.0)
    median_rate = float(network.get("transfer_rate_median_bytes_per_second", 0.0) or 0.0)
    if large_bytes >= large_transfer_limit and median_rate > 0 and median_rate < slow_rate_limit:
        degraded.append("slow_observed_transfer")

    if non_comparable:
        classification = "non-comparable"
        include = False
        reasons = non_comparable + degraded
    elif int(host.get("samples", 0) or 0) == 0:
        classification = "unknown"
        include = False
        reasons = ["host_quality_unavailable"] + degraded
    elif degraded:
        classification = "degraded"
        include = False
        reasons = degraded
    else:
        classification = "healthy"
        include = True
        reasons = []

    return {
        "schema_version": 1,
        "classification": classification,
        "include_in_performance_baseline": include,
        "reasons": reasons,
        "host": host,
        "network": network,
        "thresholds": {
            "cpu_psi_some_avg10": cpu_psi_limit,
            "io_psi_some_avg10": io_psi_limit,
            "memory_psi_some_avg10": memory_psi_limit,
            "cpu_throttled_time_vs_wall_ratio": throttle_limit,
            "slow_transfer_bytes_per_second": slow_rate_limit,
            "large_transfer_bytes": large_transfer_limit,
        },
    }


def _hff_python() -> Path:
    configured = os.environ.get("HFF_VENV", "")
    if configured:
        candidate = Path(configured) / "bin" / "python"
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def publish_profile(run_path: Path, report: dict) -> None:
    if not _enabled("CUSTOM_NODE_PROFILE_PUBLISH", True):
        return
    if not os.environ.get("HF_TOKEN"):
        print(
            "[custom-nodes] profile publish skipped: HF_TOKEN is not set",
            file=sys.stderr,
            flush=True,
        )
        return

    repo = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO")
        or os.environ.get("HFF_REPO")
        or os.environ.get("HF_MY_REPO_ID")
        or ""
    ).strip()
    if not repo:
        print(
            "[custom-nodes] profile publish skipped: no telemetry repository configured",
            file=sys.stderr,
            flush=True,
        )
        return

    repo_type = (
        os.environ.get("CUSTOM_NODE_PROFILE_REPO_TYPE")
        or os.environ.get("HFF_REPO_TYPE")
        or os.environ.get("HF_MY_REPO_TYPE")
        or "model"
    ).strip()
    if repo_type not in {"model", "dataset"}:
        repo_type = "model"

    prefix = (
        os.environ.get("CUSTOM_NODE_PROFILE_REMOTE_PREFIX")
        or os.environ.get("HFF_TELEMETRY_PREFIX")
        or "telemetry/custom_nodes/v1"
    ).strip()

    telemetry_py = Path(
        os.environ.get("HFF_TELEMETRY_PY") or Path(__file__).with_name("hff_telemetry.py")
    )
    if not telemetry_py.is_file():
        print(
            f"[custom-nodes] profile publish skipped: hff telemetry helper not found: {telemetry_py}",
            file=sys.stderr,
            flush=True,
        )
        return

    try:
        timeout = max(1.0, float(os.environ.get("CUSTOM_NODE_PROFILE_PUBLISH_TIMEOUT", "45")))
    except ValueError:
        timeout = 45.0

    command = [
        str(_hff_python()),
        str(telemetry_py),
        "--repo",
        repo,
        "--type",
        repo_type,
        "--prefix",
        prefix,
        str(run_path),
        "--message",
        f"custom-node profile {report.get('run_id', run_path.stem)}",
    ]

    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        print(
            f"[custom-nodes] profile publish timed out after {timeout:g}s; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return
    except Exception as error:
        print(
            f"[custom-nodes] profile publish failed: {error}; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"hff telemetry exited {completed.returncode}"
        print(
            f"[custom-nodes] profile publish failed: {message}; local profile kept at {run_path}",
            file=sys.stderr,
            flush=True,
        )
        return

    uri = (completed.stdout or "").strip().splitlines()
    published = uri[-1] if uri else "<unknown>"
    print(
        f"[custom-nodes] profile published: {published}",
        file=sys.stderr,
        flush=True,
    )


def persist_and_publish(report: dict, status_path: Path, log_dir: Path) -> Path:
    report["quality"] = _quality_profile(report)
    run_path = _ORIGINAL_PERSIST_PROFILE(report, status_path, log_dir)
    quality = report["quality"]
    print(
        "[custom-nodes] run quality: "
        f"{quality.get('classification')}"
        + (f" ({', '.join(quality.get('reasons', []))})" if quality.get("reasons") else ""),
        file=sys.stderr,
        flush=True,
    )
    publish_profile(run_path, report)
    return run_path


def install_with_quality(args, manifest: dict) -> int:
    global _ACTIVE_SAMPLER
    sampler = HostQualitySampler()
    _ACTIVE_SAMPLER = sampler
    sampler.start()
    try:
        return _ORIGINAL_BASE_INSTALL(args, manifest)
    finally:
        sampler.stop()
        _ACTIVE_SAMPLER = None


# profiled_install resolves persist_profile through its module globals, so replacing
# the module attribute adds quality metadata + publication without changing the
# underlying profiler. base.install is wrapped so host sampling spans the whole run.
profiled.persist_profile = persist_and_publish
base.install = install_with_quality


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("custom_nodes: interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
