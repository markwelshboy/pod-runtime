#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_BASE_PATH = Path(__file__).with_name("custom_nodes_profile_report.py")
_SPEC = importlib.util.spec_from_file_location("pod_runtime_custom_nodes_profile_report", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load profile report tool: {_BASE_PATH}")
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)


def quality_class(run: dict[str, Any]) -> str:
    quality = run.get("quality")
    if not isinstance(quality, dict):
        return "legacy"
    return str(quality.get("classification") or "unknown")


def include_run(run: dict[str, Any], mode: str) -> bool:
    classification = quality_class(run)
    if mode == "all":
        return True
    if mode == "healthy":
        return bool(run.get("quality", {}).get("include_in_performance_baseline"))
    if mode == "degraded":
        return classification == "degraded"
    if mode == "non-comparable":
        return classification in {"non-comparable", "unknown", "legacy"}
    return False


def quality_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for run in runs:
        key = quality_class(run)
        result[key] = result.get(key, 0) + 1
    return result


def print_report(report: dict[str, Any], profile_dir: Path, selected: int, total: int, mode: str, counts: dict[str, int]) -> None:
    summary = report["run_summary"]
    print(f"Profile directory : {profile_dir}")
    print(f"Quality selection : {mode}")
    print(f"Runs selected     : {selected}/{total}")
    print(
        "Run quality       : "
        + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
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
                base.human_bytes(item["download_bytes_observed"]),
                item["hint"],
            ]
        )
    base.print_table(
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
    print("Default reporting uses only runs explicitly marked healthy/comparable.")
    print("Use --quality all to inspect degraded, dry-run, failed, unknown, and legacy runs.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate quality-aware custom-node installation profiles")
    parser.add_argument("--profile-dir", type=Path, default=base.profile_dir_default())
    parser.add_argument("--runs", type=int, default=20, help="Most recent collected runs to inspect; 0 means all")
    parser.add_argument("--min-runs", type=int, default=1)
    parser.add_argument(
        "--quality",
        choices=["healthy", "all", "degraded", "non-comparable"],
        default="healthy",
        help="run-quality population to aggregate",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    all_runs = base.load_runs(args.profile_dir.expanduser(), args.runs)
    if not all_runs:
        print(f"No custom-node profiles found in {args.profile_dir}", file=sys.stderr)
        return 1

    counts = quality_counts(all_runs)
    selected_runs = [run for run in all_runs if include_run(run, args.quality)]
    if not selected_runs:
        print(
            f"No runs matched quality={args.quality}; collected quality counts: {counts}",
            file=sys.stderr,
        )
        return 1

    report = base.aggregate(selected_runs)
    report["nodes"] = [item for item in report["nodes"] if item["runs"] >= args.min_runs]
    report["quality_selection"] = args.quality
    report["collection_run_count"] = len(all_runs)
    report["quality_counts"] = counts

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print_report(
        report,
        args.profile_dir,
        selected=len(selected_runs),
        total=len(all_runs),
        mode=args.quality,
        counts=counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
