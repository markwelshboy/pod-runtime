"""Offline regression tests for the RunPod REST v2 migration.

These use representative response shapes from RunPod's v2 documentation.
They do not rent or terminate any actual Pods.
"""
from __future__ import annotations

import argparse
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

import rent_pod as core
import rent_pod_lifecycle as lifecycle
import rent_pod_manage as manage
import rpods


POD = {
    "id": "pod123",
    "name": "podlet-5090",
    "status": "RUNNING",
    "cloud": "COMMUNITY",
    "dataCenterId": "US-XX-1",
    "gpu": {"id": "NVIDIA GeForce RTX 5090", "count": 1},
    "cost": 0.79,
    "startedAt": "2026-11-16T09:00:00Z",
    "runtime": {
        "uptime": 83,
        "ports": [{"private": 22, "public": 33123, "type": "tcp", "ip": "10.20.30.40"}],
    },
    "ssh": {
        "direct": {"host": "10.20.30.40", "port": 33123, "username": "root"},
        "proxy": {"host": "ssh.runpod.io", "port": 22, "username": "pod-user"},
    },
}


class V2ApiTests(unittest.TestCase):
    def test_base_url_is_v2_by_default(self):
        # This test assumes RUNPOD_API_BASE was not overridden in the runner.
        if not os.environ.get("RUNPOD_API_BASE"):
            self.assertEqual(core.API_BASE, "https://api.runpod.io/v2")

    def test_create_payload_preserves_template_and_gpu_without_removed_filters(self):
        args = argparse.Namespace(
            gpu_alias="5090", gpu="NVIDIA GeForce RTX 5090",
            name="test-pod", template="template123", cloud="COMMUNITY",
            min_download=500, min_upload=100, min_disk=None,
        )
        payload = core.pod_create_payload(args, 1)
        self.assertEqual(payload["templateId"], "template123")
        self.assertEqual(payload["gpu"], {"id": "NVIDIA GeForce RTX 5090", "count": 1})
        self.assertEqual(payload["cloud"], "COMMUNITY")
        self.assertTrue(payload["startSsh"])
        for old in ("gpuTypeIds", "gpuTypePriority", "supportPublicIp",
                    "cloudType", "minDownloadMbps", "minUploadMbps"):
            self.assertNotIn(old, payload)
        # No port/mount override: template must keep its image and exposed services.
        self.assertNotIn("ports", payload)
        self.assertNotIn("mounts", payload)

    def test_get_pod_uses_v2_route_without_ignored_query_flags(self):
        with mock.patch.object(core, "api_request", return_value=POD) as api:
            self.assertEqual(core.get_pod("fake", "pod123")["id"], "pod123")
        api.assert_called_once_with("fake", "GET", "/pods/pod123", timeout=30.0)

    def test_pod_identity_uses_v2_ssh_and_gpu(self):
        ident = core.pod_identity(POD)
        self.assertEqual(ident["public_ip"], "10.20.30.40")
        self.assertEqual(ident["ssh_port"], 33123)
        self.assertEqual(ident["data_center_id"], "US-XX-1")
        self.assertEqual(ident["gpu"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(ident["cost_per_hr"], 0.79)
        self.assertIsNone(ident["machine_id"])

    def test_runtime_ports_fallback_if_ssh_direct_not_yet_populated(self):
        pod = dict(POD, ssh={"direct": None})
        ident = core.pod_identity(pod)
        self.assertEqual((ident["public_ip"], ident["ssh_port"]), ("10.20.30.40", 33123))

    def test_list_all_pages(self):
        pages = [
            {"pods": [{"id": "a", "name": "first"}],
             "pagination": {"hasNextPage": True, "nextCursor": "opaque/==" }},
            {"pods": [{"id": "b", "name": "second"}],
             "pagination": {"hasNextPage": False, "nextCursor": None}},
        ]
        with mock.patch.object(core, "api_request", side_effect=pages) as api:
            pods = manage.list_pods("fake")
        self.assertEqual([p["id"] for p in pods], ["a", "b"])
        self.assertEqual(api.call_args_list[0].args, ("fake", "GET", "/pods"))
        self.assertEqual(
            api.call_args_list[1].args,
            ("fake", "GET", "/pods?cursor=opaque%2F%3D%3D"),
        )

    def test_broken_pagination_fails_closed(self):
        with mock.patch.object(core, "api_request", return_value={
            "pods": [{"id": "a"}],
            "pagination": {"hasNextPage": True, "nextCursor": None},
        }):
            with self.assertRaises(core.RunPodError):
                manage.list_pods("fake")

    def test_lifecycle_snapshot_no_longer_needs_graphql(self):
        with mock.patch.object(core, "get_pod", return_value=POD), \
             mock.patch.object(lifecycle, "graphql_pod", side_effect=AssertionError("GraphQL call")):
            rest, snapshot = lifecycle._fetch_snapshot("fake", "pod123")
        self.assertEqual(rest["id"], "pod123")
        self.assertEqual(snapshot["stage"], "NETWORK")
        self.assertEqual(snapshot["uptime"], 83)
        self.assertEqual(lifecycle.pod_started_at(POD),
                         datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc))

    def test_rpods_connectable_without_graphql(self):
        with mock.patch.object(manage, "list_pods", return_value=[POD]), \
             mock.patch.object(manage, "enriched_pod", return_value=POD), \
             mock.patch.object(lifecycle, "graphql_pods",
                               side_effect=AssertionError("GraphQL call")):
            choices = rpods.collect_choices("fake")
        self.assertEqual(len(choices), 1)
        self.assertTrue(choices[0].connectable)
        self.assertEqual(choices[0].uptime_seconds, 83)
        self.assertEqual(choices[0].gpu, "NVIDIA GeForce RTX 5090")

    def test_error_status_is_terminal(self):
        snapshot = lifecycle.build_snapshot(dict(POD, status="ERROR"), None)
        self.assertEqual(snapshot["stage"], "ERROR")
        choice = rpods.choice_from_pod(dict(POD, status="ERROR"))
        self.assertFalse(choice.connectable)

    def test_min_disk_rejected_not_silently_dropped(self):
        with mock.patch.object(sys, "argv",
                               ["rent-pod", "5090", "--min-disk", "100", "--dry-run"]), \
             mock.patch("sys.stderr"):
            self.assertEqual(core.main(), 2)


if __name__ == "__main__":
    unittest.main()
