"""ComfyUI workspace checkpoint and pod snapshot bridge.

Preserves live workflow tabs as JSON without changing their saved workflow files.
All snapshot paths are selected by this server module, never by HTTP clients.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web
from server import PromptServer

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict[str, type] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

PREFIX = "/pod_runtime/workspace_snapshot"
MAX_PAYLOAD = 32 * 1024 * 1024
MAX_TABS = 120
GROUP_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SESSION_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}$")
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_PROFILE = os.environ.get("COMFY_WORKSPACE_SNAPSHOT_PROFILE", "default")

if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", _PROFILE):
    raise RuntimeError("Invalid COMFY_WORKSPACE_SNAPSHOT_PROFILE")


def comfy_home() -> Path:
    return Path(os.environ.get("COMFY_HOME", "/workspace/ComfyUI")).expanduser().resolve()


def profile_root() -> Path:
    return comfy_home() / "user" / _PROFILE


def session_root() -> Path:
    return profile_root() / "workspace_sessions"


def auth_token_path() -> Path:
    return Path("/workspace/.pod-state/workspace-snapshot/auth-token")


def auth_token() -> str:
    supplied = os.environ.get("COMFY_WORKSPACE_SNAPSHOT_TOKEN", "").strip()
    if supplied:
        return supplied
    path = auth_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # O_EXCL ensures two ComfyUI processes cannot mint different tokens.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_urlsafe(32) + "\n")
    return path.read_text(encoding="utf-8").strip()


def authorized(request: web.Request) -> bool:
    # Never accept a cross-origin form POST, even if another web service
    # advertises a permissive CORS policy. Real authorization is the token.
    site = request.headers.get("Sec-Fetch-Site", "")
    if site and site not in ("same-origin", "none"):
        return False
    supplied = request.headers.get("X-Workspace-Snapshot-Token", "")
    return bool(supplied and hmac.compare_digest(supplied, auth_token()))


def rejected() -> web.Response:
    return web.json_response(
        {"error": "Snapshot access denied. Enter the pod token from "
                  "/workspace/.pod-state/workspace-snapshot/auth-token "
                  "(or COMFY_WORKSPACE_SNAPSHOT_TOKEN)."},
        status=401,
    )


def _is_within_workspace(path: Path) -> bool:
    try:
        root = Path("/workspace").resolve()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return resolved != root and resolved.is_relative_to(root)


def _clean_text(value: Any, *, default: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        text = default
    if len(text) > limit or any(ord(ch) < 32 for ch in text):
        raise ValueError(f"Text must be at most {limit} characters without control characters")
    return text


def validate_session(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    tabs = payload.get("tabs")
    if not isinstance(tabs, list) or not 1 <= len(tabs) <= MAX_TABS:
        raise ValueError(f"Expected 1-{MAX_TABS} open workflow tabs")
    clean_tabs: list[dict[str, Any]] = []
    for i, item in enumerate(tabs):
        if not isinstance(item, dict):
            raise ValueError(f"Tab {i + 1} is not an object")
        graph = item.get("graph")
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise ValueError(f"Tab {i + 1} has no valid graph")
        clean_tabs.append({
            "name": _clean_text(item.get("name"), default=f"Workflow {i + 1}", limit=180),
            "path": str(item.get("path") or "")[:2048],
            "modified": bool(item.get("modified", False)),
            "graph": graph,
        })
    active_index = payload.get("activeIndex", 0)
    if type(active_index) is not int or not 0 <= active_index < len(clean_tabs):
        raise ValueError("Invalid active tab index")
    return {
        "schema": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "activeIndex": active_index,
        "tabs": clean_tabs,
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # This file contains full prompts and workflow contents.
    fd, temp_name = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def save_session(payload: dict[str, Any]) -> tuple[str, Path]:
    document = validate_session(payload)
    if not _is_within_workspace(session_root().parent):
        raise ValueError(f"ComfyUI user directory is not beneath /workspace: {profile_root()}")
    sid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    path = session_root() / f"{sid}.json"
    _atomic_write_json(path, document)
    return sid, path


def session_file(sid: str) -> Path:
    if not SESSION_RE.fullmatch(sid):
        raise ValueError("Invalid session ID")
    return session_root() / f"{sid}.json"


def _summary(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("tabs"), list):
            return None
        return {
            "id": path.stem,
            "created_utc": data.get("created_utc"),
            "tab_count": len(data["tabs"]),
            "active_index": data.get("activeIndex", 0),
            "tab_names": [str(x.get("name", "")) for x in data["tabs"][:MAX_TABS]],
        }
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def list_sessions() -> list[dict[str, Any]]:
    root = session_root()
    if not root.exists():
        return []
    result = [_summary(path) for path in sorted(root.glob("*.json"), reverse=True)[:100]]
    return [item for item in result if item is not None]


def snapshot_paths(session: Path, choices: dict[str, Any]) -> tuple[list[str], list[str]]:
    home = comfy_home()
    options = (
        ("input", home / "input", True),
        ("output_gpu0", home / "output_gpu0", True),
        ("output", home / "output", False),
        ("workflows", profile_root() / "workflows", True),
        ("tab_manager", profile_root() / "ComfyUI-Tab-Manager", True),
        ("settings", profile_root() / "comfy.settings.json", True),
    )
    paths = [session]
    warnings: list[str] = []
    for key, path, default in options:
        if choices.get(key, default) is not True:
            continue
        if not path.exists():
            warnings.append(f"Skipped missing {key}: {path}")
            continue
        paths.append(path)
    for path in paths:
        if not _is_within_workspace(path):
            raise ValueError(f"Snapshot path is outside /workspace or inaccessible: {path}")
    return [str(path) for path in dict.fromkeys(paths)], warnings


def _snapshot_executable() -> str:
    configured = os.environ.get("COMFY_WORKSPACE_SNAPSHOT_COMMAND", "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute() or not candidate.is_file():
            raise RuntimeError("COMFY_WORKSPACE_SNAPSHOT_COMMAND must name an executable file")
        return str(candidate)
    executable = shutil.which("snapshot-pod")
    if executable:
        return executable
    fallback = Path("/workspace/pod-runtime/snapshot-pod")
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("snapshot-pod not found on PATH or in /workspace/pod-runtime")


def prepare_custom_nodes_manifest() -> tuple[Path, list[str]]:
    """Capture the installed custom-node environment into the snapshot.

    It never modifies the checked-out main manifest or installed nodes.
    """
    runtime = Path(os.environ.get("POD_RUNTIME_DIR", "/workspace/pod-runtime"))
    tool = runtime / "bin" / "custom_node_snapshot.py"
    if not tool.is_file():
        raise RuntimeError(f"custom-node snapshot tool not found: {tool}")
    destination = Path("/workspace/.pod-state/custom_nodes")
    source = os.environ.get("CUSTOM_NODES_MANIFEST_URL") or str(runtime / "custom_nodes_manifest.json")
    command = [
        sys.executable, str(tool), "discover",
        "--base", source,
        "--nodes-root", str(comfy_home() / "custom_nodes"),
        "--status-file", os.environ.get(
            "CUSTOM_NODE_STATUS_FILE",
            os.path.join(os.environ.get("CUSTOM_LOG_DIR", "/workspace/logs/custom_nodes"),
                         "install_status.json")),
        "--sets", os.environ.get("CUSTOM_NODE_SETS", ""),
        "--output", str(destination / "manifest.json"),
        "--inventory", str(destination / "inventory.json"),
        "--packages", str(destination / "packages.json"),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            check=False, timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Custom-node inventory timed out") from error
    if result.returncode:
        raise RuntimeError(
            "Custom-node discovery failed (snapshot cancelled): "
            + (result.stderr or result.stdout)[-2500:]
        )
    try:
        inventory = json.loads((destination / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("Custom-node discovery did not create a valid inventory") from error
    summary = inventory.get("summary", {})
    warnings = [
        f"Custom nodes: {summary.get('new_pending', 0)} new pending, "
        f"{summary.get('unresolved', 0)} unresolved; see inventory.json."
    ]
    warnings.extend(str(msg) for msg in inventory.get("warnings", [])[:30])
    return destination, warnings


def make_snapshot_command(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    sid = str(payload.get("session_id", ""))
    session = session_file(sid)
    if not session.is_file():
        raise ValueError("Session checkpoint not found; capture tabs before snapshotting")
    group = _clean_text(payload.get("group"), default="comfy-workspace", limit=64)
    if not GROUP_RE.fullmatch(group):
        raise ValueError("Group must contain only letters, numbers, underscore or hyphen")
    name = _clean_text(payload.get("name"), default=f"workspace_{sid}", limit=160)
    tag = _clean_text(payload.get("tag"), default="workspace", limit=80)
    choices = payload.get("include", {})
    if not isinstance(choices, dict) or any(type(v) is not bool for v in choices.values()):
        raise ValueError("include must contain booleans")
    if set(choices) - {"input", "output_gpu0", "output", "workflows", "tab_manager", "settings", "custom_nodes"}:
        raise ValueError("Unknown snapshot include option")
    paths, warnings = snapshot_paths(session, choices)
    if choices.get("custom_nodes", False):
        node_snapshot_dir, node_warnings = prepare_custom_nodes_manifest()
        if not _is_within_workspace(node_snapshot_dir):
            raise ValueError("Custom-node manifest is outside /workspace")
        paths.append(str(node_snapshot_dir))
        warnings.extend(node_warnings)
    command = [_snapshot_executable(), "--group", group, "--name", name,
               "--tag", tag, "--paths", *paths]
    return command, warnings


def _run_snapshot(job_id: str, command: list[str]) -> None:
    with _JOB_LOCK:
        _JOBS[job_id]["status"] = "running"
    try:
        completed = subprocess.run(
            command, cwd=str(comfy_home()), capture_output=True,
            text=True, errors="replace", check=False,
        )
        ok = completed.returncode == 0
        output = (completed.stdout + "\n" + completed.stderr)[-12000:]
        with _JOB_LOCK:
            _JOBS[job_id].update(status="completed" if ok else "failed",
                                 exit_code=completed.returncode, output=output)
    except Exception as exc:
        with _JOB_LOCK:
            _JOBS[job_id].update(status="failed", exit_code=-1, output=str(exc)[:2000])


def start_job(payload: dict[str, Any]) -> dict[str, Any]:
    # Keep discovery inside the lock so concurrent requests cannot overwrite
    # a manifest while the first snapshot is being prepared/uploaded.
    with _JOB_LOCK:
        if any(j["status"] in ("queued", "running") for j in _JOBS.values()):
            raise ValueError("Another snapshot upload is still running")
        command, warnings = make_snapshot_command(payload)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {
            "id": job_id, "status": "queued", "warnings": warnings,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "output": "", "exit_code": None,
        }
        # Retain only the newest 30 job reports (no deletion of live jobs).
        if len(_JOBS) > 30:
            completed = [k for k, v in _JOBS.items()
                         if v["status"] in ("completed", "failed") and k != job_id]
            for old in completed[:len(_JOBS) - 30]:
                _JOBS.pop(old, None)
    threading.Thread(target=_run_snapshot, args=(job_id, command), daemon=True).start()
    return dict(_JOBS[job_id])


def _require_token(handler):
    async def wrapped(request: web.Request) -> web.Response:
        if not authorized(request):
            return rejected()
        return await handler(request)
    return wrapped


@PromptServer.instance.routes.get(PREFIX + "/health")
async def workspace_snapshot_health(_request: web.Request) -> web.Response:
    # Mint the token before the frontend asks the user to read it via SSH.
    try:
        auth_token()
    except OSError:
        return web.json_response({"error": "Could not initialize access token"}, status=503)
    return web.json_response({"ready": True, "requires_token": True})


@PromptServer.instance.routes.post(PREFIX + "/session")
@_require_token
async def workspace_snapshot_session(request: web.Request) -> web.Response:
    if request.content_length is not None and request.content_length > MAX_PAYLOAD:
        return web.json_response({"error": "Session too large"}, status=413)
    try:
        payload = await request.json()
        # Chunked requests can omit Content-Length.
        if len(json.dumps(payload).encode("utf-8")) > MAX_PAYLOAD:
            return web.json_response({"error": "Session too large"}, status=413)
        sid, path = save_session(payload)
        return web.json_response({"ok": True, "id": sid, "path": str(path)})
    except (ValueError, TypeError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.get(PREFIX + "/sessions")
@_require_token
async def workspace_snapshot_sessions(_request: web.Request) -> web.Response:
    return web.json_response({"sessions": list_sessions()})


@PromptServer.instance.routes.get(PREFIX + "/sessions/{sid}")
@_require_token
async def workspace_snapshot_get_session(request: web.Request) -> web.Response:
    try:
        path = session_file(request.match_info["sid"])
        return web.json_response(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=404)


@PromptServer.instance.routes.post(PREFIX + "/snapshot")
@_require_token
async def workspace_snapshot_start(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        job = start_job(payload)
        return web.json_response(job, status=202)
    except (ValueError, RuntimeError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.get(PREFIX + "/jobs/{job_id}")
@_require_token
async def workspace_snapshot_job(request: web.Request) -> web.Response:
    with _JOB_LOCK:
        job = _JOBS.get(request.match_info["job_id"])
        return web.json_response(dict(job) if job else {"error": "Job not found"},
                                 status=200 if job else 404)
