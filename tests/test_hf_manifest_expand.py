#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "hf_manifest_expand.py"
spec = importlib.util.spec_from_file_location("hf_manifest_expand", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RepoFile:
    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size


class RepoFolder:
    def __init__(self, path: str) -> None:
        self.path = path


class FakeApi:
    def list_repo_tree(self, **_kwargs):
        return [
            RepoFile("models/loras/krea2/a.safetensors", 10),
            RepoFile("models/loras/krea2/sub/b.safetensors", 20),
            RepoFile("models/loras/krea2/README.md", 5),
            RepoFolder("models/loras/krea2/sub"),
        ]


def test_tree_expands_to_file_entries_and_preserves_relative_paths() -> None:
    manifest = {
        "vars": {"COMFY_HOME": "/workspace/ComfyUI"},
        "paths": {"LORAS_DIR": "{COMFY_HOME}/models/loras"},
        "sections": {
            "download_krea2": [
                {
                    "id": "krea2-loras",
                    "mode": "tree",
                    "repo_id": "markwelshboyx/diffusionetc",
                    "repo_type": "model",
                    "revision": "main",
                    "include": ["models/loras/krea2/**"],
                    "exclude": ["**/*.md"],
                    "strip_prefix": "models/loras/krea2",
                    "path": "{LORAS_DIR}/Krea-2",
                }
            ]
        },
    }

    expanded = module.expand_manifest(
        manifest,
        environ={"download_krea2": "true"},
        api=FakeApi(),
    )
    entries = expanded["sections"]["download_krea2"]

    assert [entry["path"] for entry in entries] == [
        "/workspace/ComfyUI/models/loras/Krea-2/a.safetensors",
        "/workspace/ComfyUI/models/loras/Krea-2/sub/b.safetensors",
    ]
    assert [entry["bytes"] for entry in entries] == [10, 20]
    assert all(entry["source_mode"] == "tree" for entry in entries)


def test_disabled_tree_section_is_not_queried() -> None:
    class ExplodingApi:
        def list_repo_tree(self, **_kwargs):
            raise AssertionError("disabled section must not query Hugging Face")

    manifest = {
        "sections": {
            "download_optional": [
                {
                    "mode": "tree",
                    "repo_id": "owner/repo",
                    "path": "/tmp/models",
                }
            ]
        }
    }
    assert module.expand_manifest(manifest, environ={}, api=ExplodingApi()) == manifest
