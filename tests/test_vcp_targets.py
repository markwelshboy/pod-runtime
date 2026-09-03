import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
MODULE = BIN / "vcp_targets.py"
spec = importlib.util.spec_from_file_location("vcp_targets", MODULE)
vcp_targets = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(vcp_targets)


class VcpTargetsTests(unittest.TestCase):
    def test_save_and_resolve_named_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            env = {"VCP_CONFIG": str(config)}
            vcp_targets.save_target(
                "comfydev3900",
                ["-i", "/key", "-p", "2222", "root@host"],
                pod_id="pod123",
                provider="runpod",
                make_active=True,
                environ=env,
            )
            cfg = vcp_targets.read_config(env)
            ssh, selected = vcp_targets.resolve_ssh(cfg)

        self.assertEqual(selected, "comfydev3900")
        self.assertEqual(ssh, ["-i", "/key", "-p", "2222", "root@host"])
        self.assertEqual(cfg["targets"]["comfydev3900"]["pod_id"], "pod123")
        self.assertEqual(cfg["targets"]["comfydev3900"]["provider"], "runpod")

    def test_explicit_target_overrides_active_target(self):
        cfg = {
            "active_target": "one",
            "targets": {
                "one": {"ssh": ["root@one"]},
                "two": {"ssh": ["root@two"]},
            },
        }
        ssh, selected = vcp_targets.resolve_ssh(cfg, "two")
        self.assertEqual(selected, "two")
        self.assertEqual(ssh, ["root@two"])

    def test_legacy_top_level_ssh_remains_supported(self):
        cfg = {"ssh": ["-p", "1234", "root@legacy"]}
        ssh, selected = vcp_targets.resolve_ssh(cfg)
        self.assertIsNone(selected)
        self.assertEqual(ssh, ["-p", "1234", "root@legacy"])

    def test_named_target_does_not_destroy_existing_vcp_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps({"hf_repo": "owner/repo", "ssh": ["root@legacy"]}),
                encoding="utf-8",
            )
            env = {"VCP_CONFIG": str(config)}
            vcp_targets.save_target("pod-a", ["root@pod-a"], environ=env)
            cfg = vcp_targets.read_config(env)

        self.assertEqual(cfg["hf_repo"], "owner/repo")
        self.assertEqual(cfg["ssh"], ["root@legacy"])
        self.assertEqual(cfg["targets"]["pod-a"]["ssh"], ["root@pod-a"])

    def test_setting_active_target_requires_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"VCP_CONFIG": str(Path(tmp) / "config.json")}
            with self.assertRaises(vcp_targets.VcpTargetError):
                vcp_targets.set_active_target("missing", environ=env)

    def test_target_name_validation(self):
        self.assertEqual(vcp_targets.validate_target_name("rtx6000-comfy_1"), "rtx6000-comfy_1")
        with self.assertRaises(vcp_targets.VcpTargetError):
            vcp_targets.validate_target_name("bad target")


if __name__ == "__main__":
    unittest.main()
