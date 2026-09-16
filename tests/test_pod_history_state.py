import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "pod_history_state.py"
SPEC = importlib.util.spec_from_file_location("pod_history_state", MODULE_PATH)
pod_history_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pod_history_state)


class RedactionTests(unittest.TestCase):
    def test_redacts_obvious_credentials_but_keeps_working_variables(self):
        text = (
            "export RUN_DIR=/workspace/run-1\n"
            "export HF_TOKEN=super-secret-value\n"
            "export TOKENIZERS_PARALLELISM=true\n"
            "huggingface-cli login --token another-secret\n"
            "curl -H 'Authorization: Bearer third-secret' https://example.invalid\n"
            "echo done\n"
        )
        safe, count = pod_history_state.redact_history_text(text)
        self.assertEqual(count, 3)
        self.assertIn("export RUN_DIR=/workspace/run-1", safe)
        self.assertIn("export TOKENIZERS_PARALLELISM=true", safe)
        self.assertIn("echo done", safe)
        self.assertNotIn("super-secret-value", safe)
        self.assertNotIn("another-secret", safe)
        self.assertNotIn("third-secret", safe)
        self.assertEqual(safe.count(pod_history_state.REDACTED_LINE), 3)


class CaptureRestoreTests(unittest.TestCase):
    def test_capture_writes_private_sanitized_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source_history"
            target = root / "state" / "bash_history"
            source.write_text(
                "export RUN_DIR=/workspace/run\nexport WANDB_API_KEY=do-not-save\necho ok\n",
                encoding="utf-8",
            )
            with mock.patch.object(pod_history_state, "history_state_path", return_value=target):
                result = pod_history_state.capture_history("demo", source=source)

            self.assertEqual(result, target)
            saved = target.read_text(encoding="utf-8")
            self.assertIn("RUN_DIR=/workspace/run", saved)
            self.assertNotIn("do-not-save", saved)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_restore_replaces_root_history_from_saved_snapshot_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "saved_history"
            destination = root / ".bash_history"
            saved.write_text("export RUN_DIR=/workspace/run\necho resumed\n", encoding="utf-8")
            destination.write_text("new pod command\n", encoding="utf-8")

            with mock.patch.object(pod_history_state, "history_state_path", return_value=saved):
                restored = pod_history_state.restore_history("demo", destination=destination)

            self.assertTrue(restored)
            self.assertEqual(destination.read_text(encoding="utf-8"), saved.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_history_file_is_added_to_snapshot_paths_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp) / "bash_history"
            saved.write_text("echo hi\n", encoding="utf-8")
            template = {"name": "demo", "snapshot": {"paths": ["/workspace/data"]}}

            with mock.patch.object(pod_history_state, "history_state_path", return_value=saved):
                pod_history_state._append_history_snapshot_path(template)
                pod_history_state._append_history_snapshot_path(template)

            self.assertEqual(template["snapshot"]["paths"], ["/workspace/data", str(saved)])


class HookTests(unittest.TestCase):
    def setUp(self):
        pod_history_state._installed = False
        pod_history_state._pending_template = None

    def tearDown(self):
        pod_history_state._installed = False
        pod_history_state._pending_template = None

    def test_snapshot_capture_and_configure_restore_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "bash_history"
            manifest = root / "manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            seen_paths = []
            events = []

            core = SimpleNamespace()

            def load_template(_name):
                return {"name": "demo", "snapshot": {"paths": ["/workspace/data"]}}

            def find_staged_manifest(_staging, _template_name):
                return manifest

            def hydrate_staging(_staging):
                events.append("hydrate")

            def cmd_snapshot(args):
                seen_paths.extend(core.load_template(args.template)["snapshot"]["paths"])
                return 0

            core.load_template = load_template
            core.find_staged_manifest = find_staged_manifest
            core.hydrate_staging = hydrate_staging
            core.cmd_snapshot = cmd_snapshot

            def capture(_template_name):
                saved.write_text("echo saved\n", encoding="utf-8")
                return saved

            with (
                mock.patch.object(pod_history_state, "history_state_path", return_value=saved),
                mock.patch.object(pod_history_state, "capture_history", side_effect=capture) as capture_mock,
                mock.patch.object(pod_history_state, "restore_history", return_value=True) as restore_mock,
            ):
                pod_history_state.install_core_hooks(core)
                rc = core.cmd_snapshot(SimpleNamespace(template="demo", dry_run=False))
                core.find_staged_manifest(root, "demo")
                core.hydrate_staging(root)

            self.assertEqual(rc, 0)
            capture_mock.assert_called_once_with("demo")
            self.assertIn(str(saved), seen_paths)
            self.assertEqual(events, ["hydrate"])
            restore_mock.assert_called_once_with("demo")


if __name__ == "__main__":
    unittest.main()
