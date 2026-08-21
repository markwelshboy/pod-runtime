from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Dict

from .commands import _build_arg_values, _build_run_script, _find_command, _manifest_for_job, _parse_command
from .common import SlError, _cleanup_policy, _command_dirs, _job_id, _local_job_dir, _read_json, _remote_job_dir, _remote_root, _runtime_ref, _runtime_repo, _sl_config, _ssh, _ssh_argv, _state_dir, _write_json, info, warn
from .remote import _clean_remote_job, _fetch_outputs, _follow_remote_log, _load_manifest, _local_status, _prepare_remote_job, _remote_status, _stage_inputs, _launch_job, _sync_metadata


def _finalize_sync_job(job_id: str, cfg: dict, *, output_dir: Path | None, no_fetch: bool, keep_remote: bool) -> int:
    _sync_metadata(job_id, cfg)
    status = _remote_status(job_id, cfg, allow_missing=True) or _local_status(job_id, cfg) or {}
    state = str(status.get("state") or "UNKNOWN")
    exit_code = status.get("exit_code")
    manifest = _load_manifest(job_id, cfg)
    has_outputs = bool(manifest.get("outputs"))
    fetched = False
    if state == "SUCCEEDED" and not no_fetch:
        info("job succeeded; fetching outputs")
        _fetch_outputs(job_id, cfg, output_dir)
        fetched = True
        remote_status_path = _remote_job_dir(job_id, cfg) + "/status.json"
        # COMPLETE means execution succeeded and output retrieval succeeded.
        _ssh(f"python3 - {shlex.quote(remote_status_path)} <<'PY_COMPLETE'\nimport json, pathlib, sys\np=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['state']='COMPLETE'; p.write_text(json.dumps(d, indent=2)+'\\n')\nPY_COMPLETE\n")
        _sync_metadata(job_id, cfg)
        state = "COMPLETE"
    policy = _cleanup_policy(cfg)
    successful_cleanup_ok = state in {"SUCCEEDED", "COMPLETE"} and (fetched or not has_outputs)
    if not keep_remote and ((policy == "always") or (policy == "successful" and successful_cleanup_ok)):
        _clean_remote_job(job_id, cfg)
    if state in {"SUCCEEDED", "COMPLETE"}:
        info(f"job {job_id}: {state}")
        return 0
    info(f"job {job_id}: {state} (exit {exit_code})")
    return int(exit_code) if isinstance(exit_code, int) and exit_code != 0 else 1


def _run_job(args: argparse.Namespace) -> int:
    cfg = _sl_config()
    _ssh_argv()
    spec = _find_command(args.command, cfg)
    operands = list(args.operands)
    job_id = _job_id()
    remote_root = _remote_root(cfg)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else Path(".")
    arg_values = _build_arg_values(spec, operands, remote_root, job_id)
    manifest = _manifest_for_job(
        job_id=job_id,
        spec=spec,
        operands=operands,
        extra_args=args.extra,
        output_dir=output_dir,
        remote_root=remote_root,
        arg_values=arg_values,
    )
    local_dir = _local_job_dir(job_id, cfg)
    local_dir.mkdir(parents=True, exist_ok=True)
    _write_json(local_dir / "manifest.json", manifest)
    _write_json(local_dir / "status.json", {"state": "CREATED", "exit_code": None})

    run_script = _build_run_script(
        job_id=job_id,
        spec=spec,
        arg_values=arg_values,
        extra_args=args.extra,
        remote_root=remote_root,
        runtime_repo=_runtime_repo(cfg),
        runtime_ref=_runtime_ref(cfg),
    )
    info(f"job: {job_id}")
    info(f"command: {spec.name}")
    _prepare_remote_job(job_id, spec, manifest, run_script, cfg)
    try:
        _stage_inputs(job_id, spec, operands, cfg)
        pid = _launch_job(job_id, cfg)
    except Exception:
        _sync_metadata(job_id, cfg)
        raise
    info(f"remote pid: {pid}")
    if args.detach:
        info(f"submitted: {job_id}")
        info(f"follow with: sl tail {job_id}")
        _sync_metadata(job_id, cfg)
        return 0

    _follow_remote_log(job_id, cfg, lines="+1", follow=True)
    return _finalize_sync_job(
        job_id,
        cfg,
        output_dir=output_dir,
        no_fetch=args.no_fetch,
        keep_remote=args.keep_remote,
    )


def _jobs(cfg: dict) -> int:
    root = _remote_root(cfg)
    script = f"""python3 - {shlex.quote(root + '/jobs')} <<'PY_JOBS'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
if root.is_dir():
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir(): continue
        try: m=json.loads((d/'manifest.json').read_text())
        except Exception: m={{}}
        try: s=json.loads((d/'status.json').read_text())
        except Exception: s={{}}
        print(json.dumps({{"job_id":d.name,"command":m.get("command","?"),"state":s.get("state","?"),"exit_code":s.get("exit_code")}}))
PY_JOBS
"""
    result = _ssh(script, capture=True, check=False)
    rows: Dict[str, dict] = {}
    if result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("job_id"):
                rows[str(row["job_id"])] = row
    state_dir = _state_dir(cfg)
    if state_dir.is_dir():
        for d in state_dir.iterdir():
            if not d.is_dir() or d.name in rows:
                continue
            m = _read_json(d / "manifest.json", default={})
            s = _read_json(d / "status.json", default={})
            if isinstance(m, dict) and isinstance(s, dict):
                rows[d.name] = {"job_id": d.name, "command": m.get("command", "?"), "state": s.get("state", "?"), "exit_code": s.get("exit_code")}
    print(f"{'JOB':<25} {'COMMAND':<18} {'STATE':<11} EXIT")
    for job_id in sorted(rows, reverse=True):
        row = rows[job_id]
        code = "-" if row.get("exit_code") is None else str(row.get("exit_code"))
        print(f"{job_id:<25} {str(row.get('command','?')):<18} {str(row.get('state','?')):<11} {code}")
    return 0


def _status(job_id: str, cfg: dict) -> int:
    remote = _remote_status(job_id, cfg, allow_missing=True)
    if remote is not None:
        _sync_metadata(job_id, cfg)
        status = remote
    else:
        status = _local_status(job_id, cfg)
    if status is None:
        raise SlError(f"job not found: {job_id}")
    manifest = _load_manifest(job_id, cfg)
    print(f"job:       {job_id}")
    print(f"command:   {manifest.get('command', '?')}")
    print(f"state:     {status.get('state', '?')}")
    print(f"exit:      {status.get('exit_code') if status.get('exit_code') is not None else '-'}")
    print(f"created:   {manifest.get('created_at', '-')}")
    print(f"output:    {manifest.get('local_output_dir', '-')}")
    return 0


def _logs(job_id: str, cfg: dict, *, follow: bool) -> int:
    job_id = _validate_job_id(job_id)
    if follow:
        rc = _follow_remote_log(job_id, cfg, lines="+1", follow=True)
        _sync_metadata(job_id, cfg)
        return rc
    remote_log = _remote_job_dir(job_id, cfg) + "/job.log"
    result = _ssh(f"cat {shlex.quote(remote_log)}\n", capture=True, check=False)
    if result.returncode == 0:
        sys.stdout.write(result.stdout or "")
        _sync_metadata(job_id, cfg)
        return 0
    local = _local_job_dir(job_id, cfg) / "job.log"
    if local.is_file():
        sys.stdout.write(local.read_text(encoding="utf-8", errors="replace"))
        return 0
    raise SlError(f"log unavailable for job {job_id}")


def _tail(job_id: str, cfg: dict, *, lines: int, follow: bool) -> int:
    job_id = _validate_job_id(job_id)
    rc = _follow_remote_log(job_id, cfg, lines=str(lines), follow=follow)
    if rc == 0:
        _sync_metadata(job_id, cfg)
        return 0
    local = _local_job_dir(job_id, cfg) / "job.log"
    if local.is_file() and not follow:
        text = local.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(text[-lines:]))
        return 0
    return rc


def _commands(cfg: dict) -> int:
    found: Dict[str, CommandSpec] = {}
    for directory in _command_dirs(cfg):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.cmd")):
            try:
                spec = _parse_command(path)
            except SlError as exc:
                warn(str(exc))
                continue
            found.setdefault(spec.name, spec)
    print(f"{'COMMAND':<18} {'INPUTS':<10} {'OUTPUTS':<10} DESCRIPTION")
    for name in sorted(found):
        spec = found[name]
        inputs = ",".join(map(str, spec.inputs)) or "-"
        outputs = ",".join(map(str, spec.outputs)) or "-"
        print(f"{name:<18} {inputs:<10} {outputs:<10} {spec.description}")
    return 0


def _command_show(name: str, cfg: dict) -> int:
    spec = _find_command(name, cfg)
    print(f"name:          {spec.name}")
    print(f"file:          {spec.path}")
    print(f"description:   {spec.description or '-'}")
    print(f"inputs:        {', '.join(map(str, spec.inputs)) or '-'}")
    print(f"outputs:       {', '.join(map(str, spec.outputs)) or '-'}")
    print(f"setup version: {spec.setup_version}")
    print("\n--- command ---")
    print(spec.text, end="" if spec.text.endswith("\n") else "\n")
    return 0
