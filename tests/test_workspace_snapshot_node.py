"""Standalone tests: run without importing ComfyUI, AIOHTTP or torch."""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class RouteRegistry:
    def get(self, _path):
        return lambda fn: fn

    def post(self, _path):
        return lambda fn: fn


mock_aiohttp = types.ModuleType("aiohttp")
mock_aiohttp.web = types.SimpleNamespace(
    Request=object, Response=object,
    json_response=lambda payload, status=200: (payload, status),
)
mock_server = types.ModuleType("server")
mock_server.PromptServer = types.SimpleNamespace(
    instance=types.SimpleNamespace(routes=RouteRegistry())
)

ORIGINALS = {name: sys.modules.get(name) for name in ("aiohttp", "server")}
sys.modules["aiohttp"] = mock_aiohttp
sys.modules["server"] = mock_server
try:
    source = (Path(__file__).resolve().parents[1] /
              "custom_nodes/pod_runtime_workspace_snapshot/__init__.py")
    spec = importlib.util.spec_from_file_location("workspace_snapshot_test_module", source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
finally:
    for name, original in ORIGINALS.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class SnapshotCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.sample = {
            "tabs": [
                {"name": "A", "path": "workflows/a.json", "modified": True,
                 "graph": {"nodes": [{"id": 1, "type": "test"}], "links": []}},
                {"name": "B", "path": "", "modified": True,
                 "graph": {"nodes": [], "links": []}},
            ],
            "activeIndex": 1,
        }

    def test_valid_tab_checkpoint_keeps_unsaved_data_and_active_index(self):
        result = mod.validate_session(self.sample)
        self.assertEqual(result["schema"], 1)
        self.assertTrue(result["tabs"][0]["modified"])
        self.assertEqual(result["tabs"][0]["graph"]["nodes"][0]["id"], 1)
        self.assertEqual(result["activeIndex"], 1)

    def test_reject_bad_graph_and_active_index(self):
        sample = dict(self.sample, tabs=[{"name": "No graph"}])
        with self.assertRaisesRegex(ValueError, "valid graph"):
            mod.validate_session(sample)
        sample = dict(self.sample, activeIndex=9)
        with self.assertRaisesRegex(ValueError, "active tab"):
            mod.validate_session(sample)

    def test_session_id_rejects_traversal(self):
        with self.assertRaisesRegex(ValueError, "Invalid session"):
            mod.session_file("../../root/.ssh/id_rsa")
        self.assertEqual(
            mod.session_file("20261108T220000Z_a1b2c3d4").name,
            "20261108T220000Z_a1b2c3d4.json",
        )

    def test_authentication_requires_explicit_token_and_same_origin(self):
        with mock.patch.object(mod, "auth_token", return_value="sensitive"):
            self.assertTrue(mod.authorized(types.SimpleNamespace(
                headers={"X-Workspace-Snapshot-Token": "sensitive",
                         "Sec-Fetch-Site": "same-origin"}
            )))
            self.assertFalse(mod.authorized(types.SimpleNamespace(
                headers={"X-Workspace-Snapshot-Token": "sensitive",
                         "Sec-Fetch-Site": "cross-site"}
            )))
            self.assertFalse(mod.authorized(types.SimpleNamespace(headers={})))

    def test_secure_atomic_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(mod, "session_root", return_value=root), \
                    mock.patch.object(mod, "_is_within_workspace", return_value=True):
                sid, path = mod.save_session(self.sample)
            self.assertRegex(sid, mod.SESSION_RE)
            self.assertEqual(json.loads(path.read_text())["activeIndex"], 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with mock.patch.object(mod, "session_root", return_value=root):
                summary = mod.list_sessions()
            self.assertEqual(summary[0]["tab_count"], 2)

    def test_snapshot_command_rejects_invalid_groups_and_uses_fixed_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "a.json"
            checkpoint.write_text("{}")
            with mock.patch.object(mod, "session_file", return_value=checkpoint), \
                    mock.patch.object(mod, "snapshot_paths",
                                      return_value=([str(checkpoint)], [])), \
                    mock.patch.object(mod, "_snapshot_executable",
                                      return_value="/usr/local/bin/snapshot-pod"):
                command, warnings = mod.make_snapshot_command({
                    "session_id": "valid",
                    "name": "Experiment 1",
                    "group": "krea-comparisons",
                    "tag": "to process",
                    "include": {"input": True, "output": False},
                })
                self.assertEqual(command[:7], [
                    "/usr/local/bin/snapshot-pod", "--group", "krea-comparisons",
                    "--name", "Experiment 1", "--tag", "to process",
                ])
                self.assertEqual(command[-2:], ["--paths", str(checkpoint)])
                with self.assertRaisesRegex(ValueError, "Group"):
                    mod.make_snapshot_command({
                        "session_id": "valid", "group": "../../etc",
                    })

    def test_snapshot_can_add_discovered_custom_node_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "tabs.json"
            checkpoint.write_text("{}")
            node_root = Path("/workspace/.pod-state/custom_nodes")
            with mock.patch.object(mod, "session_file", return_value=checkpoint), \
                 mock.patch.object(mod, "snapshot_paths", return_value=([str(checkpoint)], [])), \
                 mock.patch.object(mod, "_snapshot_executable", return_value="/bin/snapshot-pod"), \
                 mock.patch.object(mod, "_is_within_workspace", return_value=True), \
                 mock.patch.object(mod, "prepare_custom_nodes_manifest",
                                   return_value=(node_root, ["2 pending custom nodes"])) as discover:
                cmd, messages = mod.make_snapshot_command({
                    "session_id": "valid",
                    "include": {"custom_nodes": True},
                })
            discover.assert_called_once_with()
            self.assertEqual(cmd[-2:], [str(checkpoint), str(node_root)])
            self.assertIn("2 pending custom nodes", messages)

    def test_custom_node_discovery_is_opt_in_for_legacy_api_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "tabs.json"
            checkpoint.write_text("{}")
            with mock.patch.object(mod, "session_file", return_value=checkpoint), \
                 mock.patch.object(mod, "snapshot_paths", return_value=([str(checkpoint)], [])), \
                 mock.patch.object(mod, "_snapshot_executable", return_value="/bin/snapshot-pod"), \
                 mock.patch.object(mod, "prepare_custom_nodes_manifest",
                                   side_effect=AssertionError("must not discover")):
                mod.make_snapshot_command({"session_id": "valid", "include": {}})

    def test_snapshot_options_do_not_allow_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "a.json"
            checkpoint.write_text("{}")
            with mock.patch.object(mod, "session_file", return_value=checkpoint):
                with self.assertRaisesRegex(ValueError, "Unknown snapshot include"):
                    mod.make_snapshot_command({
                        "session_id": "valid",
                        "include": {"../../root": True},
                    })

    def test_backend_workspace_guard_rejects_outside_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(mod._is_within_workspace(Path(tmp)))
        self.assertFalse(mod._is_within_workspace(Path("/workspace")))


if __name__ == "__main__":
    unittest.main()
