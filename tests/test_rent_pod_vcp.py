import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_vcp.py"
spec = importlib.util.spec_from_file_location("rent_pod_vcp", MODULE)
vcp_handoff = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(vcp_handoff)


class RentPodVcpTests(unittest.TestCase):
    def setUp(self):
        self.original_wait = vcp_handoff.core.wait_for_ssh
        self.original_run_provision = vcp_handoff.core.run_provision
        vcp_handoff._installed = False

    def tearDown(self):
        vcp_handoff.core.wait_for_ssh = self.original_wait
        vcp_handoff.core.run_provision = self.original_run_provision
        vcp_handoff._installed = False

    def test_consume_vcp_arg(self):
        argv, enabled = vcp_handoff.consume_vcp_args(
            ["l40s", "--vcp", "--cuda-min", "13.0"]
        )
        self.assertTrue(enabled)
        self.assertEqual(argv, ["l40s", "--cuda-min", "13.0"])

    def test_display_command_uses_proven_endpoint_and_key(self):
        got = vcp_handoff.vcp_display_command(
            {"public_ip": "64.247.206.216", "ssh_port": 13479},
            "/home/markr/.ssh/id_ed25519_runpod",
        )
        self.assertEqual(
            got,
            "vcp config ssh -i /home/markr/.ssh/id_ed25519_runpod "
            "-p 13479 root@64.247.206.216",
        )

    def test_wait_hook_prints_manual_handoff_on_success(self):
        def fake_wait(*args, **kwargs):
            return {"public_ip": "1.2.3.4", "ssh_port": 2222}, None

        vcp_handoff.core.wait_for_ssh = fake_wait
        vcp_handoff.core.run_provision = lambda identity, key: 0
        vcp_handoff.install_core_hooks(False)

        out = io.StringIO()
        with redirect_stdout(out):
            identity, reason = vcp_handoff.core.wait_for_ssh(
                "token", "pod", "/tmp/key", 10, 1, Path("/tmp/state"), 24, False
            )
        self.assertIsNone(reason)
        self.assertEqual(identity["ssh_port"], 2222)
        self.assertIn("vcp config ssh -i /tmp/key -p 2222 root@1.2.3.4", out.getvalue())

    def test_wait_hook_does_not_print_for_rejected_pod(self):
        def fake_wait(*args, **kwargs):
            return {"public_ip": "1.2.3.4", "ssh_port": 2222}, "ssh-exposure-timeout"

        vcp_handoff.core.wait_for_ssh = fake_wait
        vcp_handoff.core.run_provision = lambda identity, key: 0
        vcp_handoff.install_core_hooks(False)

        out = io.StringIO()
        with redirect_stdout(out):
            _identity, reason = vcp_handoff.core.wait_for_ssh(
                "token", "pod", "/tmp/key", 10, 1, Path("/tmp/state"), 24, False
            )
        self.assertEqual(reason, "ssh-exposure-timeout")
        self.assertNotIn("VCP remote", out.getvalue())

    def test_auto_config_only_after_successful_provision(self):
        identity = {"public_ip": "1.2.3.4", "ssh_port": 2222}
        vcp_handoff.core.wait_for_ssh = lambda *args, **kwargs: (identity, None)
        vcp_handoff.core.run_provision = lambda identity, key: 0

        with mock.patch.object(vcp_handoff, "configure_vcp", return_value=0) as configure:
            vcp_handoff.install_core_hooks(True)
            rc = vcp_handoff.core.run_provision(identity, "/tmp/key")
        self.assertEqual(rc, 0)
        configure.assert_called_once_with(identity, "/tmp/key")

    def test_failed_provision_never_retargets_vcp(self):
        identity = {"public_ip": "1.2.3.4", "ssh_port": 2222}
        vcp_handoff.core.wait_for_ssh = lambda *args, **kwargs: (identity, None)
        vcp_handoff.core.run_provision = lambda identity, key: 78

        with mock.patch.object(vcp_handoff, "configure_vcp", return_value=0) as configure:
            vcp_handoff.install_core_hooks(True)
            rc = vcp_handoff.core.run_provision(identity, "/tmp/key")
        self.assertEqual(rc, 78)
        configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
