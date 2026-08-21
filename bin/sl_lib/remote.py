from __future__ import annotations

import base64
import json
import os
import re
import shlex
import sys
from pathlib import Path, PurePosixPath
from typing import Sequence

from .commands import CommandSpec
from .common import ACTIVE_STATES, SlError, _cleanup_policy, _local_job_dir, _read_json, _remote_job_dir, _ssh, _vcp, info


def _prepare_remote_job(job_id: str, spec: CommandSpec, manifest: dict, run_script: str, cfg: dict) -> None:
    job_dir = _remote_job_dir(job_id, cfg)
    encoded_command = base64.b64encode(spec.text.encode()).decode()
    encoded_manifest = base64.b64encode((json.dumps(manifest, indent=2) + "\n").encode()).decode()
    encoded_runner = base64.b64encode(run_script.encode()).decode()
    initial_status = base64.b64encode((json.dumps({"state": "CREATED", "exit_code": None}, indent=2) + "\n").encode()).decode()
    output_parents = []
    for item in manifest.get("outputs", []):
        if isinstance(item, dict) and item.get("remote"):
            output_parents.append(str(PurePosixPath(str(item["remote"])).parent))
    mkdir_outputs = "\n".join(f"mkdir -p {shlex.quote(path)}" for path in output_parents)
    script = f"""set -euo pipefail
job={shlex.quote(job_dir)}
mkdir -p "$job/input" "$job/output" "$job/work"
{mkdir_outputs}
printf '%s' {shlex.quote(encoded_command)} | base64 -d > "$job/command.cmd"
printf '%s' {shlex.quote(encoded_manifest)} | base64 -d > "$job/manifest.json"
printf '%s' {shlex.quote(encoded_runner)} | base64 -d > "$job/run.sh"
printf '%s' {shlex.quote(initial_status)} | base64 -d > "$job/status.json"
: > "$job/job.log"
chmod 700 "$job/run.sh"
"""
    _ssh(script)


def _stage_inputs(job_id: str, spec: CommandSpec, operands: Sequence[str], cfg: dict) -> None:
    job_dir = _remote_job_dir(job_id, cfg)
    if not spec.inputs:
        return
    _ssh(f"set -euo pipefail\nprintf '%s\\n' '{{\"state\": \"STAGING\", \"exit_code\": null}}' > {shlex.quote(job_dir + '/status.json')}\n")
    for idx in spec.inputs:
        local = str(Path(operands[idx - 1]).expanduser().resolve())
        remote_parent = f"{job_dir}/input/arg{idx}"
        _ssh(f"mkdir -p {shlex.quote(remote_parent)}\n")
        info(f"staging input arg{idx}: {local}")
        _vcp([local, f"r:{remote_parent}/"])


def _launch_job(job_id: str, cfg: dict) -> int:
    job_dir = _remote_job_dir(job_id, cfg)
    token = os.environ.get("HF_TOKEN", "")
    token_assignment = f"SL_CONTROLLER_HF_TOKEN={shlex.quote(token)} " if token else ""
    script = f"""set -euo pipefail
job={shlex.quote(job_dir)}
started="$(date -Is)"
printf '%s\\n' "$started" > "$job/started_at"
if command -v setsid >/dev/null 2>&1; then
  {token_assignment}nohup setsid bash "$job/run.sh" >> "$job/job.log" 2>&1 < /dev/null &
else
  {token_assignment}nohup bash "$job/run.sh" >> "$job/job.log" 2>&1 < /dev/null &
fi
pid=$!
printf '%s\\n' "$pid" > "$job/pid"
printf '%s\\n' "$pid"
"""
    result = _ssh(script, capture=True)
    try:
        return int((result.stdout or "").strip().splitlines()[-1])
    except Exception as exc:
        raise SlError(f"could not determine remote job pid from: {result.stdout!r}") from exc


def _remote_status(job_id: str, cfg: dict, *, allow_missing: bool = False) -> dict | None:
    path = _remote_job_dir(job_id, cfg) + "/status.json"
    result = _ssh(f"cat {shlex.quote(path)}\n", capture=True, check=False)
    if result.returncode != 0:
        if allow_missing:
            return None
        raise SlError(f"remote job not found: {job_id}")
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SlError(f"invalid remote status for {job_id}") from exc
    return value if isinstance(value, dict) else None


def _local_status(job_id: str, cfg: dict) -> dict | None:
    path = _local_job_dir(job_id, cfg) / "status.json"
    value = _read_json(path, default=None)
    return value if isinstance(value, dict) else None


def _sync_metadata(job_id: str, cfg: dict) -> None:
    job_dir = _remote_job_dir(job_id, cfg)
    names = ["manifest.json", "status.json", "job.log", "command.cmd", "run.sh"]
    py_names = repr(names)
    script = f"""python3 - {shlex.quote(job_dir)} <<'PY_META'
import base64, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
names = {py_names}
out = {{}}
for name in names:
    p = root / name
    if p.is_file():
        out[name] = base64.b64encode(p.read_bytes()).decode()
print(json.dumps(out))
PY_META
"""
    result = _ssh(script, capture=True, check=False)
    if result.returncode != 0:
        return
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    local = _local_job_dir(job_id, cfg)
    local.mkdir(parents=True, exist_ok=True)
    for name, encoded in payload.items():
        if name not in names or not isinstance(encoded, str):
            continue
        try:
            (local / name).write_bytes(base64.b64decode(encoded))
        except Exception:
            continue


def _follow_remote_log(job_id: str, cfg: dict, *, lines: str, follow: bool) -> int:
    job_dir = _remote_job_dir(job_id, cfg)
    log = f"{job_dir}/job.log"
    pidfile = f"{job_dir}/pid"
    if not follow:
        cmd = f"tail -n {shlex.quote(lines)} {shlex.quote(log)}\n" if lines != "+1" else f"cat {shlex.quote(log)}\n"
        return _ssh(cmd, check=False).returncode
    if lines == "+1":
        tail_arg = "-n +1"
    else:
        if not re.fullmatch(r"[0-9]+", lines):
            raise SlError("tail line count must be numeric")
        tail_arg = f"-n {lines}"
    script = f"""set -euo pipefail
log={shlex.quote(log)}
pidfile={shlex.quote(pidfile)}
status_file={shlex.quote(job_dir + '/status.json')}
state="$(python3 - "$status_file" <<'PY_STATE' 2>/dev/null || true
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("state", ""))
except Exception:
    pass
PY_STATE
)"
if [[ "$state" != "SUCCEEDED" && "$state" != "FAILED" && "$state" != "COMPLETE" ]] \
   && [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
  exec tail {tail_arg} --pid="$(cat "$pidfile")" -F "$log"
else
  exec tail {tail_arg} "$log"
fi
"""
    return _ssh(script, check=False).returncode


def _load_manifest(job_id: str, cfg: dict) -> dict:
    local_path = _local_job_dir(job_id, cfg) / "manifest.json"
    local = _read_json(local_path, default=None)
    if isinstance(local, dict):
        return local
    remote = _remote_job_dir(job_id, cfg) + "/manifest.json"
    result = _ssh(f"cat {shlex.quote(remote)}\n", capture=True, check=False)
    if result.returncode != 0:
        raise SlError(f"manifest unavailable for job {job_id}")
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SlError(f"invalid manifest for job {job_id}") from exc
    if not isinstance(value, dict):
        raise SlError(f"invalid manifest for job {job_id}")
    return value


def _fetch_outputs(job_id: str, cfg: dict, output_dir: Path | None = None) -> None:
    manifest = _load_manifest(job_id, cfg)
    status = _remote_status(job_id, cfg, allow_missing=True) or _local_status(job_id, cfg)
    if status and status.get("state") in ACTIVE_STATES:
        raise SlError(f"job {job_id} is still {status.get('state')}")
    outputs = manifest.get("outputs", [])
    if not isinstance(outputs, list):
        raise SlError(f"invalid outputs in manifest for {job_id}")
    dest_root = output_dir or Path(str(manifest.get("local_output_dir") or "."))
    dest_root = dest_root.expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    for item in outputs:
        if not isinstance(item, dict):
            continue
        requested = str(item.get("requested") or "")
        remote = str(item.get("remote") or "")
        if not requested or not remote:
            continue
        rel = PurePosixPath(requested)
        local_parent = dest_root.joinpath(*rel.parts[:-1])
        local_parent.mkdir(parents=True, exist_ok=True)
        exists = _ssh(f"test -e {shlex.quote(remote)} -o -L {shlex.quote(remote)}\n", check=False)
        if exists.returncode != 0:
            raise SlError(f"expected output missing on remote: {remote}")
        info(f"fetching output: {requested}")
        _vcp([f"r:{remote}", str(local_parent) + "/"])
    _sync_metadata(job_id, cfg)


def _clean_remote_job(job_id: str, cfg: dict) -> None:
    status = _remote_status(job_id, cfg, allow_missing=True)
    if status and status.get("state") in ACTIVE_STATES:
        raise SlError(f"refusing to clean running job {job_id} ({status.get('state')})")
    job_dir = _remote_job_dir(job_id, cfg)
    script = f"rm -rf {shlex.quote(job_dir + '/input')} {shlex.quote(job_dir + '/output')} {shlex.quote(job_dir + '/work')}\n"
    _ssh(script)
    info(f"cleaned heavy workspace for {job_id}; logs and metadata retained")


def _purge_job(job_id: str, cfg: dict, *, force: bool = False) -> None:
    status = _remote_status(job_id, cfg, allow_missing=True)
    active = bool(status and status.get("state") in ACTIVE_STATES)
    if active and not force:
        raise SlError(f"refusing to purge running job {job_id}; use --force")
    job_dir = _remote_job_dir(job_id, cfg)
    if active and force:
        kill_script = f"""set +e
pidfile={shlex.quote(job_dir + '/pid')}
if [[ -f "$pidfile" ]]; then
  pid="$(cat "$pidfile")"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
fi
"""
        _ssh(kill_script, check=False)
    _ssh(f"rm -rf {shlex.quote(job_dir)}\n", check=False)
    local = _local_job_dir(job_id, cfg)
    if local.exists():
        import shutil
        shutil.rmtree(local)
    info(f"purged job {job_id}")
