import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "pod_state.py"
SPEC = importlib.util.spec_from_file_location("pod_state", MODULE_PATH)
pod_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pod_state)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, check=True, stdout=subprocess.PIPE)
    return result.stdout.strip()


class TemplateTests(unittest.TestCase):
    def test_qwen_template_has_no_branch_configuration(self):
        template = pod_state.load_template(str(Path(__file__).resolve().parents[1] / "snapshot-templates" / "qwen3-captioning.yaml"))
        self.assertEqual(template["name"], "qwen3-captioning")
        self.assertNotIn("branch", template["repos"][0])
        self.assertEqual(
            template["repos"][0]["configure"]["scripts"],
            ["./build_workspace.sh", "./build_sam3d_workspace.sh", "./build_vllm_workspace.sh"],
        )

    def test_builtin_template_loads_without_pyyaml(self):
        path = Path(__file__).resolve().parents[1] / "snapshot-templates" / "qwen3-captioning.yaml"
        with mock.patch.object(pod_state, "yaml", None):
            template = pod_state.load_template(str(path))
        self.assertEqual(template["name"], "qwen3-captioning")

    def test_snapshot_dir_is_scoped_per_template(self):
        self.assertEqual(pod_state.snapshot_dir("qwen3-captioning"), "snapshot/pods/qwen3-captioning")

    def test_snapshot_dir_honors_hff_snapshot_dir(self):
        with mock.patch.dict("os.environ", {"HFF_SNAPSHOT_DIR": "saved"}, clear=False):
            self.assertEqual(pod_state.snapshot_dir("qwen3-captioning"), "saved/pods/qwen3-captioning")

    def test_latest_uses_first_hff_snapshot(self):
        with mock.patch.object(pod_state, "run_hff", return_value="20260901_120000__new\n20260901_110000__old\n") as hff:
            self.assertEqual(pod_state.latest_snapshot_id("qwen3-captioning"), "20260901_120000__new")
        hff.assert_called_once_with(["snapshot", "--snapdir", "snapshot/pods/qwen3-captioning", "list"])


class GitStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        self.work = root / "work"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "clone", str(self.remote), str(self.work)], check=True, stdout=subprocess.DEVNULL)
        git(self.work, "config", "user.name", "Pod State Test")
        git(self.work, "config", "user.email", "pod-state@example.invalid")
        (self.work / "README.md").write_text("one\n", encoding="utf-8")
        git(self.work, "add", "README.md")
        git(self.work, "commit", "-m", "initial")
        branch = git(self.work, "branch", "--show-current")
        git(self.work, "push", "-u", "origin", branch)
        self.cfg = {"name": "repo", "path": str(self.work), "url": str(self.remote)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_pushed_repo_is_safe(self):
        state = pod_state.repo_state(self.cfg)
        self.assertFalse(state["dirty"])
        self.assertEqual(state["ahead"], 0)
        self.assertEqual(pod_state.snapshot_safety_issues(state), [])

    def test_untracked_file_is_unsafe(self):
        (self.work / "scratch.txt").write_text("work\n", encoding="utf-8")
        state = pod_state.repo_state(self.cfg)
        self.assertTrue(state["dirty"])
        self.assertIn("working tree has uncommitted/untracked changes", pod_state.snapshot_safety_issues(state))

    def test_unpushed_commit_is_unsafe(self):
        (self.work / "README.md").write_text("two\n", encoding="utf-8")
        git(self.work, "add", "README.md")
        git(self.work, "commit", "-m", "local")
        state = pod_state.repo_state(self.cfg)
        self.assertEqual(state["ahead"], 1)
        issues = pod_state.snapshot_safety_issues(state)
        self.assertTrue(any("ahead" in issue for issue in issues))


class ManifestTests(unittest.TestCase):
    def test_manifest_records_branch_and_commit(self):
        template = {
            "name": "example",
        }
        repo_state = {
            "name": "repo",
            "branch": "agent/test",
            "commit": "abc123",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            pod_state, "state_manifest_path", return_value=Path(tmp) / "manifest.json"
        ):
            path = pod_state.write_state_manifest(template, [repo_state], ["/workspace/data"])
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["repos"][0]["branch"], "agent/test")
        self.assertEqual(data["repos"][0]["commit"], "abc123")
        self.assertEqual(data["snapshot_paths"], ["/workspace/data"])


if __name__ == "__main__":
    unittest.main()
