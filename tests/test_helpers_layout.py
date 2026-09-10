import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOVED_HELPERS = [
    "helpers_active_workflow.sh",
    "helpers_custom_node_add.sh",
    "helpers_custom_node_manifest_manage.sh",
    "helpers_custom_node_rollback.sh",
    "helpers_git_auth.sh",
    "helpers_hf_manifest.sh",
    "helpers_hf_manifest_selection.sh",
    "helpers_hf_manifest_tree.sh",
    "helpers_hf_repo_sync.sh",
    "helpers_hff_runtime.sh",
    "helpers_network.sh",
    "helpers_network_guard.sh",
    "helpers_network_transfers.sh",
    "helpers_session.sh",
]


class HelpersLayoutTests(unittest.TestCase):
    def test_root_keeps_public_entrypoint_legacy_core_and_compatibility_shim(self):
        self.assertTrue((ROOT / "helpers.sh").is_file())
        self.assertTrue((ROOT / "helpers_core.sh").is_file())
        self.assertFalse((ROOT / "helpers.d" / "helpers_core.sh").exists())

        for name in MOVED_HELPERS:
            self.assertFalse((ROOT / name).exists(), name)
            self.assertTrue((ROOT / "helpers.d" / name).is_file(), name)

        # Old SL bootstrap clients used this filename as a runtime sentinel.
        compat = ROOT / "helpers_shell.sh"
        self.assertTrue(compat.is_file())
        self.assertTrue((ROOT / "helpers.d" / "helpers_shell.sh").is_file())
        self.assertIn("Deprecated compatibility entrypoint", compat.read_text(encoding="utf-8"))

    def test_manifest_fragments_moved_with_loader(self):
        for name in ("01-common.sh", "02-download.sh", "03-status.sh", "04-dispatch.sh"):
            self.assertFalse((ROOT / "helpers_hf_manifest.d" / name).exists())
            self.assertTrue((ROOT / "helpers.d" / "helpers_hf_manifest.d" / name).is_file())

    def test_shell_only_sources_public_entrypoint(self):
        text = (ROOT / ".bash_functions").read_text(encoding="utf-8")
        self.assertIn('source_if_exists "$repo_root/helpers.sh"', text)
        self.assertNotIn("helpers_shell.sh", text)

    def test_entrypoint_establishes_canonical_runtime_root(self):
        text = (ROOT / "helpers.sh").read_text(encoding="utf-8")
        self.assertIn("export POD_RUNTIME_DIR", text)
        self.assertIn("helpers.d", text)
        self.assertIn("${POD_RUNTIME_DIR}/helpers_core.sh", text)
        self.assertIn("${POD_RUNTIME_DIR}/custom_nodes.env", text)
        self.assertIn("${POD_RUNTIME_DIR}/bin/custom_nodes_profiled.py", text)
        self.assertIn("__POD_RUNTIME_HELPERS_LOADED", text)

    def test_implementation_helpers_do_not_rediscover_runtime_root(self):
        offenders = []
        for path in sorted((ROOT / "helpers.d").rglob("*.sh")):
            if "BASH_SOURCE" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_runtime_root_sensitive_helpers_use_pod_runtime_dir(self):
        tree = (ROOT / "helpers.d" / "helpers_hf_manifest_tree.sh").read_text(encoding="utf-8")
        self.assertIn('${POD_RUNTIME_DIR:?POD_RUNTIME_DIR not set}/bin/hf_manifest_expand.py', tree)

        guard = (ROOT / "helpers.d" / "helpers_network_guard.sh").read_text(encoding="utf-8")
        self.assertIn('local runtime_dir="${POD_RUNTIME_DIR:?POD_RUNTIME_DIR not set}"', guard)
        self.assertNotIn("BASH_SOURCE", guard)

    def test_public_entrypoint_is_quiet_and_hff_has_no_path_fallback(self):
        command = (
            f'export POD_RUNTIME_DIR={str(ROOT)!r}; '
            f'source {str(ROOT / "helpers.sh")!r}; '
            'type hff'
        )
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Loading helpers_shell.sh", result.stdout)
        self.assertNotIn("BASH_SOURCE", result.stdout)

    def test_helper_shell_syntax(self):
        paths = [
            ROOT / "helpers.sh",
            ROOT / "helpers_core.sh",
            ROOT / "helpers_shell.sh",
            *sorted((ROOT / "helpers.d").rglob("*.sh")),
        ]
        for path in paths:
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
