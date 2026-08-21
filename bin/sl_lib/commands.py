from __future__ import annotations

import os
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Sequence

from .common import DIRECTIVE_RE, SlError, _command_dirs


class CommandSpec:
    def __init__(self, path: Path, text: str, directives: Dict[str, List[str]]) -> None:
        self.path = path
        self.text = text
        self.directives = directives
        self.name = self._one("name") or path.stem
        self.description = self._one("description") or ""
        self.setup_version = self._one("setup-version") or "1"
        self.inputs = self._indices("input")
        self.outputs = self._indices("output")
        overlap = set(self.inputs) & set(self.outputs)
        if overlap:
            raise SlError(f"command {self.name}: arguments cannot be both input and output: {sorted(overlap)}")
        if "sl_run" not in text:
            raise SlError(f"command {self.name}: command file must define sl_run()")

    def _one(self, key: str) -> str | None:
        values = self.directives.get(key, [])
        if not values:
            return None
        if len(values) > 1:
            raise SlError(f"command {self.path}: duplicate sl:{key} directive")
        return values[0]

    def _indices(self, key: str) -> List[int]:
        result: List[int] = []
        for value in self.directives.get(key, []):
            try:
                n = int(value)
            except ValueError as exc:
                raise SlError(f"command {self.path}: sl:{key} expects a positive argument index") from exc
            if n < 1:
                raise SlError(f"command {self.path}: sl:{key} expects a positive argument index")
            if n in result:
                raise SlError(f"command {self.path}: duplicate sl:{key} {n}")
            result.append(n)
        return sorted(result)


def _parse_command(path: Path) -> CommandSpec:
    text = path.read_text(encoding="utf-8")
    directives: Dict[str, List[str]] = {}
    for line in text.splitlines():
        match = DIRECTIVE_RE.match(line)
        if not match:
            continue
        key = match.group(1).lower()
        value = (match.group(2) or "").strip()
        directives.setdefault(key, []).append(value)
    return CommandSpec(path, text, directives)


def _find_command(name: str, cfg: dict | None = None) -> CommandSpec:
    candidates = [name]
    if not name.endswith(".cmd"):
        candidates.append(name + ".cmd")
    for directory in _command_dirs(cfg):
        for candidate in candidates:
            path = directory / candidate
            if path.is_file():
                return _parse_command(path)
    raise SlError(f"command not found: {name}; searched: {', '.join(str(p) for p in _command_dirs(cfg))}")


def _validate_output_arg(value: str) -> str:
    raw = value.rstrip("/")
    if not raw:
        raise SlError("output argument cannot be empty")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SlError(f"output arguments must be safe relative paths: {value}")
    return str(path)


def _shell_array(values: Iterable[str]) -> str:
    return " ".join(shlex.quote(v) for v in values)


def _build_run_script(
    *,
    job_id: str,
    spec: CommandSpec,
    arg_values: Dict[int, str],
    extra_args: Sequence[str],
    remote_root: str,
    runtime_repo: str,
    runtime_ref: str,
) -> str:
    job_dir = f"{remote_root}/jobs/{job_id}"
    cache_dir = f"{remote_root}/cache"
    runtime_dir = f"{remote_root}/runtime/pod-runtime"
    command_cache = f"{cache_dir}/commands/{spec.name}"
    arg_lines = [f"export SL_ARG_{idx}={shlex.quote(value)}" for idx, value in sorted(arg_values.items())]
    extras = _shell_array(extra_args)
    return f"""#!/usr/bin/env bash
set -uo pipefail

export SL_JOB_ID={shlex.quote(job_id)}
export SL_JOB_DIR={shlex.quote(job_dir)}
export SL_INPUT_DIR="$SL_JOB_DIR/input"
export SL_OUTPUT_DIR="$SL_JOB_DIR/output"
export SL_WORK_DIR="$SL_JOB_DIR/work"
export SL_CACHE_DIR={shlex.quote(cache_dir)}
export SL_REMOTE_ROOT={shlex.quote(remote_root)}
export SL_RUNTIME_DIR={shlex.quote(runtime_dir)}
export SL_COMMAND_NAME={shlex.quote(spec.name)}
export SL_COMMAND_CACHE={shlex.quote(command_cache)}
export SL_COMMAND_FILE="$SL_JOB_DIR/command.cmd"
export SL_LOG_FILE="$SL_JOB_DIR/job.log"
export SL_STATUS_FILE="$SL_JOB_DIR/status.json"
{os.linesep.join(arg_lines)}
SL_EXTRA_ARGS=({extras})
export POD_RUNTIME_DIR="$SL_RUNTIME_DIR"
export PYTHONUNBUFFERED=1

_sl_now() {{ date -Is; }}
_sl_log() {{ printf '%s [sl] %s\n' "$(_sl_now)" "$*"; }}
_sl_status() {{
  local state="$1" code="${{2:-}}" started completed
  started="$(cat "$SL_JOB_DIR/started_at" 2>/dev/null || true)"
  completed=""
  if [[ "$state" == "SUCCEEDED" || "$state" == "FAILED" || "$state" == "COMPLETE" ]]; then
    completed="$(_sl_now)"
  fi
  SL_STATE="$state" SL_CODE="$code" SL_STARTED="$started" SL_COMPLETED="$completed" \
    python3 - "$SL_STATUS_FILE" <<'PY_STATUS'
import json, os, pathlib, sys
p = pathlib.Path(sys.argv[1])
data = {{
    "state": os.environ["SL_STATE"],
    "exit_code": int(os.environ["SL_CODE"]) if os.environ.get("SL_CODE") not in (None, "") else None,
    "started_at": os.environ.get("SL_STARTED") or None,
    "completed_at": os.environ.get("SL_COMPLETED") or None,
}}
tmp = p.with_suffix(".tmp")
tmp.write_text(json.dumps(data, indent=2) + "\\n")
tmp.replace(p)
PY_STATUS
}}

_sl_status PREPARING
_sl_log "job $SL_JOB_ID preparing command $SL_COMMAND_NAME"

# Reconstruct the normal pod environment first. The controller token, when
# supplied, is deliberately applied after these files so they cannot clobber it.
for env_file in /etc/rp_environment /root/.secrets/env.current; do
  if [[ -f "$env_file" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "$env_file"
    set -u
  fi
done
if [[ -n "${{SL_CONTROLLER_HF_TOKEN:-}}" ]]; then
  export HF_TOKEN="$SL_CONTROLLER_HF_TOKEN"
  export HUGGINGFACE_HUB_TOKEN="$HF_TOKEN"
  unset SL_CONTROLLER_HF_TOKEN
fi

mkdir -p "$(dirname "$SL_RUNTIME_DIR")" "$SL_CACHE_DIR" "$SL_COMMAND_CACHE" "$SL_WORK_DIR"
if [[ -d "$SL_RUNTIME_DIR/.git" ]]; then
  _sl_log "updating pod-runtime ($SL_RUNTIME_DIR)"
  git -C "$SL_RUNTIME_DIR" fetch --quiet origin {shlex.quote(runtime_ref)} || true
else
  _sl_log "cloning pod-runtime"
  rm -rf "$SL_RUNTIME_DIR"
  git clone --quiet {shlex.quote(runtime_repo)} "$SL_RUNTIME_DIR"
fi
if [[ -d "$SL_RUNTIME_DIR/.git" ]]; then
  git -C "$SL_RUNTIME_DIR" checkout --quiet {shlex.quote(runtime_ref)}
  git -C "$SL_RUNTIME_DIR" reset --hard --quiet "origin/{runtime_ref}" 2>/dev/null || true
fi
if [[ ! -f "$SL_RUNTIME_DIR/helpers.sh" ]]; then
  _sl_log "ERROR: pod-runtime/helpers.sh unavailable"
  _sl_status FAILED 127
  exit 127
fi
export repo_root="$SL_RUNTIME_DIR"
# Load the full pod-runtime entrypoint so command jobs receive the same helper
# stack/accelerators as an interactive pod session.
# shellcheck disable=SC1090
source "$SL_RUNTIME_DIR/helpers.sh"
_sl_log "pod-runtime helper stack loaded: $SL_RUNTIME_DIR"

# shellcheck disable=SC1090
source "$SL_COMMAND_FILE"

_sl_status PREPARING
if declare -F sl_prepare >/dev/null 2>&1; then
  _sl_log "preparing command runtime"
  sl_prepare
  rc=$?
  if [[ $rc -ne 0 ]]; then
    _sl_log "ERROR: sl_prepare failed with exit $rc"
    _sl_status FAILED "$rc"
    exit "$rc"
  fi
fi

setup_version={shlex.quote(spec.setup_version)}
setup_marker="$SL_COMMAND_CACHE/setup.version"
if declare -F sl_setup >/dev/null 2>&1; then
  current="$(cat "$setup_marker" 2>/dev/null || true)"
  if [[ "$current" != "$setup_version" ]]; then
    _sl_log "cold setup for $SL_COMMAND_NAME (version $setup_version)"
    sl_setup
    rc=$?
    if [[ $rc -ne 0 ]]; then
      _sl_log "ERROR: sl_setup failed with exit $rc"
      _sl_status FAILED "$rc"
      exit "$rc"
    fi
    printf '%s\n' "$setup_version" > "$setup_marker"
  else
    _sl_log "warm setup cache hit for $SL_COMMAND_NAME (version $setup_version)"
  fi
fi

_sl_status RUNNING
_sl_log "running command"
sl_run
rc=$?
if [[ $rc -eq 0 ]]; then
  _sl_log "command completed successfully"
  _sl_status SUCCEEDED 0
else
  _sl_log "command failed with exit $rc"
  _sl_status FAILED "$rc"
fi
exit "$rc"
"""


def _manifest_for_job(
    *,
    job_id: str,
    spec: CommandSpec,
    operands: Sequence[str],
    extra_args: Sequence[str],
    output_dir: Path,
    remote_root: str,
    arg_values: Dict[int, str],
) -> dict:
    outputs = []
    for idx in spec.outputs:
        requested = _validate_output_arg(operands[idx - 1])
        outputs.append({
            "arg": idx,
            "requested": requested,
            "remote": arg_values[idx],
        })
    return {
        "job_id": job_id,
        "command": spec.name,
        "command_file": spec.path.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "operands": list(operands),
        "extra_args": list(extra_args),
        "inputs": [
            {"arg": idx, "local": str(Path(operands[idx - 1]).expanduser().resolve()), "remote": arg_values[idx]}
            for idx in spec.inputs
        ],
        "outputs": outputs,
        "local_output_dir": str(output_dir.expanduser().resolve()),
        "remote_job_dir": f"{remote_root}/jobs/{job_id}",
    }


def _build_arg_values(spec: CommandSpec, operands: Sequence[str], remote_root: str, job_id: str) -> Dict[int, str]:
    required = max(spec.inputs + spec.outputs + [0])
    if len(operands) < required:
        raise SlError(f"command {spec.name} requires at least {required} positional arguments")
    job_dir = f"{remote_root}/jobs/{job_id}"
    values: Dict[int, str] = {}
    for idx, raw in enumerate(operands, 1):
        if idx in spec.inputs:
            local = Path(raw).expanduser()
            if not (local.exists() or local.is_symlink()):
                raise SlError(f"input argument {idx} not found: {raw}")
            base = local.name or local.resolve().name
            values[idx] = f"{job_dir}/input/arg{idx}/{base}"
        elif idx in spec.outputs:
            requested = _validate_output_arg(raw)
            values[idx] = f"{job_dir}/output/{requested}"
        else:
            values[idx] = raw
    return values
