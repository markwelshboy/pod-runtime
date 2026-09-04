import importlib.util
import io
import json
import os
import subprocess
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

    def test_no_name_config_ssh_discovers_and_names_runpod_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ssh": ["-p", "3000", "root@new"],
                        "active_target": "old-target",
                        "targets": {
                            "old-target": {
                                "ssh": ["-p", "2000", "root@old"],
                                "pod_id": "oldpod",
                                "provider": "runpod",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), \
                 mock.patch.object(vcp_entry, "_discover_runpod_pod_id", return_value="pod456"), \
                 mock.patch.object(vcp_entry, "_runpod_name_for_id", return_value="qwen3-captioning"), \
                 redirect_stdout(out):
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
        self.assertEqual(cfg["active_target"], "qwen3-captioning")
        self.assertNotIn("ssh", cfg)
        self.assertIn("old-target", cfg["targets"])
        discovered = cfg["targets"]["qwen3-captioning"]
        self.assertEqual(
            discovered["ssh"],
            ["-p", "3000", "-i", "/key", "root@new"],
        )
        self.assertEqual(discovered["pod_id"], "pod456")
        self.assertEqual(discovered["provider"], "runpod")
        self.assertEqual(discovered["runpod_name"], "qwen3-captioning")
        self.assertIn("Discovered RunPod target qwen3-captioning (pod pod456)", out.getvalue())
        self.assertIn("Removed duplicate legacy/default SSH mapping", out.getvalue())

    def test_no_name_config_ssh_falls_back_to_legacy_and_makes_it_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "active_target": "old-target",
                        "targets": {
                            "old-target": {"ssh": ["-p", "2000", "root@old"]}
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"VCP_CONFIG": str(config)}), \
                 mock.patch.object(vcp_entry, "_discover_runpod_pod_id", return_value=None):
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
        self.assertIn("old-target", cfg["targets"])

    def test_runpod_probe_reads_runtime_environment(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="noise\n__VCP_RUNPOD_POD_ID__=pod123\n",
        )
        with mock.patch.object(vcp_entry.subprocess, "run", return_value=completed) as run:
            pod_id = vcp_entry._discover_runpod_pod_id(
                ["root@64.247.206.212", "-p", "14463", "-i", "/key"]
            )

        self.assertEqual(pod_id, "pod123")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "ssh")
        self.assertEqual(cmd[-3:], ["root@64.247.206.212", "bash", "-s"])
        script = run.call_args.kwargs["input"]
        self.assertIn("/etc/rp_environment", script)
        self.assertIn("RUNPOD_POD_ID", script)

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
        self.assertIn("auto-discovers RunPod target", out.getvalue())
        self.assertIn("vcp --target NAME", out.getvalue())


if __name__ == "__main__":
    unittest.main()
