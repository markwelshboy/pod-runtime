import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "bin" / "rent_pod_env.py"
spec = importlib.util.spec_from_file_location("rent_pod_env", MODULE)
rent_env = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(rent_env)


class RentPodEnvTests(unittest.TestCase):
    def test_cuda_env_default(self):
        got = rent_env.apply_env_defaults(
            ["4090"], {"RENT_POD_CUDA_MIN": "13.0"}
        )
        self.assertEqual(got, ["4090", "--cuda-min", "13.0"])

    def test_cli_cuda_wins(self):
        got = rent_env.apply_env_defaults(
            ["4090", "--cuda-min", "12.8"],
            {"RENT_POD_CUDA_MIN": "13.0"},
        )
        self.assertEqual(got, ["4090", "--cuda-min", "12.8"])

    def test_selection_defaults(self):
        got = rent_env.apply_env_defaults(
            ["4090"],
            {
                "RENT_POD_MIN_DOWNLOAD": "750",
                "RENT_POD_MIN_UPLOAD": "250",
                "RENT_POD_STARTUP_TIMEOUT": "900",
                "RENT_POD_SSH_KEY": "~/.ssh/pod",
            },
        )
        self.assertEqual(
            got,
            [
                "4090",
                "--min-download",
                "750",
                "--min-upload",
                "250",
                "--startup-timeout",
                "900",
                "--ssh-key",
                "~/.ssh/pod",
            ],
        )

    def test_community_env_shortcut(self):
        got = rent_env.apply_env_defaults(
            ["4090"], {"RENT_POD_COMMUNITY": "true"}
        )
        self.assertEqual(got, ["4090", "--community"])

    def test_cli_pool_wins(self):
        got = rent_env.apply_env_defaults(
            ["4090", "--community"], {"RENT_POD_CLOUD": "SECURE"}
        )
        self.assertEqual(got, ["4090", "--community"])

    def test_cloud_conflict_rejected(self):
        with self.assertRaises(ValueError):
            rent_env.apply_env_defaults(
                ["4090"],
                {
                    "RENT_POD_CLOUD": "SECURE",
                    "RENT_POD_COMMUNITY": "true",
                },
            )


if __name__ == "__main__":
    unittest.main()
