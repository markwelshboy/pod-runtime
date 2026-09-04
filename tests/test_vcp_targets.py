import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_host_first_ssh_is_normalized_and_displayed_correctly(self):
        host_first = ["root@64.247.206.212", "-p", "14463", "-i", "/key"]
        self.assertEqual(
            vcp_targets.normalize_ssh_args(host_first),
            ["-p", "14463", "-i", "/key", "root@64.247.206.212"],
        )
        self.assertEqual(
            vcp_targets.endpoint_from_ssh(host_first),
            "root@64.247.206.212:14463",
        )

        cfg = {
            "active_target": "qwen3-captioning",
            "targets": {"qwen3-captioning": {"ssh": host_first}},
        }
        ssh, selected = vcp_targets.resolve_ssh(cfg)
        self.assertEqual(selected, "qwen3-captioning")
        self.assertEqual(
            ssh,
            ["-p", "14463", "-i", "/key", "root@64.247.206.212"],
        )

    def test_save_target_persists_canonical_ssh_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"VCP_CONFIG": str(Path(tmp) / "config.json")}
            vcp_targets.save_target(
                "qwen",
                ["root@host", "-p", "1234", "-i", "/key"],
                environ=env,
            )
            cfg = vcp_targets.read_config(env)
        self.assertEqual(
            cfg["targets"]["qwen"]["ssh"],
            ["-p", "1234", "-i", "/key", "root@host"],
        )

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

    def test_persistent_top_level_ssh_is_not_a_fallback(self):
        cfg = {"ssh": ["-p", "1234", "root@legacy"]}
        with self.assertRaises(vcp_targets.VcpTargetError):
            vcp_targets.resolve_ssh(cfg)

    def test_named_target_write_prunes_obsolete_top_level_ssh(self):
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
        self.assertNotIn("ssh", cfg)
        self.assertEqual(cfg["targets"]["pod-a"]["ssh"], ["root@pod-a"])

    def test_prune_legacy_ssh_only_removes_top_level_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ssh": ["root@legacy"],
                        "active_target": "one",
                        "targets": {"one": {"ssh": ["root@one"]}},
                        "hf_repo": "owner/repo",
                    }
                ),
                encoding="utf-8",
            )
            env = {"VCP_CONFIG": str(config)}
            self.assertTrue(vcp_targets.prune_legacy_ssh(env))
            cfg = vcp_targets.read_config(env)

        self.assertNotIn("ssh", cfg)
        self.assertEqual(cfg["active_target"], "one")
        self.assertIn("one", cfg["targets"])
        self.assertEqual(cfg["hf_repo"], "owner/repo")

    def test_setting_active_target_requires_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"VCP_CONFIG": str(Path(tmp) / "config.json")}
            with self.assertRaises(vcp_targets.VcpTargetError):
                vcp_targets.set_active_target("missing", environ=env)

    def test_remove_matching_targets_by_pod_and_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "active_target": "auto",
                        "ssh": ["-p", "2222", "root@10.0.0.2"],
                        "targets": {
                            "auto": {
                                "pod_id": "pod123",
                                "provider": "runpod",
                                "ssh": ["-p", "1111", "root@10.0.0.1"],
                            },
                            "manual": {
                                "ssh": ["root@10.0.0.2", "-p", "2222", "-i", "/key"]
                            },
                            "keep": {"ssh": ["-p", "3333", "root@10.0.0.3"]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            env = {"VCP_CONFIG": str(config)}
            result = vcp_targets.remove_matching_targets(
                pod_id="pod123",
                endpoints={("10.0.0.2", 2222)},
                environ=env,
            )
            cfg = vcp_targets.read_config(env)

        self.assertEqual(result["targets"], ["auto", "manual"])
        self.assertTrue(result["legacy"])
        self.assertNotIn("active_target", cfg)
        self.assertNotIn("ssh", cfg)
        self.assertEqual(set(cfg["targets"]), {"keep"})

    def test_target_name_validation(self):
        self.assertEqual(vcp_targets.validate_target_name("rtx6000-comfy_1"), "rtx6000-comfy_1")
        with self.assertRaises(vcp_targets.VcpTargetError):
            vcp_targets.validate_target_name("bad target")


if __name__ == "__main__":
    unittest.main()
