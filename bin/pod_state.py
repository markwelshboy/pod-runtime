#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None


class PodStateError(RuntimeError):
    pass


def info(message: str) -> None:
    print(f"[pod-state] {message}")


def warn(message: str) -> None:
    print(f"[pod-state] WARN: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> NoReturn:
    print(f"[pod-state] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_root() -> Path:
    env = os.environ.get("POD_RUNTIME_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def template_dir() -> Path:
    env = os.environ.get("POD_SNAPSHOT_TEMPLATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return runtime_root() / "snapshot-templates"


def resolve_template(name_or_path: str) -> Path:
    candidate = Path(name_or_path).expanduser()
    if candidate.exists():
        return candidate.resolve()

    base = template_dir()
    for suffix in (".yaml", ".yml"):
        path = base / f"{name_or_path}{suffix}"
        if path.exists():
            return path.resolve()
    raise PodStateError(f"template not found: {name_or_path} (looked in {base})")


def load_template(name_or_path: str) -> dict[str, Any]:
    path = resolve_template(name_or_path)
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text)
    else:
        # JSON is valid YAML 1.2. Keeping the built-in templates in the JSON
        # subset means configure-pod works on a bare Python install while still
        # allowing conventional YAML whenever PyYAML is available.
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PodStateError(
                "PyYAML is not installed and this template is not JSON-compatible YAML: "
                f"{path}. Install PyYAML or use the JSON subset of YAML."
            ) from exc
    if not isinstance(raw, dict):
        raise PodStateError(f"template must contain a YAML mapping: {path}")
    validate_template(raw, path)
    raw["_template_path"] = str(path)
    return raw


def validate_template(template: dict[str, Any], path: Path | None = None) -> None:
    where = f" ({path})" if path else ""
    if template.get("version") != 1:
        raise PodStateError(f"template version must be 1{where}")
    if not isinstance(template.get("name"), str) or not template["name"].strip():
        raise PodStateError(f"template name is required{where}")
    if not isinstance(template.get("workspace"), str) or not template["workspace"].startswith("/workspace"):
        raise PodStateError(f"workspace must be /workspace or beneath it{where}")
    repos = template.get("repos")
    if not isinstance(repos, list) or not repos:
        raise PodStateError(f"at least one repo is required{where}")
    seen: set[str] = set()
    for repo in repos:
        if not isinstance(repo, dict):
            raise PodStateError(f"repo entries must be mappings{where}")
        name = repo.get("name")
        url = repo.get("url")
        repo_path = repo.get("path")
        if not isinstance(name, str) or not name:
            raise PodStateError(f"repo name is required{where}")
        if name in seen:
            raise PodStateError(f"duplicate repo name: {name}{where}")
        seen.add(name)
        if not isinstance(url, str) or not url:
            raise PodStateError(f"repo {name}: url is required{where}")
        if not isinstance(repo_path, str) or not repo_path.startswith("/workspace/"):
            raise PodStateError(f"repo {name}: path must be beneath /workspace{where}")
        scripts = repo.get("configure", {}).get("scripts", [])
        if not isinstance(scripts, list) or not all(isinstance(s, str) and s for s in scripts):
            raise PodStateError(f"repo {name}: configure.scripts must be a list of paths{where}")
    snapshot = template.get("snapshot", {})
    if not isinstance(snapshot, dict):
        raise PodStateError(f"snapshot must be a mapping{where}")
    paths = snapshot.get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) and p.startswith("/workspace/") for p in paths):
        raise PodStateError(f"snapshot.paths must be beneath /workspace{where}")


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "text": True,
        "check": check,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(cmd, **kwargs)


def git(repo: Path, *args: str, capture: bool = True, check: bool = True) -> str:
    result = run(["git", *args], cwd=repo, capture=capture, check=check)
    return (result.stdout or "").strip()


def repo_state(repo_cfg: dict[str, Any]) -> dict[str, Any]:
    repo = Path(repo_cfg["path"])
    if not (repo / ".git").exists():
        raise PodStateError(f"repo is missing or is not a git checkout: {repo}")

    commit = git(repo, "rev-parse", "HEAD")
    branch_proc = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo, capture=True, check=False)
    branch = (branch_proc.stdout or "").strip() or None
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    dirty = bool(status)

    upstream_proc = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=repo,
        capture=True,
        check=False,
    )
    upstream = (upstream_proc.stdout or "").strip() or None
    ahead = behind = None
    if upstream:
        counts = git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        left, right = counts.split()
        behind = int(left)
        ahead = int(right)

    origin_proc = run(["git", "remote", "get-url", "origin"], cwd=repo, capture=True, check=False)
    origin = (origin_proc.stdout or "").strip() or repo_cfg["url"]

    return {
        "name": repo_cfg["name"],
        "path": str(repo),
        "url": origin,
        "branch": branch,
        "commit": commit,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "status": status.splitlines() if status else [],
    }


def snapshot_safety_issues(state: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if state["dirty"]:
        issues.append("working tree has uncommitted/untracked changes")
    if state["upstream"] is None:
        issues.append("branch has no upstream; commit recoverability cannot be verified")
    elif (state["ahead"] or 0) > 0:
        issues.append(f"branch is {state['ahead']} commit(s) ahead of {state['upstream']}")
    return issues


def hff_context() -> tuple[Path, Path, str, str]:
    home = Path.home()
    venv = Path(os.environ.get("HFF_VENV", str(home / ".venvs" / "hf-tools"))).expanduser()
    hff_py = Path(os.environ.get("HFF_PY", str(home / ".local" / "bin" / "hff.py"))).expanduser()
    if not hff_py.exists():
        fallback = runtime_root() / "bin" / "hff.py"
        if fallback.exists():
            hff_py = fallback
    python = venv / "bin" / "python"
    repo = os.environ.get("HFF_REPO") or os.environ.get("HF_MY_REPO_ID") or "markwelshboyx/diffusionetc"
    repo_type = os.environ.get("HFF_REPO_TYPE") or os.environ.get("HF_MY_REPO_TYPE") or "model"
    if not python.exists():
        raise PodStateError(f"HFF python is missing: {python}; run 'hff ensure' first")
    if not hff_py.exists():
        raise PodStateError(f"hff.py is missing: {hff_py}; run 'hff ensure' first")
    return python, hff_py, repo, repo_type


def run_hff(args: list[str], *, capture: bool = True) -> str:
    python, hff_py, repo, repo_type = hff_context()
    cmd = [str(python), str(hff_py), "--repo", repo, "--type", repo_type, *args]
    result = run(cmd, capture=capture)
    return (result.stdout or "").strip()


def snapshot_dir(template_name: str) -> str:
    base = os.environ.get("HFF_SNAPSHOT_DIR", "snapshot").strip("/") or "snapshot"
    return f"{base}/pods/{template_name}"


def latest_snapshot_id(template_name: str) -> str:
    output = run_hff(["snapshot", "--snapdir", snapshot_dir(template_name), "list"])
    ids = [line.strip() for line in output.splitlines() if line.strip()]
    if not ids:
        raise PodStateError(f"no snapshots found for template {template_name}")
    return ids[0]


def resolve_snapshot_id(template_name: str, requested: str) -> str:
    if requested == "latest":
        return latest_snapshot_id(template_name)
    return requested


def state_manifest_path(template_name: str) -> Path:
    return Path("/workspace/.pod-state") / template_name / "manifest.json"


def write_state_manifest(template: dict[str, Any], repo_states: list[dict[str, Any]], paths: list[str]) -> Path:
    path = state_manifest_path(template["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "template": template["name"],
        "created_utc": utc_now(),
        "repos": repo_states,
        "snapshot_paths": paths,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def find_staged_manifest(staging: Path, template_name: str) -> Path:
    rel = Path("workspace/.pod-state") / template_name / "manifest.json"
    path = staging / rel
    if not path.exists():
        raise PodStateError(f"snapshot is missing pod state manifest: {rel}")
    return path


def hydrate_staging(staging: Path) -> None:
    staged_workspace = staging / "workspace"
    if staged_workspace.exists():
        Path("/workspace").mkdir(parents=True, exist_ok=True)
        run(["rsync", "-a", f"{staged_workspace}/", "/workspace/"])


def ensure_repo(repo_cfg: dict[str, Any], recorded: dict[str, Any] | None, dry_run: bool = False) -> None:
    path = Path(repo_cfg["path"])
    url = repo_cfg["url"]
    if dry_run:
        target = recorded.get("commit") if recorded else "remote default branch"
        info(f"would configure repo {repo_cfg['name']}: {url} -> {path} @ {target}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        if path.exists() and any(path.iterdir()):
            raise PodStateError(f"cannot clone into non-empty path: {path}")
        info(f"cloning {url} -> {path}")
        run(["git", "clone", url, str(path)])
    else:
        info(f"using existing checkout: {path}")

    run(["git", "fetch", "--all", "--tags", "--prune"], cwd=path)

    if recorded:
        commit = recorded["commit"]
        branch = recorded.get("branch")
        info(f"restoring {repo_cfg['name']} to {commit[:12]}" + (f" on {branch}" if branch else " (detached)"))
        if branch:
            run(["git", "switch", "-C", branch, commit], cwd=path)
            upstream = recorded.get("upstream")
            if upstream:
                run(["git", "branch", "--set-upstream-to", upstream, branch], cwd=path, check=False)
        else:
            run(["git", "checkout", "--detach", commit], cwd=path)
    else:
        # A newly cloned repo is already on the remote default branch. For an
        # existing checkout, keep its current branch and only fast-forward it.
        run(["git", "pull", "--ff-only"], cwd=path)


def run_configure_scripts(repo_cfg: dict[str, Any], dry_run: bool = False) -> None:
    repo = Path(repo_cfg["path"])
    for script in repo_cfg.get("configure", {}).get("scripts", []):
        script_path = repo / script
        if dry_run:
            info(f"would run {repo_cfg['name']}: bash {script}")
            continue
        if not script_path.is_file():
            raise PodStateError(f"configure script not found in {repo_cfg['name']}: {script_path}")
        info(f"running {repo_cfg['name']}: bash {script}")
        run(["bash", script], cwd=repo)


def cmd_snapshot(args: argparse.Namespace) -> int:
    template = load_template(args.template)
    repo_states: list[dict[str, Any]] = []
    for repo_cfg in template["repos"]:
        repo_path = Path(repo_cfg["path"])
        if not (repo_path / ".git").exists():
            raise PodStateError(f"repo is missing or is not a git checkout: {repo_path}")
        info(f"refreshing git remote state: {repo_cfg['name']}")
        run(["git", "fetch", "--quiet", "--prune", "origin"], cwd=repo_path)
        repo_states.append(repo_state(repo_cfg))

    unsafe: list[tuple[str, str]] = []
    for state in repo_states:
        for issue in snapshot_safety_issues(state):
            unsafe.append((state["name"], issue))

    for state in repo_states:
        branch = state["branch"] or "DETACHED"
        sync = ""
        if state["upstream"]:
            sync = f" ahead={state['ahead']} behind={state['behind']}"
        info(f"repo {state['name']}: {branch} @ {state['commit'][:12]} dirty={state['dirty']}{sync}")

    if unsafe and not args.force:
        for repo_name, issue in unsafe:
            warn(f"{repo_name}: {issue}")
        raise PodStateError("snapshot refused because source state is not safely recoverable; commit/push first or use --force")

    declared_paths = list(template.get("snapshot", {}).get("paths", []))
    existing_paths: list[str] = []
    for raw in declared_paths:
        if Path(raw).exists():
            existing_paths.append(raw)
        else:
            warn(f"snapshot path does not exist; skipping: {raw}")

    manifest = state_manifest_path(template["name"])
    if args.dry_run:
        info(f"would write state manifest: {manifest}")
        for path in existing_paths:
            info(f"would snapshot: {path}")
        info(f"remote snapshot dir: {snapshot_dir(template['name'])}")
        return 0

    manifest = write_state_manifest(template, repo_states, declared_paths)
    items = [str(manifest), *existing_paths]
    snap_name = args.name or template["name"]
    info(f"creating HFF snapshot in {snapshot_dir(template['name'])}")
    with tempfile.TemporaryDirectory(prefix=f"snapshot-pod-{template['name']}-") as hff_tmp:
        sid = run_hff(
            [
                "snapshot", "--snapdir", snapshot_dir(template["name"]), "create",
                "--name", snap_name,
                "--tmp-dir", hff_tmp,
                *items,
            ]
        ).splitlines()[-1].strip()
    if not sid:
        raise PodStateError("hff snapshot create did not return a snapshot id")

    # Read it back so a successful command means the remote manifest is visible.
    shown = run_hff(["snapshot", "--snapdir", snapshot_dir(template["name"]), "show", sid])
    remote_meta = json.loads(shown)
    if remote_meta.get("id") != sid:
        raise PodStateError(f"snapshot verification failed for {sid}")

    info(f"snapshot: {sid}")
    if unsafe:
        warn("snapshot was forced with source-state safety issues; code may not be fully recoverable")
    else:
        info("snapshot verified; source commit(s) are recoverable from their upstreams")
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    template = load_template(args.template)
    Path(template["workspace"]).mkdir(parents=True, exist_ok=True) if not args.dry_run else None

    recorded_by_name: dict[str, dict[str, Any]] = {}
    staging_cm = None
    staging: Path | None = None
    sid: str | None = None

    try:
        if args.snapshot:
            sid = resolve_snapshot_id(template["name"], args.snapshot)
            info(f"snapshot: {sid}")
            if args.dry_run:
                info(f"would download snapshot {sid} from {snapshot_dir(template['name'])}")
            else:
                staging_cm = tempfile.TemporaryDirectory(prefix=f"configure-pod-{template['name']}-")
                staging = Path(staging_cm.name)
                run_hff(
                    [
                        "snapshot", "--snapdir", snapshot_dir(template["name"]), "get", sid,
                        "--extract-dir", str(staging),
                    ],
                    capture=False,
                )
                manifest_path = find_staged_manifest(staging, template["name"])
                state = json.loads(manifest_path.read_text(encoding="utf-8"))
                if state.get("template") != template["name"]:
                    raise PodStateError(
                        f"snapshot template mismatch: expected {template['name']}, got {state.get('template')}"
                    )
                recorded_by_name = {repo["name"]: repo for repo in state.get("repos", [])}

        for repo_cfg in template["repos"]:
            recorded = recorded_by_name.get(repo_cfg["name"]) if args.snapshot and not args.dry_run else None
            if args.snapshot and not args.dry_run and recorded is None:
                raise PodStateError(f"snapshot manifest has no state for repo {repo_cfg['name']}")
            ensure_repo(repo_cfg, recorded, dry_run=args.dry_run)

        if staging is not None:
            info("hydrating saved project data into /workspace")
            hydrate_staging(staging)
        elif args.snapshot and args.dry_run:
            info("would hydrate saved project data into /workspace")

        for repo_cfg in template["repos"]:
            run_configure_scripts(repo_cfg, dry_run=args.dry_run)

        if args.dry_run:
            info("dry run complete")
        elif sid:
            info(f"configured {template['name']} from snapshot {sid}")
        else:
            info(f"configured fresh {template['name']} environment")
        return 0
    finally:
        if staging_cm is not None:
            staging_cm.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pod-state")
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure")
    configure.add_argument("template", nargs="?", help="template name or YAML path")
    configure.add_argument("--template", dest="template_opt", default="", help="template name or YAML path")
    configure.add_argument("--snapshot", default="", help="snapshot id or 'latest'")
    configure.add_argument("--dry-run", action="store_true")
    configure.set_defaults(func=cmd_configure)

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("template", nargs="?", help="template name or YAML path")
    snapshot.add_argument("--template", dest="template_opt", default="", help="template name or YAML path")
    snapshot.add_argument("--name", default="", help="optional snapshot label")
    snapshot.add_argument("--force", action="store_true", help="allow dirty/unpushed source state")
    snapshot.add_argument("--dry-run", action="store_true")
    snapshot.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    positional = getattr(args, "template", None)
    option = getattr(args, "template_opt", "")
    if positional and option and positional != option:
        die("template specified twice with different values", 2)
    args.template = option or positional
    if not args.template:
        die("template is required (positional or --template)", 2)
    try:
        return int(args.func(args))
    except PodStateError as exc:
        die(str(exc))
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(str(part) for part in exc.cmd)
        die(f"command failed ({exc.returncode}): {rendered}", exc.returncode or 1)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
