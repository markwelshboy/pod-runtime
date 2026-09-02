import importlib.util
import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_manage.py"
spec = importlib.util.spec_from_file_location("rent_pod_manage_lifecycle_tests", MODULE)
manage = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(manage)


class RentPodLifecycleManageTests(unittest.TestCase):
    def test_parse_status(self):
        self.assertEqual(
            manage.parse_management_args(["--status", "pod123"]),
            {"action": "status", "pod_id": "pod123", "assume_yes": False},
        )
        self.assertEqual(
            manage.parse_management_args(["--status=pod456"]),
            {"action": "status", "pod_id": "pod456", "assume_yes": False},
        )

    def test_parse_watch(self):
        self.assertEqual(
            manage.parse_management_args(["--watch", "pod123"]),
            {"action": "watch", "pod_id": "pod123", "assume_yes": False},
        )

    def test_watch_conflicts_with_kill(self):
        with self.assertRaises(ValueError):
            manage.parse_management_args(["--watch", "pod123", "--kill", "pod123"])

    def test_yes_only_valid_for_kill_all(self):
        with self.assertRaises(ValueError):
            manage.parse_management_args(["--status", "pod123", "--yes"])


if __name__ == "__main__":
    unittest.main()
