import importlib.util
import json
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "vcp.py"
SPEC = importlib.util.spec_from_file_location("vcp", MODULE_PATH)
vcp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vcp)


class VcpTests(unittest.TestCase):
    def test_remote_paths_must_be_absolute(self):
        self.assertEqual(vcp._remote_path("r:/workspace/a.txt"), "/workspace/a.txt")
        with self.assertRaises(vcp.VcpError):
            vcp._remote_path("r:workspace/a.txt")

    def test_duplicate_source_basenames_are_rejected(self):
        with self.assertRaises(vcp.VcpError):
            vcp._validate_unique_basenames(["/one/a.txt", "/two/a.txt"])

    def test_config_ssh_preserves_ssh_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with mock.patch.object(vcp, "CONFIG_PATH", config):
                vcp._config_command(["ssh", "-i", "/keys/pod", "-p", "12234", "root@host"])
                data = json.loads(config.read_text())
        self.assertEqual(data["ssh"], ["-i", "/keys/pod", "-p", "12234", "root@host"])

    def test_local_pack_and_copy_preserves_multiple_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "report.txt").write_text("report", encoding="utf-8")
            (source / "logs").mkdir()
            (source / "logs" / "run.log").write_text("log", encoding="utf-8")
            dest = root / "dest"
            dest.mkdir()

            with mock.patch.dict(os.environ, {"VCP_TMP_DIR": str(root / "tmp")}):
                archive, names = vcp._local_pack(
                    [str(source / "report.txt"), str(source / "logs")], "test-transfer"
                )
                vcp._local_copy_from_archive(archive, names, str(dest), "test-transfer")

            self.assertEqual((dest / "report.txt").read_text(encoding="utf-8"), "report")
            self.assertEqual((dest / "logs" / "run.log").read_text(encoding="utf-8"), "log")

    def test_remote_bootstrap_injects_controller_token_after_helpers(self):
        token = "token'withquote"
        bootstrap = vcp._remote_hff_bootstrap("owner/repo", "dataset", token)
        helper_line = 'source "$_vcp_runtime/helpers_shell.sh"'
        token_line = "export HF_TOKEN="

        self.assertLess(bootstrap.index(helper_line), bootstrap.index(token_line))
        self.assertIn(shlex.quote(token), bootstrap)
        self.assertIn('export HUGGINGFACE_HUB_TOKEN="$HF_TOKEN"', bootstrap)

    def test_remote_extract_does_not_restore_source_ownership(self):
        captured = {}

        def fake_ssh(cfg, script, **kwargs):
            captured["script"] = script
            return None

        with mock.patch.object(vcp, "_ssh", side_effect=fake_ssh):
            vcp._remote_download_and_copy(
                {"ssh": ["root@host"]},
                "owner/repo",
                "dataset",
                "token",
                "vcp/test.tar",
                ["source"],
                "/workspace/dest/",
                "test-transfer",
                {},
                {},
            )

        self.assertIn(
            'tar --no-same-owner -xf "$archive" -C "$stage"',
            captured["script"],
        )

    def test_remote_marker_parser_extracts_timings_and_bytes(self):
        timings = {}
        sizes = {}
        stdout = (
            "ok\n"
            "__VCP_TIMING__ remote_pack 1500000000\n"
            "__VCP_BYTES__ archive 2147483648\n"
            "path\n"
        )

        cleaned = vcp._parse_remote_markers(stdout, timings, sizes)

        self.assertEqual(cleaned, "ok\npath\n")
        self.assertAlmostEqual(timings["remote_pack"], 1.5)
        self.assertEqual(sizes["archive"], 2147483648)

    def test_local_to_remote_route_uses_hf_then_ssh(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "item.txt"
            source.write_text("x", encoding="utf-8")
            args = type("Args", (), {"operands": [str(source), "r:/workspace/"], "keep": False})()
            calls = []

            def remote_copy(*call_args):
                calls.append("remote-copy")
                timing_sink = call_args[-2]
                byte_sink = call_args[-1]
                timing_sink["remote_hf_download"] = 1.0
                timing_sink["remote_copy"] = 0.5
                byte_sink["archive"] = 10240

            with mock.patch.object(vcp, "_read_config", return_value={"ssh": ["root@host"]}), \
                 mock.patch.object(vcp, "_need_token", return_value="token"), \
                 mock.patch.object(vcp, "_hf_upload", side_effect=lambda *a: calls.append("upload")), \
                 mock.patch.object(vcp, "_remote_download_and_copy", side_effect=remote_copy), \
                 mock.patch.object(vcp, "_hf_delete", side_effect=lambda *a: calls.append("delete")), \
                 mock.patch.object(vcp.TransferStats, "print_summary", return_value=None), \
                 mock.patch.dict(os.environ, {"VCP_TMP_DIR": str(Path(tmp) / "cache")}):
                vcp._copy(args)

            self.assertEqual(calls, ["upload", "remote-copy", "delete"])


if __name__ == "__main__":
    unittest.main()
