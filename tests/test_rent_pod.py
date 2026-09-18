import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
import io

MODULE = Path(__file__).resolve().parents[1] / "bin" / "rent_pod.py"
spec = importlib.util.spec_from_file_location("rent_pod", MODULE)
rent_pod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rent_pod
assert spec.loader is not None
spec.loader.exec_module(rent_pod)


class RentPodTests(unittest.TestCase):
    def test_gpu_aliases(self):
        self.assertEqual(rent_pod.resolve_gpu("4090"), "NVIDIA GeForce RTX 4090")
        self.assertEqual(rent_pod.resolve_gpu("L40S"), "NVIDIA L40S")
        self.assertEqual(rent_pod.resolve_gpu("Custom GPU"), "Custom GPU")

    def test_pod_identity(self):
        pod = {
            "id": "pod1",
            "machineId": "m1",
            "publicIp": "1.2.3.4",
            "portMappings": {"22": 2222},
            "adjustedCostPerHr": 0.5,
            "gpu": {"displayName": "RTX 4090"},
            "machine": {
                "dataCenterId": "DC1",
                "location": "US",
                "maxDownloadSpeedMbps": 900,
                "maxUploadSpeedMbps": 500,
                "diskThroughputMBps": 3000,
            },
        }
        got = rent_pod.pod_identity(pod)
        self.assertEqual(got["ssh_port"], 2222)
        self.assertEqual(got["machine_id"], "m1")
        self.assertEqual(got["max_download_mbps"], 900)

    def test_rejection_match_prefers_machine(self):
        identity = {"machine_id": "m2", "public_ip": "1.2.3.4"}
        match = rent_pod.rejection_match(
            identity,
            [{"machine_id": "m2", "reason": "bad"}],
        )
        self.assertIsNotNone(match)
        self.assertEqual(match[0], "machine_id")

    def test_recent_rejection_ttl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            now = datetime.now(timezone.utc)
            rent_pod.save_rejections(
                path,
                [
                    {
                        "timestamp": (now - timedelta(hours=1)).isoformat(),
                        "machine_id": "new",
                    },
                    {
                        "timestamp": (now - timedelta(hours=48)).isoformat(),
                        "machine_id": "old",
                    },
                ],
            )
            got = rent_pod.recent_rejections(path, 24)
            self.assertEqual([item["machine_id"] for item in got], ["new"])


    def test_confirmed_delete_recovers_when_delete_times_out_but_probe_is_404(self):
        timeout_error = rent_pod.RunPodError("TLS handshake timed out")
        gone = rent_pod.RunPodError("not found", status_code=404)
        with mock.patch.object(
            rent_pod, "delete_pod", side_effect=timeout_error
        ) as delete, mock.patch.object(
            rent_pod, "get_pod", side_effect=gone
        ) as get:
            rent_pod.delete_pod_confirmed(
                "token", "pod123", attempts=3, retry_delay=0, timeout=1
            )
        delete.assert_called_once_with("token", "pod123", timeout=1)
        get.assert_called_once_with("token", "pod123", timeout=1)

    def test_confirmed_delete_retries_until_probe_returns_404(self):
        gone = rent_pod.RunPodError("not found", status_code=404)
        with mock.patch.object(
            rent_pod,
            "delete_pod",
            side_effect=[rent_pod.RunPodError("TLS timeout"), None],
        ) as delete, mock.patch.object(
            rent_pod,
            "get_pod",
            side_effect=[{"id": "pod123"}, gone],
        ) as get, mock.patch.object(rent_pod.time, "sleep") as sleep:
            rent_pod.delete_pod_confirmed(
                "token", "pod123", attempts=3, retry_delay=1, timeout=1
            )
        self.assertEqual(delete.call_count, 2)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_confirmed_delete_raises_when_absence_cannot_be_confirmed(self):
        with mock.patch.object(
            rent_pod, "delete_pod", side_effect=rent_pod.RunPodError("TLS timeout")
        ), mock.patch.object(
            rent_pod, "get_pod", return_value={"id": "pod123"}
        ), mock.patch.object(rent_pod.time, "sleep"):
            with self.assertRaises(rent_pod.RunPodError) as ctx:
                rent_pod.delete_pod_confirmed(
                    "token", "pod123", attempts=2, retry_delay=0, timeout=1
                )
        self.assertIn("could not confirm deletion of pod pod123", str(ctx.exception))

    def test_cleanup_failure_prints_loud_manual_recovery(self):
        err = rent_pod.RunPodError("still present")
        stderr = io.StringIO()
        with mock.patch.object(
            rent_pod, "delete_pod_confirmed", side_effect=err
        ), redirect_stderr(stderr):
            ok = rent_pod.cleanup_inflight_pod("token", "pod123", "q3c")
        self.assertFalse(ok)
        text = stderr.getvalue()
        self.assertIn("POD DELETION NOT CONFIRMED", text)
        self.assertIn("q3c (pod123)", text)
        self.assertIn("rent-pod --kill pod123", text)


if __name__ == "__main__":
    unittest.main()
