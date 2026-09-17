import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SnapshotEntrypointTests(unittest.TestCase):
    def _assert_bash_env_not_sourced(self, launcher: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="snapshot-entrypoint-") as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "bash-env-was-sourced"
            bash_env = tmp_path / "bash_env.sh"
            bash_env.write_text(
                f"printf sourced > {marker}\n"
                "export CUSTOM_NODES_MANIFEST_URL=mutated-by-bash-env\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["BASH_ENV"] = str(bash_env)
            proc = subprocess.run(
                [str(launcher), "--help"],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("usage:", proc.stdout.lower())
            self.assertFalse(
                marker.exists(),
                f"{launcher} started Bash and sourced BASH_ENV",
            )

    def test_root_snapshot_launcher_does_not_source_bash_env(self):
        self._assert_bash_env_not_sourced(ROOT / "snapshot-pod")

    def test_bin_snapshot_launcher_does_not_source_bash_env(self):
        self._assert_bash_env_not_sourced(ROOT / "bin" / "snapshot-pod")


if __name__ == "__main__":
    unittest.main()
