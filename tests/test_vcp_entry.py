import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "vcp_entry.py"
spec = importlib.util.spec_from_file_location("vcp_entry", MODULE)
vcp_entry = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(vcp_entry)


class VcpEntryTests(unittest.TestCase):
    def test_named_config_and_target_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}):
                self.assertEqual(
                    vcp_entry.main(
                        [
                            "config",
                            "comfydev3900",
                            "ssh",
                            "-i",
                            "/key",
                            "-p",
                            "2222",
                            "root@host",
                        ]
                    ),
                    0,
                )
                self.assertEqual(vcp_entry.main(["target", "comfydev3900"]), 0)
                cfg = json.loads(config.read_text(encoding="utf-8"))

        self.assertEqual(cfg["active_target"], "comfydev3900")
        self.assertEqual(
            cfg["targets"]["comfydev3900"]["ssh"],
            ["-i", "/key", "-p", "2222", "root@host"],
        )

    def test_one_shot_target_projects_selected_ssh_to_existing_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "active_target": "one",
                        "targets": {
                            "one": {"ssh": ["root@one"]},
                            "two": {"ssh": ["-p", "2222", "root@two"]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            captured = {}

            def fake_main(argv):
                captured["argv"] = list(argv)
                captured["cfg"] = vcp_entry.vcp._read_config()
                return 0

            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), \
                 mock.patch.object(vcp_entry.vcp, "main", side_effect=fake_main):
                rc = vcp_entry.main(
                    ["--target", "two", "r:/workspace/report.txt", "."]
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["argv"], ["r:/workspace/report.txt", "."])
        self.assertEqual(captured["cfg"]["ssh"], ["-p", "2222", "root@two"])

    def test_active_target_is_used_when_no_override_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "active_target": "one",
                        "targets": {"one": {"ssh": ["root@one"]}},
                    }
                ),
                encoding="utf-8",
            )
            captured = {}

            def fake_main(argv):
                captured["cfg"] = vcp_entry.vcp._read_config()
                return 0

            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), \
                 mock.patch.object(vcp_entry.vcp, "main", side_effect=fake_main):
                rc = vcp_entry.main(["r:/workspace/report.txt", "."])

        self.assertEqual(rc, 0)
        self.assertEqual(captured["cfg"]["ssh"], ["root@one"])

    def test_help_does_not_require_target_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "missing.json"
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), \
                 redirect_stdout(out):
                rc = vcp_entry.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("vcp targets", out.getvalue())
        self.assertIn("vcp --target NAME", out.getvalue())


if __name__ == "__main__":
    unittest.main()
