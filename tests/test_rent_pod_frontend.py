import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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
    def test_cuda_min_13(self):
        self.assertEqual(frontend.allowed_cuda_versions("13.0"), ["13.0"])

    def test_cuda_min_12_8(self):
        self.assertEqual(
            frontend.allowed_cuda_versions("12.8"),
            ["13.0", "12.9", "12.8"],
        )

    def test_cuda_too_new(self):
        with self.assertRaises(ValueError):
            frontend.allowed_cuda_versions("14.0")

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
            ["--list", "4090 5090 l40s", "--cuda-min", "13.0"]
        )
        self.assertEqual(forwarded, [])
        self.assertTrue(options["list_requested"])
        self.assertEqual(options["list_spec"], "4090 5090 l40s")
        self.assertEqual(options["cuda_min"], "13.0")
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
            rc = frontend.list_gpus("token", None, "SECURE", "13.0", 500, 100)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("RTX PRO 6000", text)
        self.assertNotIn("Route floor", text)
        self.assertNotIn("None↓", text)

    def test_community_conflicts_with_explicit_secure(self):
        with self.assertRaises(ValueError):
            frontend.cloud_from_args(["4090", "--cloud", "SECURE"], True)


if __name__ == "__main__":
    unittest.main()
