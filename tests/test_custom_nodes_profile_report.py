from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "custom_nodes_profile_report.py"
spec = importlib.util.spec_from_file_location("custom_nodes_profile_report", MODULE_PATH)
assert spec and spec.loader
profile_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_report)


def node(commit: str, *, pip: float = 0, install_py: float = 0, total: float = 0, builds: int = 0):
    return {
        "id": "kjnodes",
        "clone": "ok",
        "install": "installed",
        "source_profile": {"commit_after": commit, "commit_changed": False},
        "timing": {"clone_seconds": 2, "install_seconds": pip + install_py, "total_seconds": total},
        "install_profile": {
            "pip": {"seconds": pip, "wheel_build_count": builds},
            "install_py": {"seconds": install_py, "wheel_build_count": 0},
        },
    }


def run(item):
    return {
        "timing": {"wall_seconds": 10, "clone_phase_seconds": 2, "install_phase_seconds": 8},
        "nodes": [item],
    }


def test_commit_transitions_mark_fast_moving_node_live():
    report = profile_report.aggregate(
        [run(node("a", total=3)), run(node("b", total=3)), run(node("c", total=3))]
    )
    item = report["nodes"][0]
    assert item["commit_change_rate"] == 1.0
    assert item["hint"] == "keep live/update"


def test_wheel_build_has_priority_over_update_rate():
    report = profile_report.aggregate(
        [run(node("a", pip=90, total=92, builds=1)), run(node("b", pip=90, total=92, builds=1))]
    )
    assert report["nodes"][0]["hint"] == "compiled bundle"
