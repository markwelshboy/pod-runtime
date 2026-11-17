"""Offline regression checks for the existing RunPod REST v2 compatibility bridge.

No test in this module contacts RunPod or creates/deletes a real GPU pod.
Run with: python3 -m unittest discover -s tests -p test_runpod_rest_v2.py
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

import rpods  # Imports and installs the REST v2 compatibility bridge.
import rent_pod as core
import rent_pod_api_v2 as api_v2
import rent_pod_lifecycle as lifecycle
import rent_pod_manage as manage


V2_POD = {
    "id": "pod123",
    "name": "podlet-5090",
    "status": "RUNNING",
    "dataCenterId": "US-XX-1",
    "gpu": {"id": "NVIDIA GeForce RTX 5090", "count": 1},
    "cost": 0.79,
    "startedAt": "2026-11-16T09:00:00Z",
    "runtime": {"uptime": 83},
    "ssh": {"direct": {"host": "192.0.2.10", "port": 33123, "username": "root"}},
}


def page(pods, has_next=False, cursor=None):
    return {
        "pods": pods,
        "pagination": {"hasNextPage": has_next, "nextCursor": cursor},
    }


class RunPodV2BridgeTests(unittest.TestCase):
    def test_rpods_bootstraps_the_existing_v2_bridge(self):
        with mock.patch.object(api_v2, "v2_request", return_value=page([V2_POD])) as req:
            pods = manage.list_pods("fake-key")
        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0]["id"], "pod123")
        self.assertEqual(pods[0]["publicIp"], "192.0.2.10")
        self.assertEqual(pods[0]["portMappings"]["22"], 33123)
        req.assert_called_once_with("fake-key", "GET", "/pods", timeout=core.DEFAULT_API_TIMEOUT)

    def test_all_cursor_pages_are_collected(self):
        with mock.patch.object(api_v2, "v2_request", side_effect=[
            page([{"id": "a"}], has_next=True, cursor="opaque/=="),
            page([{"id": "b"}]),
        ]) as req:
            pods = manage.list_pods("fake-key")
        self.assertEqual([p["id"] for p in pods], ["a", "b"])
        self.assertEqual(req.call_args_list[1].args, (
            "fake-key", "GET", "/pods?cursor=opaque%2F%3D%3D",
        ))

    def test_missing_cursor_fails_closed(self):
        with mock.patch.object(api_v2, "v2_request", return_value=page(
            [{"id": "a"}], has_next=True, cursor=None,
        )):
            with self.assertRaises(core.RunPodError):
                manage.list_pods("fake-key")

    def test_repeated_cursor_fails_closed(self):
        with mock.patch.object(api_v2, "v2_request", side_effect=[
            page([{"id": "a"}], has_next=True, cursor="stuck"),
            page([{"id": "b"}], has_next=True, cursor="stuck"),
        ]):
            with self.assertRaises(core.RunPodError):
                manage.list_pods("fake-key")

    def test_pod_details_are_normalized_without_v1_network_access(self):
        with mock.patch.object(api_v2, "v2_request", return_value=V2_POD) as req:
            pod = core.get_pod("fake-key", "pod123")
        self.assertEqual(pod["gpu"]["displayName"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(pod["publicIp"], "192.0.2.10")
        self.assertEqual(pod["desiredStatus"], "RUNNING")
        self.assertEqual(pod["machine"]["dataCenterId"], "US-XX-1")
        req.assert_called_once_with("fake-key", "GET", "/pods/pod123", timeout=core.DEFAULT_API_TIMEOUT)

    def test_delete_routes_to_v2(self):
        with mock.patch.object(api_v2, "v2_request", return_value=None) as req:
            core.delete_pod("fake-key", "pod123")
        req.assert_called_once_with("fake-key", "DELETE", "/pods/pod123",
                                    timeout=core.DEFAULT_API_TIMEOUT)

    def test_graphql_create_retains_selection_constraints(self):
        payload = {
            "name": "test-5090", "gpuTypeIds": ["NVIDIA GeForce RTX 5090"],
            "gpuCount": 1, "cloudType": "COMMUNITY", "supportPublicIp": True,
            "minDownloadMbps": 500, "minUploadMbps": 100,
            "minDiskBandwidthMBps": 42, "templateId": "template123",
        }
        converted = api_v2.graphql_create_input(payload, "13.0")
        self.assertEqual(converted["gpuTypeId"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(converted["minDownload"], 500)
        self.assertEqual(converted["minUpload"], 100)
        self.assertEqual(converted["minDisk"], 42)
        self.assertEqual(converted["minCudaVersion"], "13.0")
        self.assertEqual(converted["templateId"], "template123")
        self.assertTrue(converted["startSsh"])

    def test_rest_started_at_and_uptime_work_without_graphql(self):
        normalized = api_v2.normalize_v2_pod(V2_POD)
        snapshot = lifecycle.build_snapshot(normalized, None)
        self.assertEqual(snapshot["uptime"], 83)
        self.assertEqual(snapshot["public_ip"], "192.0.2.10")
        self.assertEqual(snapshot["ssh_port"], 33123)
        self.assertEqual(snapshot["stage"], "NETWORK")
        self.assertEqual(lifecycle.pod_started_at(normalized),
                         datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc))

    def test_rpods_recovers_from_graphql_retirement(self):
        with mock.patch.object(api_v2, "v2_request", side_effect=[
            page([V2_POD]), V2_POD
        ]), mock.patch.object(
            lifecycle, "graphql_pods",
            side_effect=core.RunPodError("retired GraphQL endpoint")
        ):
            choices = rpods.collect_choices("fake-key")
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].pod_id, "pod123")
        self.assertEqual(choices[0].uptime_seconds, 83)
        self.assertEqual(choices[0].gpu, "NVIDIA GeForce RTX 5090")
        self.assertTrue(choices[0].connectable)

    def test_rpods_disallows_error_status_for_ssh(self):
        choice = rpods.choice_from_pod(
            api_v2.normalize_v2_pod(dict(V2_POD, status="ERROR"))
        )
        self.assertFalse(choice.connectable)


if __name__ == "__main__":
    unittest.main()
