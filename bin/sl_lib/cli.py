from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import List, Sequence

from .common import SL_CONFIG_PATH, VCP_CONFIG_PATH, SlError, _cleanup_policy, _command_dirs, _remote_job_dir, _remote_root, _runtime_ref, _runtime_repo, _sl_config, _ssh, _ssh_argv, _state_dir, _validate_job_id, _write_sl_config
from .jobs import _command_show, _commands, _finalize_sync_job, _jobs, _logs, _run_job, _status, _tail
from .remote import _clean_remote_job, _fetch_outputs, _local_status, _purge_job, _remote_status, _sync_metadata


def _config_command(argv: Sequence[str]) -> int:
    cfg = _sl_config()
    if not argv or argv[0] in {"show", "list"}:
        print(f"config:        {SL_CONFIG_PATH}")
        print(f"transport:     vcp ({VCP_CONFIG_PATH})")
        try:
            ssh = _ssh_argv()
            print(f"ssh:           {shlex.join(ssh)}")
        except SlError:
            print("ssh:           <not configured>")
        print(f"remote root:   {_remote_root(cfg)}")
        print(f"command dir:   {_command_dirs(cfg)[0]}")
        print(f"state dir:     {_state_dir(cfg)}")
        print(f"cleanup:       {_cleanup_policy(cfg)}")
        print(f"runtime repo:  {_runtime_repo(cfg)}")
        print(f"runtime ref:   {_runtime_ref(cfg)}")
        return 0
    action = argv[0]
    if action == "remote-root":
        if len(argv) != 2 or not argv[1].startswith("/") or argv[1] == "/":
            raise SlError("usage: sl config remote-root /absolute/path")
        cfg["remote_root"] = argv[1].rstrip("/")
    elif action == "command-dir":
        if len(argv) != 2:
            raise SlError("usage: sl config command-dir PATH")
        cfg["command_dir"] = str(Path(argv[1]).expanduser())
    elif action == "state-dir":
        if len(argv) != 2:
            raise SlError("usage: sl config state-dir PATH")
        cfg["state_dir"] = str(Path(argv[1]).expanduser())
    elif action == "cleanup":
        if len(argv) != 2 or argv[1] not in {"never", "successful", "always"}:
            raise SlError("usage: sl config cleanup never|successful|always")
        cfg["cleanup"] = argv[1]
    elif action == "runtime-repo":
        if len(argv) != 2:
            raise SlError("usage: sl config runtime-repo URL")
        cfg["runtime_repo"] = argv[1]
    elif action == "runtime-ref":
        if len(argv) != 2:
            raise SlError("usage: sl config runtime-ref REF")
        cfg["runtime_ref"] = argv[1]
    elif action == "clear":
        if SL_CONFIG_PATH.exists():
            SL_CONFIG_PATH.unlink()
        print(f"removed config: {SL_CONFIG_PATH}")
        return 0
    else:
        raise SlError(f"unknown config command: {action}")
    _write_sl_config(cfg)
    return _config_command(["show"])


def _usage() -> str:
    return """sl — durable GPU jobs on the vcp-configured pod

Usage:
  sl run [--detach] [--output-dir DIR] [--no-fetch] [--keep-remote] COMMAND <operands...> [-- <command args...>]
  sl --command COMMAND <operands...> [-- <command args...>]
  sl jobs
  sl status JOB
  sl logs [-f] JOB
  sl tail [-n N] [--no-follow] JOB
  sl fetch [--output-dir DIR] JOB
  sl clean JOB
  sl purge [--force] JOB
  sl commands
  sl command show COMMAND
  sl config [show|...]

Transport/SSH are inherited from vcp. Successful synchronous jobs fetch declared
outputs automatically and, by default, clean heavy remote workspace while keeping
logs, manifest, status, command definition and runner metadata.
"""


def _split_run_argv(argv: Sequence[str]) -> tuple[List[str], List[str]]:
    argv = list(argv)
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    return argv, []


def _parse_run(argv: Sequence[str], *, command_alias: str | None = None) -> argparse.Namespace:
    front, extra = _split_run_argv(argv)
    parser = argparse.ArgumentParser(prog="sl run", add_help=True)
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--keep-remote", action="store_true")
    if command_alias is None:
        parser.add_argument("command")
    parser.add_argument("operands", nargs="*")
    ns = parser.parse_args(front)
    if command_alias is not None:
        ns.command = command_alias
    ns.extra = extra
    return ns


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"help", "-h", "--help"}:
        print(_usage())
        return 0
    cfg = _sl_config()
    if argv[0] == "run":
        return _run_job(_parse_run(argv[1:]))
    if argv[0] == "--command":
        if len(argv) < 2:
            raise SlError("usage: sl --command COMMAND <operands...> [-- <command args...>]")
        return _run_job(_parse_run(argv[2:], command_alias=argv[1]))
    if argv[0] == "jobs":
        return _jobs(cfg)
    if argv[0] == "status" and len(argv) == 2:
        return _status(_validate_job_id(argv[1]), cfg)
    if argv[0] == "logs":
        parser = argparse.ArgumentParser(prog="sl logs")
        parser.add_argument("-f", "--follow", action="store_true")
        parser.add_argument("job")
        ns = parser.parse_args(argv[1:])
        return _logs(ns.job, cfg, follow=ns.follow)
    if argv[0] == "tail":
        parser = argparse.ArgumentParser(prog="sl tail")
        parser.add_argument("-n", type=int, default=100)
        parser.add_argument("--no-follow", action="store_true")
        parser.add_argument("job")
        ns = parser.parse_args(argv[1:])
        return _tail(ns.job, cfg, lines=ns.n, follow=not ns.no_follow)
    if argv[0] == "fetch":
        parser = argparse.ArgumentParser(prog="sl fetch")
        parser.add_argument("--output-dir")
        parser.add_argument("job")
        ns = parser.parse_args(argv[1:])
        _fetch_outputs(_validate_job_id(ns.job), cfg, Path(ns.output_dir).expanduser() if ns.output_dir else None)
        status = _remote_status(ns.job, cfg, allow_missing=True)
        if status and status.get("state") == "SUCCEEDED":
            remote_status_path = _remote_job_dir(ns.job, cfg) + "/status.json"
            _ssh(f"python3 - {shlex.quote(remote_status_path)} <<'PY_COMPLETE'\nimport json, pathlib, sys\np=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['state']='COMPLETE'; p.write_text(json.dumps(d, indent=2)+'\\n')\nPY_COMPLETE\n")
        _sync_metadata(ns.job, cfg)
        current = _remote_status(ns.job, cfg, allow_missing=True) or _local_status(ns.job, cfg) or {}
        policy = _cleanup_policy(cfg)
        if policy == "always" or (policy == "successful" and current.get("state") == "COMPLETE"):
            _clean_remote_job(ns.job, cfg)
        return 0
    if argv[0] == "clean" and len(argv) == 2:
        _clean_remote_job(_validate_job_id(argv[1]), cfg)
        _sync_metadata(argv[1], cfg)
        return 0
    if argv[0] == "purge":
        parser = argparse.ArgumentParser(prog="sl purge")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("job")
        ns = parser.parse_args(argv[1:])
        _purge_job(_validate_job_id(ns.job), cfg, force=ns.force)
        return 0
    if argv[0] == "commands":
        return _commands(cfg)
    if argv[0:2] == ["command", "show"] and len(argv) == 3:
        return _command_show(argv[2], cfg)
    if argv[0] == "config":
        return _config_command(argv[1:])
    raise SlError(f"unknown command; run 'sl --help': {shlex.join(argv)}")
