import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOVED_HELPERS = [
    "helpers_active_workflow.sh",
    "helpers_core.sh",
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
    def test_root_has_one_public_helper_entrypoint_and_one_compatibility_shim(self):
        self.assertTrue((ROOT / "helpers.sh").is_file())
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
        self.assertIn("${POD_RUNTIME_DIR}/custom_nodes.env", text)
        self.assertIn("${POD_RUNTIME_DIR}/bin/custom_nodes_profiled.py", text)

    def test_helper_shell_syntax(self):
        paths = [
            ROOT / "helpers.sh",
            ROOT / "helpers_shell.sh",
            *sorted((ROOT / "helpers.d").rglob("*.sh")),
        ]
        for path in paths:
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
