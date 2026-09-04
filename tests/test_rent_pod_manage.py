import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_manage.py"
spec = importlib.util.spec_from_file_location("rent_pod_manage", MODULE)
manage = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(manage)


class RentPodManageTests(unittest.TestCase):
    def test_parse_show(self):
        self.assertEqual(
            manage.parse_management_args(["--show"]),
            {"action": "show", "pod_id": None, "assume_yes": False},
        )

    def test_parse_kill(self):
        self.assertEqual(
            manage.parse_management_args(["--kill", "abc123"]),
            {"action": "kill", "pod_id": "abc123", "assume_yes": False},
        )
        self.assertEqual(
            manage.parse_management_args(["--kill=xyz789"]),
            {"action": "kill", "pod_id": "xyz789", "assume_yes": False},
        )

    def test_parse_kill_all_yes(self):
        self.assertEqual(
            manage.parse_management_args(["--kill-all", "--yes"]),
            {"action": "kill-all", "pod_id": None, "assume_yes": True},
        )
        self.assertTrue(
            manage.parse_management_args(["--kill-all", "--force"])["assume_yes"]
        )

    def test_management_modes_conflict(self):
        with self.assertRaises(ValueError):
            manage.parse_management_args(["--show", "--kill", "abc123"])

    def test_management_rejects_rental_options(self):
        with self.assertRaises(ValueError):
            manage.parse_management_args(["--show", "4090"])

    def test_non_management_returns_none(self):
        self.assertIsNone(manage.parse_management_args(["4090", "--cuda-min", "13.0"]))

    def test_pod_row(self):
        pod = {
            "id": "pod1",
            "name": "podlet-4090",
            "desiredStatus": "RUNNING",
            "gpuTypeId": "NVIDIA GeForce RTX 4090",
            "gpuCount": 1,
            "costPerHr": 0.74,
            "publicIp": "1.2.3.4",
            "portMappings": {"22": 2222},
            "machineId": "m1",
            "machine": {"dataCenterId": "US-CA-1"},
        }
        row = manage.pod_row(pod)
        self.assertEqual(row["id"], "pod1")
        self.assertEqual(row["status"], "RUNNING")
        self.assertEqual(row["cost"], "$0.740")
        self.assertEqual(row["dc"], "US-CA-1")
        self.assertEqual(row["ssh"], "1.2.3.4:2222")

    def test_pod_row_prefers_live_runtime_ssh_mapping(self):
        rest_pod = {
            "id": "pod1",
            "name": "podlet-l40s",
            "desiredStatus": "RUNNING",
            "gpuTypeId": "NVIDIA L40S",
            "gpuCount": 1,
            "costPerHr": 0.99,
            "publicIp": "64.247.206.216",
            "portMappings": {"22": 13481},
            "machineId": "m1",
            "machine": {"dataCenterId": "US-MO-1"},
        }
        gql_pod = {
            "id": "pod1",
            "desiredStatus": "RUNNING",
            "runtime": {
                "uptimeInSeconds": 122,
                "ports": [
                    {
                        "ip": "64.247.206.216",
                        "isIpPublic": True,
                        "privatePort": 22,
                        "publicPort": 13479,
                        "type": "tcp",
                    }
                ],
            },
        }
        row = manage.pod_row(rest_pod, gql_pod)
        self.assertEqual(row["status"], "NETWORK")
        self.assertEqual(row["ssh"], "64.247.206.216:13479")

    def test_pod_vcp_endpoints_uses_rest_ssh_mapping(self):
        pod = {
            "id": "pod1",
            "publicIp": "64.247.206.212",
            "portMappings": {"22": 14463},
        }
        self.assertEqual(
            manage.pod_vcp_endpoints(pod),
            {("64.247.206.212", 14463)},
        )

    def test_kill_pod_reaps_vcp_after_successful_delete(self):
        pod = {
            "id": "pod123",
            "name": "qwen3-captioning",
            "publicIp": "64.247.206.212",
            "portMappings": {"22": 14463},
        }
        with mock.patch.object(manage.core, "get_pod", return_value=pod), \
             mock.patch.object(manage.core, "delete_pod") as delete, \
             mock.patch.object(
                 manage.vcp_targets,
                 "remove_matching_targets",
                 return_value={"targets": ["qwen3-captioning"], "legacy": True},
             ) as reap:
            rc = manage.kill_pod("token", "pod123")

        self.assertEqual(rc, 0)
        delete.assert_called_once_with("token", "pod123")
        reap.assert_called_once_with(
            pod_id="pod123",
            endpoints={("64.247.206.212", 14463)},
        )

    def test_kill_does_not_reap_if_delete_fails(self):
        pod = {"id": "pod123", "name": "qwen"}
        with mock.patch.object(manage.core, "get_pod", return_value=pod), \
             mock.patch.object(
                 manage.core,
                 "delete_pod",
                 side_effect=manage.core.RunPodError("delete failed"),
             ), \
             mock.patch.object(manage.vcp_targets, "remove_matching_targets") as reap:
            with self.assertRaises(manage.core.RunPodError):
                manage.kill_pod("token", "pod123")
        reap.assert_not_called()

    def test_kill_all_yes_deletes_every_pod_and_reaps_each(self):
        pods = [
            {"id": "p1", "name": "one"},
            {"id": "p2", "name": "two"},
        ]
        with mock.patch.object(manage, "list_pods", return_value=pods), \
             mock.patch.object(manage.core, "delete_pod") as delete, \
             mock.patch.object(
                 manage.vcp_targets,
                 "remove_matching_targets",
                 return_value={"targets": [], "legacy": False},
             ) as reap:
            rc = manage.kill_all("token", assume_yes=True)
        self.assertEqual(rc, 0)
        self.assertEqual(delete.call_count, 2)
        delete.assert_any_call("token", "p1")
        delete.assert_any_call("token", "p2")
        self.assertEqual(reap.call_count, 2)
        reap.assert_any_call(pod_id="p1", endpoints=set())
        reap.assert_any_call(pod_id="p2", endpoints=set())


if __name__ == "__main__":
    unittest.main()
