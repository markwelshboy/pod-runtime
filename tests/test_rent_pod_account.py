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

MODULE = BIN / "rent_pod_account.py"
spec = importlib.util.spec_from_file_location("rent_pod_account", MODULE)
account = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(account)


class RentPodAccountTests(unittest.TestCase):
    def test_format_runway(self):
        self.assertEqual(account.format_runway(18.42, 0.74), "1d 0h 53m")
        self.assertEqual(account.format_runway(1.0, 0.0), "∞ (no current spend)")
        self.assertEqual(account.format_runway(0.0, 0.74), "0m")

    def test_balance_meta_command_requires_exact_mode(self):
        with self.assertRaises(ValueError):
            account.handle_balance_command(["--balance", "4090"], {"RUNPOD_API_KEY": "token"})
        self.assertIsNone(account.handle_balance_command(["4090"], {"RUNPOD_API_KEY": "token"}))

    def test_balance_requires_api_key(self):
        self.assertEqual(account.handle_balance_command(["--balance"], {}), 2)

    def test_show_balance(self):
        with mock.patch.object(
            account,
            "graphql_account",
            return_value={
                "clientBalance": 18.42,
                "currentSpendPerHr": 0.74,
                "spendLimit": 80.0,
            },
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = account.show_balance("token")
        self.assertEqual(rc, 0)
        text = output.getvalue()
        self.assertIn("balance:          $18.42", text)
        self.assertIn("current spend:    $0.740/hr", text)
        self.assertIn("spend limit:      $80.00/hr", text)
        self.assertIn("runway:           1d 0h 53m", text)


if __name__ == "__main__":
    unittest.main()
