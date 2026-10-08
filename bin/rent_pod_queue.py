#!/usr/bin/env python3
"""Persistent local availability queue for rent-pod.

This intentionally models RunPod's "deploy when available" behavior without
using an undocumented console endpoint. Requests are stored on disk and serviced
by one detached worker process. The worker only launches the existing rent-pod
pipeline; qualification/provision/startup semantics remain centralized there.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

STATE_VERSION = 1
DEFAULT_STATE_FILE = Path(
    os.environ.get(
        "RENT_POD_QUEUE_FILE",
        "~/.cache/pod-runtime/rent-pod-queue.json",
    )
).expanduser()
DEFAULT_LOG_FILE = Path(
    os.environ.get(
        "RENT_POD_QUEUE_LOG",
        "~/.cache/pod-runtime/rent-pod-queue.log",
    )
).expanduser()
GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")
USER_AGENT = os.environ.get(
    "RUNPOD_USER_AGENT",
    "pod-runtime-rent-pod/1.0 (Linux; Python)",
)
ACTIVE_STATES = {"pending", "launching"}
FINAL_STATES = {"launched", "expired", "cancelled", "failed", "attention"}
POD_ID_RE = re.compile(r"^\[rent-pod\]\s+Pod\s+(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class QueueOptions:
    duration_seconds: int
    window: str | None
    check_every: int


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_duration(value: str) -> int:
    text = value.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mhd])", text)
    if not match:
        raise ValueError("--for expects a duration such as 30m, 12h, or 2d")
    amount = float(match.group(1))
    if amount <= 0:
        raise ValueError("--for duration must be greater than zero")
    scale = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = int(amount * scale)
    if seconds < 60:
        raise ValueError("--for duration must be at least 1 minute")
    return seconds


def _parse_hhmm(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError("--window expects HH:MM-HH:MM using local time")
    return int(match.group(1)), int(match.group(2))


def validate_window(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if "-" not in text:
        raise ValueError("--window expects HH:MM-HH:MM using local time")
    start, end = text.split("-", 1)
    sh, sm = _parse_hhmm(start)
    eh, em = _parse_hhmm(end)
    return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"


def window_allows(window: str | None, when: datetime | None = None) -> bool:
    if not window:
        return True
    local = (when or datetime.now().astimezone()).astimezone()
    start, end = window.split("-", 1)
    sh, sm = _parse_hhmm(start)
    eh, em = _parse_hhmm(end)
    minute = local.hour * 60 + local.minute
    start_minute = sh * 60 + sm
    end_minute = eh * 60 + em
    if start_minute == end_minute:
        return True
    if start_minute < end_minute:
        return start_minute <= minute < end_minute
    return minute >= start_minute or minute < end_minute


def consume_queue_args(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], QueueOptions | None]:
    env = environ if environ is not None else os.environ
    enabled = False
    queue_modifier_seen = False
    duration_text = env.get("RENT_POD_QUEUE_FOR", "24h")
    window_text = env.get("RENT_POD_QUEUE_WINDOW") or None
    check_every = int(env.get("RENT_POD_QUEUE_CHECK_SECONDS", "60"))
    forwarded: list[str] = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--when-available":
            enabled = True
            i += 1
            continue
        if arg == "--for":
            queue_modifier_seen = True
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--for requires a duration such as 24h")
            duration_text = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--for="):
            queue_modifier_seen = True
            duration_text = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--window":
            queue_modifier_seen = True
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--window requires HH:MM-HH:MM")
            window_text = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--window="):
            queue_modifier_seen = True
            window_text = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--check-every":
            queue_modifier_seen = True
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--check-every requires seconds")
            check_every = int(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--check-every="):
            queue_modifier_seen = True
            check_every = int(arg.split("=", 1)[1])
            i += 1
            continue
        forwarded.append(arg)
        i += 1

    if not enabled:
        if queue_modifier_seen:
            raise ValueError("--for/--window/--check-every require --when-available")
        return forwarded, None
    if "--dry-run" in forwarded:
        raise ValueError("--when-available cannot be combined with --dry-run")
    if check_every < 15:
        raise ValueError("--check-every must be at least 15 seconds")

    return forwarded, QueueOptions(
        duration_seconds=parse_duration(duration_text),
        window=validate_window(window_text),
        check_every=check_every,
    )


def state_paths(state_file: Path = DEFAULT_STATE_FILE) -> tuple[Path, Path, Path]:
    return (
        state_file,
        state_file.with_suffix(state_file.suffix + ".lock"),
        state_file.with_suffix(state_file.suffix + ".worker.lock"),
    )


@contextmanager
def state_lock(state_file: Path = DEFAULT_STATE_FILE) -> Iterator[None]:
    state_file, lock_file, _worker_lock = state_paths(state_file)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_state(state_file: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    try:
        obj = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": STATE_VERSION, "requests": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read queue state {state_file}: {exc}") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("requests"), list):
        raise RuntimeError(f"invalid queue state in {state_file}")
    return obj


def save_state(state: dict[str, Any], state_file: Path = DEFAULT_STATE_FILE) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(state_file)


def _request_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"rpa-{stamp}-{uuid.uuid4().hex[:6]}"


def _append_log(message: str, log_file: Path = DEFAULT_LOG_FILE) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def spawn_worker(
    state_file: Path = DEFAULT_STATE_FILE,
    log_file: Path = DEFAULT_LOG_FILE,
    environ: Mapping[str, str] | None = None,
) -> None:
    env = dict(environ if environ is not None else os.environ)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(state_file)]
    with log_file.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
            env=env,
        )


def enqueue_request(
    argv: list[str],
    options: QueueOptions,
    probe: dict[str, Any],
    environ: Mapping[str, str] | None = None,
    state_file: Path = DEFAULT_STATE_FILE,
) -> int:
    env = environ if environ is not None else os.environ
    if not (env.get("RUNPOD_API_KEY") or "").strip():
        raise ValueError("RUNPOD_API_KEY is required for --when-available")

    created = now_utc()
    request = {
        "id": _request_id(),
        "status": "pending",
        "created_at": iso(created),
        "expires_at": iso(created + timedelta(seconds=options.duration_seconds)),
        "window": options.window,
        "check_every": options.check_every,
        "next_attempt_at": iso(created),
        "attempt_count": 0,
        "last_checked_at": None,
        "last_error": None,
        "available_at": None,
        "launched_at": None,
        "pod_id": None,
        "argv": list(argv),
        "probe": dict(probe),
        "approval": {"mode": "auto", "state": "not_required"},
    }
    with state_lock(state_file):
        state = load_state(state_file)
        state["schema_version"] = STATE_VERSION
        state["requests"].append(request)
        save_state(state, state_file)

    spawn_worker(state_file, DEFAULT_LOG_FILE, env)
    gpu = probe.get("gpu_label") or probe.get("gpu_id") or "GPU"
    print(f"[rent-pod] Queued availability request: {request['id']}")
    print(f"[rent-pod] GPU:                        {gpu}")
    print(f"[rent-pod] Expires:                    {request['expires_at']}")
    if options.window:
        print(f"[rent-pod] Daily launch window:        {options.window} (local time)")
    print(f"[rent-pod] Availability check:         every {options.check_every}s")
    print("[rent-pod] Use `rent-pod --queued` to inspect it.")
    return 0


def _format_remaining(expires_at: str) -> str:
    remaining = parse_iso(expires_at) - now_utc()
    seconds = max(0, int(remaining.total_seconds()))
    if seconds >= 86400:
        return f"{seconds / 86400:.1f}d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds // 60}m"


def show_queue(state_file: Path = DEFAULT_STATE_FILE) -> int:
    with state_lock(state_file):
        requests = list(load_state(state_file).get("requests", []))
    if not requests:
        print("[rent-pod] No queued availability requests.")
        return 0
    print(f"{'ID':<29} {'STATUS':<10} {'GPU':<24} {'REMAIN':>7} {'WINDOW':<12} LAST")
    print("-" * 110)
    for request in reversed(requests):
        probe = request.get("probe") or {}
        gpu = str(probe.get("gpu_label") or probe.get("gpu_id") or "-")
        status = str(request.get("status") or "-")
        remaining = "-" if status in FINAL_STATES else _format_remaining(str(request["expires_at"]))
        window = str(request.get("window") or "any")
        last = str(request.get("last_error") or request.get("pod_id") or "-")
        print(
            f"{str(request.get('id') or '-'):<29.29} {status:<10.10} {gpu:<24.24} "
            f"{remaining:>7} {window:<12.12} {last[:24]}"
        )
    return 0


def cancel_request(request_id: str, state_file: Path = DEFAULT_STATE_FILE) -> int:
    with state_lock(state_file):
        state = load_state(state_file)
        matches = [r for r in state.get("requests", []) if r.get("id") == request_id]
        if not matches:
            raise ValueError(f"queued request not found: {request_id}")
        request = matches[0]
        if request.get("status") in FINAL_STATES:
            print(f"[rent-pod] Request {request_id} is already {request.get('status')}.")
            return 0
        request["status"] = "cancelled"
        request["last_error"] = "cancelled by user"
        save_state(state, state_file)
    print(f"[rent-pod] Cancelled queued request {request_id}.")
    return 0


def handle_queue_meta_command(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> int | None:
    env = environ if environ is not None else os.environ
    if "--queued" in argv:
        if argv != ["--queued"]:
            raise ValueError("--queued cannot be combined with other options")
        with state_lock(DEFAULT_STATE_FILE):
            active = any(
                request.get("status") in ACTIVE_STATES
                for request in load_state(DEFAULT_STATE_FILE).get("requests", [])
            )
        if active:
            spawn_worker(DEFAULT_STATE_FILE, DEFAULT_LOG_FILE, env)
        return show_queue()

    cancel_value: str | None = None
    extras: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--cancel-queued":
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--cancel-queued requires a request ID")
            cancel_value = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--cancel-queued="):
            cancel_value = arg.split("=", 1)[1].strip()
            i += 1
            continue
        extras.append(arg)
        i += 1
    if cancel_value is None:
        return None
    if not cancel_value:
        raise ValueError("--cancel-queued requires a request ID")
    if extras:
        raise ValueError("--cancel-queued cannot be combined with other options")
    return cancel_request(cancel_value)


def _graphql_availability(api_key: str, probe: dict[str, Any]) -> tuple[bool, str]:
    cloud = str(probe.get("cloud") or "SECURE").upper()
    secure = "true" if cloud == "SECURE" else "false"
    price_args = [
        "gpuCount: 1",
        f"secureCloud: {secure}",
        "supportPublicIp: true",
        f"minDownload: {int(float(probe.get('min_download') or 0))}",
        f"minUpload: {int(float(probe.get('min_upload') or 0))}",
    ]
    min_disk = probe.get("min_disk")
    if min_disk is not None:
        price_args.append(f"minDisk: {int(float(min_disk))}")
    cuda_min = str(probe.get("cuda_min") or "").strip()
    if cuda_min:
        price_args.append(f"minCudaVersion: {json.dumps(cuda_min)}")
    query = f"""
query rentPodAvailability {{
  gpuTypes {{
    id
    displayName
    lowestPrice(input: {{ {', '.join(price_args)} }}) {{
      stockStatus
      availableGpuCounts
    }}
  }}
}}
"""
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": {}}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"availability API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"availability API failed: {exc.reason}") from exc

    if result.get("errors"):
        raise RuntimeError(f"availability API errors: {json.dumps(result['errors'])}")
    data = result.get("data") or {}
    rows = data.get("gpuTypes") or []
    wanted = str(probe.get("gpu_id") or "").casefold()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").casefold() != wanted:
            continue
        lowest = row.get("lowestPrice") or {}
        status = str(lowest.get("stockStatus") or "NONE").upper()
        counts = lowest.get("availableGpuCounts") or []
        available = status not in {"NONE", "UNAVAILABLE", "UNKNOWN", "N/A", "OUT OF STOCK"}
        if counts and 1 not in counts:
            available = False
        return available, status
    return False, "GPU_NOT_FOUND"


def availability_decision(request: dict[str, Any]) -> str:
    """Future approval hook; auto mode launches immediately today."""
    approval = request.get("approval") or {}
    return "launch" if approval.get("mode", "auto") == "auto" else "defer"


def _run_launch(request: dict[str, Any], log_file: Path) -> tuple[int, str | None, str]:
    entry = Path(__file__).resolve().with_name("rent_pod_entry.py")
    command = [sys.executable, str(entry), *[str(v) for v in request.get("argv", [])]]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )
    output = result.stdout or ""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== queue launch {request.get('id')} rc={result.returncode} =====\n")
        handle.write(output)
        if output and not output.endswith("\n"):
            handle.write("\n")
    match = POD_ID_RE.search(output)
    return result.returncode, match.group(1) if match else None, output


def _update_request(state_file: Path, request_id: str, **updates: Any) -> dict[str, Any] | None:
    with state_lock(state_file):
        state = load_state(state_file)
        for request in state.get("requests", []):
            if request.get("id") == request_id:
                request.update(updates)
                save_state(state, state_file)
                return dict(request)
    return None


def _process_request(request: dict[str, Any], state_file: Path, log_file: Path) -> None:
    request_id = str(request["id"])
    if request.get("status") == "launching":
        _update_request(
            state_file,
            request_id,
            status="attention",
            last_error="worker recovered an interrupted launch; refusing automatic retry to avoid a duplicate Pod",
        )
        _append_log(f"{request_id}: recovered interrupted launch; manual attention", log_file)
        return

    now = now_utc()
    if parse_iso(str(request["expires_at"])) <= now:
        _update_request(state_file, request_id, status="expired", last_error="subscription window expired")
        _append_log(f"{request_id}: expired", log_file)
        return
    if not window_allows(request.get("window")):
        return
    next_attempt = parse_iso(str(request.get("next_attempt_at") or request["created_at"]))
    if next_attempt > now:
        return

    api_key = (os.environ.get("RUNPOD_API_KEY") or "").strip()
    if not api_key:
        _update_request(
            state_file,
            request_id,
            last_checked_at=iso(now),
            last_error="RUNPOD_API_KEY missing in queue worker environment",
            next_attempt_at=iso(now + timedelta(seconds=int(request.get("check_every") or 60))),
        )
        return

    try:
        available, stock = _graphql_availability(api_key, dict(request.get("probe") or {}))
    except Exception as exc:
        _update_request(
            state_file,
            request_id,
            last_checked_at=iso(now),
            last_error=str(exc),
            next_attempt_at=iso(now + timedelta(seconds=int(request.get("check_every") or 60))),
        )
        _append_log(f"{request_id}: availability probe error: {exc}", log_file)
        return

    updates: dict[str, Any] = {
        "last_checked_at": iso(now),
        "last_error": None if available else f"stock={stock}",
        "next_attempt_at": iso(now + timedelta(seconds=int(request.get("check_every") or 60))),
    }
    if not available:
        _update_request(state_file, request_id, **updates)
        return

    updates["available_at"] = request.get("available_at") or iso(now)
    decision = availability_decision(request)
    if decision != "launch":
        updates["last_error"] = f"availability action deferred: {decision}"
        _update_request(state_file, request_id, **updates)
        return

    current = _update_request(
        state_file,
        request_id,
        **updates,
        status="launching",
        attempt_count=int(request.get("attempt_count") or 0) + 1,
    )
    if not current or current.get("status") != "launching":
        return

    _append_log(f"{request_id}: capacity available ({stock}); launching", log_file)
    rc, pod_id, _output = _run_launch(current, log_file)
    finished = now_utc()
    if rc == 0:
        _update_request(
            state_file,
            request_id,
            status="launched",
            launched_at=iso(finished),
            pod_id=pod_id,
            last_error=None,
        )
        _append_log(f"{request_id}: launch succeeded pod={pod_id or 'unknown'}", log_file)
        return

    if pod_id:
        _update_request(
            state_file,
            request_id,
            status="attention",
            pod_id=pod_id,
            last_error=f"rent-pod exited rc={rc} after Pod creation; not retrying automatically",
        )
        _append_log(f"{request_id}: launch rc={rc} with pod={pod_id}; manual attention", log_file)
        return

    if rc == 2:
        _update_request(
            state_file,
            request_id,
            status="failed",
            last_error="rent-pod rejected queued command (rc=2); see queue log",
        )
        _append_log(f"{request_id}: launch command invalid rc=2", log_file)
        return

    delay = max(int(request.get("check_every") or 60), 60)
    _update_request(
        state_file,
        request_id,
        status="pending",
        last_error=f"launch race/failure rc={rc}; retrying while subscription remains active",
        next_attempt_at=iso(finished + timedelta(seconds=delay)),
    )
    _append_log(f"{request_id}: launch rc={rc} before Pod creation; returned to pending", log_file)


def worker_main(state_file: Path = DEFAULT_STATE_FILE, log_file: Path = DEFAULT_LOG_FILE) -> int:
    state_file, _state_lock_path, worker_lock = state_paths(state_file)
    worker_lock.parent.mkdir(parents=True, exist_ok=True)
    with worker_lock.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        _append_log(f"worker started for {state_file}", log_file)
        while True:
            with state_lock(state_file):
                requests = [
                    dict(request)
                    for request in load_state(state_file).get("requests", [])
                    if request.get("status") in ACTIVE_STATES
                ]
            if not requests:
                _append_log("worker exiting: no active requests", log_file)
                return 0
            for request in requests:
                try:
                    _process_request(request, state_file, log_file)
                except Exception as exc:
                    _append_log(f"{request.get('id')}: worker error: {exc}", log_file)
            time.sleep(15)


def _main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--worker":
        return worker_main(Path(argv[1]).expanduser())
    print("rent_pod_queue.py is an internal rent-pod helper", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
