import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

import pod_snapshot_cli as cli  # noqa: E402
import pod_snapshot_display as display  # noqa: E402


class SnapshotDisplayTests(unittest.TestCase):
    def setUp(self):
        # install_cli_hooks is process-global; reset it so every test can install
        # against the imported CLI module deterministically.
        display._installed = False

    def _snapshots(self):
        return [
            {
                "id": "20260915_174351__qwen3-captioning",
                "created_utc": "2026-09-16T00:43:51Z",
                "journal": {
                    "name": "latest work",
                    "next": "Carry on",
                    "tags": ["qwen3"],
                    "pinned": False,
                },
            },
            {
                "id": "20260914_181517__qwen3-captioning",
                "created_utc": "2026-09-15T01:15:17Z",
                "journal": {"name": "older", "tags": [], "pinned": True},
            },
        ]

    def test_list_shows_full_snapshot_ids_and_local_time(self):
        display.install_cli_hooks(cli)
        snapshots = self._snapshots()

        out = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"POD_TIMEZONE": "America/Los_Angeles"},
            clear=False,
        ), contextlib.redirect_stdout(out):
            cli.print_snapshot_list(snapshots, "qwen3-captioning")
        rendered = out.getvalue()

        self.assertIn("SNAPSHOT ID", rendered)
        self.assertIn("20260915_174351__qwen3-captioning", rendered)
        self.assertIn("20260914_181517__qwen3-captioning", rendered)
        self.assertIn("Sep 15 17:43 PDT", rendered)
        self.assertIn("Sep 14 18:15 PDT", rendered)
        self.assertNotIn("Sep 16 00:43Z", rendered)
        self.assertIn("latest work", rendered)
        self.assertIn("older", rendered)

    def test_next_is_aligned_with_name_column(self):
        display.install_cli_hooks(cli)

        out = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"POD_TIMEZONE": "America/Los_Angeles"},
            clear=False,
        ), contextlib.redirect_stdout(out):
            cli.print_snapshot_list(self._snapshots(), "qwen3-captioning")
        lines = out.getvalue().splitlines()

        header = next(line for line in lines if "SNAPSHOT ID" in line and "NAME" in line)
        next_line = next(line for line in lines if "Next: Carry on" in line)
        self.assertEqual(header.index("NAME"), next_line.index("Next:"))

    def test_detail_uses_local_time(self):
        display.install_cli_hooks(cli)

        out = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"POD_TIMEZONE": "America/Los_Angeles"},
            clear=False,
        ), contextlib.redirect_stdout(out):
            cli.print_snapshot_detail(self._snapshots()[0], "qwen3-captioning")
        rendered = out.getvalue()

        self.assertIn("Created:  Sep 15 17:43 PDT", rendered)


if __name__ == "__main__":
    unittest.main()
