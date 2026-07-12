import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


class CommitOperationAdd:
    def __init__(self, path_in_repo, path_or_fileobj):
        self.path_in_repo = path_in_repo
        self.path_or_fileobj = path_or_fileobj


class CommitOperationDelete:
    def __init__(self, path_in_repo):
        self.path_in_repo = path_in_repo


class CommitOperationCopy:
    def __init__(self, path_in_repo, path_in_repo_dest):
        self.path_in_repo = path_in_repo
        self.path_in_repo_dest = path_in_repo_dest


hub_stub = types.ModuleType("huggingface_hub")
hub_stub.HfApi = object
hub_stub.CommitOperationAdd = CommitOperationAdd
hub_stub.CommitOperationDelete = CommitOperationDelete
hub_stub.CommitOperationCopy = CommitOperationCopy
sys.modules.setdefault("huggingface_hub", hub_stub)


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "hff.py"
SPEC = importlib.util.spec_from_file_location("hff", MODULE_PATH)
hff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(hff)


@contextlib.contextmanager
def working_directory(path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class FakeApi:
    def __init__(self):
        self.commits = []
        self.uploads = []

    def create_commit(self, **kwargs):
        self.commits.append(kwargs)

    def upload_file(self, **kwargs):
        self.uploads.append(kwargs)


class HffPathTests(unittest.TestCase):
    def test_trailing_slash_is_preserved_as_intent(self):
        self.assertTrue(hff.has_trailing_slash("training/"))
        self.assertTrue(hff.has_trailing_slash(r"training\"))
        self.assertFalse(hff.has_trailing_slash("training"))
        self.assertEqual(hff.normalize_path("/training/"), "training")

    def test_put_parser_accepts_shell_expanded_files(self):
        args = hff.build_parser().parse_args(
            ["--repo", "owner/repo", "put", "a.pt", "b.pt", "training/"]
        )
        self.assertEqual(args.local, ["a.pt", "b.pt"])
        self.assertEqual(args.dst, "training/")

    def test_put_expands_quoted_glob_and_uploads_into_directory(self):
        fake_api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp, working_directory(tmp):
            Path("a.pt").write_bytes(b"a")
            Path("b.pt").write_bytes(b"b")

            args = Namespace(
                repo="owner/repo",
                type="model",
                local=["*.pt"],
                dst="training/",
                message="",
            )

            with mock.patch.object(hff, "need_token", return_value="token"), mock.patch.object(
                hff, "api", return_value=fake_api
            ), mock.patch.object(hff, "list_files", return_value=[]):
                hff.cmd_put(args)

        self.assertEqual(
            [upload["path_in_repo"] for upload in fake_api.uploads],
            ["training/a.pt", "training/b.pt"],
        )

    def test_put_accepts_already_expanded_file_list(self):
        fake_api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp, working_directory(tmp):
            Path("a.pt").write_bytes(b"a")
            Path("b.pt").write_bytes(b"b")

            args = Namespace(
                repo="owner/repo",
                type="model",
                local=["a.pt", "b.pt"],
                dst="training/",
                message="",
            )

            with mock.patch.object(hff, "need_token", return_value="token"), mock.patch.object(
                hff, "api", return_value=fake_api
            ), mock.patch.object(hff, "list_files", return_value=["training/.gitkeep"]):
                hff.cmd_put(args)

        self.assertEqual(
            [upload["path_in_repo"] for upload in fake_api.uploads],
            ["training/a.pt", "training/b.pt"],
        )

    def test_rm_directory_uses_original_trailing_slash(self):
        args = Namespace(
            repo="owner/repo",
            type="model",
            path="training/",
            dry_run=True,
        )
        output = io.StringIO()

        with mock.patch.object(hff, "need_token", return_value="token"), mock.patch.object(
            hff, "api", return_value=FakeApi()
        ), mock.patch.object(
            hff,
            "list_files",
            return_value=["training/a.pt", "training/b.pt", "other/c.pt"],
        ), contextlib.redirect_stdout(output):
            hff.cmd_rm(args)

        self.assertEqual(output.getvalue().splitlines(), ["training/a.pt", "training/b.pt"])


if __name__ == "__main__":
    unittest.main()
