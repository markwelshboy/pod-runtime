#!/usr/bin/env bash
# ======================================================================
# Approximate Hugging Face manifest download throughput.
#
# This layer intentionally leaves the download workers untouched. It samples
# the already-observed work-tree byte counts exposed by 03-status.sh and adds:
#   - per-item average throughput since the item started
#   - per-item recent throughput between status samples
#   - aggregate active throughput across concurrent streams
#
# Recent speed is approximate and is based on file growth, not NIC counters.
# ======================================================================

: "${HF_MANIFEST_SPEED_MIN_INTERVAL:=3}"
: "${HF_MANIFEST_SPEED_STALE_AFTER:=120}"
: "${HF_MANIFEST_SPEED_COMPLETED_MAX:=5}"
export HF_MANIFEST_SPEED_MIN_INTERVAL HF_MANIFEST_SPEED_STALE_AFTER
export HF_MANIFEST_SPEED_COMPLETED_MAX

# Preserve the state-reader defined by 03-status.sh, then enrich its JSON.
if declare -F _hf_download_status_json_state >/dev/null 2>&1 \
   && ! declare -F _hf_download_status_json_state_without_speed >/dev/null 2>&1; then
  eval "$(declare -f _hf_download_status_json_state \
    | sed '1s/^_hf_download_status_json_state[[:space:]]*()/_hf_download_status_json_state_without_speed ()/')"
fi

_hf_download_status_json_state() {
  local state="${1:?state directory}" raw py
  raw="$(_hf_download_status_json_state_without_speed "$state")" || return 1

  # Missing/not-yet-started scopes have nothing useful to sample.
  if [[ "$(jq -r '.exists // false' <<<"$raw")" != "true" ]]; then
    printf '%s\n' "$raw"
    return 0
  fi

  py="$(_hf_manifest_python)" || return 1

  printf '%s\n' "$raw" | \
    HF_MANIFEST_SPEED_STATE="$state" \
    HF_MANIFEST_SPEED_MIN_INTERVAL="${HF_MANIFEST_SPEED_MIN_INTERVAL:-3}" \
    HF_MANIFEST_SPEED_STALE_AFTER="${HF_MANIFEST_SPEED_STALE_AFTER:-120}" \
    "$py" -c '
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

payload = json.load(sys.stdin)
state = Path(os.environ["HF_MANIFEST_SPEED_STATE"])
sample_path = state / "speed-sample.json"

try:
    min_interval = max(0.1, float(os.environ.get("HF_MANIFEST_SPEED_MIN_INTERVAL", "3") or 3))
except (TypeError, ValueError):
    min_interval = 3.0
try:
    stale_after = max(min_interval, float(os.environ.get("HF_MANIFEST_SPEED_STALE_AFTER", "120") or 120))
except (TypeError, ValueError):
    stale_after = 120.0

now = time.time()
previous = {}
try:
    previous = json.loads(sample_path.read_text(encoding="utf-8"))
except Exception:
    previous = {}

try:
    previous_ts = float(previous.get("timestamp") or 0)
except (TypeError, ValueError):
    previous_ts = 0.0
sample_age = now - previous_ts if previous_ts > 0 else None
previous_valid = sample_age is not None and 0 <= sample_age <= stale_after
advance_sample = (not previous_valid) or sample_age >= min_interval
previous_items = previous.get("items") if isinstance(previous.get("items"), dict) else {}

def parse_time(value):
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None

running_sample = {}
active_average = 0.0
active_recent = 0.0
active_recent_ready = 0
active_recent_warming = 0

for item in payload.get("items") or []:
    status = str(item.get("status") or "")
    item_id = str(item.get("id") or item.get("path") or item.get("name") or "")
    try:
        observed = max(0, int(item.get("observed_bytes") or 0))
    except (TypeError, ValueError):
        observed = 0

    started_at = item.get("started_at")
    start_ts = parse_time(started_at)
    if status in {"completed", "failed"}:
        end_ts = parse_time(item.get("finished_at")) or now
    else:
        end_ts = now

    elapsed = max(0.0, end_ts - start_ts) if start_ts is not None else 0.0
    average_bps = observed / elapsed if observed > 0 and elapsed > 0 else 0.0

    recent_bps = 0.0
    warming_up = status == "running"
    recent_sample_seconds = 0.0

    if status == "running" and previous_valid:
        prev = previous_items.get(item_id) if isinstance(previous_items.get(item_id), dict) else None
        same_run = prev is not None and prev.get("started_at") == started_at
        if same_run:
            if advance_sample:
                try:
                    previous_bytes = max(0, int(prev.get("observed_bytes") or 0))
                except (TypeError, ValueError):
                    previous_bytes = 0
                delta = observed - previous_bytes
                if delta >= 0 and sample_age and sample_age > 0:
                    recent_bps = delta / sample_age
                    recent_sample_seconds = sample_age
                    warming_up = False
            else:
                try:
                    recent_bps = max(0.0, float(prev.get("recent_bytes_per_sec") or 0))
                except (TypeError, ValueError):
                    recent_bps = 0.0
                warming_up = bool(prev.get("warming_up", True))
                try:
                    recent_sample_seconds = max(0.0, float(prev.get("recent_sample_seconds") or 0))
                except (TypeError, ValueError):
                    recent_sample_seconds = 0.0

    item["elapsed_seconds"] = round(elapsed, 1)
    item["average_bytes_per_sec"] = int(round(average_bps))
    item["recent_bytes_per_sec"] = int(round(recent_bps))
    item["recent_sample_seconds"] = round(recent_sample_seconds, 2)
    item["recent_warming_up"] = bool(warming_up)

    if status == "running":
        active_average += average_bps
        if warming_up:
            active_recent_warming += 1
        else:
            active_recent += recent_bps
            active_recent_ready += 1
        running_sample[item_id] = {
            "observed_bytes": observed,
            "started_at": started_at,
            "recent_bytes_per_sec": int(round(recent_bps)),
            "recent_sample_seconds": round(recent_sample_seconds, 2),
            "warming_up": bool(warming_up),
        }

payload["active_average_bytes_per_sec"] = int(round(active_average))
payload["active_recent_bytes_per_sec"] = int(round(active_recent))
payload["active_recent_ready_streams"] = active_recent_ready
payload["active_recent_warming_streams"] = active_recent_warming
payload["speed_sample_age_seconds"] = round(sample_age, 2) if previous_valid and sample_age is not None else None

# Do not move the baseline forward on rapid repeated status calls; otherwise
# polling faster than the minimum interval would permanently prevent a useful
# recent-speed sample from forming. Clear stale samples when nothing is running.
if advance_sample or not running_sample:
    sample = {
        "timestamp": now,
        "items": running_sample,
    }
    try:
        state.mkdir(parents=True, exist_ok=True)
        tmp = sample_path.with_name(f"{sample_path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(sample, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(tmp, sample_path)
    except OSError:
        # Status reporting should not fail just because the optional speed
        # sample cannot be persisted.
        pass

print(json.dumps(payload, separators=(",", ":")))
'
}

# Preserve the scope aggregator, then add aggregate speed fields to its result.
if declare -F _hf_download_snapshot_aggregate >/dev/null 2>&1 \
   && ! declare -F _hf_download_snapshot_aggregate_without_speed >/dev/null 2>&1; then
  eval "$(declare -f _hf_download_snapshot_aggregate \
    | sed '1s/^_hf_download_snapshot_aggregate[[:space:]]*()/_hf_download_snapshot_aggregate_without_speed ()/')"
fi

_hf_download_snapshot_aggregate() {
  local input result
  input="$(cat)"
  result="$(printf '%s\n' "$input" | _hf_download_snapshot_aggregate_without_speed)" || return 1

  jq -c '
    . + {
      active_average_bytes_per_sec: ([.items[]? | select(.status == "running") | (.average_bytes_per_sec // 0)] | add // 0),
      active_recent_bytes_per_sec: ([.items[]? | select(.status == "running" and ((.recent_warming_up // true) | not)) | (.recent_bytes_per_sec // 0)] | add // 0),
      active_recent_ready_streams: ([.items[]? | select(.status == "running" and ((.recent_warming_up // true) | not))] | length),
      active_recent_warming_streams: ([.items[]? | select(.status == "running" and (.recent_warming_up // true))] | length)
    }
  ' <<<"$result"
}

_hf_manifest_human_rate() {
  local bps="${1:-0}" human
  bps="${bps%.*}"
  [[ "$bps" =~ ^[0-9]+$ ]] || bps=0
  human="$(helpers_human_bytes "$bps")"
  printf '%s/s' "$human"
}

_hf_manifest_human_duration() {
  local raw="${1:-0}" total h m s
  total="${raw%.*}"
  [[ "$total" =~ ^[0-9]+$ ]] || total=0
  h=$((total / 3600))
  m=$(((total % 3600) / 60))
  s=$((total % 60))
  if ((h > 0)); then
    printf '%dh %02dm %02ds' "$h" "$m" "$s"
  elif ((m > 0)); then
    printf '%dm %02ds' "$m" "$s"
  else
    printf '%ds' "$s"
  fi
}

_hf_download_show_speed_render() {
  local status="${1:?status json}"
  local running completed recent_bps average_bps ready warming

  read -r running completed recent_bps average_bps ready warming < <(
    jq -r '[.running,.completed,.active_recent_bytes_per_sec,.active_average_bytes_per_sec,.active_recent_ready_streams,.active_recent_warming_streams] | @tsv' <<<"$status"
  )

  # Nothing has ever run in these scopes, so avoid adding an empty section.
  ((running > 0 || completed > 0)) || return 0

  echo "Throughput (approximate; derived from observed download-file growth)"
  echo "--------------------------------------------------------------------------------"

  if ((running > 0)); then
    if ((warming == 0)); then
      printf '  Aggregate active: %s recent | %s avg across %d stream(s)\n' \
        "$(_hf_manifest_human_rate "$recent_bps")" \
        "$(_hf_manifest_human_rate "$average_bps")" "$running"
    elif ((ready > 0)); then
      printf '  Aggregate active: %s recent across %d/%d sampled stream(s) | %s avg across %d stream(s)\n' \
        "$(_hf_manifest_human_rate "$recent_bps")" "$ready" "$running" \
        "$(_hf_manifest_human_rate "$average_bps")" "$running"
    else
      printf '  Aggregate active: recent speed warming up | %s avg across %d stream(s)\n' \
        "$(_hf_manifest_human_rate "$average_bps")" "$running"
    fi

    local rows scope name recent average elapsed warm recent_text
    rows="$(jq -r '.items[] | select(.status=="running") | [.scope,.name,(.recent_bytes_per_sec|tostring),(.average_bytes_per_sec|tostring),(.elapsed_seconds|tostring),(.recent_warming_up|tostring)] | @tsv' <<<"$status")"
    while IFS=$'\t' read -r scope name recent average elapsed warm; do
      if [[ "$warm" == "true" ]]; then
        recent_text="warming up"
      else
        recent_text="$(_hf_manifest_human_rate "$recent")"
      fi
      printf '  %-8s %-38s  %14s recent | %14s avg | %8s\n' \
        "$scope" "$name" "$recent_text" "$(_hf_manifest_human_rate "$average")" \
        "$(_hf_manifest_human_duration "$elapsed")"
    done <<<"$rows"
  else
    echo "  Active: (none)"
  fi

  local completed_max="${HF_MANIFEST_SPEED_COMPLETED_MAX:-5}"
  [[ "$completed_max" =~ ^[0-9]+$ ]] || completed_max=5
  if ((completed_max > 0 && completed > 0)); then
    local completed_rows scope name average elapsed
    completed_rows="$(jq -r --argjson max "$completed_max" '
      [.items[] | select(.status=="completed" and (.average_bytes_per_sec // 0) > 0)]
      | sort_by(.finished_at // .created_at // "")
      | reverse
      | .[:$max][]
      | [.scope,.name,(.average_bytes_per_sec|tostring),(.elapsed_seconds|tostring)] | @tsv
    ' <<<"$status")"
    if [[ -n "$completed_rows" ]]; then
      echo ""
      echo "  Completed averages (latest ${completed_max})"
      while IFS=$'\t' read -r scope name average elapsed; do
        printf '  %-8s %-38s  %14s avg | %8s\n' \
          "$scope" "$name" "$(_hf_manifest_human_rate "$average")" \
          "$(_hf_manifest_human_duration "$elapsed")"
      done <<<"$completed_rows"
    fi
  fi
  echo ""
}

# Preserve the existing snapshot renderer and append the throughput view.
if declare -F _hf_download_show_snapshot_render >/dev/null 2>&1 \
   && ! declare -F _hf_download_show_snapshot_render_without_speed >/dev/null 2>&1; then
  eval "$(declare -f _hf_download_show_snapshot_render \
    | sed '1s/^_hf_download_show_snapshot_render[[:space:]]*()/_hf_download_show_snapshot_render_without_speed ()/')"
fi

_hf_download_show_snapshot_render() {
  _hf_download_show_snapshot_render_without_speed "$@" || return $?
  _hf_download_show_speed_render "$@"
}
