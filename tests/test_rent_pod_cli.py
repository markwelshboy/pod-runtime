import importlib.util
import io
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "bin" / "rent_pod_cli.py"
spec = importlib.util.spec_from_file_location("rent_pod_cli", MODULE)
cli = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(cli)


class RentPodCliTests(unittest.TestCase):
    def test_min_cuda_is_normalized_to_legacy_internal_flag(self):
        self.assertEqual(
            cli.normalize_cuda_option(["4090", "--min-cuda", "12.8"]),
            ["4090", "--cuda-min", "12.8"],
        )
        self.assertEqual(
            cli.normalize_cuda_option(["4090", "--min-cuda=13.0"]),
            ["4090", "--cuda-min=13.0"],
        )

    def test_legacy_cuda_min_remains_accepted(self):
        argv = ["4090", "--cuda-min", "12.8"]
        self.assertEqual(cli.normalize_cuda_option(argv), argv)

    def test_min_cuda_requires_value(self):
        with self.assertRaises(ValueError):
            cli.normalize_cuda_option(["4090", "--min-cuda"])
        with self.assertRaises(ValueError):
            cli.normalize_cuda_option(["4090", "--min-cuda="])

    def test_help_documents_min_cuda_and_semantics(self):
        stream = io.StringIO()
        cli.print_help(stream)
        text = stream.getvalue()
        self.assertIn("--min-cuda VERSION", text)
        self.assertIn("allowedCudaVersions", text)
        self.assertIn("minCudaVersion", text)
        self.assertIn("RENT_POD_CUDA_MIN", text)
        self.assertIn("Legacy alias for --min-cuda", text)

    def test_help_documents_local_templates_and_secrets(self):
        stream = io.StringIO()
        cli.print_help(stream)
        text = stream.getvalue()
        self.assertIn("~/.config/rent-pod/templates/*.toml", text)
        self.assertIn("docker_start_cmd", text)
        self.assertIn("[secrets]", text)
        self.assertIn("RUNPOD_SECRET_name", text)
        self.assertIn("~/.config/rent-pod", text)


if __name__ == "__main__":
    unittest.main()
