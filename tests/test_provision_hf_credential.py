import subprocess
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


if __name__ == "__main__":
    unittest.main()
