#!/usr/bin/env python3
"""vcp - copy between this machine and one configured SSH remote via Hugging Face.

The command is intentionally controlled from the local machine. Remote paths are
written as r:/absolute/path; the remote never needs an SSH route back to local.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


DEFAULT_HF_REPO = "markwelshboyx/hf-scratchpad"
DEFAULT_HF_TYPE = "dataset"
CONFIG_PATH = Path(os.environ.get("VCP_CONFIG", "~/.config/vcp/config.json")).expanduser()
TIMING_PREFIX = "__VCP_TIMING__"
BYTES_PREFIX = "__VCP_BYTES__"


class VcpError(RuntimeError):
    pass


def info(msg: str) -> None:
    print(f"[vcp] {msg}", file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    print(f"[vcp] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


class StageTiming:
    def __init__(self, name: str, seconds: float, byte_count: int | None = None) -> None:
        self.name = name
        self.seconds = seconds
        self.byte_count = byte_count


class TransferStats:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.stages: List[StageTiming] = []
        self.logical_bytes: int | None = None

    def add(self, name: str, seconds: float, byte_count: int | None = None) -> None:
        self.stages.append(StageTiming(name, max(0.0, seconds), byte_count))
        if byte_count is not None and self.logical_bytes is None:
            self.logical_bytes = byte_count

    def set_logical_bytes(self, byte_count: int | None) -> None:
        if byte_count is not None and byte_count >= 0:
            self.logical_bytes = byte_count

    def print_summary(self) -> None:
        total = max(0.0, time.perf_counter() - self.started)
        info("Transfer summary:")
        for stage in self.stages:
            detail = f"{stage.seconds:7.2f}s"
            if stage.byte_count and stage.seconds > 0:
                rate = stage.byte_count / stage.seconds / 1_000_000
                detail += f"  {rate:7.1f} MB/s"
            info(f"  {stage.name:<24} {detail}")
        info(f"  {'Total':<24} {total:7.2f}s")
        if self.logical_bytes and total > 0:
            effective = self.logical_bytes / total / 1_000_000
            info(f"  {'Effective throughput':<24} {effective:7.1f} MB/s")


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VcpError(f"could not read config {CONFIG_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise VcpError(f"invalid config {CONFIG_PATH}: expected JSON object")
    return data


def _write_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def _hf_repo(cfg: dict) -> str:
    return os.environ.get("VCP_HF_REPO") or cfg.get("hf_repo") or DEFAULT_HF_REPO


def _hf_type(cfg: dict) -> str:
    return os.environ.get("VCP_HF_REPO_TYPE") or cfg.get("hf_repo_type") or DEFAULT_HF_TYPE


def _ssh_argv(cfg: dict) -> List[str]:
    value = cfg.get("ssh")
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise VcpError("SSH remote is not configured; run: vcp config ssh [ssh options] user@host")
    return list(value)


def _need_token() -> str:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise VcpError("HF_TOKEN is not set on the local machine")
    return token


def _is_remote(spec: str) -> bool:
    return spec.startswith("r:")


def _remote_path(spec: str) -> str:
    path = spec[2:]
    if not path.startswith("/"):
        raise VcpError(f"remote paths must be absolute: {spec}")
    if path == "/":
        raise VcpError("copying the remote filesystem root is not supported")
    return path


def _strip_source_slash(path: str) -> str:
    if path == "/":
        return path
    return path.rstrip("/") or "/"


def _basename(path: str) -> str:
    name = os.path.basename(_strip_source_slash(path))
    if not name or name in {".", ".."}:
        raise VcpError(f"could not determine source basename: {path}")
    return name


def _validate_unique_basenames(paths: Sequence[str]) -> List[str]:
    names = [_basename(p) for p in paths]
    seen = set()
    duplicates = set()
    for n in names:
        if n in seen:
            duplicates.add(n)
        seen.add(n)
    if duplicates:
        dup = ", ".join(sorted(duplicates))
        raise VcpError(f"multiple sources have the same basename ({dup}); copy them separately")
    return names


def _local_abs(path: str) -> str:
    return os.path.abspath(os.path.expanduser(_strip_source_slash(path)))


def _tar_create_command(archive: str, sources: Sequence[str]) -> List[str]:
    cmd = ["tar", "-cf", archive]
    for src in sources:
        src2 = _strip_source_slash(src)
        parent = os.path.dirname(src2) or "."
        base = os.path.basename(src2)
        cmd.extend(["-C", parent, f"./{base}"])
    return cmd


def _run(cmd: Sequence[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _parse_remote_markers(stdout: str, timing_sink: Dict[str, float] | None, byte_sink: Dict[str, int] | None) -> str:
    visible: List[str] = []
    for line in stdout.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped.startswith(TIMING_PREFIX + " "):
            parts = stripped.split()
            if len(parts) == 3 and timing_sink is not None:
                try:
                    timing_sink[parts[1]] = int(parts[2]) / 1_000_000_000
                except ValueError:
                    pass
            continue
        if stripped.startswith(BYTES_PREFIX + " "):
            parts = stripped.split()
            if len(parts) == 3 and byte_sink is not None:
                try:
                    byte_sink[parts[1]] = int(parts[2])
                except ValueError:
                    pass
            continue
        visible.append(line)
    return "".join(visible)


def _ssh(
    cfg: dict,
    script: str,
    *,
    capture: bool = False,
    timing_sink: Dict[str, float] | None = None,
    byte_sink: Dict[str, int] | None = None,
) -> subprocess.CompletedProcess:
    cmd = ["ssh", *_ssh_argv(cfg), "bash", "-s"]
    result = subprocess.run(
        cmd,
        input=script,
        text=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if capture else None,
    )
    cleaned_stdout = _parse_remote_markers(result.stdout or "", timing_sink, byte_sink)
    result.stdout = cleaned_stdout
    if not capture and cleaned_stdout:
        sys.stdout.write(cleaned_stdout)
        sys.stdout.flush()
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=cleaned_stdout,
            stderr=result.stderr,
        )
    return result


def _shell_array(values: Iterable[str]) -> str:
    return " ".join(shlex.quote(v) for v in values)


def _remote_timer_helpers() -> str:
    return f"""
_vcp_ns() {{ date +%s%N; }}
_vcp_timing() {{
  local _name=\"$1\" _start=\"$2\" _end
  _end=\"$(_vcp_ns)\"
  printf '{TIMING_PREFIX} %s %s\\n' \"$_name\" \"$((_end - _start))\"
}}
"""


def _remote_hff_bootstrap(repo: str, repo_type: str, token: str) -> str:
    # vcp is local-controller-only. Supply the controller credential only after
    # the pod's environment and helper files are loaded so they cannot clobber
    # it. The token travels in encrypted SSH stdin, never argv or a pod file.
    return f"""
source_if_exists() {{ if [[ -f \"$1\" ]]; then set +u; source \"$1\"; set -u; fi; }}
source_if_exists /etc/rp_environment
source_if_exists /root/.secrets/env.current

_vcp_runtime=\"\"
for _cand in \"${{POD_RUNTIME_DIR:-}}\" \"${{repo_root:-}}\" /workspace/pod-runtime /opt/pod-runtime /workspace/git/pod-runtime; do
  [[ -n \"$_cand\" && -f \"$_cand/helpers_shell.sh\" ]] || continue
  _vcp_runtime=\"$_cand\"
  break
done
if [[ -z \"$_vcp_runtime\" ]]; then
  _vcp_runtime=\"$(find /workspace /opt /root -maxdepth 4 -type f -name helpers_shell.sh -path '*/pod-runtime/*' -printf '%h\\n' 2>/dev/null | head -n1)\"
fi
[[ -n \"$_vcp_runtime\" && -f \"$_vcp_runtime/helpers_shell.sh\" ]] || {{
  echo '[vcp] ERROR: could not locate pod-runtime/helpers_shell.sh on remote' >&2
  exit 127
}}
export POD_RUNTIME_DIR=\"$_vcp_runtime\"
source \"$_vcp_runtime/helpers_shell.sh\"
export HF_TOKEN={shlex.quote(token)}
export HUGGINGFACE_HUB_TOKEN=\"$HF_TOKEN\"
export HFF_REPO={shlex.quote(repo)}
export HFF_REPO_TYPE={shlex.quote(repo_type)}
export HF_XET_HIGH_PERFORMANCE=1
"""


def _remote_pack_and_upload(
    cfg: dict,
    repo: str,
    repo_type: str,
    token: str,
    scratch_path: str,
    remote_sources: Sequence[str],
    transfer_id: str,
    timing_sink: Dict[str, float],
    byte_sink: Dict[str, int],
) -> None:
    _validate_unique_basenames(remote_sources)
    archive = f"/workspace/.vcp/{transfer_id}.tar"
    tar_parts: List[str] = []
    checks: List[str] = []
    for src in remote_sources:
        src2 = _strip_source_slash(src)
        parent = os.path.dirname(src2) or "/"
        base = os.path.basename(src2)
        msg = shlex.quote(f"[vcp] ERROR: remote source not found: {src2}")
        checks.append(f"[[ -e {shlex.quote(src2)} || -L {shlex.quote(src2)} ]] || {{ echo {msg} >&2; exit 1; }}")
        tar_parts.extend(["-C", parent, f"./{base}"])

    script = f"""set -euo pipefail
umask 077
{_remote_timer_helpers()}
mkdir -p /workspace/.vcp
archive={shlex.quote(archive)}
trap 'rm -f \"$archive\"' EXIT
{os.linesep.join(checks)}
echo '[vcp] Packing on remote...' >&2
_vcp_start=\"$(_vcp_ns)\"
tar -cf \"$archive\" {_shell_array(tar_parts)}
_vcp_timing remote_pack \"$_vcp_start\"
_vcp_bytes=\"$(stat -c %s \"$archive\")\"
printf '{BYTES_PREFIX} archive %s\\n' \"$_vcp_bytes\"
echo \"[vcp] Remote archive: $(du -h \"$archive\" | awk '{{print $1}}')\" >&2
{_remote_hff_bootstrap(repo, repo_type, token)}
echo '[vcp] Uploading remote archive to Hugging Face...' >&2
_vcp_start=\"$(_vcp_ns)\"
hff put \"$archive\" {shlex.quote(scratch_path)}
_vcp_timing remote_hf_upload \"$_vcp_start\"
"""
    _ssh(cfg, script, timing_sink=timing_sink, byte_sink=byte_sink)


def _remote_download_and_copy(
    cfg: dict,
    repo: str,
    repo_type: str,
    token: str,
    scratch_path: str,
    source_names: Sequence[str],
    remote_dest: str,
    transfer_id: str,
    timing_sink: Dict[str, float],
    byte_sink: Dict[str, int],
) -> None:
    archive = f"/workspace/.vcp/{transfer_id}.tar"
    stage = f"/workspace/.vcp/{transfer_id}.extract"
    srcs = [f"{stage}/{name}" for name in source_names]
    script = f"""set -euo pipefail
umask 077
{_remote_timer_helpers()}
mkdir -p /workspace/.vcp
archive={shlex.quote(archive)}
stage={shlex.quote(stage)}
cleanup() {{ rm -f \"$archive\"; rm -rf \"$stage\"; }}
trap cleanup EXIT
{_remote_hff_bootstrap(repo, repo_type, token)}
echo '[vcp] Downloading archive from Hugging Face on remote...' >&2
_vcp_start=\"$(_vcp_ns)\"
hff get {shlex.quote(scratch_path)} \"$archive\"
_vcp_timing remote_hf_download \"$_vcp_start\"
_vcp_bytes=\"$(stat -c %s \"$archive\")\"
printf '{BYTES_PREFIX} archive %s\\n' \"$_vcp_bytes\"
_vcp_start=\"$(_vcp_ns)\"
mkdir -p \"$stage\"
tar -xf \"$archive\" -C \"$stage\"
echo '[vcp] Copying into remote destination...' >&2
cp -a -- {_shell_array(srcs)} {shlex.quote(remote_dest)}
_vcp_timing remote_copy \"$_vcp_start\"
"""
    _ssh(cfg, script, timing_sink=timing_sink, byte_sink=byte_sink)


def _local_tmp_root() -> Path:
    root = Path(os.environ.get("VCP_TMP_DIR", "~/.cache/vcp")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_pack(sources: Sequence[str], transfer_id: str) -> Tuple[Path, List[str]]:
    abs_sources = [_local_abs(s) for s in sources]
    for raw, src in zip(sources, abs_sources):
        if not (os.path.exists(src) or os.path.islink(src)):
            raise VcpError(f"local source not found: {raw}")
    names = _validate_unique_basenames(abs_sources)
    archive = _local_tmp_root() / f"{transfer_id}.tar"
    info("Packing locally...")
    _run(_tar_create_command(str(archive), abs_sources))
    info(f"Local archive: {archive.stat().st_size / (1024 * 1024):.1f} MiB")
    return archive, names


def _local_copy_from_archive(archive: Path, source_names: Sequence[str], dest: str, transfer_id: str) -> None:
    stage = _local_tmp_root() / f"{transfer_id}.extract"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        _run(["tar", "-xf", str(archive), "-C", str(stage)])
        srcs = [str(stage / name) for name in source_names]
        info("Copying into local destination...")
        _run(["cp", "-a", "--", *srcs, os.path.expanduser(dest)])
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _hff_path() -> Path:
    path = Path(os.environ.get("VCP_HFF_PY", str(Path(__file__).with_name("hff.py")))).expanduser()
    if not path.is_file():
        raise VcpError(f"hff.py not found: {path}")
    return path


def _hff(repo: str, repo_type: str, args: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return _run(
        [sys.executable, str(_hff_path()), "--repo", repo, "--type", repo_type, *args],
        capture=capture,
    )


def _hf_upload(repo: str, repo_type: str, local_file: Path, scratch_path: str, token: str) -> None:
    _ = token
    info(f"Uploading to hf://datasets/{repo}/{scratch_path} ...")
    _hff(repo, repo_type, ["put", str(local_file), scratch_path, "-m", f"vcp stage {Path(scratch_path).name}"])


def _hf_download(repo: str, repo_type: str, scratch_path: str, token: str, transfer_id: str) -> Path:
    _ = token
    target = _local_tmp_root() / f"{transfer_id}.download.tar"
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    info(f"Downloading hf://datasets/{repo}/{scratch_path} ...")
    _hff(repo, repo_type, ["get", scratch_path, str(target)])
    return target


def _hf_delete(repo: str, repo_type: str, scratch_path: str, token: str) -> None:
    _ = token
    try:
        _hff(repo, repo_type, ["rm", scratch_path])
        info("Removed scratch archive from Hugging Face")
    except Exception as exc:
        info(f"WARNING: could not remove scratch archive {scratch_path}: {exc}")


def _copy(args: argparse.Namespace) -> None:
    cfg = _read_config()
    _ssh_argv(cfg)
    repo = _hf_repo(cfg)
    repo_type = _hf_type(cfg)
    token = _need_token()

    operands = args.operands
    if len(operands) < 2:
        raise VcpError("usage: vcp [options] <source...> <destination>")
    sources = operands[:-1]
    dest = operands[-1]

    src_remote = [_is_remote(s) for s in sources]
    dst_remote = _is_remote(dest)
    if any(src_remote) and not all(src_remote):
        raise VcpError("all source operands must be on the same side")
    if bool(src_remote[0]) == bool(dst_remote):
        raise VcpError("exactly one side must be remote (r:); vcp is for local↔remote copies")

    transfer_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:12]
    scratch_path = f"vcp/{transfer_id}.tar"
    local_archive: Path | None = None
    staged = False
    completed = False
    stats = TransferStats()

    try:
        if src_remote[0]:
            remote_sources = [_remote_path(s) for s in sources]
            names = _validate_unique_basenames(remote_sources)
            remote_timings: Dict[str, float] = {}
            remote_bytes: Dict[str, int] = {}
            _remote_pack_and_upload(
                cfg, repo, repo_type, token, scratch_path, remote_sources, transfer_id,
                remote_timings, remote_bytes,
            )
            archive_bytes = remote_bytes.get("archive")
            stats.set_logical_bytes(archive_bytes)
            if "remote_pack" in remote_timings:
                stats.add("Remote pack", remote_timings["remote_pack"], archive_bytes)
            if "remote_hf_upload" in remote_timings:
                stats.add("HF upload (remote)", remote_timings["remote_hf_upload"], archive_bytes)
            staged = True

            started = time.perf_counter()
            cached = _hf_download(repo, repo_type, scratch_path, token, transfer_id)
            stats.add("HF download (local)", time.perf_counter() - started, cached.stat().st_size)
            if stats.logical_bytes is None:
                stats.set_logical_bytes(cached.stat().st_size)
            try:
                started = time.perf_counter()
                _local_copy_from_archive(cached, names, dest, transfer_id)
                stats.add("Extract/copy (local)", time.perf_counter() - started, cached.stat().st_size)
            finally:
                try:
                    cached.unlink()
                except FileNotFoundError:
                    pass
        else:
            remote_dest = _remote_path(dest)
            started = time.perf_counter()
            local_archive, names = _local_pack(sources, transfer_id)
            archive_bytes = local_archive.stat().st_size
            stats.set_logical_bytes(archive_bytes)
            stats.add("Local pack", time.perf_counter() - started, archive_bytes)

            started = time.perf_counter()
            _hf_upload(repo, repo_type, local_archive, scratch_path, token)
            stats.add("HF upload (local)", time.perf_counter() - started, archive_bytes)
            staged = True

            remote_timings = {}
            remote_bytes = {}
            _remote_download_and_copy(
                cfg, repo, repo_type, token, scratch_path, names, remote_dest, transfer_id,
                remote_timings, remote_bytes,
            )
            remote_archive_bytes = remote_bytes.get("archive", archive_bytes)
            if "remote_hf_download" in remote_timings:
                stats.add("HF download (remote)", remote_timings["remote_hf_download"], remote_archive_bytes)
            if "remote_copy" in remote_timings:
                stats.add("Extract/copy (remote)", remote_timings["remote_copy"], remote_archive_bytes)

        completed = True
    finally:
        if local_archive is not None:
            try:
                local_archive.unlink()
            except FileNotFoundError:
                pass
        if staged:
            if args.keep:
                info(f"Keeping scratch archive: hf://datasets/{repo}/{scratch_path}")
            else:
                started = time.perf_counter()
                _hf_delete(repo, repo_type, scratch_path, token)
                stats.add("HF cleanup", time.perf_counter() - started)

    if completed:
        info("Copy complete")
        stats.print_summary()


def _config_command(argv: Sequence[str]) -> None:
    if not argv or argv[0] in {"show", "list"}:
        cfg = _read_config()
        print(f"config:       {CONFIG_PATH}")
        ssh = cfg.get("ssh")
        print("ssh:          " + (shlex.join(ssh) if isinstance(ssh, list) and ssh else "<not configured>"))
        print(f"hf repo:      {_hf_repo(cfg)}")
        print(f"hf repo type: {_hf_type(cfg)}")
        return

    action = argv[0]
    cfg = _read_config()
    if action == "ssh":
        ssh_args = list(argv[1:])
        if ssh_args and ssh_args[0] == "--":
            ssh_args = ssh_args[1:]
        if not ssh_args:
            raise VcpError("usage: vcp config ssh [ssh options] user@host")
        cfg["ssh"] = ssh_args
        _write_config(cfg)
        print(f"saved SSH remote: {shlex.join(ssh_args)}")
        return

    if action in {"hf-repo", "repo"}:
        if len(argv) != 2 or "/" not in argv[1]:
            raise VcpError("usage: vcp config hf-repo OWNER/REPO")
        cfg["hf_repo"] = argv[1]
        cfg["hf_repo_type"] = "dataset"
        _write_config(cfg)
        print(f"saved HF scratch repo: {argv[1]} (dataset)")
        return

    if action == "clear":
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        print(f"removed config: {CONFIG_PATH}")
        return

    raise VcpError(f"unknown config command: {action}")


def _usage() -> str:
    return f"""vcp — copy local↔SSH-remote through a Hugging Face scratch dataset

Remote paths use r:/absolute/path. vcp is run on the local controller only;
the configured remote never needs to SSH back to this machine.

Usage:
  vcp config ssh [ssh options] user@host
  vcp config hf-repo OWNER/REPO
  vcp config show
  vcp [--keep] <source...> <destination>

Examples:
  vcp config ssh -i ~/.ssh/id_ed25519 -p 12234 root@199.199.88.88
  vcp r:/workspace/report.txt r:/workspace/logs .
  vcp interestingdirectory/ r:/workspace/

Defaults:
  HF scratch dataset: {DEFAULT_HF_REPO}
  Config file:        {CONFIG_PATH}

Environment:
  HF_TOKEN             local Hugging Face token used for both HF legs
  VCP_HF_REPO          override scratch OWNER/REPO
  VCP_CONFIG           override config path
  VCP_TMP_DIR          local temporary archive/extract directory
"""


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_usage())
        return
    if argv[0] == "config":
        _config_command(argv[1:])
        return

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--keep", action="store_true", help="keep the staged HF archive after copy")
    parser.add_argument("operands", nargs="+")
    args = parser.parse_args(argv)
    _copy(args)


if __name__ == "__main__":
    try:
        main()
    except VcpError as exc:
        die(str(exc), 1)
    except subprocess.CalledProcessError as exc:
        die(f"command failed with exit status {exc.returncode}", exc.returncode or 1)
    except KeyboardInterrupt:
        die("interrupted", 130)
    except Exception as exc:
        if os.environ.get("VCP_TRACEBACK") == "1":
            raise
        die(str(exc), 1)
