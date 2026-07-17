#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize_name(value: str) -> str:
    return _NORMALIZE_RE.sub("-", value).lower()


def load_manifest(source: str) -> tuple[dict, Path | None]:
    path = Path(source).expanduser()
    if path.is_file():
        return json.loads(path.read_text()), path
    with urllib.request.urlopen(source, timeout=30) as response:
        return json.load(response), None


def local_name(node: dict) -> str:
    return node.get("local") or Path(node["remote"].rstrip("/")).name.removesuffix(".git")


def validate_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    nodes = manifest.get("nodes")
    sets = manifest.get("sets")
    if not isinstance(nodes, dict) or not isinstance(sets, dict):
        raise ValueError("nodes and sets must be JSON objects")
    if "default" not in sets:
        raise ValueError("sets.default is required")

    destinations: dict[str, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or not node.get("remote"):
            raise ValueError(f"{node_id}: remote is required")
        destination = local_name(node)
        if destination in destinations:
            raise ValueError(
                f"duplicate local directory {destination}: "
                f"{destinations[destination]} and {node_id}"
            )
        destinations[destination] = node_id
        if "clone_options" in node and not isinstance(node["clone_options"], list):
            raise ValueError(f"{node_id}.clone_options must be an array")

    for set_name, node_ids in sets.items():
        if not isinstance(node_ids, list):
            raise ValueError(f"set {set_name} must be an array")
        for node_id in node_ids:
            if node_id not in nodes:
                raise ValueError(f"set {set_name} references unknown node {node_id}")


def resolve_nodes(manifest: dict, requested: str) -> list[tuple[str, dict]]:
    set_names = ["default"]
    set_names.extend(
        name
        for name in re.split(r"[\s,]+", requested.strip())
        if name and name != "default"
    )

    resolved: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for set_name in set_names:
        if set_name not in manifest["sets"]:
            raise ValueError(f"unknown custom-node set: {set_name}")
        for node_id in manifest["sets"][set_name]:
            if node_id not in seen:
                seen.add(node_id)
                resolved.append((node_id, manifest["nodes"][node_id]))
    return resolved


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    log=None,
) -> int:
    print("+", shlex.join(command), file=log or sys.stderr, flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT if log else None,
        check=False,
    )
    return completed.returncode


def clone_node(item: tuple[str, dict], custom_dir: Path, log_dir: Path) -> tuple[str, int]:
    node_id, node = item
    destination = custom_dir / local_name(node)
    log_path = log_dir / f"{local_name(node)}.log"

    with log_path.open("a") as log:
        options = [str(value) for value in node.get("clone_options", [])]
        if (destination / ".git").exists():
            rc = run_command(
                ["git", "-C", str(destination), "fetch", "--all", "--tags", "--prune"],
                log=log,
            )
            if rc == 0:
                rc = run_command(
                    ["git", "-C", str(destination), "pull", "--ff-only"],
                    log=log,
                )
        elif destination.exists():
            print(f"ERROR: destination exists but is not a git checkout: {destination}", file=log)
            rc = 1
        else:
            rc = run_command(
                ["git", "clone", *options, node["remote"], str(destination)],
                log=log,
            )

        if rc == 0 and node.get("ref"):
            rc = run_command(
                ["git", "-C", str(destination), "checkout", str(node["ref"])],
                log=log,
            )
        return node_id, rc


def requirement_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return None
    try:
        from packaging.requirements import Requirement

        return normalize_name(Requirement(stripped).name)
    except Exception:
        match = re.match(r"([A-Za-z0-9_.-]+)", stripped)
        return normalize_name(match.group(1)) if match else None


def materialize_constraints(node: dict, temporary_dir: Path) -> list[str]:
    paths: list[str] = []
    for index, entry in enumerate(node.get("pip", {}).get("constraints", [])):
        if isinstance(entry, str):
            entry = {"url": entry}
        if entry.get("path"):
            paths.append(str(Path(entry["path"]).expanduser()))
            continue
        url = entry.get("url")
        if not url:
            continue
        data = urllib.request.urlopen(url, timeout=30).read()
        expected = entry.get("sha256")
        if expected and hashlib.sha256(data).hexdigest().lower() != expected.lower():
            raise ValueError(f"constraint sha256 mismatch: {url}")
        path = temporary_dir / f"constraint-{index}.txt"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


def install_node(
    item: tuple[str, dict],
    custom_dir: Path,
    log_dir: Path,
    *,
    dry_run: bool,
) -> int:
    _node_id, node = item
    destination = custom_dir / local_name(node)
    pip_config = node.get("pip", {})
    log_path = log_dir / f"{local_name(node)}.log"

    if pip_config.get("enabled", True) is False:
        return 0

    with tempfile.TemporaryDirectory(prefix="custom-node-") as temporary, log_path.open("a") as log:
        temporary_dir = Path(temporary)
        requirements_config = pip_config.get("requirements", {})
        requirement_files = requirements_config.get("files", ["requirements.txt"])
        removals = {
            normalize_name(name) for name in requirements_config.get("remove", [])
        }
        additions = requirements_config.get("add", [])
        effective_lines: list[str] = []

        for relative_path in requirement_files:
            path = destination / relative_path
            if path.is_file():
                for line in path.read_text(errors="replace").splitlines():
                    if requirement_name(line) not in removals:
                        effective_lines.append(line)
        effective_lines.extend(additions)

        if effective_lines:
            effective_requirements = temporary_dir / "requirements.txt"
            effective_requirements.write_text("\n".join(effective_lines) + "\n")

            command = [
                os.environ.get("PIP_BIN", os.environ.get("PIP", "pip")),
                "install",
                "--verbose",
            ]
            command.extend(
                str(value)
                for value in pip_config.get(
                    "options", ["--upgrade-strategy", "only-if-needed"]
                )
            )

            constraint_mode = pip_config.get("constraint_mode", "inherit")
            environment = os.environ.copy()
            if constraint_mode in ("replace", "none"):
                environment.pop("PIP_CONSTRAINT", None)
                environment.pop("PIP_BUILD_CONSTRAINT", None)

            if constraint_mode != "none":
                for constraint in materialize_constraints(node, temporary_dir):
                    command.extend(["-c", constraint])

            if dry_run:
                command.append("--dry-run")
            command.extend(["-r", str(effective_requirements)])

            rc = run_command(command, cwd=destination, env=environment, log=log)
            if rc:
                return rc

        if not dry_run and (destination / "install.py").is_file():
            rc = run_command(
                [
                    os.environ.get("PY_BIN", os.environ.get("PY", "python")),
                    "-u",
                    "install.py",
                ],
                cwd=destination,
                log=log,
            )
            if rc:
                return rc
    return 0


def install(args, manifest: dict) -> int:
    requested_sets = args.sets or os.environ.get("CUSTOM_NODE_SETS", "")
    nodes = resolve_nodes(manifest, requested_sets)
    custom_dir = Path(
        args.custom_dir
        or os.environ.get(
            "CUSTOM_DIR",
            os.environ.get("COMFY_HOME", "/workspace/ComfyUI") + "/custom_nodes",
        )
    )
    log_dir = Path(
        os.environ.get(
            "CUSTOM_LOG_DIR",
            os.environ.get("COMFY_LOGS", "/workspace/logs") + "/custom_nodes",
        )
    )
    custom_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    print("Selected custom nodes:")
    for node_id, node in nodes:
        print(f"  {node_id}: {node['remote']} -> {local_name(node)}")
    if args.plan:
        return 0

    clone_jobs = max(1, int(os.environ.get("MAX_CUSTOM_NODE_JOBS", "8")))
    failures: list[str] = []

    # Network-bound git work is bounded and parallel.
    with concurrent.futures.ThreadPoolExecutor(max_workers=clone_jobs) as executor:
        for node_id, rc in executor.map(
            lambda item: clone_node(item, custom_dir, log_dir), nodes
        ):
            if rc:
                failures.append(node_id)
    if failures:
        print("Clone failures: " + ", ".join(failures), file=sys.stderr)
        return 1

    # Environment mutation is intentionally serialized.
    for item in nodes:
        rc = install_node(item, custom_dir, log_dir, dry_run=args.dry_run)
        if rc:
            failures.append(item[0])

    if failures:
        print("Install failures: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def add_node(args, manifest: dict, manifest_path: Path | None) -> int:
    if manifest_path is None:
        raise ValueError("add requires a local manifest path")

    node: dict = {
        "remote": args.remote,
        "local": args.local
        or Path(args.remote.rstrip("/")).name.removesuffix(".git"),
    }
    if args.clone_option:
        node["clone_options"] = args.clone_option

    pip_config: dict = {}
    requirements: dict = {}
    if args.pip_option:
        pip_config["options"] = args.pip_option
    if args.remove_requirement:
        requirements["remove"] = args.remove_requirement
    if args.add_requirement:
        requirements["add"] = args.add_requirement
    if requirements:
        pip_config["requirements"] = requirements
    if pip_config:
        node["pip"] = pip_config

    manifest["nodes"][args.id] = node
    manifest["sets"].setdefault(args.set, [])
    if args.id not in manifest["sets"][args.set]:
        manifest["sets"][args.set].append(args.id)

    validate_manifest(manifest)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", default=os.environ.get("CUSTOM_NODES_MANIFEST_URL", "")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate")

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--sets", default="")

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--sets", default="")
    install_parser.add_argument("--custom-dir")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--plan", action="store_true")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--set", default="default")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--remote", required=True)
    add_parser.add_argument("--local")
    add_parser.add_argument("--clone-option", action="append", default=[])
    add_parser.add_argument("--pip-option", action="append", default=[])
    add_parser.add_argument("--remove-requirement", action="append", default=[])
    add_parser.add_argument("--add-requirement", action="append", default=[])

    args = parser.parse_args()
    if not args.manifest:
        raise ValueError("manifest source is required")

    manifest, manifest_path = load_manifest(args.manifest)
    validate_manifest(manifest)

    if args.command == "validate":
        return 0
    if args.command == "plan":
        requested_sets = args.sets or os.environ.get("CUSTOM_NODE_SETS", "")
        for node_id, node in resolve_nodes(manifest, requested_sets):
            print(f"{node_id}\t{local_name(node)}\t{node['remote']}")
        return 0
    if args.command == "install":
        return install(args, manifest)
    if args.command == "add":
        return add_node(args, manifest, manifest_path)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"custom_nodes: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
