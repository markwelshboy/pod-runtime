import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_frontend.py"
spec = importlib.util.spec_from_file_location("rent_pod_frontend", MODULE)
frontend = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(frontend)


class RentPodFrontendTests(unittest.TestCase):
    def tearDown(self):
        frontend.set_create_context_hook(None)

    def test_cuda_13_3_is_accepted(self):
        self.assertEqual(frontend.validate_cuda_version("13.3"), "13.3")

    def test_future_cuda_version_is_not_client_capped(self):
        self.assertEqual(frontend.validate_cuda_version("14.0"), "14.0")

    def test_invalid_cuda_version_is_rejected(self):
        with self.assertRaises(ValueError):
            frontend.validate_cuda_version("13.x")

    def test_default_cloud_is_secure(self):
        cloud, argv = frontend.cloud_from_args(["4090"], False)
        self.assertEqual(cloud, "SECURE")
        self.assertEqual(argv[-2:], ["--cloud", "SECURE"])

    def test_community_shortcut(self):
        cloud, argv = frontend.cloud_from_args(["4090"], True)
        self.assertEqual(cloud, "COMMUNITY")
        self.assertEqual(argv[-2:], ["--cloud", "COMMUNITY"])

    def test_list_quoted_gpu_set(self):
        forwarded, options = frontend.split_frontend_args(
            ["--list", "4090 5090 l40s", "--cuda-min", "13.3"]
        )
        self.assertEqual(forwarded, [])
        self.assertTrue(options["list_requested"])
        self.assertEqual(options["list_spec"], "4090 5090 l40s")
        self.assertEqual(options["cuda_min"], "13.3")
        self.assertEqual(
            frontend.parse_gpu_list(options["list_spec"]),
            [
                "NVIDIA GeForce RTX 4090",
                "NVIDIA GeForce RTX 5090",
                "NVIDIA L40S",
            ],
        )

    def test_list_table_omits_route_floor(self):
        response = {
            "gpuTypes": [
                {
                    "id": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                    "displayName": "RTX PRO 6000",
                    "memoryInGb": 96,
                    "secureCloud": True,
                    "communityCloud": False,
                    "securePrice": 2.09,
                    "communityPrice": None,
                    "lowestPrice": {
                        "stockStatus": "High",
                        "uninterruptablePrice": 2.09,
                        "availableGpuCounts": [],
                    },
                }
            ]
        }
        out = io.StringIO()
        with mock.patch.object(frontend, "graphql_request", return_value=response), redirect_stdout(out):
            rc = frontend.list_gpus("token", None, "SECURE", "13.3", 500, 100)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("RTX PRO 6000", text)
        self.assertNotIn("Route floor", text)
        self.assertNotIn("None↓", text)

    def test_community_conflicts_with_explicit_secure(self):
        with self.assertRaises(ValueError):
            frontend.cloud_from_args(["4090", "--cloud", "SECURE"], True)

    def test_graphql_create_input_preserves_selection_floors(self):
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
        got = frontend.graphql_create_input(payload, "13.3")
        self.assertEqual(got["minCudaVersion"], "13.3")
        self.assertEqual(got["minDownload"], 700)
        self.assertEqual(got["minUpload"], 200)
        self.assertEqual(got["minDisk"], 400)
        self.assertEqual(got["gpuTypeId"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(got["templateId"], "tmpl123")
        self.assertTrue(got["startSsh"])

    def test_graphql_create_input_translates_local_profile_fields(self):
        payload = {
            "name": "qwen-test",
            "gpuTypeIds": ["NVIDIA GeForce RTX 5090"],
            "gpuCount": 1,
            "gpuTypePriority": "availability",
            "supportPublicIp": True,
            "minDownloadMbps": 500,
            "minUploadMbps": 100,
            "cloudType": "COMMUNITY",
            "imageName": "runpod/pytorch:qwen",
            "containerDiskInGb": 40,
            "volumeInGb": 100,
            "volumeMountPath": "/workspace",
            "ports": ["22/tcp", "8000/http"],
            "dockerStartCmd": ["sleep", "infinity"],
            "env": {
                "HF_TOKEN": "{{ RUNPOD_SECRET_huggingface_token }}",
                "PROJECT": "qwen3",
            },
        }
        got = frontend.graphql_create_input(payload, "13.2")
        self.assertEqual(got["imageName"], "runpod/pytorch:qwen")
        self.assertEqual(got["ports"], "22/tcp,8000/http")
        self.assertEqual(got["dockerArgs"], "sleep infinity")
        self.assertEqual(
            got["env"],
            [
                {"key": "HF_TOKEN", "value": "{{ RUNPOD_SECRET_huggingface_token }}"},
                {"key": "PROJECT", "value": "qwen3"},
            ],
        )

    def test_graphql_create_rejects_local_entrypoint_override(self):
        payload = {
            "name": "test",
            "gpuTypeIds": ["NVIDIA L40S"],
            "gpuCount": 1,
            "gpuTypePriority": "availability",
            "supportPublicIp": True,
            "minDownloadMbps": 500,
            "minUploadMbps": 100,
            "cloudType": "SECURE",
            "imageName": "example/image:latest",
            "dockerEntrypoint": ["bash", "-lc"],
        }
        with self.assertRaisesRegex(ValueError, "dockerEntrypoint"):
            frontend.graphql_create_input(payload, "13.3")

    def test_base_payload_runs_template_context_hook(self):
        args = SimpleNamespace(
            gpu_alias="5090",
            gpu="NVIDIA GeForce RTX 5090",
            name="captioner",
            template="qwen3-captioning",
            min_download=500,
            min_upload=100,
            min_disk=None,
            cloud="SECURE",
        )

        def transform(payload):
            payload.pop("templateId")
            payload["imageName"] = "runpod/pytorch:qwen"
            payload["env"] = {"PROJECT": "qwen3"}
            return payload

        frontend.set_create_context_hook(transform)
        payload = frontend.base_create_payload(args, 1)
        self.assertNotIn("templateId", payload)
        self.assertEqual(payload["imageName"], "runpod/pytorch:qwen")
        self.assertEqual(payload["env"], {"PROJECT": "qwen3"})

    def test_graphql_create_pod_uses_min_cuda_variable(self):
        payload = {
            "name": "test",
            "templateId": "tmpl123",
            "gpuTypeIds": ["NVIDIA L40S"],
            "gpuCount": 1,
            "gpuTypePriority": "availability",
            "supportPublicIp": True,
            "minDownloadMbps": 500,
            "minUploadMbps": 100,
            "cloudType": "SECURE",
        }
        response = {"podFindAndDeployOnDemand": {"id": "pod123", "name": "test"}}
        with mock.patch.object(frontend, "graphql_request", return_value=response) as request:
            result = frontend.graphql_create_pod("token", payload, "13.3")
        self.assertEqual(result["id"], "pod123")
        variables = request.call_args.args[2]
        self.assertEqual(variables["input"]["minCudaVersion"], "13.3")
        self.assertNotIn("allowedCudaVersions", variables["input"])


if __name__ == "__main__":
    unittest.main()
