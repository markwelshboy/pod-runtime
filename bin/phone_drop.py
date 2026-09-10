#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

SCHEMA_VERSION = 1
DEFAULT_BUCKET = "pod-phone-drop"
DEFAULT_PREFIX = "inbox"
DEFAULT_MAX_BYTES = 1_900_000_000


class PhoneDropError(RuntimeError):
    pass


def info(message: str) -> None:
    print(f"[send-phone] {message}", flush=True)


def worker_info(message: str) -> None:
    print(f"[phone-drop] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[phone-drop] WARN: {message}", file=sys.stderr, flush=True)


def die(message: str, code: int = 1) -> NoReturn:
    print(f"[phone-drop] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_string() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def human_bytes(value: int) -> str:
    n = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{value} B"


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def need_hf_token() -> str:
    token = env_first("PHONE_DROP_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")
    if not token:
        raise PhoneDropError("HF token is not set (PHONE_DROP_HF_TOKEN or HF_TOKEN)")
    return token


def normalize_prefix(raw: str) -> str:
    value = raw.strip().strip("/")
    if not value or value in {".", ".."} or ".." in value.split("/"):
        raise PhoneDropError(f"invalid PHONE_DROP_PREFIX: {raw!r}")
    return value


def safe_filename(name: str) -> str:
    base = Path(name).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._()\-+]+", "_", base).strip("._")
    return cleaned[:180] or "payload.bin"


def resolve_bucket(token: str, *, create: bool = True) -> str:
    configured = env_first("PHONE_DROP_BUCKET", default=DEFAULT_BUCKET)
    try:
        from huggingface_hub import bucket_info, create_bucket
    except ImportError as exc:
        raise PhoneDropError(
            "huggingface_hub with Storage Bucket support is required; use the send-phone wrapper or worker image"
        ) from exc

    if create:
        url = create_bucket(configured, private=True, exist_ok=True, token=token)
        bucket_id = str(url.bucket_id)
    else:
        bucket_id = configured

    try:
        meta = bucket_info(bucket_id, token=token)
    except Exception as exc:
        raise PhoneDropError(f"cannot access HF bucket {bucket_id}: {exc}") from exc
    if not bool(getattr(meta, "private", False)):
        raise PhoneDropError(f"HF bucket {bucket_id} is public; phone-drop requires a private bucket")
    return bucket_id


def source_metadata() -> dict[str, Any]:
    source: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "cwd": os.getcwd(),
    }
    optional = {
        "runpod_pod_id": env_first("RUNPOD_POD_ID", "RUNPOD_POD_ID_OVERRIDE"),
        "vast_container_label": env_first("CONTAINER_ID", "VAST_CONTAINERLABEL"),
        "telegram_name": env_first("TELEGRAM_NAME"),
    }
    source.update({k: v for k, v in optional.items() if v})
    return source


def make_job_id() -> str:
    return f"{now_utc().strftime('%Y%m%d_%H%M%S')}__{secrets.token_hex(4)}"


def enqueue(file_path: Path, caption: str, bucket_override: str | None = None) -> int:
    if bucket_override:
        os.environ["PHONE_DROP_BUCKET"] = bucket_override
    path = file_path.expanduser().resolve()
    if not path.exists():
        raise PhoneDropError(f"file not found: {path}")
    if not path.is_file():
        raise PhoneDropError(f"send-phone currently accepts files only; tar/zip the directory first: {path}")

    size = path.stat().st_size
    max_bytes = int(env_first("PHONE_DROP_MAX_BYTES", default=str(DEFAULT_MAX_BYTES)))
    if size <= 0:
        raise PhoneDropError(f"refusing to queue empty file: {path}")
    if size > max_bytes:
        raise PhoneDropError(
            f"file is {human_bytes(size)}, above configured limit {human_bytes(max_bytes)}"
        )

    token = need_hf_token()
    bucket_id = resolve_bucket(token)
    prefix = normalize_prefix(env_first("PHONE_DROP_PREFIX", default=DEFAULT_PREFIX))
    job_id = make_job_id()
    filename = safe_filename(path.name)
    job_prefix = f"{prefix}/{job_id}"
    payload_path = f"{job_prefix}/{filename}"
    ready_path = f"{job_prefix}/ready.json"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "id": job_id,
        "filename": filename,
        "payload_path": payload_path,
        "bytes": size,
        "caption": caption.strip(),
        "created_utc": utc_string(),
        "source": source_metadata(),
    }

    try:
        from huggingface_hub import batch_bucket_files
    except ImportError as exc:
        raise PhoneDropError("huggingface_hub Storage Bucket APIs are unavailable") from exc

    info(f"{path.name} ({human_bytes(size)})")
    info(f"HF bucket: {bucket_id}")
    info("uploading payload...")
    batch_bucket_files(bucket_id, add=[(path, payload_path)], token=token)
    info("payload uploaded; publishing ready marker...")
    batch_bucket_files(
        bucket_id,
        add=[(json.dumps(manifest, indent=2).encode("utf-8"), ready_path)],
        token=token,
    )
    info(f"queued ✓  {job_id}")
    info("safe to terminate the pod")
    return 0


def _bucket_files(bucket_id: str, token: str, prefix: str) -> dict[str, Any]:
    try:
        from huggingface_hub import list_bucket_tree
    except ImportError as exc:
        raise PhoneDropError("huggingface_hub Storage Bucket APIs are unavailable") from exc
    found: dict[str, Any] = {}
    for item in list_bucket_tree(bucket_id, prefix=prefix, recursive=True, token=token):
        if getattr(item, "type", None) == "file":
            found[str(item.path)] = item
    return found


def _download(bucket_id: str, token: str, remote_path: str, local_path: Path) -> None:
    try:
        from huggingface_hub import download_bucket_files
    except ImportError as exc:
        raise PhoneDropError("huggingface_hub Storage Bucket APIs are unavailable") from exc
    local_path.parent.mkdir(parents=True, exist_ok=True)
    download_bucket_files(
        bucket_id,
        files=[(remote_path, local_path)],
        raise_on_missing_files=True,
        token=token,
    )


def _upload_json(bucket_id: str, token: str, remote_path: str, payload: dict[str, Any]) -> None:
    from huggingface_hub import batch_bucket_files

    batch_bucket_files(
        bucket_id,
        add=[(json.dumps(payload, indent=2).encode("utf-8"), remote_path)],
        token=token,
    )


def _delete_paths(bucket_id: str, token: str, paths: list[str]) -> None:
    if not paths:
        return
    from huggingface_hub import batch_bucket_files

    batch_bucket_files(bucket_id, delete=paths, token=token)


def _load_ready(bucket_id: str, token: str, ready_path: str, spool: Path) -> dict[str, Any]:
    parts = ready_path.split("/")
    if len(parts) < 3 or parts[-1] != "ready.json":
        raise PhoneDropError(f"invalid ready marker path: {ready_path}")
    job_id = parts[-2]
    local = spool / job_id / "ready.json"
    _download(bucket_id, token, ready_path, local)
    try:
        raw = json.loads(local.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhoneDropError(f"invalid ready marker {ready_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise PhoneDropError(f"unsupported ready marker schema: {ready_path}")
    if raw.get("id") != job_id:
        raise PhoneDropError(f"job id mismatch in {ready_path}")
    return raw


def _telegram_config() -> tuple[str, str, str, str]:
    token = env_first("PHONE_DROP_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN")
    chat_id = env_first("PHONE_DROP_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID", "TG_CHAT_ID")
    api_base = env_first("TELEGRAM_API_BASE", default="http://telegram-bot:8081").rstrip("/")
    local_root = env_first("TELEGRAM_LOCAL_FILE_ROOT", default="/phone-drop").rstrip("/")
    if not token:
        raise PhoneDropError("Telegram bot token is not set")
    if not chat_id:
        raise PhoneDropError("Telegram chat id is not set")
    return token, chat_id, api_base, local_root


def _telegram_post(method: str, data: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise PhoneDropError("requests is required by the delivery worker") from exc
    token, _, api_base, _ = _telegram_config()
    url = f"{api_base}/bot{token}/{method}"
    response = requests.post(url, data=data, timeout=timeout)
    try:
        payload = response.json()
    except ValueError as exc:
        raise PhoneDropError(f"Telegram {method} returned HTTP {response.status_code} with non-JSON response") from exc
    if not response.ok or not payload.get("ok"):
        description = payload.get("description") or response.text[:300]
        raise PhoneDropError(f"Telegram {method} failed: HTTP {response.status_code}: {description}")
    return payload


def telegram_check() -> None:
    timeout = int(env_first("PHONE_DROP_TELEGRAM_TIMEOUT", default="3600"))
    payload = _telegram_post("getMe", {}, timeout=min(timeout, 30))
    user = payload.get("result") or {}
    worker_info(f"Telegram bot: @{user.get('username', '?')}")


def telegram_send(local_path: Path, manifest: dict[str, Any], spool: Path) -> dict[str, Any]:
    _, chat_id, _, local_root = _telegram_config()
    timeout = int(env_first("PHONE_DROP_TELEGRAM_TIMEOUT", default="3600"))

    try:
        rel = local_path.resolve().relative_to(spool.resolve())
    except ValueError as exc:
        raise PhoneDropError(f"spool file is outside configured spool: {local_path}") from exc
    telegram_path = f"{local_root}/{rel.as_posix()}"

    caption = str(manifest.get("caption") or "").strip()
    source = manifest.get("source") or {}
    source_name = str(source.get("telegram_name") or source.get("hostname") or "").strip()
    if source_name:
        caption = f"{caption}\n\nFrom: {source_name}" if caption else f"From: {source_name}"
    caption = caption[:1024]

    data: dict[str, Any] = {
        "chat_id": chat_id,
        "document": f"file://{telegram_path}",
    }
    if caption:
        data["caption"] = caption
    return _telegram_post("sendDocument", data, timeout=timeout)


def _cleanup_completed_job(
    bucket_id: str,
    token: str,
    job_prefix: str,
    files: dict[str, Any],
    spool_job: Path,
) -> None:
    delivered_path = f"{job_prefix}/delivered.json"
    other_paths = sorted(path for path in files if path.startswith(job_prefix + "/") and path != delivered_path)
    if other_paths:
        _delete_paths(bucket_id, token, other_paths)
    current = _bucket_files(bucket_id, token, job_prefix)
    remaining_other = [path for path in current if path != delivered_path]
    if remaining_other:
        raise PhoneDropError(f"cleanup incomplete for {job_prefix}: {remaining_other}")
    if delivered_path in current:
        _delete_paths(bucket_id, token, [delivered_path])

    if spool_job.exists():
        for child in sorted(spool_job.rglob("*"), reverse=True):
            try:
                child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
            except OSError:
                pass
        try:
            spool_job.rmdir()
        except OSError:
            pass


def deliver_one(
    bucket_id: str,
    token: str,
    prefix: str,
    ready_path: str,
    files: dict[str, Any],
    spool: Path,
) -> None:
    job_prefix = ready_path.rsplit("/", 1)[0]
    job_id = job_prefix.rsplit("/", 1)[-1]
    delivered_path = f"{job_prefix}/delivered.json"
    spool_job = spool / job_id
    local_delivered = spool_job / "delivered.json"

    if delivered_path in files or local_delivered.exists():
        worker_info(f"{job_id}: already delivered; finishing cleanup")
        if delivered_path not in files and local_delivered.exists():
            try:
                delivered = json.loads(local_delivered.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                delivered = {
                    "schema_version": SCHEMA_VERSION,
                    "id": job_id,
                    "delivered_utc": utc_string(),
                    "recovered_from_local_marker": True,
                }
            _upload_json(bucket_id, token, delivered_path, delivered)
            files = _bucket_files(bucket_id, token, job_prefix)
        _cleanup_completed_job(bucket_id, token, job_prefix, files, spool_job)
        return

    manifest = _load_ready(bucket_id, token, ready_path, spool)
    payload_path = str(manifest.get("payload_path") or "")
    expected_prefix = job_prefix + "/"
    if not payload_path.startswith(expected_prefix) or payload_path.endswith("/"):
        raise PhoneDropError(f"{job_id}: unsafe payload path in ready marker: {payload_path!r}")
    if payload_path not in files:
        raise PhoneDropError(f"{job_id}: ready marker exists but payload is missing: {payload_path}")

    filename = safe_filename(str(manifest.get("filename") or Path(payload_path).name))
    local_payload = spool_job / filename
    expected_bytes = int(manifest.get("bytes") or 0)
    if not local_payload.exists() or (expected_bytes and local_payload.stat().st_size != expected_bytes):
        worker_info(f"{job_id}: downloading {filename} ({human_bytes(expected_bytes)})")
        _download(bucket_id, token, payload_path, local_payload)
    actual_bytes = local_payload.stat().st_size
    if expected_bytes and actual_bytes != expected_bytes:
        raise PhoneDropError(
            f"{job_id}: downloaded size mismatch: expected {expected_bytes}, got {actual_bytes}"
        )
    local_payload.chmod(0o644)
    spool_job.chmod(0o755)

    worker_info(f"{job_id}: sending {filename} to Telegram")
    telegram_result = telegram_send(local_payload, manifest, spool)
    message = telegram_result.get("result") or {}
    delivered = {
        "schema_version": SCHEMA_VERSION,
        "id": job_id,
        "delivered_utc": utc_string(),
        "telegram_message_id": message.get("message_id"),
    }
    spool_job.mkdir(parents=True, exist_ok=True)
    local_delivered.write_text(json.dumps(delivered, indent=2) + "\n", encoding="utf-8")
    local_delivered.chmod(0o644)
    _upload_json(bucket_id, token, delivered_path, delivered)
    worker_info(f"{job_id}: Telegram delivery confirmed; cleaning HF queue")
    refreshed = _bucket_files(bucket_id, token, job_prefix)
    _cleanup_completed_job(bucket_id, token, job_prefix, refreshed, spool_job)
    worker_info(f"{job_id}: complete ✓")


def worker_once(bucket_id: str, token: str, spool: Path) -> int:
    prefix = normalize_prefix(env_first("PHONE_DROP_PREFIX", default=DEFAULT_PREFIX))
    files = _bucket_files(bucket_id, token, prefix)
    ready = sorted(path for path in files if path.endswith("/ready.json"))

    delivered = sorted(path for path in files if path.endswith("/delivered.json"))
    delivered_jobs = {path.rsplit("/", 1)[0] for path in delivered}
    ready_jobs = {path.rsplit("/", 1)[0] for path in ready}
    for job_prefix in sorted(delivered_jobs - ready_jobs):
        job_id = job_prefix.rsplit("/", 1)[-1]
        try:
            worker_info(f"{job_id}: found delivered marker without ready marker; finishing cleanup")
            _cleanup_completed_job(bucket_id, token, job_prefix, files, spool / job_id)
        except Exception as exc:
            warn(f"{job_id}: cleanup retry failed: {exc}")

    handled = 0
    for ready_path in ready:
        try:
            deliver_one(bucket_id, token, prefix, ready_path, files, spool)
            handled += 1
            files = _bucket_files(bucket_id, token, prefix)
        except Exception as exc:
            job_id = ready_path.rsplit("/", 2)[-2]
            warn(f"{job_id}: delivery failed; queue retained for retry: {exc}")
    return handled


def run_worker(once: bool = False) -> int:
    token = need_hf_token()
    bucket_id = resolve_bucket(token)
    spool = Path(env_first("PHONE_DROP_SPOOL", default="/spool")).expanduser().resolve()
    spool.mkdir(parents=True, exist_ok=True)
    spool.chmod(0o755)
    poll = max(5, int(env_first("PHONE_DROP_POLL_SECONDS", default="20")))

    worker_info(f"HF bucket: {bucket_id}")
    worker_info(f"spool: {spool}")
    telegram_check()
    worker_info(f"polling every {poll}s")

    while True:
        try:
            worker_once(bucket_id, token, spool)
        except KeyboardInterrupt:
            worker_info("stopped")
            return 0
        except Exception as exc:
            warn(f"poll failed: {exc}")
        if once:
            return 0
        time.sleep(poll)


def cmd_enqueue(args: argparse.Namespace) -> int:
    return enqueue(Path(args.file), args.caption or "", args.bucket)


def cmd_worker(args: argparse.Namespace) -> int:
    if args.bucket:
        os.environ["PHONE_DROP_BUCKET"] = args.bucket
    return run_worker(once=args.once)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phone-drop")
    sub = parser.add_subparsers(dest="command", required=True)

    enqueue_p = sub.add_parser("enqueue", help="queue a local file for delivery to the configured phone")
    enqueue_p.add_argument("file")
    enqueue_p.add_argument("--caption", "-c", default="")
    enqueue_p.add_argument("--bucket", default="")
    enqueue_p.set_defaults(func=cmd_enqueue)

    worker_p = sub.add_parser("worker", help="poll HF and deliver queued files through Telegram")
    worker_p.add_argument("--once", action="store_true", help="perform one poll and exit")
    worker_p.add_argument("--bucket", default="")
    worker_p.set_defaults(func=cmd_worker)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PhoneDropError as exc:
        die(str(exc))
    except KeyboardInterrupt:
        die("interrupted", 130)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
