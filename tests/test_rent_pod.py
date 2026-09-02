import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
