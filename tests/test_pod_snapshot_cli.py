import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

MODULE_PATH = BIN_DIR / "pod_snapshot_cli.py"
SPEC = importlib.util.spec_from_file_location("pod_snapshot_cli", MODULE_PATH)
pod_snapshot_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pod_snapshot_cli)


def snapshot(sid: str, created: str, *, pinned: bool = False, name: str = "") -> dict:
    meta = {
        "id": sid,
        "name": "qwen3-captioning",
        "created_utc": created,
        "tar": {"bytes": 1024, "basename": f"{sid}.tar", "compress": "none"},
    }
    if pinned or name:
        meta["journal"] = {
            "schema_version": 1,
            "name": name,
            "note": "",
            "next": "",
            "tags": [],
            "pinned": pinned,
            "parent_snapshot": None,
        }
    return meta


class JournalTests(unittest.TestCase):
    def test_legacy_custom_snapshot_name_is_display_fallback(self):
        meta = {"id": "20260901_120000__baseline", "name": "baseline"}
        journal = pod_snapshot_cli.journal(meta, "qwen3-captioning")
        self.assertEqual(journal["name"], "baseline")

    def test_patch_preserves_unspecified_metadata(self):
        meta = {
            "id": "sid",
            "name": "qwen3-captioning",
            "journal": {
                "schema_version": 1,
                "name": "Baseline",
                "note": "Known good",
                "next": "Try prompt B",
                "tags": ["baseline", "qwen"],
                "pinned": False,
                "parent_snapshot": "parent",
            },
        }
        updated = pod_snapshot_cli.update_journal(
            "qwen3-captioning", meta, add_tags=["pose"], pinned=True
        )
        journal = updated["journal"]
        self.assertEqual(journal["name"], "Baseline")
        self.assertEqual(journal["note"], "Known good")
        self.assertEqual(journal["next"], "Try prompt B")
        self.assertEqual(journal["parent_snapshot"], "parent")
        self.assertEqual(journal["tags"], ["baseline", "pose", "qwen"])
        self.assertTrue(journal["pinned"])


class ParserTests(unittest.TestCase):
    def test_bare_configure_remains_fresh(self):
        args = pod_snapshot_cli.configure_parser().parse_args(["qwen3-captioning"])
        self.assertEqual(args.snapshot, "")

    def test_bare_snapshot_option_invokes_picker(self):
        args = pod_snapshot_cli.configure_parser().parse_args(["qwen3-captioning", "--snapshot"])
        self.assertEqual(args.snapshot, pod_snapshot_cli.PICK_SNAPSHOT)

    def test_bare_configure_never_loads_snapshot_history(self):
        with mock.patch.object(
            pod_snapshot_cli.core, "load_template", return_value={"name": "qwen3-captioning"}
        ), mock.patch.object(
            pod_snapshot_cli, "load_snapshots", side_effect=AssertionError("snapshot history should not be read")
        ), mock.patch.object(
            pod_snapshot_cli.core, "cmd_configure", return_value=0
        ) as configure:
            result = pod_snapshot_cli.cmd_configure(["qwen3-captioning", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertEqual(configure.call_args.args[0].snapshot, "")


class RetentionTests(unittest.TestCase):
    def test_retention_protects_recent_grace_daily_weekly_and_pinned(self):
        snapshots = [
            snapshot("20260910_110000__q", "2026-09-10T11:00:00Z"),
            snapshot("20260910_100000__q", "2026-09-10T10:00:00Z"),
            snapshot("20260909_120000__q", "2026-09-09T12:00:00Z"),
            snapshot("20260909_110000__q", "2026-09-09T11:00:00Z"),
            snapshot("20260908_120000__q", "2026-09-08T12:00:00Z"),
            snapshot("20260901_120000__q", "2026-09-01T12:00:00Z"),
            snapshot("20260831_120000__q", "2026-08-31T12:00:00Z"),
            snapshot("20260801_120000__q", "2026-08-01T12:00:00Z", pinned=True),
        ]
        policy = {"recent": 2, "daily": 3, "weekly": 2, "grace_hours": 24}
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        with mock.patch.object(pod_snapshot_cli, "now_utc", return_value=now):
            keep, eligible = pod_snapshot_cli.retention_plan(
                snapshots, "qwen3-captioning", policy
            )
        eligible_ids = {meta["id"] for meta in eligible}
        self.assertIn("20260909_110000__q", eligible_ids)
        self.assertIn("20260831_120000__q", eligible_ids)
        self.assertNotIn("20260910_110000__q", eligible_ids)
        self.assertNotIn("20260909_120000__q", eligible_ids)
        self.assertNotIn("20260908_120000__q", eligible_ids)
        self.assertNotIn("20260901_120000__q", eligible_ids)
        self.assertNotIn("20260801_120000__q", eligible_ids)
        self.assertIn("pinned", keep["20260801_120000__q"])

    def test_unreadable_manifest_is_never_pruned(self):
        meta = {"id": "mystery", "_manifest_unreadable": True}
        policy = {"recent": 0, "daily": 0, "weekly": 0, "grace_hours": 0}
        keep, eligible = pod_snapshot_cli.retention_plan([meta], "qwen3-captioning", policy)
        self.assertIn("mystery", keep)
        self.assertEqual(eligible, [])


class SnapshotCreationTests(unittest.TestCase):
    def test_snapshot_records_parent_and_advances_lineage(self):
        sid = "20260910_120000__qwen3-captioning"
        meta = snapshot(sid, "2026-09-10T12:00:00Z")
        with mock.patch.object(
            pod_snapshot_cli.core, "load_template", return_value={"name": "qwen3-captioning", "snapshot": {}}
        ), mock.patch.object(
            pod_snapshot_cli, "run_core_snapshot", return_value=sid
        ), mock.patch.object(
            pod_snapshot_cli, "load_snapshot", return_value=meta
        ), mock.patch.object(
            pod_snapshot_cli, "get_parent_snapshot", return_value="20260909_120000__qwen3-captioning"
        ), mock.patch.object(
            pod_snapshot_cli, "write_snapshot"
        ) as write_snapshot, mock.patch.object(
            pod_snapshot_cli, "set_parent_snapshot"
        ) as set_parent, mock.patch.object(
            pod_snapshot_cli, "retention_policy", return_value=None
        ):
            result = pod_snapshot_cli.cmd_snapshot_create(["qwen3-captioning"])

        self.assertEqual(result, 0)
        written_meta = write_snapshot.call_args.args[1]
        self.assertEqual(
            written_meta["journal"]["parent_snapshot"],
            "20260909_120000__qwen3-captioning",
        )
        set_parent.assert_called_once_with("qwen3-captioning", sid)


if __name__ == "__main__":
    unittest.main()
