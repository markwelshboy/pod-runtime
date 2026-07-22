#!/usr/bin/env python3
"""Collapse repeated files from the user's HF repo into mode=tree entries."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

TARGET_REPO = "markwelshboyx/diffusionetc"
HF_FILE_RE = re.compile(
    r"^/(?:(datasets|spaces)/)?([^/]+/[^/]+)/(?:resolve|blob|raw)/([^/]+)/(.+)$"
)


def parse_hf_file_url(url: str) -> tuple[str, str, str, str] | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"huggingface.co", "www.huggingface.co"}:
        return None
    match = HF_FILE_RE.match(parsed.path)
    if not match:
        return None
    kind, repo_id, revision, repo_file = match.groups()
    repo_type = "dataset" if kind == "datasets" else "space" if kind == "spaces" else "model"
    return repo_type, repo_id, revision, repo_file


def collapse_section(section: str, entries: list[Any]) -> tuple[list[Any], int]:
    groups: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(list)

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or str(entry.get("mode", "file")).lower() != "file":
            continue
        parsed = parse_hf_file_url(str(entry.get("url") or ""))
        path = str(entry.get("path") or "")
        if not parsed or not path:
            continue
        repo_type, repo_id, revision, repo_file = parsed
        if repo_id != TARGET_REPO:
            continue
        source = PurePosixPath(repo_file)
        destination = PurePosixPath(path)
        # Preserve renamed files as explicit entries.
        if source.name != destination.name:
            continue
        groups[(repo_type, repo_id, revision, str(source.parent), str(destination.parent))].append(index)

    replacements: dict[int, dict[str, Any]] = {}
    removed: set[int] = set()
    collapsed = 0

    for (repo_type, repo_id, revision, source_dir, destination_dir), indexes in groups.items():
        if len(indexes) < 2:
            continue
        extensions = sorted(
            {
                PurePosixPath(parse_hf_file_url(entries[index]["url"])[3]).suffix
                for index in indexes
            }
        )
        if not extensions or "" in extensions:
            continue
        include = [f"{source_dir}/*{suffix}" for suffix in extensions]
        slug = re.sub(r"[^a-z0-9]+", "-", source_dir.lower()).strip("-")
        replacements[indexes[0]] = {
            "id": f"{section}-{slug}",
            "mode": "tree",
            "repo_id": repo_id,
            "repo_type": repo_type,
            "revision": revision,
            "include": include,
            "strip_prefix": source_dir,
            "path": destination_dir,
        }
        removed.update(indexes[1:])
        collapsed += len(indexes) - 1

    rewritten: list[Any] = []
    for index, entry in enumerate(entries):
        if index in removed:
            continue
        rewritten.append(replacements.get(index, entry))
    return rewritten, collapsed


def refactor(manifest: dict[str, Any]) -> tuple[dict[str, Any], int]:
    sections = manifest.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("manifest.sections must be an object")
    total = 0
    for section, entries in list(sections.items()):
        if not isinstance(entries, list):
            continue
        sections[section], count = collapse_section(section, entries)
        total += count
    return manifest, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", default="model_manifest.json")
    args = parser.parse_args()
    with open(args.manifest, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest, collapsed = refactor(manifest)
    with open(args.manifest, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"Collapsed {collapsed} repeated file entries into tree declarations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
