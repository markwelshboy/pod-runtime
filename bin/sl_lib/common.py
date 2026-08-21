from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_ROOT = "/workspace/.sl"
DEFAULT_COMMAND_DIR = REPO_ROOT / "commands" / "sl"
SL_CONFIG_PATH = Path(os.environ.get("SL_CONFIG", "~/.config/sl/config.json")).expanduser()
VCP_CONFIG_PATH = Path(os.environ.get("VCP_CONFIG", "~/.config/vcp/config.json")).expanduser()
DEFAULT_STATE_DIR = Path(os.environ.get("SL_STATE_DIR", "~/.local/state/sl/jobs")).expanduser()
DEFAULT_RUNTIME_REPO = "https://github.com/markwelshboy/pod-runtime.git"
DEFAULT_RUNTIME_REF = "main"
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "COMPLETE"}
ACTIVE_STATES = {"CREATED", "STAGING", "PREPARING", "RUNNING", "FETCHING"}
DIRECTIVE_RE = re.compile(r"^\s*#\s*sl:([a-zA-Z0-9_-]+)(?:\s+(.*?))?\s*$")
JOB_ID_RE = re.compile(r"^[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$")


class SlError(RuntimeError):
    pass


def info(msg: str) -> None:
    print(f"[sl] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[sl] WARNING: {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    print(f"[sl] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _read_json(path: Path, *, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SlError(f"could not read {path}: {exc}") from exc


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _sl_config() -> dict:
    value = _read_json(SL_CONFIG_PATH, default={})
    if not isinstance(value, dict):
        raise SlError(f"invalid config {SL_CONFIG_PATH}: expected JSON object")
    return value


def _write_sl_config(cfg: dict) -> None:
    _write_json(SL_CONFIG_PATH, cfg)


def _vcp_config() -> dict:
    value = _read_json(VCP_CONFIG_PATH, default={})
    if not isinstance(value, dict):
        raise SlError(f"invalid vcp config {VCP_CONFIG_PATH}: expected JSON object")
    return value


def _ssh_argv() -> List[str]:
    value = _vcp_config().get("ssh")
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise SlError("vcp SSH remote is not configured; run: vcp config ssh [ssh options] user@host")
    return list(value)


def _remote_root(cfg: dict | None = None) -> str:
    cfg = _sl_config() if cfg is None else cfg
    value = os.environ.get("SL_REMOTE_ROOT") or cfg.get("remote_root") or DEFAULT_REMOTE_ROOT
    if not isinstance(value, str) or not value.startswith("/") or value == "/":
        raise SlError("SL remote root must be an absolute non-root path")
    return value.rstrip("/")


def _state_dir(cfg: dict | None = None) -> Path:
    cfg = _sl_config() if cfg is None else cfg
    raw = os.environ.get("SL_STATE_DIR") or cfg.get("state_dir")
    return Path(raw).expanduser() if raw else DEFAULT_STATE_DIR


def _command_dirs(cfg: dict | None = None) -> List[Path]:
    cfg = _sl_config() if cfg is None else cfg
    raw = cfg.get("command_dir")
    dirs: List[Path] = []
    if isinstance(raw, str) and raw:
        dirs.append(Path(raw).expanduser())
    dirs.append(DEFAULT_COMMAND_DIR)
    seen = set()
    result: List[Path] = []
    for path in dirs:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _cleanup_policy(cfg: dict | None = None) -> str:
    cfg = _sl_config() if cfg is None else cfg
    value = cfg.get("cleanup", "successful")
    if value not in {"never", "successful", "always"}:
        raise SlError(f"invalid cleanup policy: {value}")
    return value


def _runtime_repo(cfg: dict | None = None) -> str:
    cfg = _sl_config() if cfg is None else cfg
    return str(cfg.get("runtime_repo") or DEFAULT_RUNTIME_REPO)


def _runtime_ref(cfg: dict | None = None) -> str:
    cfg = _sl_config() if cfg is None else cfg
    return str(cfg.get("runtime_ref") or DEFAULT_RUNTIME_REF)


def _vcp_path() -> Path:
    override = os.environ.get("SL_VCP")
    path = Path(override).expanduser() if override else REPO_ROOT / "vcp"
    if not path.exists():
        raise SlError(f"vcp launcher not found: {path}")
    return path


def _run(cmd: Sequence[str], *, check: bool = True, capture: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        check=check,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _ssh(script: str, *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ssh", *_ssh_argv(), "bash", "-s"]
    return _run(cmd, check=check, capture=capture, input_text=script)


def _vcp(args: Sequence[str]) -> None:
    _run([str(_vcp_path()), *args])


def _job_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise SlError(f"invalid job id: {job_id}")
    return job_id


def _remote_job_dir(job_id: str, cfg: dict | None = None) -> str:
    return f"{_remote_root(cfg)}/jobs/{_validate_job_id(job_id)}"


def _local_job_dir(job_id: str, cfg: dict | None = None) -> Path:
    return _state_dir(cfg) / _validate_job_id(job_id)
