"""Offline regression for rpods Ollama + PixlStash combined SSH tunnels and skills sync."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rpods
import rpods_vlm as vlm
import rpods_pixlstash as pix


class VlmTunnelTests(unittest.TestCase):
    def setUp(self):
        self.base = ["ssh", "-o", "BatchMode=yes", "-i", "/tmp/key",
                     "-p", "53292", "root@195.26.232.177"]
        self.choice = rpods.PodChoice(
            pod_id="pod1", name="rp-krea2-wait-1", stage="NETWORK",
            gpu="L40S", machine="-", datacenter="US-TX-4",
            public_ip="195.26.232.177", ssh_port=53292,
            uptime_seconds=100, started_at=None)

    def make_zip(self, root, files=None):
        path = Path(root) / "analysis.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for key, value in (files or {
                    "image-detailer-analysis/SKILL.md": "# Skill\n",
                    "image-detailer-analysis/references/states.md": "state\n",
                    "vlm-face-benchmark/README.md": "# Benchmark\n",
            }).items():
                archive.writestr(key, value)
        return path

    def test_parser_supports_combined_modes_and_overrides(self):
        args = rpods.build_parser().parse_args(
            ["--tunnel", "pixlstash", "vlm", "--ollama-local-port", "47961",
             "--ollama-port", "11434"])
        self.assertEqual(args.tunnel, ["pixlstash", "vlm"])
        self.assertIsNone(args.selector)
        self.assertEqual((args.ollama_local_port, args.ollama_port), (47961, 11434))
        standalone = rpods.build_parser().parse_args(["--tunnel", "vlm"])
        self.assertEqual(standalone.tunnel, ["vlm"])
        self.assertEqual(standalone.local_port, 47960)
        self.assertIsNone(rpods.build_parser().parse_args([]).tunnel)

    def test_tunnel_argv_is_loopback_and_single_connection(self):
        cmd = vlm.tunnel_argv(self.base)
        self.assertEqual(cmd[cmd.index("-L") + 1],
                         "127.0.0.1:47961:127.0.0.1:11434")
        self.assertNotIn("-R", cmd)
        self.assertEqual(cmd[-1], self.base[-1])
        combined = pix.tunnel_argv(
            self.base, local_comfy_port=47960, remote_comfy_port=8288,
            local_pixlstash_port=64404, remote_pixlstash_port=64404,
            local_ollama_port=47961, remote_ollama_port=11434)
        self.assertEqual(combined.count("-L"), 2)
        self.assertEqual(combined.count("-R"), 1)
        self.assertIn("127.0.0.1:47960:127.0.0.1:8288", combined)
        self.assertIn("127.0.0.1:47961:127.0.0.1:11434", combined)
        self.assertIn("127.0.0.1:64404:127.0.0.1:64404", combined)
        self.assertNotIn("0.0.0.0", " ".join(combined))
        with self.assertRaisesRegex(ValueError, "ports must differ"):
            pix.tunnel_argv(
                self.base, local_comfy_port=47960, remote_comfy_port=8288,
                local_pixlstash_port=64404, remote_pixlstash_port=64404,
                local_ollama_port=47960, remote_ollama_port=11434)

    def test_rpods_dispatches_combined_with_selected_pod(self):
        args = rpods.build_parser().parse_args(["--tunnel", "pixlstash", "vlm"])
        with mock.patch.object(rpods, "ssh_argv", return_value=self.base), \
             mock.patch.object(pix, "run_tunnel", return_value=0) as tunnel:
            self.assertEqual(rpods.connect_or_tunnel(self.choice, "/tmp/key", args), 0)
        self.assertEqual(tunnel.call_args.kwargs["ollama_local_port"], 47961)
        self.assertEqual(tunnel.call_args.kwargs["ollama_remote_port"], 11434)
        self.assertEqual(tunnel.call_args.kwargs["local_comfy_port"], 47960)
        self.assertEqual(tunnel.call_args.kwargs["remote_pixlstash_port"], 64404)

    def test_rpods_dispatches_ollama_alone(self):
        args = rpods.build_parser().parse_args(["--tunnel", "vlm"])
        with mock.patch.object(rpods, "ssh_argv", return_value=self.base), \
             mock.patch.object(vlm, "run_tunnel", return_value=0) as tunnel:
            self.assertEqual(rpods.connect_or_tunnel(self.choice, "/tmp/key", args), 0)
        self.assertEqual(tunnel.call_args.kwargs["local_ollama_port"], 47961)

    def test_skills_zip_preflight_and_streams_on_same_ssh_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_zip(directory)
            payload = vlm.check_skills_zip(path)
            self.assertGreater(len(payload), 50)
            fake = SimpleNamespace(returncode=0,
                                   stdout=b"[rpods] Installed 3 files\n",
                                   stderr=b"")
            with mock.patch.object(vlm.subprocess, "run", return_value=fake) as run, \
                 mock.patch("sys.stdout"):
                vlm.push_skills_zip(self.base, path)
            self.assertEqual(run.call_args.kwargs["input"], payload)
            command = run.call_args.args[0]
            self.assertEqual(command[:len(self.base)-1], self.base[:-1])
            self.assertIn("python3 -c ", command[-1])
            self.assertEqual(command[-2], self.base[-1])
            self.assertNotIn("scp", command)
            args = rpods.build_parser().parse_args(["--skills-zip", str(path)])
            with mock.patch.object(rpods, "ssh_argv", return_value=self.base), \
                 mock.patch.object(vlm, "push_skills_zip") as upload, \
                 mock.patch.object(rpods, "connect") as shell:
                self.assertEqual(rpods.connect_or_tunnel(self.choice, "/tmp/key", args), 0)
            upload.assert_called_once_with(self.base, str(path))
            shell.assert_not_called()

    def test_rejects_path_traversal_and_symlink_in_skill_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            for bad in (
                {"image-detailer-analysis/SKILL.md": "#ok", "../oops": "bad"},
                {"image-detailer-analysis/SKILL.md": "#ok",
                 "image-detailer-analysis/../../etc/passwd": "bad"},
                {"other/SKILL.md": "wrong"},
            ):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        vlm.check_skills_zip(self.make_zip(directory, bad))
            path = Path(directory)/"linked.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("image-detailer-analysis/SKILL.md", "# Skill")
                entry = zipfile.ZipInfo("image-detailer-analysis/secret")
                entry.create_system = 3
                entry.external_attr = (0o120777 << 16)
                archive.writestr(entry, "/etc/passwd")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                vlm.check_skills_zip(path)

    def test_failed_upload_does_not_start_tunnel(self):
        args = rpods.build_parser().parse_args(
            ["--tunnel", "pixlstash", "vlm", "--skills-zip", "/missing.zip"])
        with mock.patch.object(rpods, "ssh_argv", return_value=self.base), \
             mock.patch.object(vlm, "push_skills_zip",
                               side_effect=ValueError("upload failed")), \
             mock.patch.object(pix, "run_tunnel") as tunnel:
            with self.assertRaisesRegex(ValueError, "upload failed"):
                rpods.connect_or_tunnel(self.choice, "/tmp/key", args)
            tunnel.assert_not_called()

    def test_ollama_endpoint_identified_by_api_version(self):
        response = mock.Mock()
        response.status = 200
        response.read.return_value = b'{"version":"0.13.2"}'
        conn = mock.Mock()
        conn.getresponse.return_value = response
        with mock.patch.object(vlm.http.client, "HTTPConnection", return_value=conn):
            self.assertTrue(vlm.is_ollama(47961))
        conn.request.assert_called_once_with("GET", "/api/version")
        response.read.return_value = b'{"unrelated":"service"}'
        with mock.patch.object(vlm.http.client, "HTTPConnection", return_value=conn):
            self.assertFalse(vlm.is_ollama(47961))

    def test_ollama_tunnel_stops_on_ctrl_c(self):
        fake = mock.Mock()
        fake.poll.return_value = None
        fake.wait.side_effect = [KeyboardInterrupt, 0]
        with mock.patch.object(vlm, "is_ollama", return_value=True), \
             mock.patch.object(vlm.subprocess, "Popen", return_value=fake) as popen, \
             mock.patch("sys.stdout"):
            self.assertEqual(vlm.run_tunnel(self.base), 130)
        fake.terminate.assert_called_once()
        self.assertIn("-L", popen.call_args.args[0])

    def test_combined_tunnel_probes_ollama(self):
        fake = mock.Mock()
        fake.poll.return_value = None
        fake.wait.side_effect = [KeyboardInterrupt, 0]
        with mock.patch.object(pix, "discover_pixlstash_port", return_value=61234), \
             mock.patch.object(pix, "_comfy_responds", return_value=True), \
             mock.patch.object(pix, "_remote_pixlstash_responds", return_value=True), \
             mock.patch.object(vlm, "is_ollama", return_value=True) as probe, \
             mock.patch.object(pix.subprocess, "Popen", return_value=fake) as popen, \
             mock.patch("sys.stdout"):
            self.assertEqual(pix.run_tunnel(self.base, ollama_local_port=47961), 130)
        probe.assert_called_once_with(47961)
        self.assertEqual(popen.call_args.args[0].count("-L"), 2)


if __name__ == "__main__":
    unittest.main()
