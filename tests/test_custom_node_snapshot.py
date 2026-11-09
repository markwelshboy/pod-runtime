import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "custom_node_snapshot.py"
SPEC = importlib.util.spec_from_file_location("custom_node_snapshot", SCRIPT)
snapshot_nodes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot_nodes)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def make_repo(root: Path, folder: str, remote: str) -> tuple[Path, str]:
    path = root / folder
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.email", "snapshot-test@example.invalid")
    git(path, "config", "user.name", "Snapshot Test")
    (path / "README.md").write_text("test\n")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "Initial")
    git(path, "remote", "add", "origin", remote)
    return path, git(path, "rev-parse", "HEAD")


class NodeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root_ctx = tempfile.TemporaryDirectory()
        self.root = Path(self.root_ctx.name)
        self.nodes = self.root / "custom_nodes"
        self.nodes.mkdir()
        self.manifest = {
            "schema_version": 1,
            "nodes": {
                "known": {
                    "remote": "https://github.com/example/known.git",
                    "local": "ComfyUI-Known",
                    "pip": {"constraint_mode": "none", "requirements": {"add": ["numpy==1.2"]}}
                }
            },
            "sets": {"default": ["known"], "krea2": []},
        }

    def tearDown(self):
        self.root_ctx.cleanup()

    def test_discovery_adds_pending_without_mutating_baseline(self):
        _, known_hash = make_repo(self.nodes, "ComfyUI-Known",
                                  "https://github.com/example/known.git")
        _, pending_hash = make_repo(self.nodes, "ComfyUI-New",
                                    "https://github.com/example/new.git")
        (self.nodes / "ComfyUI-Tab-Manager").mkdir()  # third-party untracked folder
        (self.nodes / "runtime-link").symlink_to(self.nodes / "ComfyUI-Known")
        report_file = self.root / "status.json"
        report_file.write_text(json.dumps({
            "sets": ["default", "krea2"],
            "nodes": [{"local": "ComfyUI-New", "clone": "ok", "install": "installed",
                       "commit": pending_hash}]
        }))
        before = json.loads(json.dumps(self.manifest))
        captured, report = snapshot_nodes.discover(
            self.manifest, self.nodes, status_path=report_file, selected_sets="krea2"
        )
        self.assertEqual(self.manifest, before)
        self.assertEqual(captured["nodes"]["known"]["ref"], known_hash)
        self.assertEqual(captured["nodes"]["known"]["pip"], before["nodes"]["known"]["pip"])
        self.assertEqual(captured["sets"]["pending"], ["comfyui-new"])
        self.assertEqual(captured["sets"]["snapshot-installed"], ["known", "comfyui-new"])
        self.assertEqual(captured["nodes"]["comfyui-new"], {
            "remote": "https://github.com/example/new.git",
            "local": "ComfyUI-New",
            "ref": pending_hash,
        })
        self.assertEqual(report["selected_sets"], ["krea2"])
        self.assertEqual(report["summary"]["unresolved"], 2)
        self.assertEqual(report["summary"]["new_pending"], 1)
        self.assertIn("runtime-link", [x["local"] for x in report["installed"]])

    def test_plain_folder_inside_parent_git_checkout_is_not_misidentified(self):
        git(self.nodes, "init")
        git(self.nodes, "config", "user.email", "snapshot-test@example.invalid")
        git(self.nodes, "config", "user.name", "Snapshot Test")
        (self.nodes / "README.md").write_text("parent repository\n")
        git(self.nodes, "add", "README.md")
        git(self.nodes, "commit", "-m", "Parent")
        git(self.nodes, "remote", "add", "origin", "https://github.com/example/parent.git")
        (self.nodes / "PlainFolder").mkdir()
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        self.assertNotIn("plainfolder", captured["nodes"])
        self.assertTrue(any(x["local"] == "PlainFolder" and x["status"] == "non-git"
                            for x in report["installed"]))

    def test_external_symlinked_git_node_is_recreated_as_normal_checkout(self):
        external = self.root / "external"
        external.mkdir()
        source, sha = make_repo(external, "NodeCode", "https://github.com/example/linked.git")
        (self.nodes / "LinkedNode").symlink_to(source, target_is_directory=True)
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        self.assertEqual(captured["nodes"]["linkednode"]["ref"], sha)
        self.assertEqual(captured["nodes"]["linkednode"]["local"], "LinkedNode")
        self.assertTrue(any("symlinked Git" in w for w in report["warnings"]))

    def test_dirty_changes_warn_but_do_not_get_baked_into_manifest(self):
        p, _ = make_repo(self.nodes, "ComfyUI-Known",
                         "https://github.com/example/known.git")
        (p / "README.md").write_text("modified\n")
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        self.assertEqual(captured["sets"]["pending"], [])
        self.assertTrue(any("uncommitted" in warning for warning in report["warnings"]))

    def test_unknown_remote_with_token_never_saved(self):
        make_repo(self.nodes, "SecretNode", "https://user:secret@github.com/example/private.git")
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        self.assertEqual(captured["sets"]["pending"], [])
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("secret", json.dumps(captured))

    def test_remote_conflict_does_not_overwrite_known_custom_pip(self):
        make_repo(self.nodes, "ComfyUI-Known", "https://github.com/other/repo.git")
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        self.assertNotIn("ref", captured["nodes"]["known"])
        self.assertTrue(any(r["status"] == "conflict" for r in report["installed"]))

    def test_promotion_requires_pending_and_is_non_destructive(self):
        make_repo(self.nodes, "ComfyUI-New", "https://github.com/example/new.git")
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes)
        main_manifest = self.root / "main.json"
        snapshot_manifest = self.root / "captured.json"
        main_manifest.write_text(json.dumps(self.manifest))
        snapshot_manifest.write_text(json.dumps(captured))
        args = snapshot_nodes.build_parser().parse_args([
            "promote", "comfyui-new", "--source", str(snapshot_manifest),
            "--into", str(main_manifest), "--set", "krea2"
        ])
        self.assertEqual(snapshot_nodes.cmd_promote(args), 0)
        main = json.loads(main_manifest.read_text())
        self.assertIn("comfyui-new", main["sets"]["krea2"])
        self.assertIn("comfyui-new", main["nodes"])
        self.assertEqual(json.loads(snapshot_manifest.read_text()), captured)
        self.assertEqual(self.manifest["sets"]["krea2"], [])
        with self.assertRaisesRegex(ValueError, "not in .*pending"):
            args.id = "known"
            snapshot_nodes.cmd_promote(args)

    def test_restoration_includes_pending_and_selected_sets(self):
        captured, report = snapshot_nodes.discover(self.manifest, self.nodes, selected_sets="krea2")
        captured["sets"]["pending"] = ["known"]  # simulate a historical pending node
        captured["sets"]["snapshot-installed"] = ["known"]
        report["selected_sets"] = ["krea2"]
        man, inv = self.root / "manifest.json", self.root / "inventory.json"
        man.write_text(json.dumps(captured))
        inv.write_text(json.dumps(report))
        args = snapshot_nodes.build_parser().parse_args([
            "restore-sets", "--manifest", str(man), "--inventory", str(inv),
            "--launcher-sets", "krea2"
        ])
        with mock.patch("builtins.print") as printer:
            self.assertEqual(snapshot_nodes.cmd_restore_sets(args), 0)
        self.assertEqual(printer.call_args.args[0], "krea2,pending,snapshot-installed")
        args.launcher_sets = "unknown"
        with self.assertRaisesRegex(ValueError, "missing sets"):
            snapshot_nodes.cmd_restore_sets(args)

    def test_validate_manifest_rejects_duplicate_directories(self):
        duplicate = json.loads(json.dumps(self.manifest))
        duplicate["nodes"]["second"] = {
            "remote": "https://github.com/example/second.git",
            "local": "ComfyUI-Known",
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            snapshot_nodes.validate_manifest(duplicate)

    def test_dry_run_never_writes(self):
        make_repo(self.nodes, "ComfyUI-New", "https://github.com/example/new.git")
        manifest_file = self.root / "manifest.json"
        input_file = self.root / "main.json"
        input_file.write_text(json.dumps(self.manifest))
        args = snapshot_nodes.build_parser().parse_args([
            "discover", "--base", str(input_file), "--nodes-root", str(self.nodes),
            "--output", str(manifest_file), "--inventory", str(self.root / "inventory.json"),
            "--packages", str(self.root / "packages.json"),
            "--dry-run", "--allow-test-path"
        ])
        self.assertEqual(snapshot_nodes.cmd_discover(args), 0)
        self.assertFalse(manifest_file.exists())


if __name__ == "__main__":
    unittest.main()
