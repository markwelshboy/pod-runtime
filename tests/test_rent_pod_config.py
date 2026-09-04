import importlib.util
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"

MODULE = BIN / "rent_pod_config.py"
spec = importlib.util.spec_from_file_location("rent_pod_config", MODULE)
config = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(config)


class RentPodConfigTests(unittest.TestCase):
    def test_default_uses_rent_pod_directory(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self.assertEqual(
                config.config_root({"HOME": str(home)}),
                home / ".config" / "rent-pod",
            )

    def test_xdg_config_home_is_honored(self):
        self.assertEqual(
            config.config_root({"XDG_CONFIG_HOME": "/tmp/xdg"}),
            Path("/tmp/xdg/rent-pod"),
        )

    def test_explicit_root_wins(self):
        self.assertEqual(
            config.config_root(
                {"HOME": "/tmp/home", "RENT_POD_CONFIG_DIR": "/tmp/custom-rent-pod"}
            ),
            Path("/tmp/custom-rent-pod"),
        )


if __name__ == "__main__":
    unittest.main()
