import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_queue.py"
spec = importlib.util.spec_from_file_location("rent_pod_queue", MODULE)
queue = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = queue
spec.loader.exec_module(queue)


class RentPodQueueTests(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(queue.parse_duration("30m"), 1800)
        self.assertEqual(queue.parse_duration("12h"), 43200)
        self.assertEqual(queue.parse_duration("2d"), 172800)

    def test_queue_modifiers_require_when_available_even_when_equal_default(self):
        with self.assertRaisesRegex(ValueError, "require --when-available"):
            queue.consume_queue_args(["5090", "--for", "24h"], {})

    def test_queue_args_are_consumed(self):
        forwarded, options = queue.consume_queue_args(
            [
                "5090",
                "--when-available",
                "--for",
                "12h",
                "--window",
                "20:00-02:00",
                "--check-every",
                "45",
                "--min-download",
                "700",
            ],
            {},
        )
        self.assertEqual(forwarded, ["5090", "--min-download", "700"])
        self.assertIsNotNone(options)
        assert options is not None
        self.assertEqual(options.duration_seconds, 43200)
        self.assertEqual(options.window, "20:00-02:00")
        self.assertEqual(options.check_every, 45)

    def test_overnight_window(self):
        winter = datetime(2026, 1, 1, 23, 0).astimezone()
        morning = datetime(2026, 1, 2, 1, 0).astimezone()
        midday = datetime(2026, 1, 2, 12, 0).astimezone()
        self.assertTrue(queue.window_allows("20:00-02:00", winter))
        self.assertTrue(queue.window_allows("20:00-02:00", morning))
        self.assertFalse(queue.window_allows("20:00-02:00", midday))

    def test_enqueue_persists_future_approval_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            options = queue.QueueOptions(3600, None, 60)
            probe = {
                "gpu_id": "NVIDIA GeForce RTX 5090",
                "gpu_label": "5090",
                "cloud": "SECURE",
            }
            with mock.patch.object(queue, "spawn_worker") as spawn:
                rc = queue.enqueue_request(
                    ["5090", "--template", "qwen3-captioning"],
                    options,
                    probe,
                    {"RUNPOD_API_KEY": "token"},
                    state_file,
                )
            self.assertEqual(rc, 0)
            spawn.assert_called_once()
            state = json.loads(state_file.read_text(encoding="utf-8"))
            request = state["requests"][0]
            self.assertEqual(request["status"], "pending")
            self.assertEqual(request["approval"], {"mode": "auto", "state": "not_required"})
            self.assertEqual(request["argv"][0], "5090")
            self.assertIsNone(request["launch_pid"])

    def test_interrupted_launch_recovers_to_attention_not_duplicate_retry(self):
        request = {
            "id": "rpa-test",
            "status": "launching",
            "expires_at": queue.iso(queue.now_utc()),
        }
        with mock.patch.object(queue, "_update_request") as update, mock.patch.object(
            queue, "_append_log"
        ):
            queue._process_request(request, Path("/tmp/state"), Path("/tmp/log"))
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["status"], "attention")

    def test_availability_probe_includes_disk_network_and_cuda_floors(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "data": {
                            "gpuTypes": [
                                {
                                    "id": "gpu-test",
                                    "displayName": "GPU Test",
                                    "lowestPrice": {
                                        "stockStatus": "Low",
                                        "availableGpuCounts": [1],
                                    },
                                }
                            ]
                        }
                    }
                ).encode()

        def fake_open(req, timeout=0):
            captured["body"] = req.data.decode()
            return Response()

        probe = {
            "gpu_id": "gpu-test",
            "cloud": "SECURE",
            "min_download": 700,
            "min_upload": 200,
            "min_disk": 400,
            "cuda_min": "13.3",
        }
        with mock.patch.object(queue.urllib.request, "urlopen", side_effect=fake_open):
            available, stock = queue._graphql_availability("token", probe)
        self.assertTrue(available)
        self.assertEqual(stock, "LOW")
        query_text = json.loads(captured["body"])["query"]
        self.assertIn("minDownload: 700", query_text)
        self.assertIn("minUpload: 200", query_text)
        self.assertIn("minDisk: 400", query_text)
        self.assertIn('minCudaVersion: "13.3"', query_text)

    def test_pod_id_extraction_ignores_human_pod_rented_message(self):
        output = "\n".join(
            [
                "[rent-pod] Pod rented.",
                "[rent-pod] Pod                    abc123",
            ]
        )
        self.assertEqual(queue._extract_pod_id(output), "abc123")
        self.assertIsNone(queue._extract_pod_id("[rent-pod] Pod rented.\n"))
        self.assertEqual(
            queue._extract_pod_id("[rent-pod] Pod ID: xyz789\n"),
            "xyz789",
        )

    def test_legacy_rented_word_record_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            state_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "requests": [
                            {
                                "id": "old",
                                "status": "launched",
                                "pod_id": "rented.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            request = queue.load_state(state_file)["requests"][0]
            self.assertEqual(request["status"], "legacy")
            self.assertIsNone(request["pod_id"])
            self.assertIn("Pod ID was not captured", request["last_error"])

    def test_cancel_launching_request_signals_recorded_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            queue.save_state(
                {
                    "requests": [
                        {
                            "id": "rpa-test",
                            "status": "launching",
                            "launch_pid": 12345,
                        }
                    ]
                },
                state_file,
            )
            with mock.patch.object(queue, "_signal_launch_pid", return_value=True) as signal_pid:
                rc = queue.cancel_request("rpa-test", state_file)
            self.assertEqual(rc, 0)
            signal_pid.assert_called_once_with(12345)
            stored = queue.load_state(state_file)["requests"][0]
            self.assertEqual(stored["status"], "cancelled")

    def test_cancel_all_active_requests_signals_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            queue.save_state(
                {
                    "requests": [
                        {"id": "pending", "status": "pending", "launch_pid": None},
                        {"id": "launching", "status": "launching", "launch_pid": 321},
                        {"id": "done", "status": "cancelled", "launch_pid": None},
                    ]
                },
                state_file,
            )
            with mock.patch.object(queue, "_signal_launch_pid", side_effect=lambda pid: pid == 321):
                cancelled, signalled = queue.cancel_all_active_requests(
                    "cancelled by --kill-all", state_file
                )
            self.assertEqual(cancelled, 2)
            self.assertEqual(signalled, 1)
            stored = {r["id"]: r for r in queue.load_state(state_file)["requests"]}
            self.assertEqual(stored["pending"]["status"], "cancelled")
            self.assertEqual(stored["launching"]["status"], "cancelled")

    def test_post_create_failure_moves_to_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            log_file = Path(tmp) / "queue.log"
            now = queue.now_utc()
            request = {
                "id": "rpa-test",
                "status": "pending",
                "created_at": queue.iso(now),
                "expires_at": queue.iso(now + timedelta(hours=1)),
                "window": None,
                "check_every": 60,
                "next_attempt_at": queue.iso(now),
                "attempt_count": 0,
                "probe": {"gpu_id": "gpu-test"},
                "argv": ["l40s"],
            }
            queue.save_state({"requests": [request]}, state_file)
            with mock.patch.dict(os.environ, {"RUNPOD_API_KEY": "token"}), mock.patch.object(
                queue, "_graphql_availability", return_value=(True, "LOW")
            ), mock.patch.object(
                queue,
                "_run_launch",
                return_value=(1, "pod123", "[rent-pod] ERROR: startup failed\n"),
            ):
                queue._process_request(request, state_file, log_file)
            stored = queue.load_state(state_file)["requests"][0]
            self.assertEqual(stored["status"], "attention")
            self.assertEqual(stored["pod_id"], "pod123")
            self.assertIn("not retrying automatically", stored["last_error"])

    def test_cancel_during_launch_stays_cancelled_without_pod(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            log_file = Path(tmp) / "queue.log"
            now = queue.now_utc()
            request = {
                "id": "rpa-test",
                "status": "pending",
                "created_at": queue.iso(now),
                "expires_at": queue.iso(now + timedelta(hours=1)),
                "window": None,
                "check_every": 60,
                "next_attempt_at": queue.iso(now),
                "attempt_count": 0,
                "probe": {"gpu_id": "gpu-test"},
                "argv": ["l40s"],
            }
            queue.save_state({"requests": [request]}, state_file)

            def cancelled_launch(_request, _state, _log):
                queue.cancel_request("rpa-test", state_file)
                return 1, None, "[rent-pod] ERROR: no capacity\n"

            with mock.patch.dict(os.environ, {"RUNPOD_API_KEY": "token"}), mock.patch.object(
                queue, "_graphql_availability", return_value=(True, "LOW")
            ), mock.patch.object(queue, "_run_launch", side_effect=cancelled_launch):
                queue._process_request(request, state_file, log_file)
            stored = queue.load_state(state_file)["requests"][0]
            self.assertEqual(stored["status"], "cancelled")
            self.assertEqual(stored["last_error"], "cancelled by user")

    def test_cancel_during_launch_with_confirmed_cleanup_stays_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "queue.json"
            log_file = Path(tmp) / "queue.log"
            now = queue.now_utc()
            request = {
                "id": "rpa-test",
                "status": "pending",
                "created_at": queue.iso(now),
                "expires_at": queue.iso(now + timedelta(hours=1)),
                "window": None,
                "check_every": 60,
                "next_attempt_at": queue.iso(now),
                "attempt_count": 0,
                "probe": {"gpu_id": "gpu-test"},
                "argv": ["l40s"],
            }
            queue.save_state({"requests": [request]}, state_file)

            def cancelled_launch(_request, _state, _log):
                queue.cancel_request("rpa-test", state_file)
                return (
                    130,
                    "pod123",
                    "[rent-pod] Pod                    pod123\n"
                    "[rent-pod] Pod deletion confirmed: pod123.\n",
                )

            with mock.patch.dict(os.environ, {"RUNPOD_API_KEY": "token"}), mock.patch.object(
                queue, "_graphql_availability", return_value=(True, "LOW")
            ), mock.patch.object(queue, "_run_launch", side_effect=cancelled_launch):
                queue._process_request(request, state_file, log_file)
            stored = queue.load_state(state_file)["requests"][0]
            self.assertEqual(stored["status"], "cancelled")
            self.assertEqual(stored["pod_id"], "pod123")
            self.assertIn("deletion", stored["last_error"])


if __name__ == "__main__":
    unittest.main()
