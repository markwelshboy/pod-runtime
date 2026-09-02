import importlib.util
import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_lifecycle.py"
spec = importlib.util.spec_from_file_location("rent_pod_lifecycle", MODULE)
lifecycle = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lifecycle)


class RentPodLifecycleTests(unittest.TestCase):
    def rest_pod(self):
        return {
            "id": "p1",
            "machineId": "m1",
            "desiredStatus": "RUNNING",
            "machine": {
                "dataCenterId": "US-1",
                "maxDownloadSpeedMbps": 4752,
                "maxUploadSpeedMbps": 10072,
            },
        }

    def test_starting_when_runtime_is_null(self):
        snapshot = lifecycle.build_snapshot(
            self.rest_pod(),
            {
                "id": "p1",
                "desiredStatus": "RUNNING",
                "lastStatusChange": "Rented by User",
                "runtime": None,
            },
        )
        self.assertEqual(snapshot["stage"], "STARTING")
        self.assertFalse(snapshot["runtime_present"])
        self.assertIsNone(snapshot["ssh_port"])
        self.assertEqual(snapshot["last_event"], "Rented by User")

    def test_container_when_runtime_appears(self):
        snapshot = lifecycle.build_snapshot(
            self.rest_pod(),
            {
                "id": "p1",
                "desiredStatus": "RUNNING",
                "runtime": {"uptimeInSeconds": 4, "ports": []},
            },
        )
        self.assertEqual(snapshot["stage"], "CONTAINER")
        self.assertTrue(snapshot["runtime_present"])
        self.assertEqual(snapshot["uptime"], 4)

    def test_network_when_public_ssh_mapping_appears(self):
        snapshot = lifecycle.build_snapshot(
            self.rest_pod(),
            {
                "id": "p1",
                "desiredStatus": "RUNNING",
                "runtime": {
                    "uptimeInSeconds": 10,
                    "ports": [
                        {
                            "ip": "1.2.3.4",
                            "isIpPublic": True,
                            "privatePort": 22,
                            "publicPort": 38192,
                            "type": "tcp",
                        }
                    ],
                },
            },
        )
        self.assertEqual(snapshot["stage"], "NETWORK")
        self.assertEqual(snapshot["public_ip"], "1.2.3.4")
        self.assertEqual(snapshot["ssh_port"], 38192)

    def test_stopped_overrides_stale_runtime(self):
        snapshot = lifecycle.build_snapshot(
            self.rest_pod(),
            {
                "id": "p1",
                "desiredStatus": "STOPPED",
                "runtime": {
                    "uptimeInSeconds": 100,
                    "ports": [
                        {
                            "ip": "1.2.3.4",
                            "isIpPublic": True,
                            "privatePort": 22,
                            "publicPort": 38192,
                            "type": "tcp",
                        }
                    ],
                },
            },
        )
        self.assertEqual(snapshot["stage"], "STOPPED")

    def test_elapsed_format(self):
        self.assertEqual(lifecycle.format_elapsed(18), "00:18")
        self.assertEqual(lifecycle.format_elapsed(167), "02:47")
        self.assertEqual(lifecycle.format_elapsed(3661), "1:01:01")


if __name__ == "__main__":
    unittest.main()
