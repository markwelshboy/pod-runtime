import importlib.util
import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_api_v2.py"
spec = importlib.util.spec_from_file_location("rent_pod_api_v2", MODULE)
api = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = api
spec.loader.exec_module(api)


class RentPodApiV2Tests(unittest.TestCase):
    def test_graphql_create_input_preserves_scheduler_floors(self):
        payload = {
            "name": "qwen-test",
            "templateId": "tmpl123",
            "gpuTypeIds": ["NVIDIA GeForce RTX 5090"],
            "gpuCount": 1,
            "gpuTypePriority": "availability",
            "supportPublicIp": True,
            "minDownloadMbps": 700,
            "minUploadMbps": 200,
            "minDiskBandwidthMBps": 400,
            "cloudType": "SECURE",
        }
        got = api.graphql_create_input(payload, "13.3")
        self.assertEqual(got["minCudaVersion"], "13.3")
        self.assertEqual(got["minDownload"], 700)
        self.assertEqual(got["minUpload"], 200)
        self.assertEqual(got["minDisk"], 400)
        self.assertEqual(got["gpuTypeId"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(got["templateId"], "tmpl123")
        self.assertTrue(got["startSsh"])

    def test_normalize_v2_pod_supplies_legacy_lifecycle_aliases(self):
        got = api.normalize_v2_pod(
            {
                "id": "pod123",
                "name": "captioner",
                "status": "RUNNING",
                "dataCenterId": "US-CA-1",
                "cost": 1.25,
                "gpu": {"id": "NVIDIA GeForce RTX 5090", "count": 1},
                "ssh": {"direct": {"host": "203.0.113.10", "port": 22022}},
            }
        )
        self.assertEqual(got["desiredStatus"], "RUNNING")
        self.assertEqual(got["publicIp"], "203.0.113.10")
        self.assertEqual(got["portMappings"]["22"], 22022)
        self.assertEqual(got["adjustedCostPerHr"], 1.25)
        self.assertEqual(got["machine"]["dataCenterId"], "US-CA-1")
        self.assertEqual(got["gpu"]["displayName"], "NVIDIA GeForce RTX 5090")

    def test_graphql_create_translates_local_template_start_command(self):
        got = api.graphql_create_input(
            {
                "name": "local",
                "gpuTypeIds": ["gpu"],
                "gpuCount": 1,
                "gpuTypePriority": "availability",
                "supportPublicIp": True,
                "minDownloadMbps": 500,
                "minUploadMbps": 100,
                "cloudType": "COMMUNITY",
                "imageName": "example/image:latest",
                "ports": ["22/tcp", "8000/http"],
                "dockerStartCmd": ["sleep", "infinity"],
                "env": {"PROJECT": "qwen3"},
            }
        )
        self.assertEqual(got["dockerArgs"], "sleep infinity")
        self.assertEqual(got["ports"], "22/tcp,8000/http")
        self.assertEqual(got["env"], [{"key": "PROJECT", "value": "qwen3"}])


if __name__ == "__main__":
    unittest.main()
