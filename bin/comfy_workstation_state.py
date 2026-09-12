#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MODEL_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
WORKFLOW_SUFFIX = ".json"
OUTPUT_SKIP_NAMES = {".gitkeep"}
SCHEMA_VERSION = 1


class WorkstationStateError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_root() -> Path:
    env = os.environ.get("POD_RUNTIME_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def default_comfy_root() -> Path:
    return Path(os.environ.get("COMFYUI_ROOT", "/workspace/ComfyUI")).expanduser()


def default_state_dir() -> Path:
    return Path(os.environ.get("COMFY_WORKSTATION_STATE_DIR", "/workspace/.pod-state/comfy")).expanduser()


def default_custom_node_manifest() -> Path:
    return Path(os.environ.get("CUSTOM_NODES_MANIFEST", str(runtime_root() / "custom_nodes_manifest.json"))).expanduser()


def normalize_abs(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except OSError:
        return str(path.expanduser().absolute())


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": relpath(path, root),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "atime_ns": st.st_atime_ns,
    }


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkstationStateError(f"cannot read JSON {path}: {exc}") from exc


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


def workflow_candidates(comfy_root: Path) -> list[Path]:
    roots = [comfy_root / "user", comfy_root / "workflows"]
    found: set[Path] = set()
    for base in roots:
        if not base.is_dir():
            continue
        for path in base.rglob(f"*{WORKFLOW_SUFFIX}"):
            if not path.is_file():
                continue
            if base.name == "user":
                parts = {part.casefold() for part in path.relative_to(base).parts[:-1]}
                if "workflow" not in parts and "workflows" not in parts:
                    continue
            found.add(path)
    return sorted(found)


def model_files(comfy_root: Path) -> list[Path]:
    models_root = comfy_root / "models"
    if not models_root.is_dir():
        return []
    return sorted(
        path
        for path in models_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in MODEL_SUFFIXES
    )


def build_model_indexes(comfy_root: Path, models: list[Path]) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    by_basename: dict[str, list[Path]] = {}
    by_models_rel: dict[str, list[Path]] = {}
    models_root = comfy_root / "models"
    for path in models:
        by_basename.setdefault(path.name.casefold(), []).append(path)
        try:
            model_rel = path.relative_to(models_root).as_posix().casefold()
        except ValueError:
            continue
        by_models_rel.setdefault(model_rel, []).append(path)
    return by_basename, by_models_rel


def plausible_model_ref(value: str) -> bool:
    cleaned = value.strip().replace("\\", "/")
    if not cleaned:
        return False
    return Path(cleaned).suffix.casefold() in MODEL_SUFFIXES


def resolve_model_ref(
    raw: str,
    by_basename: dict[str, list[Path]],
    by_models_rel: dict[str, list[Path]],
) -> tuple[str, list[Path]]:
    cleaned = raw.strip().replace("\\", "/").lstrip("./")
    lowered = cleaned.casefold()
    while lowered.startswith("models/"):
        cleaned = cleaned[len("models/"):]
        lowered = cleaned.casefold()
    exact = by_models_rel.get(lowered, [])
    if exact:
        return "resolved" if len(exact) == 1 else "ambiguous", exact
    matches = by_basename.get(Path(cleaned).name.casefold(), [])
    if not matches:
        return "missing", []
    return "resolved" if len(matches) == 1 else "ambiguous", matches


def scan_workflows(comfy_root: Path, models: list[Path]) -> tuple[list[dict[str, Any]], dict[Path, set[str]]]:
    by_basename, by_models_rel = build_model_indexes(comfy_root, models)
    refs_by_model: dict[Path, set[str]] = {path: set() for path in models}
    workflows: list[dict[str, Any]] = []

    for path in workflow_candidates(comfy_root):
        record = file_record(path, comfy_root)
        record["model_references"] = []
        try:
            data = read_json(path)
        except WorkstationStateError as exc:
            record["error"] = str(exc)
            workflows.append(record)
            continue

        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for value in walk_strings(data):
            if not plausible_model_ref(value):
                continue
            status, matches = resolve_model_ref(value, by_basename, by_models_rel)
            rel_matches = tuple(relpath(match, comfy_root) for match in matches)
            key = (value, status, rel_matches)
            if key in seen:
                continue
            seen.add(key)
            record["model_references"].append(
                {"value": value, "status": status, "matches": list(rel_matches)}
            )
            for match in matches:
                refs_by_model.setdefault(match, set()).add(record["path"])
        workflows.append(record)

    return workflows, refs_by_model


def load_events(events_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not events_path.is_file():
        return [], []
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [], [f"cannot read event journal: {exc}"]
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"events.jsonl:{lineno}: {exc}")
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            errors.append(f"events.jsonl:{lineno}: event is not an object")
    return events, errors


def event_provenance(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") not in {"asset_acquired", "asset_adopted"}:
            continue
        destination = str(event.get("destination") or "").strip()
        if not destination:
            continue
        source = str(event.get("source") or "unknown").strip() or "unknown"
        provenance = {
            k: v
            for k, v in event.items()
            if k not in {"schema_version", "time", "event", "destination"}
        }
        provenance["type"] = source
        latest[normalize_abs(Path(destination))] = provenance
    return latest


def scan_assets(
    comfy_root: Path,
    models: list[Path],
    refs_by_model: dict[Path, set[str]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    provenance_by_path = event_provenance(events)
    assets: list[dict[str, Any]] = []
    for path in models:
        record = file_record(path, comfy_root)
        provenance = provenance_by_path.get(normalize_abs(path), {"type": "unknown"})
        reconstructable = provenance.get("type") in {"huggingface", "civitai", "owned"}
        references = sorted(refs_by_model.get(path, set()))
        record.update(
            {
                "kind": "model",
                "state": "reconstructable" if reconstructable else "transient",
                "provenance": provenance,
                "references": {"workflows": references},
                "activity": {"referenced": bool(references)},
            }
        )
        assets.append(record)
    return assets


def git_output(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return (proc.stdout or "").strip()


def load_custom_node_policy(path: Path) -> tuple[dict[str, dict[str, Any]], set[str], list[str]]:
    if not path.is_file():
        return {}, set(), [f"custom-node manifest not found: {path}"]
    try:
        data = read_json(path)
    except WorkstationStateError as exc:
        return {}, set(), [str(exc)]
    if not isinstance(data, dict):
        return {}, set(), [f"custom-node manifest is not an object: {path}"]
    nodes_raw = data.get("nodes")
    sets_raw = data.get("sets")
    nodes = (
        {str(k): v for k, v in nodes_raw.items() if isinstance(v, dict)}
        if isinstance(nodes_raw, dict)
        else {}
    )
    default_set = (
        set(map(str, sets_raw.get("default", [])))
        if isinstance(sets_raw, dict) and isinstance(sets_raw.get("default"), list)
        else set()
    )
    return nodes, default_set, []


def canonical_remote(value: str) -> str:
    return value.strip().rstrip("/").removesuffix(".git").casefold()


def scan_custom_nodes(comfy_root: Path, manifest_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    nodes_policy, default_set, warnings = load_custom_node_policy(manifest_path)
    by_local: dict[str, tuple[str, dict[str, Any]]] = {}
    by_remote: dict[str, tuple[str, dict[str, Any]]] = {}
    for node_id, cfg in nodes_policy.items():
        local = str(cfg.get("local") or "").strip()
        remote = str(cfg.get("remote") or "").strip()
        if local:
            by_local[local.casefold()] = (node_id, cfg)
        if remote:
            by_remote[canonical_remote(remote)] = (node_id, cfg)

    custom_root = comfy_root / "custom_nodes"
    if not custom_root.is_dir():
        return [], warnings
    result: list[dict[str, Any]] = []
    for path in sorted(p for p in custom_root.iterdir() if p.is_dir() and p.name != "__pycache__"):
        if (path / ".git").exists():
            remote = git_output(path, "remote", "get-url", "origin")
            commit = git_output(path, "rev-parse", "HEAD")
            branch = git_output(path, "branch", "--show-current") or None
            status = git_output(path, "status", "--porcelain=v1", "--untracked-files=all")
            match = by_remote.get(canonical_remote(remote)) if remote else None
            if match is None:
                match = by_local.get(path.name.casefold())
            node_id = match[0] if match else None
            baseline = bool(node_id and node_id in default_set)
            result.append(
                {
                    "path": relpath(path, comfy_root),
                    "local": path.name,
                    "node_id": node_id,
                    "state": "baseline" if baseline else "transient",
                    "repo": {
                        "remote": remote or None,
                        "commit": commit or None,
                        "branch": branch,
                        "dirty": bool(status),
                        "status": status.splitlines() if status else [],
                    },
                }
            )
        else:
            match = by_local.get(path.name.casefold())
            node_id = match[0] if match else None
            result.append(
                {
                    "path": relpath(path, comfy_root),
                    "local": path.name,
                    "node_id": node_id,
                    "state": "baseline-unmanaged" if node_id and node_id in default_set else "untracked",
                    "repo": None,
                }
            )
    return result, warnings


def scan_outputs(comfy_root: Path) -> dict[str, Any]:
    output_root = comfy_root / "output"
    files: list[dict[str, Any]] = []
    if output_root.is_dir():
        for path in sorted(
            p for p in output_root.rglob("*") if p.is_file() and p.name not in OUTPUT_SKIP_NAMES
        ):
            files.append(file_record(path, comfy_root))
    total = sum(int(item["size"]) for item in files)
    mtimes = [int(item["mtime_ns"]) for item in files]
    return {
        "files": files,
        "count": len(files),
        "bytes": total,
        "oldest_mtime_ns": min(mtimes) if mtimes else None,
        "newest_mtime_ns": max(mtimes) if mtimes else None,
    }


def summarize(
    assets: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    custom_nodes: list[dict[str, Any]],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    reconstructable = [asset for asset in assets if asset.get("state") == "reconstructable"]
    transient = [asset for asset in assets if asset.get("state") == "transient"]
    referenced = [asset for asset in assets if asset.get("activity", {}).get("referenced")]
    missing_refs = 0
    ambiguous_refs = 0
    for workflow in workflows:
        for ref in workflow.get("model_references", []):
            if ref.get("status") == "missing":
                missing_refs += 1
            elif ref.get("status") == "ambiguous":
                ambiguous_refs += 1
    dirty_nodes = [
        node
        for node in custom_nodes
        if isinstance(node.get("repo"), dict) and node["repo"].get("dirty")
    ]
    transient_nodes = [node for node in custom_nodes if node.get("state") == "transient"]
    return {
        "models": {
            "count": len(assets),
            "bytes": sum(int(asset.get("size") or 0) for asset in assets),
            "reconstructable_count": len(reconstructable),
            "reconstructable_bytes": sum(int(asset.get("size") or 0) for asset in reconstructable),
            "transient_count": len(transient),
            "transient_bytes": sum(int(asset.get("size") or 0) for asset in transient),
            "referenced_count": len(referenced),
        },
        "workflows": {
            "count": len(workflows),
            "missing_model_references": missing_refs,
            "ambiguous_model_references": ambiguous_refs,
        },
        "custom_nodes": {
            "count": len(custom_nodes),
            "baseline_count": sum(
                1 for node in custom_nodes if str(node.get("state", "")).startswith("baseline")
            ),
            "transient_count": len(transient_nodes),
            "dirty_count": len(dirty_nodes),
            "untracked_count": sum(1 for node in custom_nodes if node.get("state") == "untracked"),
        },
        "outputs": {
            "count": int(outputs.get("count") or 0),
            "bytes": int(outputs.get("bytes") or 0),
        },
    }


def scan(comfy_root: Path, state_dir: Path, custom_node_manifest: Path) -> dict[str, Any]:
    comfy_root = comfy_root.expanduser().resolve(strict=False)
    state_dir = state_dir.expanduser().resolve(strict=False)
    if not comfy_root.is_dir():
        raise WorkstationStateError(f"ComfyUI root does not exist: {comfy_root}")
    events, event_errors = load_events(state_dir / "events.jsonl")
    models = model_files(comfy_root)
    workflows, refs_by_model = scan_workflows(comfy_root, models)
    assets = scan_assets(comfy_root, models, refs_by_model, events)
    custom_nodes, custom_warnings = scan_custom_nodes(comfy_root, custom_node_manifest)
    outputs = scan_outputs(comfy_root)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": utc_now(),
        "comfy_root": str(comfy_root),
        "assets": assets,
        "workflows": workflows,
        "custom_nodes": custom_nodes,
        "outputs": outputs,
        "warnings": [*event_errors, *custom_warnings],
    }
    payload["summary"] = summarize(assets, workflows, custom_nodes, outputs)
    return payload


def write_manifest(payload: dict[str, Any], state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "workstation.json"
    tmp = state_dir / ".workstation.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def human_bytes(value: int) -> str:
    amount = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def print_status(payload: dict[str, Any]) -> None:
    summary = payload.get("summary", {})
    models = summary.get("models", {})
    workflows = summary.get("workflows", {})
    nodes = summary.get("custom_nodes", {})
    outputs = summary.get("outputs", {})
    print("ComfyUI workstation state")
    print(f"  root: {payload.get('comfy_root', '?')}")
    print(f"  scanned: {payload.get('created_utc', '?')}")
    print()
    print("Models")
    print(f"  {models.get('count', 0)} files / {human_bytes(int(models.get('bytes', 0)))}")
    print(
        f"  reconstructable: {models.get('reconstructable_count', 0)} / "
        f"{human_bytes(int(models.get('reconstructable_bytes', 0)))}"
    )
    print(
        f"  transient:       {models.get('transient_count', 0)} / "
        f"{human_bytes(int(models.get('transient_bytes', 0)))}"
    )
    print(f"  referenced:      {models.get('referenced_count', 0)}")
    print()
    print("Workflows")
    print(f"  {workflows.get('count', 0)} workflow files")
    print(f"  missing model refs:   {workflows.get('missing_model_references', 0)}")
    print(f"  ambiguous model refs: {workflows.get('ambiguous_model_references', 0)}")
    print()
    print("Custom nodes")
    print(f"  {nodes.get('count', 0)} checkouts")
    print(f"  baseline:  {nodes.get('baseline_count', 0)}")
    print(f"  transient: {nodes.get('transient_count', 0)}")
    print(f"  dirty:     {nodes.get('dirty_count', 0)}")
    print(f"  untracked: {nodes.get('untracked_count', 0)}")
    print()
    print("Outputs")
    print(f"  {outputs.get('count', 0)} files / {human_bytes(int(outputs.get('bytes', 0)))}")
    warnings = payload.get("warnings", [])
    if warnings:
        print()
        print("Warnings")
        for item in warnings:
            print(f"  - {item}")


def load_manifest(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise WorkstationStateError(f"workstation manifest is not an object: {path}")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfy-state",
        description="Portable ComfyUI workstation inventory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--root", type=Path, default=default_comfy_root())
        command_parser.add_argument("--state-dir", type=Path, default=default_state_dir())
        command_parser.add_argument(
            "--custom-node-manifest",
            type=Path,
            default=default_custom_node_manifest(),
        )

    scan_parser = sub.add_parser("scan", help="reconcile the current ComfyUI tree")
    common(scan_parser)
    scan_parser.add_argument("--no-write", action="store_true", help="scan without writing workstation.json")
    scan_parser.add_argument("--json", action="store_true", help="print full JSON inventory")

    status_parser = sub.add_parser("status", help="show the last generated workstation inventory")
    common(status_parser)
    status_parser.add_argument("--json", action="store_true", help="print full JSON inventory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            payload = scan(args.root, args.state_dir, args.custom_node_manifest)
            if not args.no_write:
                path = write_manifest(payload, args.state_dir)
                if not args.json:
                    print(f"[comfy-state] wrote {path}")
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print_status(payload)
            return 0
        if args.command == "status":
            payload = load_manifest(args.state_dir / "workstation.json")
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print_status(payload)
            return 0
        raise WorkstationStateError(f"unknown command: {args.command}")
    except WorkstationStateError as exc:
        print(f"[comfy-state] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
