import subprocess
import tempfile
import unittest
from pathlib import Path

PROVISION = Path(__file__).resolve().parents[1] / "bin" / "provision"


class ProvisionHfCredentialTests(unittest.TestCase):
    def test_provision_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(PROVISION)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_hf_token_is_not_a_hard_precondition(self):
        text = PROVISION.read_text(encoding="utf-8")
        self.assertNotIn("HF_TOKEN is not set in the local environment", text)
        self.assertIn('elif [[ -n "\\${HF_TOKEN:-}" ]]', text)
        self.assertIn('elif [[ -n "\\${HUGGINGFACE_HUB_TOKEN:-}" ]]', text)
        self.assertIn("HF credential: expecting Pod environment", text)

    def test_symlink_launcher_finds_repo_sibling_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            launcher = Path(td) / "provision"
            launcher.symlink_to(PROVISION)
            result = subprocess.run(
                [str(launcher)],
                capture_output=True,
                text=True,
                check=False,
            )

        # With no arguments provision_full deliberately prints usage and exits 2.
        # A broken symlink-relative dispatcher instead tries <link-dir>/provision_full
        # and exits 127 with "No such file or directory".
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Usage:", result.stderr)
        self.assertNotIn("No such file or directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
