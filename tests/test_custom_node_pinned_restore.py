import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("custom_nodes_snapshot_git_test", ROOT / "bin/custom_nodes.py")
node_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(node_tool)


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.strip()


class PinRestoreTests(unittest.TestCase):
    def test_shallow_clone_fetches_snapshot_commit_after_remote_advances(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            git("init", cwd=source)
            git("config", "user.email", "test@example.invalid", cwd=source)
            git("config", "user.name", "Test", cwd=source)
            (source / "readme.txt").write_text("old\n")
            git("add", "readme.txt", cwd=source)
            git("commit", "-m", "old", cwd=source)
            earlier_commit = git("rev-parse", "HEAD", cwd=source)
            (source / "readme.txt").write_text("new\n")
            git("commit", "-am", "new", cwd=source)

            # A file:// remote forces Git to respect --depth=1, unlike local
            # path clones (which would preserve the full history by default).
            remote = "file://" + str(source)
            custom_dir = root / "custom_nodes"
            logs = root / "logs"
            custom_dir.mkdir()
            logs.mkdir()
            node = {
                "remote": remote,
                "local": "restored-node",
                "ref": earlier_commit,
                "clone_options": ["--depth=1"],
                "pip": {"enabled": False},
            }
            node_id, rc, commit = node_tool.clone_node(("restored", node), custom_dir, logs)
            self.assertEqual(node_id, "restored")
            self.assertEqual(rc, 0, (logs / "restored-node.log").read_text())
            self.assertEqual(git("rev-parse", "HEAD", cwd=custom_dir / "restored-node"), earlier_commit)
            self.assertTrue(commit.startswith(earlier_commit[:7]))
            self.assertEqual((custom_dir / "restored-node" / "readme.txt").read_text(), "old\n")


if __name__ == "__main__":
    unittest.main()
