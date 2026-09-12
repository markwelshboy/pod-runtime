import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "comfy_workstation_state.py"
SPEC = importlib.util.spec_from_file_location("comfy_workstation_state", MODULE_PATH)
state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(state)


class ComfyWorkstationScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.comfy = self.root / "ComfyUI"
        self.state_dir = self.root / "state"
        (self.comfy / "models" / "loras").mkdir(parents=True)
        (self.comfy / "user" / "default" / "workflows").mkdir(parents=True)
        (self.comfy / "output").mkdir(parents=True)
        (self.comfy / "custom_nodes").mkdir(parents=True)
        self.state_dir.mkdir()
        self.custom_manifest = self.root / "custom_nodes_manifest.json"
        self.custom_manifest.write_text(
            json.dumps({"schema_version": 1, "nodes": {}, "sets": {"default": []}})
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_workflow_reference_marks_model_active_and_reports_missing(self):
        (self.comfy / "models" / "loras" / "foo.safetensors").write_bytes(b"foo")
        (self.comfy / "models" / "loras" / "orphan.safetensors").write_bytes(b"orphan")
        workflow = {
            "nodes": [
                {"type": "LoraLoader", "widgets_values": ["foo.safetensors"]},
                {"type": "ModelLoader", "widgets_values": ["missing.gguf"]},
            ]
        }
        (self.comfy / "user" / "default" / "workflows" / "demo.json").write_text(
            json.dumps(workflow)
        )

        payload = state.scan(self.comfy, self.state_dir, self.custom_manifest)

        self.assertEqual(payload["summary"]["models"]["count"], 2)
        self.assertEqual(payload["summary"]["models"]["referenced_count"], 1)
        self.assertEqual(payload["summary"]["workflows"]["missing_model_references"], 1)
        foo = next(
            asset for asset in payload["assets"] if asset["path"].endswith("foo.safetensors")
        )
        self.assertEqual(
            foo["references"]["workflows"],
            ["user/default/workflows/demo.json"],
        )
        self.assertTrue(foo["activity"]["referenced"])

    def test_acquisition_event_makes_asset_reconstructable(self):
        model = self.comfy / "models" / "loras" / "foo.safetensors"
        model.write_bytes(b"foo")
        event = {
            "schema_version": 1,
            "time": "2026-09-12T20:00:00Z",
            "event": "asset_acquired",
            "source": "huggingface",
            "repo": "owner/repo",
            "remote_path": "foo.safetensors",
            "destination": str(model),
        }
        (self.state_dir / "events.jsonl").write_text(json.dumps(event) + "\n")

        payload = state.scan(self.comfy, self.state_dir, self.custom_manifest)

        self.assertEqual(payload["summary"]["models"]["reconstructable_count"], 1)
        asset = payload["assets"][0]
        self.assertEqual(asset["state"], "reconstructable")
        self.assertEqual(asset["provenance"]["type"], "huggingface")
        self.assertEqual(asset["provenance"]["repo"], "owner/repo")

    def test_clean_default_custom_node_is_baseline_and_dirty_is_detected(self):
        repo = self.comfy / "custom_nodes" / "NodeA"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
        )
        (repo / "node.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "node.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/NodeA.git"],
            cwd=repo,
            check=True,
        )
        self.custom_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "nodes": {
                        "node-a": {
                            "remote": "https://github.com/example/NodeA.git",
                            "local": "NodeA",
                        }
                    },
                    "sets": {"default": ["node-a"]},
                }
            )
        )

        clean = state.scan(self.comfy, self.state_dir, self.custom_manifest)
        self.assertEqual(clean["custom_nodes"][0]["state"], "baseline")
        self.assertFalse(clean["custom_nodes"][0]["repo"]["dirty"])

        (repo / "node.py").write_text("x = 2\n")
        dirty = state.scan(self.comfy, self.state_dir, self.custom_manifest)
        self.assertTrue(dirty["custom_nodes"][0]["repo"]["dirty"])
        self.assertEqual(dirty["summary"]["custom_nodes"]["dirty_count"], 1)

    def test_output_inventory_records_payload_without_modifying_it(self):
        output = self.comfy / "output" / "example.png"
        output.write_bytes(b"abc")
        before = output.read_bytes()

        payload = state.scan(self.comfy, self.state_dir, self.custom_manifest)

        self.assertEqual(payload["summary"]["outputs"], {"count": 1, "bytes": 3})
        self.assertEqual(output.read_bytes(), before)

    def test_write_manifest_is_atomic_visible_state(self):
        payload = state.scan(self.comfy, self.state_dir, self.custom_manifest)
        path = state.write_manifest(payload, self.state_dir)
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["schema_version"], 1)
        self.assertEqual(loaded["comfy_root"], str(self.comfy.resolve()))
        self.assertFalse((self.state_dir / ".workstation.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
