#!/usr/bin/env python3
"""Expand Hugging Face manifest tree entries into ordinary file entries."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
TRUTHY = {"1", "true", "yes", "on"}


class ManifestTreeError(RuntimeError):
    """Raised when a tree declaration cannot be expanded safely."""


def _as_list(value: Any, *, default: list[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ManifestTreeError(f"expected a string or list of strings, got {type(value).__name__}")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def _resolve(value: Any, values: Mapping[str, Any]) -> str:
    text = str(value)
    for _ in range(20):
        changed = False

        def repl(match: re.Match[str]) -> str:
            nonlocal changed
            key = match.group(1)
            if key in values:
                changed = True
                return str(values[key])
            return match.group(0)

        text = TOKEN_RE.sub(repl, text)
        if not changed:
            break
    return text


def _resolved_values(manifest: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = dict(environ)
    for block_name in ("vars", "paths"):
        block = manifest.get(block_name) or {}
        if not isinstance(block, Mapping):
            raise ManifestTreeError(f"top-level {block_name!r} must be an object")
        for key, raw in block.items():
            if key not in values:
                values[str(key)] = _resolve(raw, values)
        for key in block:
            values[str(key)] = _resolve(values[str(key)], values)
    return values


def _section_enabled(section: str, environ: Mapping[str, str]) -> bool:
    return _truthy(environ.get(section)) or _truthy(environ.get(f"download_{section}"))


def _safe_relative(remote_path: str, strip_prefix: str, flatten: bool) -> str | None:
    remote = remote_path.strip("/")
    prefix = strip_prefix.strip("/")
    if prefix:
        if remote == prefix:
            relative = PurePosixPath(remote).name
        elif remote.startswith(prefix + "/"):
            relative = remote[len(prefix) + 1 :]
        else:
            return None
    else:
        relative = remote

    if flatten:
        relative = PurePosixPath(relative).name

    normalized = posixpath.normpath(relative)
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ManifestTreeError(f"unsafe relative path derived from {remote_path!r}")
    if normalized.startswith("/"):
        raise ManifestTreeError(f"absolute relative path derived from {remote_path!r}")
    return normalized


def _repo_file_path(item: Any) -> str:
    return str(getattr(item, "path", getattr(item, "rfilename", "")) or "")


def _repo_file_size(item: Any) -> int:
    value = getattr(item, "size", 0) or 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _is_repo_file(item: Any) -> bool:
    name = item.__class__.__name__.lower()
    if "folder" in name or "directory" in name:
        return False
    return bool(_repo_file_path(item)) and ("file" in name or hasattr(item, "size"))


def _hf_url(repo_id: str, repo_type: str, revision: str, remote_path: str) -> str:
    from huggingface_hub import hf_hub_url

    return hf_hub_url(
        repo_id=repo_id,
        filename=remote_path,
        repo_type=None if repo_type == "model" else repo_type,
        revision=revision,
    )


def _list_repo_tree(
    repo_id: str,
    repo_type: str,
    revision: str,
    token: str | None,
    *,
    api: Any | None = None,
) -> Iterable[Any]:
    if api is None:
        from huggingface_hub import HfApi

        api = HfApi(token=token)
    return api.list_repo_tree(
        repo_id=repo_id,
        recursive=True,
        revision=revision,
        repo_type=None if repo_type == "model" else repo_type,
        token=token,
    )


def expand_tree_entry(
    entry: Mapping[str, Any],
    *,
    values: Mapping[str, str],
    token: str | None,
    api: Any | None = None,
) -> list[dict[str, Any]]:
    repo_id = _resolve(entry.get("repo_id", ""), values).strip()
    repo_type = _resolve(entry.get("repo_type", "model"), values).strip() or "model"
    revision = _resolve(entry.get("revision", "main"), values).strip() or "main"
    destination_root = _resolve(entry.get("path", ""), values).rstrip("/")
    strip_prefix = _resolve(entry.get("strip_prefix", ""), values).strip("/")
    include = [_resolve(pattern, values) for pattern in _as_list(entry.get("include"), default=["**"])]
    exclude = [_resolve(pattern, values) for pattern in _as_list(entry.get("exclude"))]
    flatten = _truthy(entry.get("flatten"))
    allow_empty = _truthy(entry.get("allow_empty"))
    source_id = str(entry.get("id") or f"{repo_id}:{','.join(include)}")

    if not repo_id or "/" not in repo_id:
        raise ManifestTreeError(f"tree entry {source_id!r} requires repo_id='owner/repo'")
    if repo_type not in {"model", "dataset", "space"}:
        raise ManifestTreeError(f"tree entry {source_id!r} has invalid repo_type {repo_type!r}")
    if not destination_root:
        raise ManifestTreeError(f"tree entry {source_id!r} requires a destination path")
    if not include:
        raise ManifestTreeError(f"tree entry {source_id!r} requires at least one include pattern")

    expanded: list[dict[str, Any]] = []
    destination_paths: set[str] = set()
    for item in _list_repo_tree(repo_id, repo_type, revision, token, api=api):
        if not _is_repo_file(item):
            continue
        remote_path = _repo_file_path(item).strip("/")
        if not any(fnmatch.fnmatchcase(remote_path, pattern) for pattern in include):
            continue
        if exclude and any(fnmatch.fnmatchcase(remote_path, pattern) for pattern in exclude):
            continue

        relative = _safe_relative(remote_path, strip_prefix, flatten)
        if relative is None:
            continue
        destination = posixpath.normpath(f"{destination_root}/{relative}")
        if destination in destination_paths:
            raise ManifestTreeError(
                f"tree entry {source_id!r} maps multiple files to {destination!r}; "
                "adjust strip_prefix or disable flatten"
            )
        destination_paths.add(destination)
        expanded.append(
            {
                "url": _hf_url(repo_id, repo_type, revision, remote_path),
                "path": destination,
                "bytes": _repo_file_size(item),
                "source_mode": "tree",
                "source_id": source_id,
                "repo_id": repo_id,
                "repo_type": repo_type,
                "revision": revision,
                "repo_file": remote_path,
            }
        )

    expanded.sort(key=lambda item: (item["path"], item["url"]))
    if not expanded and not allow_empty:
        raise ManifestTreeError(
            f"tree entry {source_id!r} matched no files in {repo_id}@{revision}; "
            f"include={include!r} exclude={exclude!r} strip_prefix={strip_prefix!r}"
        )
    return expanded


def expand_manifest(
    manifest: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    api: Any | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    values = _resolved_values(manifest, env)
    token = env.get("HF_TOKEN") or None
    output = json.loads(json.dumps(manifest))
    sections = output.get("sections") or {}
    if not isinstance(sections, dict):
        raise ManifestTreeError("top-level 'sections' must be an object")

    for section, entries in list(sections.items()):
        if not _section_enabled(section, env):
            continue
        if not isinstance(entries, list):
            raise ManifestTreeError(f"section {section!r} must be a list")
        rewritten: list[Any] = []
        for entry in entries:
            if not isinstance(entry, Mapping) or str(entry.get("mode", "file")).lower() != "tree":
                rewritten.append(entry)
                continue
            expanded = expand_tree_entry(entry, values=values, token=token, api=api)
            print(
                f"[hf-manifest] expanded tree tag={section} id={entry.get('id', '<unnamed>')} "
                f"files={len(expanded)} repo={entry.get('repo_id')} include={entry.get('include')}",
                file=sys.stderr,
            )
            rewritten.extend(expanded)
        sections[section] = rewritten
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="input manifest JSON")
    parser.add_argument("output", help="expanded manifest JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.manifest, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        expanded = expand_manifest(manifest)
        tmp = f"{args.output}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(expanded, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, args.output)
    except Exception as exc:
        print(f"[hf-manifest] tree expansion failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
