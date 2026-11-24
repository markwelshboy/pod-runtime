"""Offline regression tests for rpods PixlStash/ComfyUI bidirectional tunnels.

No RunPod API calls or paid Pods are involved.
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rpods
import rpods_pixlstash as pix


class PixlStashTunnelTests(unittest.TestCase):
    def setUp(self):
        self.base = [
            "ssh", "-o", "BatchMode=yes", "-i", "/home/markr/.ssh/id_ed25519_runpod",
            "-p", "47960", "root@103.196.86.5",
        ]

    def test_parser_preserves_existing_rpods_and_adds_pixlstash_mode(self):
        args = rpods.build_parser().parse_args(
            ["rp-krea2-wait-2", "--tunnel", "pixlstash"]
        )
        self.assertEqual(args.selector, "rp-krea2-wait-2")
        self.assertEqual(args.tunnel, ["pixlstash"])
        self.assertEqual(args.local_port, 47960)
        self.assertEqual(args.comfy_port, 8288)
        self.assertIsNone(args.pixlstash_port)
        self.assertEqual(args.pixlstash_remote_port, 64404)
        self.assertIsNone(rpods.build_parser().parse_args([]).tunnel)

    def test_parser_can_override_all_four_ports(self):
        args = rpods.build_parser().parse_args([
            "--tunnel", "pixlstash", "--local-port", "18188",
            "--comfy-port", "8188", "--pixlstash-port", "61234",
            "--pixlstash-remote-port", "64404",
        ])
        self.assertEqual((args.local_port, args.comfy_port, args.pixlstash_port),
                         (18188, 8188, 61234))

    def test_parser_rejects_invalid_port(self):
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                rpods.build_parser().parse_args(["--local-port", "70000"])

    def test_tunnel_argv_is_bidirectional_loopback_only(self):
        args = pix.tunnel_argv(
            self.base,
            local_comfy_port=47960, remote_comfy_port=8288,
            local_pixlstash_port=61234, remote_pixlstash_port=64404,
        )
        self.assertEqual(args[0], "ssh")
        self.assertEqual(args[-1], "root@103.196.86.5")
        self.assertIn("ExitOnForwardFailure=yes", args)
        self.assertIn("ServerAliveInterval=30", args)
        self.assertIn("ServerAliveCountMax=3", args)
        self.assertIn("-N", args)
        self.assertIn("-T", args)
        self.assertEqual(args[args.index("-L")+1],
                         "127.0.0.1:47960:127.0.0.1:8288")
        self.assertEqual(args[args.index("-R")+1],
                         "127.0.0.1:64404:127.0.0.1:61234")

    def test_custom_comfy_port(self):
        args = pix.tunnel_argv(
            self.base, local_comfy_port=18188, remote_comfy_port=8188,
            local_pixlstash_port=64404, remote_pixlstash_port=64404,
        )
        self.assertIn("127.0.0.1:18188:127.0.0.1:8188", args)

    def test_explicit_pixlstash_port_must_pass_version_probe(self):
        with mock.patch.object(pix, "_is_pixlstash", return_value=True) as probe:
            self.assertEqual(pix.discover_pixlstash_port(61234), 61234)
        probe.assert_called_once_with(61234)
        with mock.patch.object(pix, "_is_pixlstash", return_value=False):
            with self.assertRaisesRegex(ValueError, "did not answer"):
                pix.discover_pixlstash_port(61234)

    def test_environment_override(self):
        with mock.patch.dict("os.environ", {"PIXLSTASH_API_PORT": "61234"}), \
             mock.patch.object(pix, "_is_pixlstash", return_value=True):
            self.assertEqual(pix.discover_pixlstash_port(), 61234)

    def test_autodiscovery_uses_windows_listeners_and_checks_identity(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(pix, "_windows_listening_ports", return_value=[61111, 61234]), \
             mock.patch.object(pix, "_linux_listening_ports", return_value=[]), \
             mock.patch.object(pix, "_is_pixlstash", side_effect=lambda p: p == 61234):
            self.assertEqual(pix.discover_pixlstash_port(), 61234)

    def test_ambiguous_autodiscovery_rejected(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(pix, "_windows_listening_ports", return_value=[61111, 61234]), \
             mock.patch.object(pix, "_linux_listening_ports", return_value=[]), \
             mock.patch.object(pix, "_is_pixlstash",
                               side_effect=lambda p: p in {61111, 61234}):
            with self.assertRaisesRegex(ValueError, "More than one"):
                pix.discover_pixlstash_port()

    def test_failed_autodiscovery_has_override_help(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(pix, "_windows_listening_ports", return_value=[]), \
             mock.patch.object(pix, "_linux_listening_ports", return_value=[]), \
             mock.patch.object(pix, "_is_pixlstash", return_value=False):
            with self.assertRaisesRegex(ValueError, "--pixlstash-port"):
                pix.discover_pixlstash_port()

    def test_windows_ports_are_parsed_without_needing_admin_process_lookup(self):
        output = SimpleNamespace(
            returncode=0, stdout="61234\r\n64404\r\nnope\r\n80\r\n",
        )
        with mock.patch.object(pix.shutil, "which", return_value="powershell.exe"), \
             mock.patch.object(pix.subprocess, "run", return_value=output) as run:
            self.assertEqual(pix._windows_listening_ports(), [61234, 64404])
        self.assertIn("Get-NetTCPConnection", run.call_args.args[0][-1])

    def test_rpods_dispatches_to_pixlstash_helper_with_selected_pod(self):
        choice = rpods.PodChoice(
            pod_id="pod123", name="rp-krea2-wait-2", stage="NETWORK",
            gpu="L40S", machine="-", datacenter="US-NC-1",
            public_ip="103.196.86.5", ssh_port=47960,
            uptime_seconds=42, started_at=None,
        )
        args = rpods.build_parser().parse_args(["--tunnel", "pixlstash"])
        with mock.patch.object(pix, "run_tunnel", return_value=0) as runner:
            self.assertEqual(rpods.connect_or_tunnel(choice, "/tmp/key", args), 0)
        self.assertEqual(runner.call_args.kwargs, {
            "local_comfy_port": 47960,
            "remote_comfy_port": 8288,
            "pixlstash_port": None,
            "remote_pixlstash_port": 64404,
        })
        self.assertIn("root@103.196.86.5", runner.call_args.args[0])

    def test_run_tunnel_stops_ssh_on_interrupt(self):
        fake = mock.Mock()
        fake.poll.return_value = None
        fake.wait.side_effect = [KeyboardInterrupt, 0]
        with mock.patch.object(pix, "discover_pixlstash_port", return_value=61234), \
             mock.patch.object(pix, "_comfy_responds", return_value=True), \
             mock.patch.object(pix, "_remote_pixlstash_responds", return_value=True), \
             mock.patch.object(pix.subprocess, "Popen", return_value=fake) as launched, \
             mock.patch("sys.stdout"):
            self.assertEqual(pix.run_tunnel(self.base), 130)
        fake.terminate.assert_called_once()
        self.assertIn("-R", launched.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
