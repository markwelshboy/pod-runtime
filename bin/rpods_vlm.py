#!/usr/bin/env python3
"""Loopback-only Ollama SSH forwarding and validated VLM skills ZIP upload.

The Pod is selected by rpods.py; neither operation opens an unauthenticated
public Ollama endpoint. Skills transfer uses a separate SSH *session* with
the same selected connection credentials, streaming the ZIP to remote Python.
No SCP port conversion, additional SSH alias, or intermediate upload file.
"""
from __future__ import annotations

import http.client
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from rpods_pixlstash import valid_port

ALLOWED_DIRS = frozenset((
    "image-detailer-analysis",
    "image-detailer-analysis-v1",
    "image-detailer-analysis-v2",
    "vlm-face-benchmark",
))
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_EXTRACTED = 32 * 1024 * 1024
MAX_FILES = 500

# Executed on the pod with no user-provided shell interpolation.
# Validates everything before writing, rejects traversal/links/oversized ZIPs.
REMOTE_INSTALL = r'''
import io
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import zipfile

ALLOWED = {"image-detailer-analysis", "image-detailer-analysis-v1",
           "image-detailer-analysis-v2", "vlm-face-benchmark"}
MAX_BYTES = 16 * 1024 * 1024
MAX_EXTRACTED = 32 * 1024 * 1024
MAX_FILES = 500
ROOT = Path("/workspace/vlm-skills")

def validate(info):
    path = PurePosixPath(info.filename)
    if (info.filename.startswith("/") or "\\" in info.filename or
            not path.parts or ".." in path.parts or
            path.parts[0] not in ALLOWED):
        raise ValueError("Unsafe or unknown ZIP member: " + info.filename)
    mode = (info.external_attr >> 16)
    if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("ZIP includes link/special file: " + info.filename)
    return path

def main():
    payload = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Skills ZIP exceeds maximum size.")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > MAX_FILES:
            raise ValueError("Too many files in skills ZIP.")
        size = 0
        targets = []
        seen = set()
        for info in members:
            member = validate(info)
            if info.is_dir():
                continue
            if str(member) in seen or len(member.parts) < 2:
                raise ValueError("Duplicate or invalid ZIP path: " + info.filename)
            seen.add(str(member))
            size += info.file_size
            if size > MAX_EXTRACTED:
                raise ValueError("Uncompressed skill data too large.")
            targets.append((info, member))
        if not any(str(p) == "image-detailer-analysis/SKILL.md" for _, p in targets):
            raise ValueError("ZIP must contain image-detailer-analysis/SKILL.md.")
        if ROOT.is_symlink():
            raise ValueError("Destination is a symlink.")
        ROOT.mkdir(parents=True, exist_ok=True)
        # Stage entire archive first. Existing skill files are replaced
        # individually only after validation; unlisted files remain.
        with tempfile.TemporaryDirectory(prefix=".skills-upload-", dir=str(ROOT)) as staging:
            stage = Path(staging)
            for info, member in targets:
                dest = stage.joinpath(*member.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as reader, dest.open("wb") as writer:
                    while True:
                        chunk = reader.read(128 * 1024)
                        if not chunk:
                            break
                        writer.write(chunk)
            for _, member in targets:
                dest = ROOT.joinpath(*member.parts)
                for directory in list(dest.parents):
                    if directory == ROOT.parent:
                        break
                    if directory.is_symlink():
                        raise ValueError("Existing skill path is a symlink: " + str(directory))
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage.joinpath(*member.parts), dest)
                os.chmod(dest, 0o644)
        print("[rpods] Installed %d VLM skill/benchmark files in %s" % (len(targets), ROOT))

try:
    main()
except (OSError, ValueError, zipfile.BadZipFile) as exc:
    print("[rpods] ERROR uploading skills: %s" % exc, file=sys.stderr)
    sys.exit(2)
'''


def is_ollama(port: int) -> bool:
    """Identify service by /api/version, not by any HTTP 200 response."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", valid_port(port), timeout=0.7)
        try:
            conn.request("GET", "/api/version")
            res = conn.getresponse()
            if res.status != 200:
                return False
            data = json.loads(res.read(2048))
            return isinstance(data, dict) and isinstance(data.get("version"), str)
        finally:
            conn.close()
    except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return False


def is_worker(port: int) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", valid_port(port), timeout=0.7)
        try:
            conn.request("GET", "/health")
            result = conn.getresponse()
            if result.status != 200:
                return False
            data = json.loads(result.read(4096))
            return isinstance(data, dict) and data.get("service") == "image-playground-vlm-worker"
        finally:
            conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return False


def tunnel_argv(ssh_base: list[str], *, local_ollama_port: int = 47961,
                remote_ollama_port: int = 11434, local_worker_port: int = 47962,
                remote_worker_port: int = 8765) -> list[str]:
    if not ssh_base or ssh_base[0] != "ssh" or not ssh_base[-1].startswith("root@"):
        raise ValueError("Expected an SSH command ending in root@<pod>.")
    local_ollama_port = valid_port(local_ollama_port)
    remote_ollama_port = valid_port(remote_ollama_port)
    local_worker_port = valid_port(local_worker_port)
    remote_worker_port = valid_port(remote_worker_port)
    if local_worker_port == local_ollama_port:
        raise ValueError("Ollama and VLM worker local ports must differ.")
    return [*ssh_base[:-1], "-N", "-T",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-L", f"127.0.0.1:{local_ollama_port}:127.0.0.1:{remote_ollama_port}",
            "-L", f"127.0.0.1:{local_worker_port}:127.0.0.1:{remote_worker_port}",
            ssh_base[-1]]


def run_tunnel(ssh_base: list[str], *, local_ollama_port: int = 47961,
               remote_ollama_port: int = 11434, local_worker_port: int = 47962,
               remote_worker_port: int = 8765) -> int:
    command = tunnel_argv(
        ssh_base, local_ollama_port=local_ollama_port,
        remote_ollama_port=remote_ollama_port,
        local_worker_port=local_worker_port, remote_worker_port=remote_worker_port)
    print(f"[rpods] Pod Ollama -> local: http://127.0.0.1:{local_ollama_port}"
          f" (pod 127.0.0.1:{remote_ollama_port})")
    print(f"[rpods] Pod VLM worker -> local: http://127.0.0.1:{local_worker_port}"
          f" (pod 127.0.0.1:{remote_worker_port})")
    print("[rpods] All services bind to local loopback only. Ctrl+C to close.")
    sys.stdout.flush()
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        print(f"[rpods] ERROR starting SSH tunnel: {exc}", file=sys.stderr)
        return 1
    try:
        ready = False
        for _ in range(35):
            if process.poll() is not None:
                print("[rpods] SSH tunnel exited (%s); check port or forwarding." %
                      process.returncode, file=sys.stderr)
                return process.returncode or 1
            if is_ollama(local_ollama_port):
                ready = True
                break
            time.sleep(0.25)
        if ready:
            print("[rpods] Ollama forward: OK (/api/version)")
        else:
            print("[rpods] WARNING: Ollama did not answer through SSH. "
                  "On the pod run 'start-ollama'.", file=sys.stderr)
        if is_worker(local_worker_port):
            print("[rpods] VLM worker forward: OK (/health)")
        else:
            print("[rpods] WARNING: VLM worker unavailable; check "
                  "/workspace/logs/vlm-worker.log on the pod.", file=sys.stderr)
        print("[rpods] Tunnel active; leave this terminal open. Ctrl+C to stop.")
        sys.stdout.flush()
        return process.wait()
    except KeyboardInterrupt:
        print("\n[rpods] Closing Ollama tunnel...")
        return 130
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def check_skills_zip(path: str | Path) -> bytes:
    """Preflight locally: only the known Image Playground ZIP layout is allowed."""
    source = Path(path).expanduser()
    if not source.is_file() or source.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError(f"Skills ZIP is missing or exceeds {MAX_ZIP_BYTES // (1024*1024)} MiB: {source}")
    payload = source.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES:
                raise ValueError("Skills ZIP has too many entries.")
            uncompressed = 0
            paths: set[str] = set()
            for entry in members:
                rel = entry.filename
                parts = rel.split("/")
                if (rel.startswith("/") or "\\" in rel or
                        not parts or parts[0] not in ALLOWED_DIRS or
                        any(part in ("", ".", "..") for part in parts[:-1]) or
                        ".." in parts or
                        stat.S_IFMT(entry.external_attr >> 16) not in (
                            0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError("Unsafe or unexpected skills ZIP entry: " + rel)
                if entry.is_dir():
                    continue
                if rel in paths or len(parts) < 2 or not parts[-1]:
                    raise ValueError("Duplicate/invalid ZIP entry: " + rel)
                paths.add(rel)
                uncompressed += entry.file_size
                if uncompressed > MAX_EXTRACTED:
                    raise ValueError("Skills ZIP uncompressed data too large.")
            if "image-detailer-analysis/SKILL.md" not in paths:
                raise ValueError("Not an Image Playground skill ZIP (missing SKILL.md).")
            if archive.testzip() is not None:
                raise ValueError("Skills ZIP failed integrity check.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid ZIP file.") from exc
    return payload


def skills_remote_command() -> str:
    """Choose a real Python >=3.10 on the pod; never assume SSH's PATH.

    Remote SSH commands run in a noninteractive shell. ComfyUI GPU images
    often have /opt/venv/bin/python without a globally installed python3.
    The interpreter reads the ZIP bytes on stdin via REMOTE_INSTALL.
    """
    return ("""set -eu
py=''
for candidate in /opt/venv/bin/python /opt/venv/bin/python3 /usr/bin/python3 /usr/local/bin/python3 /workspace/venv/bin/python /usr/bin/python /usr/local/bin/python; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        py="$candidate"
        break
    fi
done
if [ -z "$py" ]; then
    for executable in python3 python; do
        candidate="$(command -v "$executable" 2>/dev/null || true)"
        if [ -n "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            py="$candidate"
            break
        fi
    done
fi
if [ -z "$py" ]; then
    echo '[rpods] ERROR: No usable Python >=3.10 on pod. Expected /opt/venv/bin/python or an OS Python.' >&2
    exit 127
fi
exec "$py" -c """ + shlex.quote(REMOTE_INSTALL))


def push_skills_zip(ssh_base: list[str], path: str | Path) -> None:
    """Stream validated bytes over ordinary pod SSH, no public upload port."""
    if not ssh_base or ssh_base[0] != "ssh" or not ssh_base[-1].startswith("root@"):
        raise ValueError("Expected an SSH command ending in root@<pod>.")
    payload = check_skills_zip(path)
    cmd = [*ssh_base[:-1], "-T", ssh_base[-1], skills_remote_command()]
    print(f"[rpods] Uploading VLM skills ZIP ({len(payload):,} bytes) via pod SSH...")
    sys.stdout.flush()
    try:
        result = subprocess.run(cmd, input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Skills SSH upload failed: {exc}") from exc
    if result.returncode:
        details = result.stderr.decode("utf-8", "replace").strip()
        raise ValueError("Remote skills installation failed: " + details[:1500])
    print(result.stdout.decode("utf-8", "replace").strip() or
          "[rpods] Skills ZIP uploaded.")
