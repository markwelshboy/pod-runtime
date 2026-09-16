import contextlib
import io
import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

import pod_snapshot_cli as cli  # noqa: E402
import pod_snapshot_display as display  # noqa: E402


class SnapshotDisplayTests(unittest.TestCase):
    def test_list_shows_full_snapshot_ids(self):
        display.install_cli_hooks(cli)
        snapshots = [
            {
                "id": "20260915_174351__qwen3-captioning",
                "created_utc": "2026-09-16T00:43:51Z",
                "journal": {"name": "latest work", "tags": ["qwen3"], "pinned": False},
            },
            {
                "id": "20260914_181517__qwen3-captioning",
                "created_utc": "2026-09-15T01:15:17Z",
                "journal": {"name": "older", "tags": [], "pinned": True},
            },
        ]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.print_snapshot_list(snapshots, "qwen3-captioning")
        rendered = out.getvalue()

        self.assertIn("SNAPSHOT ID", rendered)
        self.assertIn("20260915_174351__qwen3-captioning", rendered)
        self.assertIn("20260914_181517__qwen3-captioning", rendered)
        self.assertIn("latest work", rendered)
        self.assertIn("older", rendered)


if __name__ == "__main__":
    unittest.main()
