#!/usr/bin/env python3
"""vcp - copy between this machine and one configured SSH remote via Hugging Face.

The command is intentionally controlled from the local machine.  Remote paths are
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
from typing import Iterable, List, Sequence, Tuple


DEFAULT_HF_REPO = "markwelshboyx/hf-scratchpad"
DEFAULT_HF_TYPE = "dataset"
CONFIG_PATH = Path(os.environ.get("VCP_CONFIG", "~/.config/vcp/config.json")).expanduser()


class VcpError(RuntimeError):
    pass


def info(msg: str) -> None:
    print(f"[vcp] {msg}", file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    print(f"[vcp] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


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


def _ssh(cfg: dict, script: str, *, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["ssh", *_ssh_argv(cfg), "bash", "-s"]
    return subprocess.run(
        cmd,
        input=script,
        text=True,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _shell_array(values: Iterable[str]) -> str:
    return " ".join(shlex.quote(v) for v in values)


def _remote_hff_bootstrap(repo: str, repo_type: str) -> str:
    # Do not send the local HF token.  The pod loads its own runtime/secrets and
    # uses the HFF toolchain already supplied by pod-runtime.
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
export HFF_REPO={shlex.quote(repo)}
export HFF_REPO_TYPE={shlex.quote(repo_type)}
export HF_XET_HIGH_PERFORMANCE=1
[[ -n \"${{HF_TOKEN:-${{HUGGINGFACE_HUB_TOKEN:-}}}}\" ]] || {{
  echo '[vcp] ERROR: HF_TOKEN is not available on remote' >&2
  exit 2
}}
if [[ -z \"${{HF_TOKEN:-}}\" && -n \"${{HUGGINGFACE_HUB_TOKEN:-}}\" ]]; then
  export HF_TOKEN=\"$HUGGINGFACE_HUB_TOKEN\"
fi
"""


def _remote_pack_and_upload(cfg: dict, repo: str, repo_type: str, scratch_path: str, remote_sources: Sequence[str], transfer_id: str) -> None:
    _validate_unique_basenames(remote_sources)
    archive = f"/workspace/.vcp/{transfer_id}.tar"
    # Build tar fragments explicitly so each absolute source lands at archive root.
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
mkdir -p /workspace/.vcp
archive={shlex.quote(archive)}
trap 'rm -f \"$archive\"' EXIT
{os.linesep.join(checks)}
echo '[vcp] Packing on remote...' >&2
tar -cf \"$archive\" {_shell_array(tar_parts)}
echo \"[vcp] Remote archive: $(du -h \"$archive\" | awk '{{print $1}}')\" >&2
{_remote_hff_bootstrap(repo, repo_type)}
echo '[vcp] Uploading remote archive to Hugging Face...' >&2
hff put \"$archive\" {shlex.quote(scratch_path)}
"""
    _ssh(cfg, script)


def _remote_download_and_copy(cfg: dict, repo: str, repo_type: str, scratch_path: str, source_names: Sequence[str], remote_dest: str, transfer_id: str) -> None:
    archive = f"/workspace/.vcp/{transfer_id}.tar"
    stage = f"/workspace/.vcp/{transfer_id}.extract"
    srcs = [f"{stage}/{name}" for name in source_names]
    script = f"""set -euo pipefail
umask 077
mkdir -p /workspace/.vcp
archive={shlex.quote(archive)}
stage={shlex.quote(stage)}
cleanup() {{ rm -f \"$archive\"; rm -rf \"$stage\"; }}
trap cleanup EXIT
{_remote_hff_bootstrap(repo, repo_type)}
echo '[vcp] Downloading archive from Hugging Face on remote...' >&2
hff get {shlex.quote(scratch_path)} \"$archive\"
mkdir -p \"$stage\"
tar -xf \"$archive\" -C \"$stage\"
echo '[vcp] Copying into remote destination...' >&2
cp -a -- {_shell_array(srcs)} {shlex.quote(remote_dest)}
"""
    _ssh(cfg, script)


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
    _ = token  # hff.py reads HF_TOKEN from the environment
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
    _ssh_argv(cfg)  # fail before spending time tarring anything
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

    try:
        if src_remote[0]:
            remote_sources = [_remote_path(s) for s in sources]
            names = _validate_unique_basenames(remote_sources)
            _remote_pack_and_upload(cfg, repo, repo_type, scratch_path, remote_sources, transfer_id)
            staged = True
            cached = _hf_download(repo, repo_type, scratch_path, token, transfer_id)
            try:
                _local_copy_from_archive(cached, names, dest, transfer_id)
            finally:
                try:
                    cached.unlink()
                except FileNotFoundError:
                    pass
        else:
            remote_dest = _remote_path(dest)
            local_archive, names = _local_pack(sources, transfer_id)
            _hf_upload(repo, repo_type, local_archive, scratch_path, token)
            staged = True
            _remote_download_and_copy(cfg, repo, repo_type, scratch_path, names, remote_dest, transfer_id)

        info("Copy complete")
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
                _hf_delete(repo, repo_type, scratch_path, token)


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

Remote paths use r:/absolute/path.  vcp is run on the local controller only;
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
  HF_TOKEN             local Hugging Face token (never written to vcp config)
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
