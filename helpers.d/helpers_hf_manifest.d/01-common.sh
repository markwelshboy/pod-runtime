#!/usr/bin/env bash
# ======================================================================
# Background Hugging Face manifest downloader with durable status.
#
# Public functions:
#   hf_download_from_manifest [manifest]
#   hf_download_status_json [state_dir]
#   hf_download_show_snapshot [state_dir]
#   hf_download_monitor_progress [interval] [log] [state_dir]
#   hf_download_is_active [state_dir]
#   hf_download_wait [state_dir]
#   hf_download_stop [state_dir]
#
# Set HF_DOWNLOADER=true to transparently route the existing bootstrap
# aria2 manifest calls through this downloader. CivitAI remains on aria2.
# ======================================================================

: "${HF_DOWNLOADER:=false}"
: "${HF_MANIFEST_STATE_DIR:=${COMFY_LOGS:-/workspace/logs}/hf_manifest}"
: "${HF_MANIFEST_PROGRESS_INTERVAL:=${ARIA2_PROGRESS_INTERVAL:-60}}"
: "${HF_MANIFEST_PROGRESS_BAR_WIDTH:=40}"
: "${HF_MANIFEST_COMPLETED_MAX:=20}"
: "${HF_MANIFEST_METADATA_JOBS:=8}"
: "${HF_MANIFEST_METADATA_TIMEOUT:=20}"
: "${HF_MANIFEST_DOWNLOAD_TIMEOUT:=120}"
: "${HF_MANIFEST_KEEP_WORK:=0}"
: "${HF_XET_HIGH_PERFORMANCE:=1}"

export HF_DOWNLOADER HF_MANIFEST_STATE_DIR HF_MANIFEST_PROGRESS_INTERVAL
export HF_MANIFEST_PROGRESS_BAR_WIDTH HF_MANIFEST_COMPLETED_MAX
export HF_MANIFEST_METADATA_JOBS HF_MANIFEST_METADATA_TIMEOUT
export HF_MANIFEST_DOWNLOAD_TIMEOUT HF_MANIFEST_KEEP_WORK
export HF_XET_HIGH_PERFORMANCE

_hf_manifest_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_hf_manifest_enabled() {
  _hf_manifest_true "${HF_DOWNLOADER:-false}"
}

_hf_manifest_python() {
  if [[ -x "${HFF_VENV:-}/bin/python" ]]; then
    printf '%s\n' "${HFF_VENV}/bin/python"
  elif [[ -x "${PY_BIN:-}" ]]; then
    printf '%s\n' "${PY_BIN}"
  elif [[ -x "${PY:-}" ]]; then
    printf '%s\n' "${PY}"
  else
    command -v python3 || command -v python
  fi
}

_hf_manifest_cli() {
  if [[ -x "${HFF_VENV:-}/bin/hf" ]]; then
    printf '%s\n' "${HFF_VENV}/bin/hf"
  elif command -v hf >/dev/null 2>&1; then
    command -v hf
  elif command -v huggingface-cli >/dev/null 2>&1; then
    command -v huggingface-cli
  else
    return 1
  fi
}

_hf_manifest_state_dir() {
  printf '%s\n' "${1:-${HF_MANIFEST_STATE_DIR}}"
}

_hf_manifest_atomic_jq() {
  local file="${1:?file}" filter="${2:?filter}"
  shift 2
  local tmp="${file}.tmp.${BASHPID:-$$}"
  jq "$@" "$filter" "$file" >"$tmp" && mv -f -- "$tmp" "$file"
}

_hf_manifest_set_item_status() {
  local item="${1:?item}" status="${2:?status}"
  local message="${3:-}" completed_bytes="${4:-0}"
  local now
  now="$(date -Is)"

  _hf_manifest_atomic_jq "$item" '
    .status = $status
    | .message = $message
    | .completed_bytes = $completed_bytes
    | if $status == "running" then
        .started_at = (.started_at // $now)
      elif ($status == "completed" or $status == "failed") then
        .finished_at = $now
      else . end
  ' --arg status "$status" --arg message "$message" --arg now "$now" \
    --argjson completed_bytes "$completed_bytes"
}

_hf_manifest_set_controller_status() {
  local state="${1:?state}" status="${2:?status}"
  local failures="${3:-0}" message="${4:-}"
  local file="${state}/controller.json" now tmp
  now="$(date -Is)"
  tmp="${file}.tmp.${BASHPID:-$$}"

  if [[ -f "$file" ]]; then
    jq \
      --arg status "$status" \
      --arg message "$message" \
      --arg now "$now" \
      --argjson pid "${BASHPID:-$$}" \
      --argjson failures "$failures" \
      '.status=$status | .pid=$pid | .failures=$failures | .message=$message | .updated_at=$now' \
      "$file" >"$tmp"
  else
    jq -n \
      --arg status "$status" \
      --arg message "$message" \
      --arg now "$now" \
      --argjson pid "${BASHPID:-$$}" \
      --argjson failures "$failures" \
      '{status:$status,pid:$pid,failures:$failures,message:$message,created_at:$now,updated_at:$now}' \
      >"$tmp"
  fi
  mv -f -- "$tmp" "$file"
}

_hf_manifest_plan() {
  local manifest="${1:?manifest}" state="${2:?state}"
  local py
  py="$(_hf_manifest_python)" || {
    echo "[hf-manifest] No Python interpreter available." >&2
    return 1
  }

  HF_MANIFEST_PLAN_FILE="$manifest" \
  HF_MANIFEST_PLAN_STATE="$state" \
  "$py" - <<'PY'
import concurrent.futures
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

manifest_path = Path(os.environ["HF_MANIFEST_PLAN_FILE"])
state = Path(os.environ["HF_MANIFEST_PLAN_STATE"])
items_dir = state / "items"
logs_dir = state / "item_logs"
work_root = state / "work"
items_dir.mkdir(parents=True, exist_ok=True)
logs_dir.mkdir(parents=True, exist_ok=True)
work_root.mkdir(parents=True, exist_ok=True)

with manifest_path.open("r", encoding="utf-8") as fh:
    manifest = json.load(fh)

truthy = {"1", "true", "yes", "on"}
def is_true(value):
    return str(value or "").strip().lower() in truthy

token_re = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
values = dict(os.environ)

def resolve(value):
    text = str(value)
    for _ in range(20):
        changed = False
        def repl(match):
            nonlocal changed
            key = match.group(1)
            if key in values:
                changed = True
                return str(values[key])
            return match.group(0)
        new = token_re.sub(repl, text)
        text = new
        if not changed:
            break
    return text

for block_name in ("vars", "paths"):
    for key, raw in (manifest.get(block_name) or {}).items():
        if key not in values:
            values[key] = resolve(raw)
    # Resolve again now that the whole block is visible.
    for key in (manifest.get(block_name) or {}):
        values[key] = resolve(values[key])

sections = manifest.get("sections") or {}
enabled = []
for section in sections:
    if is_true(os.environ.get(section)) or is_true(os.environ.get(f"download_{section}")):
        enabled.append(section)

def normalize_entry(entry):
    if isinstance(entry, dict):
        url = str(entry.get("url") or "")
        path = entry.get("path")
        if not path:
            path = str(entry.get("dir") or "")
            if entry.get("out"):
                path = f"{path.rstrip('/')}/{entry['out']}"
        size = entry.get("bytes", entry.get("size", entry.get("total_bytes", 0)))
    elif isinstance(entry, list):
        url = str(entry[0] if len(entry) > 0 else "")
        path = str(entry[1] if len(entry) > 1 else "")
        size = entry[2] if len(entry) > 2 else 0
    elif isinstance(entry, str):
        url, path, size = entry, "", 0
    else:
        return None
    if not url:
        return None
    if not path:
        path = url.rsplit("/", 1)[-1]
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    return {"url": url, "path": resolve(path), "declared_bytes": max(size, 0)}

def parse_hf_url(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"huggingface.co", "www.huggingface.co"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    repo_type = "model"
    if parts and parts[0] in {"datasets", "spaces"}:
        repo_type = "dataset" if parts[0] == "datasets" else "space"
        parts = parts[1:]
    if len(parts) < 5 or parts[2] not in {"resolve", "blob", "raw"}:
        return None
    return {
        "repo_type": repo_type,
        "repo_id": f"{parts[0]}/{parts[1]}",
        "revision": parts[3],
        "repo_file": "/".join(parts[4:]),
    }

candidates = []
seen_paths = set()
for section in enabled:
    for raw in sections.get(section) or []:
        item = normalize_entry(raw)
        if not item:
            continue
        path = item["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        item["section"] = section
        parsed = parse_hf_url(item["url"])
        if parsed:
            item.update(parsed)
            item["transport"] = "hf"
        else:
            item.update({"repo_type": "", "repo_id": "", "revision": "", "repo_file": ""})
            item["transport"] = "http"
        candidates.append(item)

metadata_timeout = float(os.environ.get("HF_MANIFEST_METADATA_TIMEOUT", "20") or 20)
metadata_jobs = max(1, int(os.environ.get("HF_MANIFEST_METADATA_JOBS", "8") or 8))
token = os.environ.get("HF_TOKEN") or None

def fetch_size(item):
    if item["declared_bytes"] > 0:
        return item["declared_bytes"], "manifest", ""
    try:
        if item["transport"] == "hf":
            from huggingface_hub import get_hf_file_metadata
            try:
                meta = get_hf_file_metadata(item["url"], token=token, timeout=metadata_timeout)
            except TypeError:
                meta = get_hf_file_metadata(item["url"], token=token)
            return int(meta.size or 0), "hub", ""
        request = urllib.request.Request(item["url"], method="HEAD")
        with urllib.request.urlopen(request, timeout=metadata_timeout) as response:
            size = response.headers.get("Content-Length")
            if size and size.isdigit():
                return int(size), "http-head", ""
    except Exception as exc:  # Download can still be attempted with unknown size.
        return 0, "unknown", f"{type(exc).__name__}: {exc}"
    return 0, "unknown", "size unavailable"

with concurrent.futures.ThreadPoolExecutor(max_workers=metadata_jobs) as pool:
    metadata = list(pool.map(fetch_size, candidates))

order_lines = []
now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).astimezone().isoformat()
for index, (item, meta) in enumerate(zip(candidates, metadata), start=1):
    total_bytes, size_source, metadata_error = meta
    item_id = f"{index:04d}"
    final_path = Path(item["path"])
    existing_bytes = final_path.stat().st_size if final_path.is_file() else 0
    complete = final_path.is_file() and (total_bytes <= 0 or existing_bytes == total_bytes)
    status = "completed" if complete else "pending"
    message = "already present" if complete else ("existing file size differs; will replace" if existing_bytes else "")
    record = {
        "id": item_id,
        "section": item["section"],
        "url": item["url"],
        "path": str(final_path),
        "name": final_path.name,
        "display_dir": str(final_path.parent),
        "transport": item["transport"],
        "repo_type": item["repo_type"],
        "repo_id": item["repo_id"],
        "revision": item["revision"],
        "repo_file": item["repo_file"],
        "total_bytes": int(total_bytes),
        "size_source": size_source,
        "metadata_error": metadata_error,
        "status": status,
        "message": message,
        "completed_bytes": existing_bytes if complete else 0,
        "work_dir": str(work_root / item_id),
        "log": str(logs_dir / f"{item_id}-{final_path.name}.log"),
        "created_at": now,
        "started_at": None,
        "finished_at": now if complete else None,
    }
    item_path = items_dir / f"{item_id}.json"
    tmp = item_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    tmp.replace(item_path)
    order_lines.append(str(item_path))

(state / "items.list").write_text("\n".join(order_lines) + ("\n" if order_lines else ""), encoding="utf-8")
controller = {
    "status": "prepared",
    "pid": 0,
    "failures": 0,
    "message": "",
    "enabled_sections": enabled,
    "created_at": now,
    "updated_at": now,
}
(state / "controller.json").write_text(json.dumps(controller, indent=2) + "\n", encoding="utf-8")
summary = {
    "enabled_sections": enabled,
    "total": len(candidates),
    "already_present": sum(1 for item_path in order_lines if json.loads(Path(item_path).read_text())["status"] == "completed"),
    "pending": sum(1 for item_path in order_lines if json.loads(Path(item_path).read_text())["status"] == "pending"),
    "known_total_bytes": sum(m[0] for m in metadata if m[0] > 0),
    "unknown_sizes": sum(1 for m in metadata if m[0] <= 0),
}
print(json.dumps(summary))
PY
}
