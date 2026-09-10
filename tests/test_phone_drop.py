import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "phone_drop.py"
SPEC = importlib.util.spec_from_file_location("phone_drop", MODULE_PATH)
phone_drop = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(phone_drop)


class HelperTests(unittest.TestCase):
    def test_safe_filename_removes_paths_and_unsafe_characters(self):
        self.assertEqual(phone_drop.safe_filename("../../weird file?.tar"), "weird_file_.tar")

    def test_prefix_rejects_parent_traversal(self):
        with self.assertRaises(phone_drop.PhoneDropError):
            phone_drop.normalize_prefix("inbox/../other")

    def test_human_bytes(self):
        self.assertEqual(phone_drop.human_bytes(1024 * 1024), "1.0 MB")

    def test_env_aliases(self):
        with mock.patch.dict(os.environ, {"TG_CHAT_ID": "123"}, clear=True):
            self.assertEqual(phone_drop.env_first("TELEGRAM_CHAT_ID", "TG_CHAT_ID"), "123")


class QueueProtocolTests(unittest.TestCase):
    def test_enqueue_uploads_payload_before_ready_marker(self):
        calls = []

        def fake_batch(bucket_id, add=None, delete=None, token=None):
            calls.append({"bucket": bucket_id, "add": add, "delete": delete, "token": token})

        fake_hf = type("FakeHF", (), {"batch_bucket_files": staticmethod(fake_batch)})

        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "debug.tar"
            payload.write_bytes(b"payload")
            with mock.patch.object(phone_drop, "need_hf_token", return_value="token"), \
                 mock.patch.object(phone_drop, "resolve_bucket", return_value="me/pod-phone-drop"), \
                 mock.patch.dict("sys.modules", {"huggingface_hub": fake_hf}), \
                 mock.patch.object(phone_drop, "make_job_id", return_value="20260910_120000__abcd1234"):
                phone_drop.enqueue(payload, "test")

        self.assertEqual(len(calls), 2)
        first_dst = calls[0]["add"][0][1]
        second_dst = calls[1]["add"][0][1]
        self.assertTrue(first_dst.endswith("/debug.tar"))
        self.assertTrue(second_dst.endswith("/ready.json"))


if __name__ == "__main__":
    unittest.main()
