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

    def test_no_name_config_ssh_updates_active_named_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ssh": ["-p", "1000", "root@legacy"],
                        "active_target": "qwen3-captioning",
                        "targets": {
                            "qwen3-captioning": {
                                "ssh": ["-p", "2000", "root@old"],
                                "pod_id": "pod123",
                                "provider": "runpod",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), redirect_stdout(out):
                rc = vcp_entry.main(
                    [
                        "config",
                        "ssh",
                        "root@new",
                        "-p",
                        "3000",
                        "-i",
                        "/key",
                    ]
                )
            cfg = json.loads(config.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(cfg["ssh"], ["-p", "1000", "root@legacy"])
        self.assertEqual(
            cfg["targets"]["qwen3-captioning"]["ssh"],
            ["-p", "3000", "-i", "/key", "root@new"],
        )
        self.assertEqual(cfg["targets"]["qwen3-captioning"]["pod_id"], "pod123")
        self.assertIn("Updated active target qwen3-captioning", out.getvalue())

    def test_no_name_config_ssh_uses_legacy_when_no_active_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}):
                rc = vcp_entry.main(
                    ["config", "ssh", "root@host", "-p", "2222", "-i", "/key"]
                )
            cfg = json.loads(config.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(
            cfg["ssh"],
            ["-p", "2222", "-i", "/key", "root@host"],
        )
        self.assertNotIn("active_target", cfg)

    def test_target_remove_convenience_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "active_target": "one",
                        "targets": {
                            "one": {"ssh": ["root@one"]},
                            "two": {"ssh": ["root@two"]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}):
                rc = vcp_entry.main(["target", "remove", "one"])
            cfg = json.loads(config.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertNotIn("active_target", cfg)
        self.assertEqual(set(cfg["targets"]), {"two"})

    def test_targets_output_handles_host_first_config_and_full_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ssh": ["-p", "1000", "root@legacy"],
                        "active_target": "local-template-smoke-test",
                        "targets": {
                            "local-template-smoke-test": {
                                "ssh": ["-i", "/key", "-p", "53245", "root@160.250.71.207"]
                            },
                            "qwen3-captioning": {
                                "ssh": ["root@64.247.206.212", "-p", "14463", "-i", "/key"]
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), redirect_stdout(out):
                rc = vcp_entry.main(["targets"])
        text = out.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("local-template-smoke-test", text)
        self.assertIn("root@160.250.71.207:53245", text)
        self.assertIn("root@64.247.206.212:14463", text)
        self.assertIn("legacy/default: root@legacy:1000", text)

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
        self.assertIn("vcp target remove NAME", out.getvalue())
        self.assertIn("vcp --target NAME", out.getvalue())


if __name__ == "__main__":
    unittest.main()
