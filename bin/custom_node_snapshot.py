#!/usr/bin/env python3
"""Discover installed ComfyUI custom nodes and record a restorable pending set.

Discovery is read-only with respect to custom_nodes checkouts and the upstream
manifest. Only snapshot-local JSON artifacts are written. Never auto-promote.
"""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1
DEFAULT_ROOT = Path("/workspace/.pod-state/custom_nodes")
NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def normalize_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom-node"


def safe_remote(value: str) -> str | None:
    """Do not persist embedded Git credentials or local paths in a snapshot."""
    value = str(value or "").strip()
    if not value or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        return None
    if re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+(?:\.git)?", value):
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in ("https", "ssh") or not parsed.hostname:
        return None
    if parsed.password is not None or parsed.query or parsed.fragment:
        return None
    if parsed.username and not (parsed.scheme == "ssh" and parsed.username == "git"):
        return None
    if any(part in (".", "..") for part in parsed.path.split("/")):
        return None
    if not parsed.path.strip("/"):
        return None
    return value


def canonical_remote(value: str) -> str:
    remote = value.lower().rstrip("/").removesuffix(".git")
    if remote.startswith("git@") and ":" in remote:
        host, path = remote[4:].split(":", 1)
        return host + "/" + path
    if remote.startswith("ssh://git@"):
        remote = remote[len("ssh://git@"):]
    elif remote.startswith("https://"):
        remote = remote[len("https://"):]
    return remote.rstrip("/")


def load_manifest(source: str) -> dict[str, Any]:
    if source.startswith(("https://", "http://")):
        if not source.startswith("https://"):
            raise ValueError("Baseline manifest URL must use HTTPS")
        with urllib.request.urlopen(source, timeout=25) as response:
            data = json.load(response)
    else:
        data = json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    validate_manifest(data)
    return data


def validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA:
        raise ValueError("Expected a schema_version=1 custom-node manifest")
    nodes, sets = manifest.get("nodes"), manifest.get("sets")
    if not isinstance(nodes, dict) or not isinstance(sets, dict) or not isinstance(sets.get("default"), list):
        raise ValueError("Manifest must contain nodes, sets, and sets.default")
    destinations: dict[str, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("remote"), str):
            raise ValueError(f"Invalid node entry: {node_id}")
        name = node.get("local") or Path(node["remote"].rstrip("/")).name.removesuffix(".git")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise ValueError(f"Unsafe node directory for {node_id}")
        if name in destinations:
            raise ValueError(f"Duplicate custom-node destination: {name}")
        destinations[name] = node_id
    for key, ids in sets.items():
        if not isinstance(ids, list) or any(not isinstance(n, str) or n not in nodes for n in ids):
            raise ValueError(f"Invalid custom-node set: {key}")


def git(path: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
            timeout=12, check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def _node_dirs(custom_dir: Path) -> list[Path]:
    if not custom_dir.is_dir():
        raise ValueError(f"Custom-node directory is missing: {custom_dir}")
    return sorted(
        (entry for entry in custom_dir.iterdir()
         if not entry.name.startswith(".") and entry.name != "__pycache__"
         and not entry.name.endswith((".disabled", ".bak", ".old"))),
        key=lambda entry: entry.name.lower(),
    )


def status_report(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = report.get("nodes", []) if isinstance(report, dict) else []
    if not isinstance(entries, list):
        return {}
    return {
        item["local"]: {
            "clone": str(item.get("clone", "")),
            "install": str(item.get("install", "")),
            "commit": str(item.get("commit", "")),
        }
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("local"), str)
    }


def _available_id(name: str, nodes: dict[str, Any]) -> str:
    base = normalize_id(name)
    selected = base
    counter = 2
    while selected in nodes:
        selected = f"{base}-{counter}"
        counter += 1
    return selected


def discover(base_manifest: dict[str, Any], custom_dir: Path, *,
             status_path: Path | None = None, selected_sets: str = "",
             pin_installed: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = copy.deepcopy(base_manifest)
    validate_manifest(manifest)
    manifest["sets"].setdefault("pending", [])
    nodes: dict[str, Any] = manifest["nodes"]
    pending: list[str] = manifest["sets"]["pending"]
    by_local = {
        node.get("local") or Path(node["remote"].rstrip("/")).name.removesuffix(".git"): node_id
        for node_id, node in nodes.items()
    }
    by_remote = {canonical_remote(node["remote"]): node_id for node_id, node in nodes.items()}
    prior_status = status_report(status_path)
    inventory: list[dict[str, Any]] = []
    warnings: list[str] = []
    new_ids: list[str] = []

    for entry in _node_dirs(custom_dir):
        record: dict[str, Any] = {"local": entry.name, "status": "unresolved"}
        # First-party modules in the pod-runtime checkout are installed by
        # bootstrap. Other symlinked Git plugins should still be discovered.
        linked = entry.is_symlink()
        if linked:
            try:
                resolved = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                resolved = None
            runtime_nodes = Path(os.environ.get("POD_RUNTIME_DIR",
                                               "/workspace/pod-runtime")) / "custom_nodes"
            if resolved and resolved.is_relative_to(runtime_nodes.resolve()):
                record["status"] = "builtin-symlink"
                inventory.append(record)
                continue
            if resolved is None or not resolved.is_dir():
                record["status"] = "dangling-symlink"
                warnings.append(f"{entry.name}: broken custom-node symlink")
                inventory.append(record)
                continue
            record["linked"] = True
        if entry.is_file():
            if entry.suffix != ".py":
                continue
            record["status"] = "single-file"
            warnings.append(f"{entry.name}: local Python file has no recoverable Git remote")
            inventory.append(record)
            continue
        if not entry.is_dir():
            continue

        # git -C can walk into the parent ComfyUI repository. An unmanaged
        # directory MUST be an independent Git checkout, not just a subfolder.
        top_rc, top = git(entry, "rev-parse", "--show-toplevel")
        if top_rc or not top or Path(top).resolve() != entry.resolve():
            record["status"] = "non-git"
            warnings.append(f"{entry.name}: no independent Git checkout; manual restoration required")
            inventory.append(record)
            continue
        exit_code, remote_raw = git(entry, "config", "--get", "remote.origin.url")
        commit_rc, commit = git(entry, "rev-parse", "HEAD")
        if exit_code or commit_rc or not COMMIT_RE.fullmatch(commit):
            record["status"] = "non-git"
            warnings.append(f"{entry.name}: no usable Git remote/commit; manual restoration required")
            inventory.append(record)
            continue
        remote = safe_remote(remote_raw)
        if not remote:
            record["status"] = "unsafe-remote"
            warnings.append(f"{entry.name}: remote is unsupported or contains credentials; not copied")
            inventory.append(record)
            continue
        dirty_rc, dirty = git(entry, "status", "--porcelain", "--untracked-files=normal")
        record.update(remote=remote, commit=commit.lower(),
                      dirty=bool(dirty) if dirty_rc == 0 else None,
                      installer=prior_status.get(entry.name))
        if linked:
            warnings.append(f"{entry.name}: symlinked Git node will be restored as a regular checkout")
        if dirty_rc != 0:
            warnings.append(f"{entry.name}: could not check Git working tree")
        elif dirty:
            warnings.append(f"{entry.name}: uncommitted or untracked changes cannot be restored from a Git commit")

        node_id = by_local.get(entry.name)
        match_by_remote = by_remote.get(canonical_remote(remote))
        if node_id and canonical_remote(nodes[node_id]["remote"]) != canonical_remote(remote):
            record["status"] = "conflict"
            record["manifest_id"] = node_id
            warnings.append(f"{entry.name}: installed remote does not match manifest entry {node_id}")
            inventory.append(record)
            continue
        if not node_id and match_by_remote:
            record["status"] = "duplicate-remote"
            record["manifest_id"] = match_by_remote
            warnings.append(f"{entry.name}: remote already declared under a different directory; review manually")
            inventory.append(record)
            continue
        if node_id:
            record["manifest_id"] = node_id
            record["status"] = "managed"
            # Pin the *snapshot copy*, preserving custom pip constraints and clone options.
            if pin_installed:
                nodes[node_id]["ref"] = commit.lower()
        else:
            node_id = _available_id(entry.name, nodes)
            nodes[node_id] = {"remote": remote, "local": entry.name, "ref": commit.lower()}
            by_local[entry.name] = node_id
            by_remote[canonical_remote(remote)] = node_id
            pending.append(node_id)
            new_ids.append(node_id)
            record["manifest_id"] = node_id
            record["status"] = "pending"
        inventory.append(record)

    chosen = {x.strip() for x in re.split(r"[\s,]+", selected_sets) if x.strip()}
    # The main installer status can include additional selected workflow sets.
    # Keep only sets present in the captured manifest.
    chosen = {name for name in chosen if name in manifest["sets"]}
    if status_path and status_path.is_file():
        try:
            report = json.loads(status_path.read_text(encoding="utf-8"))
            chosen.update(name for name in report.get("sets", [])
                          if name in manifest["sets"])
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    chosen.discard("pending")
    chosen.discard("default")
    validate_manifest(manifest)
    report_out: dict[str, Any] = {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_manifest": "configured active custom-node manifest",
        "custom_dir": str(custom_dir),
        "selected_sets": sorted(chosen),
        "pending_ids": list(dict.fromkeys(pending)),
        "new_pending_ids": new_ids,
        "installed": inventory,
        "warnings": warnings,
        "summary": {
            "installed_git": sum(1 for r in inventory if r["status"] in ("managed", "pending")),
            "new_pending": len(new_ids),
            "unresolved": sum(1 for r in inventory if r["status"] in ("non-git", "single-file",
                                                                       "unsafe-remote", "conflict", "dangling-symlink",
                                                                       "duplicate-remote")),
        },
    }
    return manifest, report_out


def packages_report() -> dict[str, Any]:
    # importlib metadata avoids pip-freeze's authenticated direct URL output.
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            packages[name] = distribution.version
    return {"python": sys.version.splitlines()[0],
            "packages": dict(sorted(packages.items(), key=lambda x: x[0].lower()))}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cmd_discover(args: argparse.Namespace) -> int:
    base = load_manifest(args.base)
    target, inventory, packages = map(Path, (args.output, args.inventory, args.packages))
    if len({target.parent.resolve(), inventory.parent.resolve(), packages.parent.resolve()}) != 1:
        raise ValueError("All capture artifacts must share the same directory")
    if not target.parent.resolve().is_relative_to(Path("/workspace").resolve()) and not args.allow_test_path:
        raise ValueError("Snapshot artifacts must be under /workspace")
    manifest, report = discover(base, Path(args.nodes_root), status_path=Path(args.status_file),
                                selected_sets=args.sets)
    print(json.dumps({"summary": report["summary"], "pending": report["pending_ids"],
                      "warnings": report["warnings"]}, indent=2))
    if args.dry_run:
        return 0
    write_json(target, manifest)
    write_json(inventory, report)
    write_json(packages, packages_report())
    print(f"[custom-nodes] Snapshot manifest: {target}")
    return 0


def cmd_restore_sets(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    if inv.get("schema_version") != 1:
        raise ValueError("Invalid inventory version")
    original = inv.get("selected_sets", [])
    if not isinstance(original, list) or any(not isinstance(s, str) for s in original):
        raise ValueError("Invalid restored set selection")
    requested = set(original)
    requested.update(s.strip() for s in re.split(r"[\s,]+", args.launcher_sets) if s.strip())
    if manifest["sets"].get("pending"):
        requested.add("pending")
    requested.discard("default")
    unknown = requested - set(manifest["sets"])
    if unknown:
        raise ValueError("Restored manifest is missing sets: " + ", ".join(sorted(unknown)))
    print(",".join(sorted(requested)))
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    source = load_manifest(args.source)
    destination = load_manifest(args.into)
    pending = source["sets"].get("pending", [])
    if args.id not in pending:
        raise ValueError(f"{args.id} is not in the snapshot's pending set")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.set) or args.set == "pending":
        raise ValueError("Choose a non-pending target set (e.g. krea2)")
    node = copy.deepcopy(source["nodes"][args.id])
    # Git remotes in the destination must not silently be replaced.
    if args.id in destination["nodes"] and destination["nodes"][args.id] != node:
        raise ValueError(f"Destination already defines a different {args.id}; review manually")
    new_remote = canonical_remote(node["remote"])
    for existing_id, existing in destination["nodes"].items():
        if existing_id != args.id and (canonical_remote(existing["remote"]) == new_remote
             or existing.get("local") == node.get("local")):
            raise ValueError(f"Destination node {existing_id} already uses this repository or directory")
    destination["nodes"].setdefault(args.id, node)
    members = destination["sets"].setdefault(args.set, [])
    if args.id not in members:
        members.append(args.id)
    validate_manifest(destination)
    if not args.dry_run:
        write_json(Path(args.into), destination)
    print(f"{'Would promote' if args.dry_run else 'Promoted'} {args.id} -> {args.set} in {args.into}")
    print("Review and commit the updated main manifest manually; the snapshot copy is unchanged.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    discovery = sub.add_parser("discover", help="Compare installed Git nodes with active manifest")
    discovery.add_argument("--base", default=os.environ.get(
        "CUSTOM_NODES_MANIFEST_URL", str(Path(__file__).resolve().parents[1] / "custom_nodes_manifest.json")))
    discovery.add_argument("--nodes-root", default=os.environ.get(
        "CUSTOM_DIR", str(Path(os.environ.get("COMFY_HOME", "/workspace/ComfyUI")) / "custom_nodes")))
    discovery.add_argument("--status-file", default=os.environ.get(
        "CUSTOM_NODE_STATUS_FILE", str(Path(os.environ.get("CUSTOM_LOG_DIR", "/workspace/logs/custom_nodes")) / "install_status.json")))
    discovery.add_argument("--sets", default=os.environ.get("CUSTOM_NODE_SETS", ""))
    discovery.add_argument("--output", default=str(DEFAULT_ROOT / "manifest.json"))
    discovery.add_argument("--inventory", default=str(DEFAULT_ROOT / "inventory.json"))
    discovery.add_argument("--packages", default=str(DEFAULT_ROOT / "packages.json"))
    discovery.add_argument("--dry-run", action="store_true")
    discovery.add_argument("--allow-test-path", action="store_true", help=argparse.SUPPRESS)
    restore = sub.add_parser("restore-sets", help="Validate restored manifest and compute install sets")
    restore.add_argument("--manifest", default=str(DEFAULT_ROOT / "manifest.json"))
    restore.add_argument("--inventory", default=str(DEFAULT_ROOT / "inventory.json"))
    restore.add_argument("--launcher-sets", default="")
    promote = sub.add_parser("promote", help="Copy one pending definition into the main manifest")
    promote.add_argument("id")
    promote.add_argument("--source", default=str(DEFAULT_ROOT / "manifest.json"))
    promote.add_argument("--into", default=str(Path(__file__).resolve().parents[1] / "custom_nodes_manifest.json"))
    promote.add_argument("--set", required=True)
    promote.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "discover":
            return cmd_discover(args)
        if args.action == "restore-sets":
            return cmd_restore_sets(args)
        if args.action == "promote":
            return cmd_promote(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[custom-nodes] ERROR: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
