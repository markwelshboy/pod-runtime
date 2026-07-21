#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def normalize_id(value: str) -> str:
    value = re.sub(r"\.git$", "", value.strip(), flags=re.I)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "custom-node"


def repo_name(remote: str) -> str:
    return Path(remote.rstrip("/")).name.removesuffix(".git")


def canonical_remote(remote: str) -> str:
    value = remote.strip().rstrip("/")
    value = re.sub(r"\.git$", "", value, flags=re.I)
    value = value.replace("http://github.com/", "https://github.com/")
    return value.lower()


def resolve_manifest(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    configured = os.environ.get("CUSTOM_NODES_MANIFEST_URL", "")
    if configured and "://" not in configured:
        candidates.append(Path(configured).expanduser())

    runtime = os.environ.get("POD_RUNTIME_DIR")
    if runtime:
        candidates.append(Path(runtime) / "default_custom_nodes_manifest.json")

    # This script lives in <repo>/bin/.
    candidates.append(Path(__file__).resolve().parent.parent / "default_custom_nodes_manifest.json")
    candidates.append(Path.cwd() / "default_custom_nodes_manifest.json")

    for path in candidates:
        if path.is_file():
            return path.resolve()

    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.parent.is_dir():
            return path

    raise RuntimeError(
        "No writable local custom-node manifest found. Use --manifest PATH or run from the pod-runtime checkout."
    )


def load_or_create(path: Path) -> dict[str, Any]:
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {"schema_version": 1, "nodes": {}, "sets": {"default": []}}
    if data.get("schema_version") != 1 or not isinstance(data.get("nodes"), dict) or not isinstance(data.get("sets"), dict):
        raise RuntimeError(f"Unsupported or invalid manifest: {path}")
    data["sets"].setdefault("default", [])
    return data


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def build_node(args: argparse.Namespace, remote: str, local: str) -> dict[str, Any]:
    node: dict[str, Any] = {"remote": remote, "local": local}
    if args.clone_option:
        node["clone_options"] = args.clone_option
    pip_config: dict[str, Any] = {}
    if args.pip_option:
        pip_config["options"] = args.pip_option
    requirements: dict[str, Any] = {}
    if args.remove_requirement:
        requirements["remove"] = args.remove_requirement
    if args.add_requirement:
        requirements["add"] = args.add_requirement
    if requirements:
        pip_config["requirements"] = requirements
    if pip_config:
        node["pip"] = pip_config
    return node


def find_existing(manifest: dict[str, Any], remote: str) -> tuple[str, dict[str, Any]] | None:
    wanted = canonical_remote(remote)
    for node_id, node in manifest["nodes"].items():
        if isinstance(node, dict) and isinstance(node.get("remote"), str):
            if canonical_remote(node["remote"]) == wanted:
                return node_id, node
    return None


def confirm(remote: str, node_id: str, local: str, set_name: str, manifest: Path, accept_default: bool) -> bool:
    print(f"Repository : {remote}")
    print(f"Manifest ID: {node_id}")
    print(f"Local dir  : {local}")
    print(f"Target set : {set_name}")
    print(f"Manifest   : {manifest}")
    if accept_default or not sys.stdin.isatty():
        return True
    answer = input("\nAdd this custom node? [Y/n]: ").strip().lower()
    return answer not in {"n", "no"}


def install_single(tool: Path, node_id: str, node: dict[str, Any]) -> int:
    manifest = {
        "schema_version": 1,
        "nodes": {node_id: node},
        "sets": {"default": [node_id]},
    }
    with tempfile.TemporaryDirectory(prefix="custom-node-add-") as temp_dir:
        path = Path(temp_dir) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        command = [
            os.environ.get("PY_BIN", os.environ.get("PY", sys.executable)),
            str(tool),
            "--manifest",
            str(path),
            "install",
            "--sets",
            "",
        ]
        print("\nInstalling added custom node...")
        return subprocess.run(command, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a custom-node repository to a local manifest, with inferred ID/local names."
    )
    parser.add_argument("repository", nargs="?", help="Git repository URL")
    parser.add_argument("--remote", help="Git repository URL (legacy explicit form)")
    parser.add_argument("--manifest", help="Writable local manifest path")
    parser.add_argument("--set", default="default", help="Manifest set/tag (default: default)")
    parser.add_argument("--id", help="Manifest ID; inferred from repository name")
    parser.add_argument("--local", help="Checkout directory; inferred from repository name")
    parser.add_argument("--clone-option", action="append", default=[])
    parser.add_argument("--pip-option", action="append", default=[])
    parser.add_argument("--remove-requirement", action="append", default=[])
    parser.add_argument("--add-requirement", action="append", default=[])
    parser.add_argument("--accept-default", action="store_true", help="Accept inferred values without prompting")
    parser.add_argument("--install", action="store_true", help="Install only this node after updating the manifest")
    parser.add_argument("--update-existing", action="store_true", help="Replace an existing repository definition with supplied options")
    args = parser.parse_args()

    remote = args.repository or args.remote
    if not remote:
        parser.error("a repository URL is required (positional or --remote)")
    if args.repository and args.remote and canonical_remote(args.repository) != canonical_remote(args.remote):
        parser.error("positional repository and --remote disagree")

    manifest_path = resolve_manifest(args.manifest)
    manifest = load_or_create(manifest_path)
    suggested_local = args.local or repo_name(remote)
    suggested_id = args.id or normalize_id(repo_name(remote))

    existing = find_existing(manifest, remote)
    if existing:
        node_id, existing_node = existing
        if args.id and args.id != node_id:
            print(f"Repository already exists as manifest ID '{node_id}'; reusing it.")
        selected_id = node_id
        selected_node = build_node(args, remote, suggested_local) if args.update_existing else existing_node
        selected_local = str(selected_node.get("local") or repo_name(remote))
    else:
        selected_id = suggested_id
        selected_node = build_node(args, remote, suggested_local)
        selected_local = suggested_local
        if selected_id in manifest["nodes"]:
            current = manifest["nodes"][selected_id]
            current_remote = current.get("remote") if isinstance(current, dict) else None
            if canonical_remote(str(current_remote or "")) != canonical_remote(remote):
                raise RuntimeError(
                    f"Manifest ID '{selected_id}' already belongs to {current_remote}. Use --id to choose another ID."
                )

    if not confirm(remote, selected_id, selected_local, args.set, manifest_path, args.accept_default):
        print("Cancelled.")
        return 1

    manifest["nodes"][selected_id] = selected_node
    manifest["sets"].setdefault(args.set, [])
    if selected_id not in manifest["sets"][args.set]:
        manifest["sets"][args.set].append(selected_id)
        membership = "added"
    else:
        membership = "already present"
    atomic_write(manifest_path, manifest)

    print("\nManifest updated successfully.")
    print(f"  Node ID       : {selected_id}")
    print(f"  Set membership: {args.set} ({membership})")
    print(f"  Manifest      : {manifest_path}")

    if args.install:
        tool = Path(os.environ.get("CUSTOM_NODES_TOOL", Path(__file__).resolve().parent / "custom_nodes.py"))
        return install_single(tool, selected_id, selected_node)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"custom_node_add: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
