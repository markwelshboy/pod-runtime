import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_ssh_phases.py"
spec = importlib.util.spec_from_file_location("rent_pod_ssh_phases", MODULE)
phases = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(phases)


class RentPodSshPhaseTests(unittest.TestCase):
    def test_exposure_timeout_env_and_cli_precedence(self):
        argv, timeout = phases.consume_ssh_phase_args(
            ["l40s"], {"RENT_POD_SSH_EXPOSURE_TIMEOUT": "240"}
        )
        self.assertEqual(argv, ["l40s"])
        self.assertEqual(timeout, 240)

        argv, timeout = phases.consume_ssh_phase_args(
            ["l40s", "--ssh-exposure-timeout", "120"],
            {"RENT_POD_SSH_EXPOSURE_TIMEOUT": "240"},
        )
        self.assertEqual(argv, ["l40s"])
        self.assertEqual(timeout, 120)

    def test_invalid_exposure_timeout_rejected(self):
        with self.assertRaises(ValueError):
            phases.consume_ssh_phase_args(
                ["l40s", "--ssh-exposure-timeout=0"], {}
            )

    def test_observed_endpoints_keeps_graphql_and_rest_candidates(self):
        rest_pod = {
            "publicIp": "1.2.3.4",
            "portMappings": {"22": 13481},
        }
        snapshot = {
            "public_ip": "1.2.3.4",
            "ssh_port": 13479,
        }
        self.assertEqual(
            phases.observed_endpoints(rest_pod, snapshot),
            [("1.2.3.4", 13479), ("1.2.3.4", 13481)],
        )

    def test_recent_mapping_is_retained_then_expires(self):
        recent = {}
        got = phases.retain_endpoints(recent, [("1.2.3.4", 1111)], 100.0, 90)
        self.assertEqual(got, [("1.2.3.4", 1111)])

        got = phases.retain_endpoints(recent, [("1.2.3.4", 2222)], 150.0, 90)
        self.assertEqual(got[0], ("1.2.3.4", 2222))
        self.assertIn(("1.2.3.4", 1111), got)

        got = phases.retain_endpoints(recent, [("1.2.3.4", 2222)], 195.0, 90)
        self.assertNotIn(("1.2.3.4", 1111), got)

    def test_phase_progression(self):
        self.assertEqual(
            phases.phase_for({"runtime_present": False, "stage": "STARTING"}, None),
            "STARTING",
        )
        self.assertEqual(
            phases.phase_for({"runtime_present": True, "stage": "CONTAINER"}, None),
            "CONTAINER",
        )
        self.assertEqual(
            phases.phase_for(
                {"runtime_present": True, "stage": "NETWORK"},
                {"tcp_ready": False, "banner_ready": False, "auth_ready": None},
            ),
            "NETWORK",
        )
        self.assertEqual(
            phases.phase_for(
                {"runtime_present": True, "stage": "NETWORK"},
                {"tcp_ready": True, "banner_ready": True, "auth_ready": False},
            ),
            "SSH",
        )

    def test_auth_probe_only_after_banner(self):
        with tempfile.NamedTemporaryFile() as fh, mock.patch.object(
            phases, "tcp_and_banner_ready", return_value=(True, True)
        ), mock.patch.object(phases.core, "ssh_ready", return_value=True) as ssh_ready:
            probes = phases.probe_endpoints([("1.2.3.4", 2222)], fh.name)
        self.assertTrue(probes[0]["tcp_ready"])
        self.assertTrue(probes[0]["banner_ready"])
        self.assertTrue(probes[0]["auth_ready"])
        ssh_ready.assert_called_once()

    def test_ssh_command_text_is_copy_paste_ready(self):
        command = phases.ssh_command_text(
            {"ip": "64.247.206.212", "port": 14463},
            "/tmp/key with space",
        )
        self.assertEqual(
            command,
            "ssh -p 14463 -i '/tmp/key with space' root@64.247.206.212",
        )

    def test_status_prints_full_ssh_command(self):
        rest_pod = {"id": "p1", "desiredStatus": "RUNNING"}
        snapshot = {
            "stage": "NETWORK",
            "runtime_present": True,
            "uptime": 10,
            "desired_status": "RUNNING",
            "last_event": None,
            "public_ip": "64.247.206.212",
            "ssh_port": 14463,
            "probe_error": None,
        }
        probe = {
            "ip": "64.247.206.212",
            "port": 14463,
            "tcp_ready": True,
            "banner_ready": True,
            "auth_ready": True,
        }
        output = io.StringIO()
        with mock.patch.object(
            phases.lifecycle, "_fetch_snapshot", return_value=(rest_pod, snapshot)
        ), mock.patch.object(
            phases, "observed_endpoints", return_value=[("64.247.206.212", 14463)]
        ), mock.patch.object(
            phases, "probe_endpoints", return_value=[probe]
        ), mock.patch.object(
            phases.lifecycle, "pod_age_seconds", return_value=None
        ), redirect_stdout(output):
            rc = phases.status_pod("token", "p1", "/home/markr/.ssh/id_ed25519_runpod")

        self.assertEqual(rc, 0)
        self.assertIn(
            "SSH command: ssh -p 14463 -i /home/markr/.ssh/id_ed25519_runpod root@64.247.206.212",
            output.getvalue(),
        )

    def test_runtime_uptime_drives_exposure_deadline(self):
        deadline = phases._runtime_deadline(
            1000.0, {"uptime": 120}, phases.DEFAULT_SSH_EXPOSURE_TIMEOUT
        )
        self.assertEqual(deadline, 1060.0)

    def test_live_runtime_timeout_has_specific_rejection_reason(self):
        rest_pod = {"id": "p1", "desiredStatus": "RUNNING"}
        snapshot = {
            "stage": "CONTAINER",
            "runtime_present": True,
            "uptime": phases.DEFAULT_SSH_EXPOSURE_TIMEOUT + 1,
            "desired_status": "RUNNING",
            "last_event": None,
            "public_ip": None,
            "ssh_port": None,
            "probe_error": None,
        }
        with mock.patch.object(
            phases.lifecycle, "_fetch_snapshot", return_value=(rest_pod, snapshot)
        ), mock.patch.object(phases.core, "recent_rejections", return_value=[]):
            identity, reason = phases.wait_for_ssh(
                "token",
                "p1",
                "/missing/key",
                900,
                5,
                Path("/tmp/unused.json"),
                24,
                True,
                phases.DEFAULT_SSH_EXPOSURE_TIMEOUT,
            )
        self.assertEqual(identity["pod_id"], "p1")
        self.assertEqual(reason, "ssh-exposure-timeout")


if __name__ == "__main__":
    unittest.main()
