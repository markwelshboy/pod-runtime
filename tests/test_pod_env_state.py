import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "bin" / "pod_env_state.py"
spec = importlib.util.spec_from_file_location("pod_env_state", MODULE)
env_state = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(env_state)


class EnvironmentOverlayTests(unittest.TestCase):
    def test_delta_keeps_working_vars_and_omits_secrets_and_session_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "env": {
                            "PATH": "/usr/bin",
                            "RUN_DIR": "/workspace/runs/old",
                            "UNCHANGED": "same",
                        },
                    }
                ),
                encoding="utf-8",
            )
            overlay = env_state.environment_overlay(
                {
                    "PATH": "/usr/bin:/workspace/tools",
                    "RUN_DIR": "/workspace/runs/new",
                    "UNCHANGED": "same",
                    "MODEL_DIR": "/workspace/models/qwen",
                    "HF_TOKEN": "do-not-store",
                    "SSH_CONNECTION": "1 2 3 4",
                    "PWD": "/workspace/project",
                },
                baseline_path=baseline,
            )

        self.assertEqual(overlay["mode"], "diff-from-provision")
        self.assertEqual(
            overlay["set"],
            {
                "MODEL_DIR": "/workspace/models/qwen",
                "PATH": "/usr/bin:/workspace/tools",
                "RUN_DIR": "/workspace/runs/new",
            },
        )
        self.assertNotIn("HF_TOKEN", overlay["set"])
        self.assertNotIn("SSH_CONNECTION", overlay["set"])

    def test_missing_baseline_falls_back_to_pid1(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            env_state,
            "_pid1_environment",
            return_value={"BASE": "same", "FROM_CONTAINER": "yes"},
        ):
            overlay = env_state.environment_overlay(
                {"BASE": "same", "FROM_CONTAINER": "yes", "RUN_DIR": "/workspace/run42"},
                baseline_path=Path(tmp) / "missing.json",
            )
        self.assertEqual(overlay["mode"], "diff-from-pid1-fallback")
        self.assertEqual(overlay["set"], {"RUN_DIR": "/workspace/run42"})

    def test_restore_updates_process_and_shell_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            shell_file = Path(tmp) / "env.current"
            json_file = Path(tmp) / "env.current.json"
            restored = env_state.apply_environment_overlay(
                {
                    "schema_version": 1,
                    "set": {
                        "RUN_DIR": "/workspace/run 7",
                        "MODEL_DIR": "/workspace/models/qwen",
                        "WANDB_API_KEY": "never-write-this",
                    },
                },
                shell_path=shell_file,
                json_path=json_file,
            )
            text = shell_file.read_text(encoding="utf-8")
            saved = json.loads(json_file.read_text(encoding="utf-8"))

            self.assertEqual(os.environ["RUN_DIR"], "/workspace/run 7")
            self.assertEqual(os.environ["MODEL_DIR"], "/workspace/models/qwen")
            self.assertNotIn("WANDB_API_KEY", os.environ)
            self.assertIn("export RUN_DIR=", text)
            self.assertNotIn("WANDB_API_KEY", text)
            self.assertEqual(saved["set"], restored["set"])

    def test_new_overlay_removes_previous_restored_names(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"OLD_RUN": "old", "KEEP": "base"}, clear=True
        ):
            shell_file = Path(tmp) / "env.current"
            json_file = Path(tmp) / "env.current.json"
            json_file.write_text(json.dumps({"set": {"OLD_RUN": "old"}}), encoding="utf-8")

            env_state.apply_environment_overlay(
                {"set": {"RUN_DIR": "/workspace/new"}},
                shell_path=shell_file,
                json_path=json_file,
            )

            self.assertNotIn("OLD_RUN", os.environ)
            self.assertEqual(os.environ["RUN_DIR"], "/workspace/new")
            self.assertEqual(os.environ["KEEP"], "base")


class ProvisionIntegrationTests(unittest.TestCase):
    def test_provision_dispatcher_captures_baseline_after_success(self):
        text = (Path(__file__).resolve().parents[1] / "bin" / "provision").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$PROVISION_IMPL" ssh "${SSH_ARGS[@]}"', text)
        self.assertIn('pod_env_state.py" capture-baseline', text)
        self.assertIn("Capturing post-provision environment baseline", text)

    def test_shell_loader_restores_snapshot_environment_last(self):
        text = (Path(__file__).resolve().parents[1] / ".bash_functions").read_text(
            encoding="utf-8"
        )
        self.assertIn('source_if_exists "/workspace/.pod-state/env.current"', text)
        self.assertGreater(
            text.index('/workspace/.pod-state/env.current'),
            text.index('source_if_exists "$repo_root/helpers.sh"'),
        )


if __name__ == "__main__":
    unittest.main()
