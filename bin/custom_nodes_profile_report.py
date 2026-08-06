#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def profile_dir_default() -> Path:
    log_dir = Path(
        os.environ.get(
            "CUSTOM_LOG_DIR",
            os.environ.get("COMFY_LOGS", "/workspace/logs") + "/custom_nodes",
        )
    )
    return Path(os.environ.get("CUSTOM_NODE_PROFILE_DIR", str(log_dir / "profiles")))


def load_runs(profile_dir: Path, limit: int) -> list[dict[str, Any]]:
    history = profile_dir / "history.jsonl"
    runs: list[dict[str, Any]] = []
    if history.is_file():
        for line in history.read_text(errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                runs.append(value)
    else:
        for path in sorted(profile_dir.glob("run-*.json")):
            try:
                value = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                runs.append(value)
    return runs[-limit:] if limit > 0 else runs


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 2)


def print_table(headers: list[str], rows: list[list[Any]]) -> None:
    rendered = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rendered:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def hint_for(item: dict[str, Any]) -> str:
    change_rate = item["commit_change_rate"]
    pip_median = item["pip_median_seconds"]
    install_py_median = item["install_py_median_seconds"]
    clone_median = item["clone_median_seconds"]
    wheel_builds = item["wheel_builds"]

    if wheel_builds > 0 or install_py_median >= 60:
        return "compiled bundle"
    if change_rate >= 0.50:
        return "keep live/update"
    if item["runs"] < 3:
        return "collect more data"
    if pip_median >= 30:
        return "pip/wheel cache"
    if clone_median >= 30 and change_rate < 0.25:
        return "source cache"
    return "runtime install"


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    node_observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_walls: list[float] = []
    clone_phases: list[float] = []
    install_phases: list[float] = []

    for run in runs:
        timing = run.get("timing", {})
        run_walls.append(number(timing.get("wall_seconds")))
        clone_phases.append(number(timing.get("clone_phase_seconds")))
        install_phases.append(number(timing.get("install_phase_seconds")))
        for node in run.get("nodes", []):
            if isinstance(node, dict) and node.get("id"):
                node_observations[str(node["id"])].append(node)

    rows: list[dict[str, Any]] = []
    total_runs = len(runs)
    for node_id, observations in node_observations.items():
        clone_times = [number(x.get("timing", {}).get("clone_seconds")) for x in observations]
        install_times = [number(x.get("timing", {}).get("install_seconds")) for x in observations]
        total_times = [number(x.get("timing", {}).get("total_seconds")) for x in observations]
        pip_times = [number(x.get("install_profile", {}).get("pip", {}).get("seconds")) for x in observations]
        install_py_times = [
            number(x.get("install_profile", {}).get("install_py", {}).get("seconds"))
            for x in observations
        ]
        commits = [str(x.get("source_profile", {}).get("commit_after", "")) for x in observations]
        commits = [value for value in commits if value]
        local_changes = sum(bool(x.get("source_profile", {}).get("commit_changed")) for x in observations)
        commit_transitions = sum(left != right for left, right in zip(commits, commits[1:]))
        transition_rate = commit_transitions / max(1, len(commits) - 1) if commits else 0.0
        local_change_rate = local_changes / len(observations)
        observed_change_rate = max(transition_rate, local_change_rate)
        failures = sum(x.get("clone") == "failed" or x.get("install") == "failed" for x in observations)
        cache_hits = sum(
            int(x.get("install_profile", {}).get("pip", {}).get("using_cached_count", 0) or 0)
            + int(x.get("install_profile", {}).get("install_py", {}).get("using_cached_count", 0) or 0)
            for x in observations
        )
        downloads = sum(
            int(x.get("install_profile", {}).get("pip", {}).get("download_count", 0) or 0)
            + int(x.get("install_profile", {}).get("install_py", {}).get("download_count", 0) or 0)
            for x in observations
        )
        download_bytes = sum(
            int(x.get("install_profile", {}).get("pip", {}).get("download_bytes_observed", 0) or 0)
            + int(x.get("install_profile", {}).get("install_py", {}).get("download_bytes_observed", 0) or 0)
            for x in observations
        )
        wheel_builds = sum(
            int(x.get("install_profile", {}).get("pip", {}).get("wheel_build_count", 0) or 0)
            + int(x.get("install_profile", {}).get("install_py", {}).get("wheel_build_count", 0) or 0)
            for x in observations
        )

        row = {
            "id": node_id,
            "runs": len(observations),
            "use_rate": round(len(observations) / total_runs, 3) if total_runs else 0.0,
            "success_rate": round((len(observations) - failures) / len(observations), 3),
            "distinct_commits": len(set(commits)),
            "commit_change_rate": round(observed_change_rate, 3),
            "clone_median_seconds": median(clone_times),
            "pip_median_seconds": median(pip_times),
            "install_py_median_seconds": median(install_py_times),
            "install_median_seconds": median(install_times),
            "total_median_seconds": median(total_times),
            "total_p90_seconds": percentile(total_times, 0.90),
            "cache_hits": cache_hits,
            "downloads": downloads,
            "download_bytes_observed": download_bytes,
            "wheel_builds": wheel_builds,
        }
        row["bake_value"] = round(row["use_rate"] * row["total_median_seconds"], 2)
        row["hint"] = hint_for(row)
        rows.append(row)

    rows.sort(key=lambda item: (item["bake_value"], item["total_median_seconds"]), reverse=True)
    return {
        "runs": total_runs,
        "run_summary": {
            "wall_median_seconds": median(run_walls),
            "clone_phase_median_seconds": median(clone_phases),
            "install_phase_median_seconds": median(install_phases),
        },
        "nodes": rows,
    }


def human_bytes(value: int) -> str:
    size = float(value)
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or suffix == "TB":
            return f"{size:.1f}{suffix}"
        size /= 1000
    return f"{size:.1f}TB"


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate custom-node installation profiles")
    parser.add_argument("--profile-dir", type=Path, default=profile_dir_default())
    parser.add_argument("--runs", type=int, default=20, help="Most recent runs to include; 0 means all")
    parser.add_argument("--min-runs", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    runs = load_runs(args.profile_dir.expanduser(), args.runs)
    if not runs:
        print(f"No custom-node profiles found in {args.profile_dir}", file=sys.stderr)
        return 1

    report = aggregate(runs)
    report["nodes"] = [item for item in report["nodes"] if item["runs"] >= args.min_runs]
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    summary = report["run_summary"]
    print(f"Profile directory : {args.profile_dir}")
    print(f"Runs analysed     : {report['runs']}")
    print(f"Median wall time  : {summary['wall_median_seconds']:.1f}s")
    print(f"Median clone phase: {summary['clone_phase_median_seconds']:.1f}s")
    print(f"Median install    : {summary['install_phase_median_seconds']:.1f}s")
    print()

    rows = []
    for item in report["nodes"]:
        rows.append(
            [
                item["id"],
                item["runs"],
                f"{item['use_rate'] * 100:.0f}%",
                f"{item['success_rate'] * 100:.0f}%",
                f"{item['commit_change_rate'] * 100:.0f}%",
                f"{item['clone_median_seconds']:.1f}",
                f"{item['pip_median_seconds']:.1f}",
                f"{item['install_py_median_seconds']:.1f}",
                f"{item['total_median_seconds']:.1f}",
                item["wheel_builds"],
                human_bytes(item["download_bytes_observed"]),
                item["hint"],
            ]
        )
    print_table(
        [
            "NODE",
            "RUNS",
            "USE",
            "OK",
            "CHANGED",
            "GIT(s)",
            "PIP(s)",
            "INST.PY(s)",
            "TOTAL(s)",
            "BUILDS",
            "DL OBS",
            "HEURISTIC",
        ],
        rows,
    )
    print()
    print("CHANGED is the observed local checkout commit-change rate, not a promise of upstream stability.")
    print("DL OBS is parsed from pip log size annotations and may undercount streamed or unlabelled transfers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
