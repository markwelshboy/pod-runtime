#!/usr/bin/env python3
"""Bidirectional localhost-only SSH tunnel for PixlStash Desktop and RunPod ComfyUI.

PixlStash's Electron REST API chooses a new loopback port at each launch.
The local SSH client runs in WSL on ddraigPC, with Windows localhost
forwarding enabled. Discover the *current* local REST port by verifying its
/version endpoint, then keep the remote forwarded port stable so the ComfyUI
PixlStash node's saved URL remains valid across desktop restarts.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def valid_port(value: Any) -> int:
    """argparse-compatible TCP port validator."""
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid TCP port: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"TCP port must be between 1 and 65535: {value!r}")
    return port


def _is_pixlstash(port: int, timeout: float = 0.5) -> bool:
    """Probe only loopback; never forward an unrelated localhost service."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/version")
        response = conn.getresponse()
        if response.status != 200:
            return False
        data = json.loads(response.read(4096))
        return (
            isinstance(data, dict)
            and data.get("message") == "PixlStash REST API"
            and isinstance(data.get("version"), str)
        )
    except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _windows_listening_ports() -> list[int]:
    """Get Windows localhost listeners from WSL (WSL's 'ss' cannot see them)."""
    executable = shutil.which("powershell.exe")
    if not executable:
        candidate = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        if candidate.exists():
            executable = str(candidate)
    if not executable:
        return []
    script = (
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::1','::') "
        "-and $_.LocalPort -ge 49152 -and $_.LocalPort -le 65535 } | "
        "Select-Object -ExpandProperty LocalPort -Unique"
    )
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return sorted({
        int(line.strip())
        for line in result.stdout.splitlines()
        if re.fullmatch(r"\d{1,5}", line.strip())
        and 49152 <= int(line.strip()) <= 65535
    })


def _linux_listening_ports() -> list[int]:
    """Discover native Linux/WSL listeners as a fallback or supplement."""
    if not shutil.which("ss"):
        return []
    try:
        result = subprocess.run(
            ["ss", "-H", "-ltn"], capture_output=True, text=True,
            timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    ports: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        address = fields[3]
        if not address.startswith(("127.0.0.1:", "0.0.0.0:", "[::1]:", "[::]:", "*:")):
            continue
        text = address.rsplit(":", 1)[-1]
        if text.isdecimal() and 1 <= int(text) <= 65535:
            ports.add(int(text))
    return sorted(ports)


def discover_pixlstash_port(explicit: int | None = None) -> int:
    """Discover the PixlStash desktop API by identifying /version, not guessing.

    Passing --pixlstash-port or PIXLSTASH_API_PORT bypasses Windows listener
    enumeration but is still checked to prevent tunneling an unrelated service.
    """
    selected = explicit if explicit is not None else os.getenv("PIXLSTASH_API_PORT")
    if selected is not None and str(selected).strip():
        port = valid_port(selected)
        if not _is_pixlstash(port):
            raise ValueError(
                f"PixlStash API did not answer at 127.0.0.1:{port}/version. "
                "Check the desktop app or omit --pixlstash-port to autodetect."
            )
        return port

    # Common previous/standalone ports are cheap to probe; the Windows desktop
    # port is ephemeral, so do not assume that yesterday's 64404 is still valid.
    candidates = [64404, 9537]
    candidates.extend(_windows_listening_ports())
    candidates.extend(_linux_listening_ports())
    candidates = list(dict.fromkeys(candidates))

    # Most listeners reject /version immediately; bound slower probes are
    # parallel so a stale port does not delay detection.
    with ThreadPoolExecutor(max_workers=16) as pool:
        hits = [
            port for port, matched in zip(candidates, pool.map(_is_pixlstash, candidates))
            if matched
        ]
    if not hits:
        raise ValueError(
            "Cannot find PixlStash's local REST API. Start PixlStash Desktop, "
            "or specify --pixlstash-port PORT (or PIXLSTASH_API_PORT=PORT). "
            "From WSL, the API must answer at http://127.0.0.1:PORT/version."
        )
    if len(hits) > 1:
        raise ValueError(
            "More than one PixlStash API listener found ("
            + ", ".join(str(port) for port in hits)
            + "); select one using --pixlstash-port PORT."
        )
    return hits[0]


def tunnel_argv(
    ssh_base: list[str],
    *,
    local_comfy_port: int,
    remote_comfy_port: int,
    local_pixlstash_port: int,
    remote_pixlstash_port: int,
    local_ollama_port: int | None = None,
    remote_ollama_port: int = 11434,
) -> list[str]:
    """Add SSH tunnel options before the final remote destination."""
    if not ssh_base or not ssh_base[-1].startswith("root@"):
        raise ValueError("expected rpods SSH command ending in root@<host>")
    local_comfy_port = valid_port(local_comfy_port)
    remote_comfy_port = valid_port(remote_comfy_port)
    local_pixlstash_port = valid_port(local_pixlstash_port)
    remote_pixlstash_port = valid_port(remote_pixlstash_port)
    if local_ollama_port is not None:
        local_ollama_port = valid_port(local_ollama_port)
        remote_ollama_port = valid_port(remote_ollama_port)
        if local_ollama_port == local_comfy_port:
            raise ValueError("Ollama and ComfyUI local tunnel ports must differ.")
        if remote_ollama_port == remote_pixlstash_port:
            raise ValueError("Ollama remote port conflicts with PixlStash reverse endpoint.")
    return [
        *ssh_base[:-1],
        "-N", "-T",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-L", f"127.0.0.1:{local_comfy_port}:127.0.0.1:{remote_comfy_port}",
        *(
            ["-L", f"127.0.0.1:{local_ollama_port}:127.0.0.1:{remote_ollama_port}"]
            if local_ollama_port is not None else []
        ),
        "-R", f"127.0.0.1:{remote_pixlstash_port}:127.0.0.1:{local_pixlstash_port}",
        ssh_base[-1],
    ]


def _comfy_responds(port: int) -> bool:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.6)
    try:
        conn.request("GET", "/system_stats")
        response = conn.getresponse()
        if response.status != 200:
            return False
        data = json.loads(response.read(32768))
        return isinstance(data, dict) and "system" in data
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _remote_pixlstash_responds(ssh_base: list[str], remote_port: int) -> bool:
    """Probe the remote loopback reverse mapping over a second SSH session."""
    command = f"curl -fsS --max-time 4 http://127.0.0.1:{remote_port}/version"
    try:
        result = subprocess.run(
            [*ssh_base, command],
            capture_output=True, text=True, timeout=12, check=False,
        )
        if result.returncode:
            return False
        data = json.loads(result.stdout)
        return isinstance(data, dict) and data.get("message") == "PixlStash REST API"
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def run_tunnel(
    ssh_base: list[str],
    *,
    local_comfy_port: int = 47960,
    remote_comfy_port: int = 8288,
    pixlstash_port: int | None = None,
    remote_pixlstash_port: int = 64404,
    ollama_local_port: int | None = None,
    ollama_remote_port: int = 11434,
) -> int:
    """Keep a foreground, self-contained bidirectional SSH tunnel alive."""
    local_port = discover_pixlstash_port(pixlstash_port)
    command = tunnel_argv(
        ssh_base,
        local_comfy_port=local_comfy_port,
        remote_comfy_port=remote_comfy_port,
        local_pixlstash_port=local_port,
        remote_pixlstash_port=remote_pixlstash_port,
        local_ollama_port=ollama_local_port,
        remote_ollama_port=ollama_remote_port,
    )
    print(f"[rpods] PixlStash API found at 127.0.0.1:{local_port}/version")
    print(f"[rpods] PixlStash -> ComfyUI: http://127.0.0.1:{local_comfy_port}"
          f"  (pod 127.0.0.1:{remote_comfy_port})")
    print(f"[rpods] ComfyUI -> PixlStash: pod 127.0.0.1:{remote_pixlstash_port}"
          f"  (local 127.0.0.1:{local_port})")
    if ollama_local_port is not None:
        print(f"[rpods] Pod Ollama -> local: http://127.0.0.1:{ollama_local_port}"
              f"  (pod 127.0.0.1:{ollama_remote_port})")
    print("[rpods] All tunnel endpoints bind to loopback only. Ctrl+C to close.")
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
                print(
                    f"[rpods] SSH tunnel exited (status {process.returncode}). "
                    "A port may already be in use or SSH forwarding disallowed.",
                    file=sys.stderr,
                )
                return process.returncode or 1
            if _comfy_responds(local_comfy_port):
                ready = True
                break
            time.sleep(0.25)

        if ready:
            print("[rpods] ComfyUI forward: OK (/system_stats)")
        else:
            print("[rpods] WARNING: Forward is open, but ComfyUI did not answer "
                  f"on local port {local_comfy_port}; it may still be starting.",
                  file=sys.stderr)
        if process.poll() is not None:
            return process.returncode or 1

        if _remote_pixlstash_responds(ssh_base, remote_pixlstash_port):
            print("[rpods] PixlStash reverse: OK (/version from pod)")
        else:
            print(
                "[rpods] WARNING: Reverse PixlStash probe failed; check that "
                f"the pod can curl 127.0.0.1:{remote_pixlstash_port}/version. "
                "The tunnel remains open for diagnosis.",
                file=sys.stderr,
            )
        if ollama_local_port is not None:
            # Lazy import avoids a cycle: rpods_vlm reuses our port validation.
            from rpods_vlm import is_ollama
            if is_ollama(ollama_local_port):
                print("[rpods] Ollama forward: OK (/api/version)")
            else:
                print("[rpods] WARNING: Ollama did not answer via forwarded "
                      "127.0.0.1. Run 'start-ollama' on the pod.", file=sys.stderr)
        print("[rpods] Tunnel active; leave this terminal open. Ctrl+C to stop.")
        sys.stdout.flush()
        return process.wait()
    except KeyboardInterrupt:
        print("\n[rpods] Closing PixlStash tunnel...")
        return 130
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
