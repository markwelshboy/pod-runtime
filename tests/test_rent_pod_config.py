import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_config.py"
spec = importlib.util.spec_from_file_location("rent_pod_config", MODULE)
config = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(config)


class RentPodConfigTests(unittest.TestCase):
    def test_new_install_uses_canonical_rentpod_directory(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self.assertEqual(
                config.config_root({"HOME": str(home)}),
                home / ".config" / "rentpod",
            )

    def test_existing_legacy_directory_is_automatic_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            legacy = home / ".config" / "rent-pod"
            legacy.mkdir(parents=True)
            self.assertEqual(config.config_root({"HOME": str(home)}), legacy)

    def test_canonical_directory_wins_when_both_exist(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            canonical = home / ".config" / "rentpod"
            legacy = home / ".config" / "rent-pod"
            canonical.mkdir(parents=True)
            legacy.mkdir(parents=True)
            self.assertEqual(config.config_root({"HOME": str(home)}), canonical)

    def test_explicit_root_wins(self):
        self.assertEqual(
            config.config_root(
                {"HOME": "/tmp/home", "RENT_POD_CONFIG_DIR": "/tmp/custom-rentpod"}
            ),
            Path("/tmp/custom-rentpod"),
        )


if __name__ == "__main__":
    unittest.main()
