#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


def normalize_repo(value: str) -> str:
    value = value.strip().rstrip("/")
    value = re.sub(r"\.git$", "", value, flags=re.I)
    value = value.replace("http://github.com/", "https://github.com/")
    return value.lower()


def load(path: Path, *, create: bool = False) -> dict[str, Any]:
    if path.is_file():
        data = json.loads(path.read_text(errors="replace"))
    elif create:
        data = {"schema_version": 1, "nodes": {}, "sets": {"default": []}}
    else:
        raise FileNotFoundError(path)
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    if not isinstance(data.get("nodes"), dict) or not isinstance(data.get("sets"), dict):
        raise ValueError(f"{path}: nodes and sets must be objects")
    data["sets"].setdefault("default", [])
    return data


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def node_local(node: dict[str, Any]) -> str:
    if node.get("local"):
        return str(node["local"])
    return Path(str(node.get("remote", "")).rstrip("/")).name.removesuffix(".git")


def repo_index(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for node_id, node in manifest["nodes"].items():
        if isinstance(node, dict) and node.get("remote"):
            result[normalize_repo(str(node["remote"]))] = node_id
    return result


def merge_manifest(source_path: Path, target_path: Path, set_name: str, update_existing: bool) -> int:
    source = load(source_path)
    target = load(target_path, create=True)
    target["sets"].setdefault(set_name, [])
    by_repo = repo_index(target)

    added_definitions = reused_definitions = updated_definitions = added_members = already_members = 0
    source_ids = source.get("sets", {}).get("default", list(source["nodes"].keys()))

    for source_id in source_ids:
        source_node = source["nodes"].get(source_id)
        if not isinstance(source_node, dict) or not source_node.get("remote"):
            continue
        key = normalize_repo(str(source_node["remote"]))
        target_id = by_repo.get(key)
        if target_id is None:
            target_id = source_id
            suffix = 2
            while target_id in target["nodes"]:
                target_id = f"{source_id}-{suffix}"
                suffix += 1
            target["nodes"][target_id] = copy.deepcopy(source_node)
            by_repo[key] = target_id
            added_definitions += 1
        else:
            reused_definitions += 1
            if update_existing:
                target["nodes"][target_id] = copy.deepcopy(source_node)
                updated_definitions += 1

        if target_id in target["sets"][set_name]:
            already_members += 1
        else:
            target["sets"][set_name].append(target_id)
            added_members += 1

    atomic_write(target_path, target)
    print(f"Manifest updated : {target_path}")
    print(f"Set              : {set_name}")
    print(f"Added definitions: {added_definitions}")
    print(f"Reused definitions: {reused_definitions}")
    print(f"Updated definitions: {updated_definitions}")
    print(f"Added set members: {added_members}")
    print(f"Already present  : {already_members}")
    return 0


def list_sets(path: Path, verbose: bool) -> int:
    manifest = load(path)
    memberships: dict[str, int] = {}
    for ids in manifest["sets"].values():
        for node_id in ids:
            memberships[node_id] = memberships.get(node_id, 0) + 1

    print(f"Manifest: {path}")
    print()
    rows: list[tuple[str, int, int]] = []
    for name, ids in manifest["sets"].items():
        unique = sum(1 for node_id in ids if memberships.get(node_id, 0) == 1)
        rows.append((name, len(ids), unique))
    width = max([3] + [len(name) for name, _, _ in rows])
    print(f"{'SET'.ljust(width)}  NODES  UNIQUE TO SET")
    print(f"{'-' * width}  -----  -------------")
    for name, count, unique in rows:
        print(f"{name.ljust(width)}  {str(count).rjust(5)}  {str(unique).rjust(13)}")
    print(f"\nTotal node definitions: {len(manifest['nodes'])}")

    if verbose:
        for name, ids in manifest["sets"].items():
            print(f"\n{name} — {len(ids)} node(s)")
            for node_id in ids:
                node = manifest["nodes"].get(node_id, {})
                print(f"  {node_id:<32} {node_local(node):<32} {node.get('remote', '-')}")
    return 0


def show_set(path: Path, set_name: str) -> int:
    manifest = load(path)
    if set_name not in manifest["sets"]:
        raise ValueError(f"unknown set: {set_name}")
    print(json.dumps({
        "set": set_name,
        "nodes": {
            node_id: manifest["nodes"].get(node_id)
            for node_id in manifest["sets"][set_name]
        },
    }, indent=2))
    return 0


def rename_set(path: Path, old: str, new: str) -> int:
    manifest = load(path)
    if old == "default":
        raise ValueError("the default set cannot be renamed")
    if old not in manifest["sets"]:
        raise ValueError(f"unknown set: {old}")
    if new in manifest["sets"]:
        raise ValueError(f"target set already exists: {new}")
    rebuilt: dict[str, list[str]] = {}
    for name, ids in manifest["sets"].items():
        rebuilt[new if name == old else name] = ids
    manifest["sets"] = rebuilt
    atomic_write(path, manifest)
    print(f"Renamed set {old} -> {new} in {path}")
    return 0


def delete_set(path: Path, name: str) -> int:
    manifest = load(path)
    if name == "default":
        raise ValueError("the default set cannot be deleted")
    if name not in manifest["sets"]:
        raise ValueError(f"unknown set: {name}")
    del manifest["sets"][name]
    atomic_write(path, manifest)
    print(f"Deleted set {name} from {path}")
    print("Node definitions were retained because other sets may reference them.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage custom-node manifest sets")
    sub = parser.add_subparsers(dest="command", required=True)

    merge = sub.add_parser("merge")
    merge.add_argument("source")
    merge.add_argument("--into", required=True)
    merge.add_argument("--set", required=True)
    merge.add_argument("--update-existing", action="store_true")

    listing = sub.add_parser("list-sets")
    listing.add_argument("--manifest", required=True)
    listing.add_argument("--verbose", action="store_true")

    show = sub.add_parser("show-set")
    show.add_argument("name")
    show.add_argument("--manifest", required=True)

    rename = sub.add_parser("rename-set")
    rename.add_argument("old")
    rename.add_argument("new")
    rename.add_argument("--manifest", required=True)

    delete = sub.add_parser("delete-set")
    delete.add_argument("name")
    delete.add_argument("--manifest", required=True)

    args = parser.parse_args()
    if args.command == "merge":
        return merge_manifest(Path(args.source).resolve(), Path(args.into).resolve(), args.set, args.update_existing)
    if args.command == "list-sets":
        return list_sets(Path(args.manifest).resolve(), args.verbose)
    if args.command == "show-set":
        return show_set(Path(args.manifest).resolve(), args.name)
    if args.command == "rename-set":
        return rename_set(Path(args.manifest).resolve(), args.old, args.new)
    return delete_set(Path(args.manifest).resolve(), args.name)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"custom-node manifest manager: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
