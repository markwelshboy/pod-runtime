import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "comfy_state_event.py"
SPEC = importlib.util.spec_from_file_location("comfy_state_event", MODULE_PATH)
events = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(events)


class ComfyStateEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.comfy = self.root / "ComfyUI"
        self.state_dir = self.root / "state"
        (self.comfy / "models" / "loras").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, destination: Path, **overrides):
        values = {
            "destination": str(destination),
            "comfy_root": self.comfy,
            "comfy_only": True,
            "source": "huggingface",
            "tool": "test",
            "mode": "downloaded",
            "repo": "owner/repo",
            "repo_type": "model",
            "remote_path": "loras/foo.safetensors",
            "remote_request": None,
            "revision": "main",
            "url": None,
            "section": "test_loras",
            "bytes": 3,
            "state_dir": self.state_dir,
        }
        values.update(overrides)
        return type("Args", (), values)()

    def test_acquire_appends_reconstructable_event(self):
        destination = self.comfy / "models" / "loras" / "foo.safetensors"
        destination.write_bytes(b"foo")

        rc = events.acquire(self._args(destination))

        self.assertEqual(rc, 0)
        journal = self.state_dir / "events.jsonl"
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event"], "asset_acquired")
        self.assertEqual(row["source"], "huggingface")
        self.assertEqual(row["destination"], str(destination.resolve()))
        self.assertEqual(row["repo"], "owner/repo")
        self.assertEqual(row["remote_path"], "loras/foo.safetensors")
        self.assertEqual(row["bytes"], 3)

    def test_comfy_only_ignores_unrelated_downloads(self):
        destination = self.root / "other" / "foo.safetensors"
        destination.parent.mkdir()
        destination.write_bytes(b"foo")

        rc = events.acquire(self._args(destination))

        self.assertEqual(rc, 0)
        self.assertFalse((self.state_dir / "events.jsonl").exists())

    def test_append_is_jsonl_and_preserves_multiple_observations(self):
        destination = self.comfy / "models" / "loras" / "foo.safetensors"
        destination.write_bytes(b"foo")

        events.acquire(self._args(destination, mode="already-present"))
        events.acquire(self._args(destination, mode="downloaded", revision="abc123"))

        rows = [
            json.loads(line)
            for line in (self.state_dir / "events.jsonl").read_text().splitlines()
        ]
        self.assertEqual([row["mode"] for row in rows], ["already-present", "downloaded"])
        self.assertEqual(rows[-1]["revision"], "abc123")


if __name__ == "__main__":
    unittest.main()
