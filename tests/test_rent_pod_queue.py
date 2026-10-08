import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
