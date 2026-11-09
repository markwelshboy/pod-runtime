import contextlib
import importlib.util
import io
import json
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
        self.assertTrue(hff.has_trailing_slash("training\\"))
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



class NestedSnapshotTests(unittest.TestCase):
    SID = "20261108_153401__dataset_simple_vs_radau"
    OTH = "20260921_090241__qwen3-captioning"

    def setUp(self):
        self.files = [
            "snapshot/20260303_154420__Photo_Fixes.manifest.json",
            "snapshot/20260303_154420__Photo_Fixes.tar.gz",
            f"snapshot/comfy-datasets/{self.SID}.manifest.json",
            f"snapshot/comfy-datasets/{self.SID}.tar",
            f"snapshot/pods/qwen/{self.OTH}.manifest.json",
            f"snapshot/pods/qwen/{self.OTH}.tar.gz",
        ]

    def namespace(self, snapdir="snapshot"):
        return Namespace(repo="owner/repo", type="model", snapdir=snapdir)

    def test_list_shows_folder_qualified_identifiers(self):
        args = self.namespace()
        out = io.StringIO()
        with mock.patch.object(hff, "need_token", return_value="token"), \
             mock.patch.object(hff, "api", return_value=FakeApi()), \
             mock.patch.object(hff, "list_files", return_value=self.files), \
             contextlib.redirect_stdout(out):
            hff.cmd_snapshot_list(args)
        lines = out.getvalue().splitlines()
        self.assertIn(f"comfy-datasets/{self.SID}", lines)
        self.assertIn(f"pods/qwen/{self.OTH}", lines)
        self.assertIn("20260303_154420__Photo_Fixes", lines)

    def test_unqualified_unique_id_is_resolved_from_nested_directory(self):
        expected = f"snapshot/comfy-datasets/{self.SID}.manifest.json"
        self.assertEqual(
            hff._resolve_snapshot_manifest(self.files, "snapshot", self.SID),
            expected,
        )
        self.assertEqual(
            hff._resolve_snapshot_manifest(
                self.files, "snapshot", f"comfy-datasets/{self.SID}"
            ),
            expected,
        )
        self.assertEqual(
            hff._resolve_snapshot_manifest(
                self.files, "snapshot", f"snapshot/comfy-datasets/{self.SID}"
            ),
            expected,
        )

    def test_get_downloads_manifest_and_archive_from_same_nested_folder(self):
        args = self.namespace()
        args.id = self.SID
        args.cache_dir = ""
        with tempfile.TemporaryDirectory() as tmp:
            args.extract_dir = tmp
            meta_file = Path(tmp) / "manifest.json"
            tar_file = Path(tmp) / "archive.tar"
            meta_file.write_text(json.dumps({
                "id": self.SID,
                "tar": {"basename": f"{self.SID}.tar", "compress": "none"}
            }))
            tar_file.write_bytes(b"archive placeholder")
            downloads = []

            def download(_repo, _type, path, _token, **_kwargs):
                downloads.append(path)
                return meta_file if path.endswith(".manifest.json") else tar_file

            with mock.patch.object(hff, "need_token", return_value="token"), \
                 mock.patch.object(hff, "api", return_value=FakeApi()), \
                 mock.patch.object(hff, "list_files", return_value=self.files), \
                 mock.patch.object(hff, "_hf_download", side_effect=download), \
                 mock.patch.object(hff, "_tar_extract") as extract, \
                 contextlib.redirect_stdout(io.StringIO()):
                hff.cmd_snapshot_get(args)

            self.assertEqual(downloads, [
                f"snapshot/comfy-datasets/{self.SID}.manifest.json",
                f"snapshot/comfy-datasets/{self.SID}.tar",
            ])
            extract.assert_called_once_with(tar_file, Path(tmp))

    def test_show_resolves_nested_snapshot(self):
        args = self.namespace()
        args.id = self.SID
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "manifest.json"
            data.write_text('{"ok": true}')
            with mock.patch.object(hff, "need_token", return_value="token"), \
                 mock.patch.object(hff, "api", return_value=FakeApi()), \
                 mock.patch.object(hff, "list_files", return_value=self.files), \
                 mock.patch.object(hff, "_hf_download", return_value=data) as download, \
                 contextlib.redirect_stdout(io.StringIO()):
                hff.cmd_snapshot_show(args)
            self.assertEqual(download.call_args.args[2],
                             f"snapshot/comfy-datasets/{self.SID}.manifest.json")

    def test_destroy_only_deletes_selected_nested_snapshot(self):
        args = self.namespace()
        args.id = self.SID
        args.yes = True
        api = FakeApi()
        with mock.patch.object(hff, "need_token", return_value="token"), \
             mock.patch.object(hff, "api", return_value=api), \
             mock.patch.object(hff, "list_files", return_value=self.files), \
             contextlib.redirect_stdout(io.StringIO()):
            hff.cmd_snapshot_destroy(args)
        removed = [op.path_in_repo for op in api.commits[0]["operations"]]
        self.assertEqual(sorted(removed), sorted([
            f"snapshot/comfy-datasets/{self.SID}.manifest.json",
            f"snapshot/comfy-datasets/{self.SID}.tar",
        ]))

    def test_duplicate_bare_id_requires_directory(self):
        extra = list(self.files) + [f"snapshot/pods/other/{self.SID}.manifest.json"]
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                hff._resolve_snapshot_manifest(extra, "snapshot", self.SID)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("multiple folders", stderr.getvalue())
        self.assertIn(f"comfy-datasets/{self.SID}", stderr.getvalue())
        self.assertEqual(
            hff._resolve_snapshot_manifest(extra, "snapshot", f"comfy-datasets/{self.SID}"),
            f"snapshot/comfy-datasets/{self.SID}.manifest.json",
        )

    def test_snapdir_scopes_results_and_blocks_parent_traversal(self):
        self.assertEqual(
            hff._resolve_snapshot_manifest(self.files, "snapshot/comfy-datasets", self.SID),
            f"snapshot/comfy-datasets/{self.SID}.manifest.json",
        )
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                hff._resolve_snapshot_manifest(self.files, "snapshot/pods", self.SID)
            with self.assertRaises(SystemExit):
                hff._resolve_snapshot_manifest(self.files, "snapshot", f"../{self.SID}")

    def test_download_manifest_rejects_tar_path_traversal(self):
        args = self.namespace()
        args.id = self.SID
        args.cache_dir = ""
        with tempfile.TemporaryDirectory() as tmp:
            args.extract_dir = tmp
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({
                "tar": {"basename": "../../outside.tar"}
            }))
            with mock.patch.object(hff, "need_token", return_value="token"), \
                 mock.patch.object(hff, "api", return_value=FakeApi()), \
                 mock.patch.object(hff, "list_files", return_value=self.files), \
                 mock.patch.object(hff, "_hf_download", return_value=manifest), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    hff.cmd_snapshot_get(args)
            self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
