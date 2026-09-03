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

    def test_requested_name_supports_split_and_equals(self):
        self.assertEqual(
            vcp_handoff.requested_name(["l40s", "--name", "comfydev3900"]),
            "comfydev3900",
        )
        self.assertEqual(
            vcp_handoff.requested_name(["l40s", "--name=comfydev3900"]),
            "comfydev3900",
        )

    def test_display_command_uses_named_target_proven_endpoint_and_key(self):
        got = vcp_handoff.vcp_display_command(
            {"public_ip": "64.247.206.216", "ssh_port": 13479, "pod_id": "pod123"},
            "/home/markr/.ssh/id_ed25519_runpod",
            "comfydev3900",
        )
        self.assertEqual(
            got,
            "vcp config comfydev3900 ssh -i /home/markr/.ssh/id_ed25519_runpod "
            "-p 13479 root@64.247.206.216",
        )

    def test_wait_hook_prints_named_manual_handoff_on_success(self):
        def fake_wait(*args, **kwargs):
            return {"public_ip": "1.2.3.4", "ssh_port": 2222, "pod_id": "pod123"}, None

        vcp_handoff.core.wait_for_ssh = fake_wait
        vcp_handoff.core.run_provision = lambda identity, key: 0
        vcp_handoff.install_core_hooks(False, "comfydev3900")

        out = io.StringIO()
        with redirect_stdout(out):
            identity, reason = vcp_handoff.core.wait_for_ssh(
                "token", "pod", "/tmp/key", 10, 1, Path("/tmp/state"), 24, False
            )
        self.assertIsNone(reason)
        self.assertEqual(identity["ssh_port"], 2222)
        text = out.getvalue()
        self.assertIn(
            "vcp config comfydev3900 ssh -i /tmp/key -p 2222 root@1.2.3.4",
            text,
        )
        self.assertIn("vcp target comfydev3900", text)

    def test_wait_hook_does_not_print_for_rejected_pod(self):
        def fake_wait(*args, **kwargs):
            return {"public_ip": "1.2.3.4", "ssh_port": 2222}, "ssh-exposure-timeout"

        vcp_handoff.core.wait_for_ssh = fake_wait
        vcp_handoff.core.run_provision = lambda identity, key: 0
        vcp_handoff.install_core_hooks(False, "target-a")

        out = io.StringIO()
        with redirect_stdout(out):
            _identity, reason = vcp_handoff.core.wait_for_ssh(
                "token", "pod", "/tmp/key", 10, 1, Path("/tmp/state"), 24, False
            )
        self.assertEqual(reason, "ssh-exposure-timeout")
        self.assertNotIn("VCP target", out.getvalue())

    def test_auto_config_only_after_successful_provision(self):
        identity = {"public_ip": "1.2.3.4", "ssh_port": 2222, "pod_id": "pod123"}
        vcp_handoff.core.wait_for_ssh = lambda *args, **kwargs: (identity, None)
        vcp_handoff.core.run_provision = lambda identity, key: 0

        with mock.patch.object(vcp_handoff, "configure_vcp", return_value=0) as configure:
            vcp_handoff.install_core_hooks(True, "comfydev3900")
            rc = vcp_handoff.core.run_provision(identity, "/tmp/key")
        self.assertEqual(rc, 0)
        configure.assert_called_once_with(identity, "/tmp/key", "comfydev3900")

    def test_configure_vcp_records_pod_metadata_and_activates_target(self):
        identity = {
            "public_ip": "1.2.3.4",
            "ssh_port": 2222,
            "pod_id": "pod123",
            "machine_id": "machine456",
            "gpu": "NVIDIA L40S",
        }
        with mock.patch.object(vcp_handoff.vcp_targets, "save_target") as save:
            rc = vcp_handoff.configure_vcp(identity, "/tmp/key", "l40development")
        self.assertEqual(rc, 0)
        args, kwargs = save.call_args
        self.assertEqual(args[0], "l40development")
        self.assertEqual(args[1], ["-i", "/tmp/key", "-p", "2222", "root@1.2.3.4"])
        self.assertEqual(kwargs["pod_id"], "pod123")
        self.assertEqual(kwargs["provider"], "runpod")
        self.assertTrue(kwargs["make_active"])
        self.assertEqual(kwargs["metadata"]["machine_id"], "machine456")

    def test_failed_provision_never_retargets_vcp(self):
        identity = {"public_ip": "1.2.3.4", "ssh_port": 2222}
        vcp_handoff.core.wait_for_ssh = lambda *args, **kwargs: (identity, None)
        vcp_handoff.core.run_provision = lambda identity, key: 78

        with mock.patch.object(vcp_handoff, "configure_vcp", return_value=0) as configure:
            vcp_handoff.install_core_hooks(True, "target-a")
            rc = vcp_handoff.core.run_provision(identity, "/tmp/key")
        self.assertEqual(rc, 78)
        configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
