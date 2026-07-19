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
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
FRONTEND_ONLY = {
    "Reroute", "MarkdownNote", "SetNode", "GetNode",
    "Bookmark (rgthree)", "Fast Bypasser (rgthree)",
    "Fast Groups Bypasser (rgthree)", "Fast Muter (rgthree)",
    "Label (rgthree)", "Node Collector (rgthree)",
}


def fetch_json(source: str, timeout: int = 45) -> Any:
    path = Path(source).expanduser()
    if path.is_file():
        return json.loads(path.read_text(errors="replace"))
    req = urllib.request.Request(source, headers={"User-Agent": "pod-runtime-workflow-resolver/2"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def normalize(value: str) -> str:
    return re.sub(r"[-_.\s]+", "-", value).strip("-").lower()


def repo_local(remote: str) -> str:
    return Path(remote.rstrip("/")).name.removesuffix(".git")


def canonical_remote(value: str) -> str:
    value = value.strip().rstrip("/")
    value = re.sub(r"\.git$", "", value, flags=re.I)
    value = value.replace("http://github.com/", "https://github.com/")
    return value.lower()


def looks_like_repo(value: str) -> bool:
    return bool(re.match(r"https?://(?:www\.)?github\.com/[^/]+/[^/]+", value, re.I))


def workflow_nodes(data: Any) -> list[dict]:
    result: list[dict] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            nodes = obj.get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    if isinstance(node, dict) and isinstance(node.get("type"), str):
                        result.append(node)
                    walk(node)
            for key, value in obj.items():
                if key != "nodes":
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for node in result:
        key = (str(node.get("id", "")), str(node.get("type", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(node)
    return deduped


def live_node_types(comfy_url: str) -> set[str]:
    data = fetch_json(comfy_url.rstrip("/") + "/object_info")
    if not isinstance(data, dict):
        raise ValueError("Unexpected /object_info response")
    return set(map(str, data.keys()))


def strings_in(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            out.add(str(key))
            out.update(strings_in(item))
    elif isinstance(value, list):
        for item in value:
            out.update(strings_in(item))
    return out


def catalog_entries(data: Any) -> list[dict]:
    if isinstance(data, dict):
        for key in ("custom_nodes", "nodes", "items"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def entry_repos(entry: dict) -> list[str]:
    repos: list[str] = []
    for key in ("reference", "repository", "repo", "url"):
        value = entry.get(key)
        if isinstance(value, str) and looks_like_repo(value):
            repos.append(value)
    for value in entry.get("files", []) if isinstance(entry.get("files"), list) else []:
        if isinstance(value, str) and looks_like_repo(value):
            repos.append(value)
    return list(dict.fromkeys(repos))


def catalog_index(entries: list[dict]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for entry in entries:
        repos = entry_repos(entry)
        labels: set[str] = set()
        for key in ("id", "title", "name", "author"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                labels.add(normalize(value))
        for remote in repos:
            labels.add(normalize(repo_local(remote)))
            parts = canonical_remote(remote).split("github.com/", 1)
            if len(parts) == 2:
                labels.add(normalize(parts[1]))
        for label in labels:
            index.setdefault(label, []).extend(repos)
    return {k: list(dict.fromkeys(v)) for k, v in index.items()}


def metadata_candidates(node: dict, index: dict[str, list[str]]) -> list[str]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    candidates: list[str] = []
    for key in ("cnr_id", "aux_id", "node_pack", "pack_id"):
        value = props.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if looks_like_repo(value):
            candidates.append(value)
            continue
        if re.match(r"^[^/\s]+/[^/\s]+$", value):
            candidates.append("https://github.com/" + value)
        candidates.extend(index.get(normalize(value), []))
    return list(dict.fromkeys(candidates))


def map_candidates(mapping: Any, node_type: str) -> list[str]:
    target = node_type.casefold()
    found: list[str] = []
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            values = {x.casefold() for x in strings_in(value)}
            if target in values:
                if looks_like_repo(str(key)):
                    found.append(str(key))
                else:
                    found.extend(x for x in strings_in(value) if looks_like_repo(x))
    return list(dict.fromkeys(found))


def known_nodes(base: dict | None) -> tuple[dict[str, tuple[str, dict]], dict[str, tuple[str, dict]]]:
    by_remote: dict[str, tuple[str, dict]] = {}
    by_local: dict[str, tuple[str, dict]] = {}
    if isinstance(base, dict):
        for node_id, node in base.get("nodes", {}).items():
            if isinstance(node, dict) and node.get("remote"):
                by_remote[canonical_remote(node["remote"])] = (node_id, node)
                by_local[normalize(node.get("local") or repo_local(node["remote"]))] = (node_id, node)
    return by_remote, by_local


def choose(prompt: str, options: list[str], accept_default: bool) -> str | None:
    options = list(dict.fromkeys(options))
    if not options:
        return None
    if accept_default or not sys.stdin.isatty() or len(options) == 1:
        return options[0]
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        print(f"  [{i}] {option}")
    print("  [s] Skip/unresolved")
    while True:
        answer = input("Selection [1]: ").strip()
        if not answer:
            return options[0]
        if answer.lower() in {"s", "skip"}:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer)-1]


def choose_ref(remote: str, accept_default: bool) -> str | None:
    if accept_default or not sys.stdin.isatty():
        return None
    print(f"\nVersion/ref for {remote}\n  [1] Repository default branch\n  [2] Enter tag, branch, or commit")
    answer = input("Selection [1]: ").strip()
    if answer == "2":
        return input("Git ref: ").strip() or None
    return None


def unique_id(remote: str, used: set[str]) -> str:
    base = normalize(repo_local(remote)) or "custom-node"
    value = base
    n = 2
    while value in used:
        value = f"{base}-{n}"
        n += 1
    used.add(value)
    return value


def build(args: argparse.Namespace) -> tuple[dict, dict]:
    workflow_path = Path(args.workflow).expanduser().resolve()
    data = json.loads(workflow_path.read_text(errors="replace"))
    nodes = workflow_nodes(data)
    loaded = live_node_types(args.comfy_url)
    mapping = fetch_json(args.extension_map)
    entries = catalog_entries(fetch_json(args.custom_node_list))
    index = catalog_index(entries)
    base = fetch_json(args.base_manifest) if args.base_manifest else None
    by_remote, by_local = known_nodes(base)

    generated: dict[str, dict] = {}
    selected_ids: list[str] = []
    unresolved: list[dict] = []
    ignored: list[str] = []
    missing_types: list[str] = []
    used_ids: set[str] = set()
    chosen_remotes: set[str] = set()

    for node in nodes:
        node_type = str(node.get("type", "")).strip()
        if not node_type or node_type in loaded:
            continue
        if UUID_RE.match(node_type) or node_type in FRONTEND_ONLY or node_type.endswith(" (rgthree)"):
            ignored.append(node_type)
            continue
        missing_types.append(node_type)
        meta = metadata_candidates(node, index)
        candidates = meta if meta else map_candidates(mapping, node_type)
        selected = choose(f"Provider for missing node: {node_type}", candidates, args.accept_default)
        if selected is None:
            unresolved.append({"node_type": node_type, "reason": "no provider selected", "candidates": candidates})
            continue
        canonical = canonical_remote(selected)
        if canonical in chosen_remotes:
            continue
        chosen_remotes.add(canonical)
        known = by_remote.get(canonical) or by_local.get(normalize(repo_local(selected)))
        if known:
            node_id, definition = known
            definition = copy.deepcopy(definition)
            if node_id in used_ids:
                node_id = unique_id(selected, used_ids)
            else:
                used_ids.add(node_id)
        else:
            node_id = unique_id(selected, used_ids)
            definition = {"remote": selected, "local": repo_local(selected)}
        ref = choose_ref(selected, args.accept_default)
        if ref:
            definition["ref"] = ref
        generated[node_id] = definition
        selected_ids.append(node_id)

    manifest = {
        "schema_version": 1,
        "generated": {
            "source_workflow": str(workflow_path),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "comfy_url": args.comfy_url,
            "workflow_nodes_scanned": len(nodes),
            "missing_backend_types": len(set(missing_types)),
            "ignored_frontend_types": sorted(set(ignored), key=str.casefold),
        },
        "nodes": generated,
        "sets": {"default": selected_ids},
    }
    if unresolved:
        manifest["unresolved"] = unresolved
    summary = {
        "workflow_nodes": len(nodes),
        "missing": sorted(set(missing_types), key=str.casefold),
        "ignored": sorted(set(ignored), key=str.casefold),
        "resolved": len(selected_ids),
        "unresolved": unresolved,
    }
    return manifest, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--base-manifest", default=os.environ.get("CUSTOM_NODES_MANIFEST_URL", ""))
    parser.add_argument("--extension-map", default=os.environ.get("COMFY_MANAGER_EXTENSION_MAP_URL", DEFAULT_MAP_URL))
    parser.add_argument("--custom-node-list", default=os.environ.get("COMFY_MANAGER_CUSTOM_NODE_LIST_URL", DEFAULT_LIST_URL))
    parser.add_argument("--accept-default", action="store_true")
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()

    manifest, summary = build(args)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    temp.replace(output)

    print(f"Workflow nodes scanned : {summary['workflow_nodes']}")
    print(f"Missing backend types  : {len(summary['missing'])}")
    print(f"Ignored frontend types : {len(summary['ignored'])}")
    print(f"Resolved node packs    : {summary['resolved']}")
    print(f"Unresolved types       : {len(summary['unresolved'])}")
    print(f"Output manifest        : {output}")
    if summary["ignored"]:
        print("\nIgnored frontend-only types:")
        for name in summary["ignored"]:
            print(f"  - {name}")
    if summary["unresolved"]:
        print("\nUnresolved backend types:")
        for item in summary["unresolved"]:
            print(f"  ! {item['node_type']}")
    if summary["unresolved"] and not args.allow_unresolved:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"workflow custom-node resolver: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
