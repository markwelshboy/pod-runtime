#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAP_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json"
DEFAULT_LIST_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"


def fetch_json(source: str, timeout: int = 45) -> Any:
    path = Path(source).expanduser()
    if path.is_file():
        return json.loads(path.read_text(errors="replace"))
    request = urllib.request.Request(source, headers={"User-Agent": "pod-runtime-workflow-resolver/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).strip("-").lower()


def repo_local(remote: str) -> str:
    return Path(remote.rstrip("/")).name.removesuffix(".git")


def canonical_remote(value: str) -> str:
    value = value.strip().rstrip("/")
    value = re.sub(r"\.git$", "", value, flags=re.I)
    value = value.replace("http://github.com/", "https://github.com/")
    return value.lower()


def workflow_node_types(data: Any) -> tuple[set[str], dict[str, list[dict]]]:
    found: set[str] = set()
    metadata: dict[str, list[dict]] = {}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            node_type = obj.get("type")
            if isinstance(node_type, str) and node_type.strip():
                # Workflow nodes normally have an id or widgets_values. This avoids
                # treating unrelated metadata objects as graph nodes.
                if "id" in obj or "widgets_values" in obj or "inputs" in obj or "outputs" in obj:
                    node_type = node_type.strip()
                    found.add(node_type)
                    props = obj.get("properties")
                    if isinstance(props, dict):
                        metadata.setdefault(node_type, []).append(props)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return found, metadata


def live_node_types(comfy_url: str) -> set[str]:
    url = comfy_url.rstrip("/") + "/object_info"
    data = fetch_json(url)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected /object_info response from {url}")
    return set(map(str, data.keys()))


def strings_in(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str):
        result.add(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            result.add(str(key))
            result.update(strings_in(item))
    elif isinstance(value, list):
        for item in value:
            result.update(strings_in(item))
    return result


def looks_like_repo(value: str) -> bool:
    return bool(re.match(r"https?://(?:www\.)?github\.com/[^/]+/[^/]+", value, flags=re.I))


def extract_repo_candidates(mapping: Any, node_type: str) -> list[str]:
    target = node_type.casefold()
    candidates: list[str] = []
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            haystack = {item.casefold() for item in strings_in(value)}
            if target in haystack:
                if looks_like_repo(str(key)):
                    candidates.append(str(key))
                else:
                    for item in strings_in(value):
                        if looks_like_repo(item):
                            candidates.append(item)
    return list(dict.fromkeys(candidates))


def catalog_entries(data: Any) -> list[dict]:
    if isinstance(data, dict):
        for key in ("custom_nodes", "nodes", "items"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def entry_repositories(entry: dict) -> list[str]:
    result: list[str] = []
    for key in ("reference", "repository", "repo", "url"):
        value = entry.get(key)
        if isinstance(value, str) and looks_like_repo(value):
            result.append(value)
    files = entry.get("files")
    if isinstance(files, list):
        for value in files:
            if isinstance(value, str) and looks_like_repo(value):
                result.append(value)
    return list(dict.fromkeys(result))


def catalog_match(catalog: list[dict], token: str) -> list[str]:
    wanted = normalize(token)
    matches: list[str] = []
    for entry in catalog:
        labels = [entry.get(key) for key in ("id", "title", "name")]
        if any(isinstance(label, str) and normalize(label) == wanted for label in labels):
            matches.extend(entry_repositories(entry))
    return list(dict.fromkeys(matches))


def known_nodes(base_manifest: dict | None) -> tuple[dict[str, tuple[str, dict]], dict[str, tuple[str, dict]]]:
    by_remote: dict[str, tuple[str, dict]] = {}
    by_local: dict[str, tuple[str, dict]] = {}
    if not isinstance(base_manifest, dict):
        return by_remote, by_local
    for node_id, node in base_manifest.get("nodes", {}).items():
        if not isinstance(node, dict) or not node.get("remote"):
            continue
        by_remote[canonical_remote(node["remote"])] = (node_id, node)
        by_local[normalize(node.get("local") or repo_local(node["remote"]))] = (node_id, node)
    return by_remote, by_local


def choose(prompt: str, options: list[str], accept_default: bool) -> str | None:
    options = list(dict.fromkeys(options))
    if not options:
        return None
    if accept_default or not sys.stdin.isatty():
        return options[0]
    print(f"\n{prompt}")
    for index, option in enumerate(options, 1):
        print(f"  [{index}] {option}")
    print("  [s] Skip/unresolved")
    while True:
        answer = input("Selection [1]: ").strip()
        if not answer:
            return options[0]
        if answer.lower() in {"s", "skip"}:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Please enter one of the displayed choices.")


def choose_ref(remote: str, accept_default: bool) -> str | None:
    if accept_default or not sys.stdin.isatty():
        return None
    print(f"\nVersion/ref for {remote}")
    print("  [1] Repository default branch (nightly/current)")
    print("  [2] Enter a tag, branch, or commit")
    answer = input("Selection [1]: ").strip()
    if answer in {"2", "ref", "custom"}:
        value = input("Git ref: ").strip()
        return value or None
    return None


def unique_id(remote: str, used: set[str]) -> str:
    base = normalize(repo_local(remote)) or "custom-node"
    result = base
    suffix = 2
    while result in used:
        result = f"{base}-{suffix}"
        suffix += 1
    used.add(result)
    return result


def build_manifest(args: argparse.Namespace) -> tuple[dict, dict]:
    workflow_path = Path(args.workflow).expanduser().resolve()
    workflow = json.loads(workflow_path.read_text(errors="replace"))
    workflow_types, workflow_metadata = workflow_node_types(workflow)
    loaded_types = live_node_types(args.comfy_url)
    missing = sorted(workflow_types - loaded_types, key=str.casefold)

    mapping = fetch_json(args.extension_map)
    catalog = catalog_entries(fetch_json(args.custom_node_list))
    base_manifest = fetch_json(args.base_manifest) if args.base_manifest else None
    by_remote, by_local = known_nodes(base_manifest)

    generated_nodes: dict[str, dict] = {}
    selected_ids: list[str] = []
    unresolved: list[dict] = []
    used_ids: set[str] = set()

    for node_type in missing:
        candidates = extract_repo_candidates(mapping, node_type)

        # Newer workflow metadata can carry pack IDs. Use those as an additional
        # lookup hint, while retaining Manager's extension map as the authority.
        for props in workflow_metadata.get(node_type, []):
            for key in ("cnr_id", "aux_id", "node_pack", "pack_id"):
                value = props.get(key)
                if isinstance(value, str) and value:
                    candidates.extend(catalog_match(catalog, value))

        candidates = list(dict.fromkeys(candidates))
        selected = choose(f"Provider for missing node: {node_type}", candidates, args.accept_default)
        if selected is None:
            unresolved.append({"node_type": node_type, "reason": "no provider selected", "candidates": candidates})
            continue

        canonical = canonical_remote(selected)
        known = by_remote.get(canonical) or by_local.get(normalize(repo_local(selected)))
        if known:
            node_id, definition = known
            node_id = node_id if node_id not in used_ids else unique_id(selected, used_ids)
            used_ids.add(node_id)
            definition = copy.deepcopy(definition)
        else:
            node_id = unique_id(selected, used_ids)
            definition = {"remote": selected, "local": repo_local(selected)}

        ref = choose_ref(selected, args.accept_default)
        if ref:
            definition["ref"] = ref
        generated_nodes[node_id] = definition
        selected_ids.append(node_id)

    manifest = {
        "schema_version": 1,
        "generated": {
            "source_workflow": str(workflow_path),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "comfy_url": args.comfy_url,
            "workflow_node_count": len(workflow_types),
            "loaded_node_count": len(loaded_types),
            "missing_node_count": len(missing),
        },
        "nodes": generated_nodes,
        "sets": {"default": selected_ids},
    }
    if unresolved:
        manifest["unresolved"] = unresolved

    summary = {
        "workflow_types": len(workflow_types),
        "loaded_types": len(loaded_types),
        "missing": missing,
        "resolved": len(selected_ids),
        "unresolved": unresolved,
    }
    return manifest, summary


def print_summary(summary: dict, output: Path) -> None:
    print(f"Workflow node types : {summary['workflow_types']}")
    print(f"Live loaded types   : {summary['loaded_types']}")
    print(f"Missing types       : {len(summary['missing'])}")
    print(f"Resolved packs      : {summary['resolved']}")
    print(f"Unresolved types    : {len(summary['unresolved'])}")
    print(f"Output manifest     : {output}")
    if summary["missing"]:
        print("\nMissing node types:")
        for name in summary["missing"]:
            marker = "!" if any(item["node_type"] == name for item in summary["unresolved"]) else "+"
            print(f"  {marker} {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a custom-node manifest from a live ComfyUI workflow")
    parser.add_argument("workflow")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--base-manifest", default=os.environ.get("CUSTOM_NODES_MANIFEST_URL", ""))
    parser.add_argument("--extension-map", default=os.environ.get("COMFY_MANAGER_EXTENSION_MAP_URL", DEFAULT_MAP_URL))
    parser.add_argument("--custom-node-list", default=os.environ.get("COMFY_MANAGER_CUSTOM_NODE_LIST_URL", DEFAULT_LIST_URL))
    parser.add_argument("--accept-default", action="store_true")
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()

    manifest, summary = build_manifest(args)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output)
    print_summary(summary, output)

    if summary["unresolved"] and not args.allow_unresolved:
        print("\nUnresolved nodes remain; rerun interactively or use --allow-unresolved.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"workflow custom-node resolver: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
