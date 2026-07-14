hf_download_status_json() {
  local state
  state="$(_hf_manifest_state_dir "${1:-}")"
  local py
  py="$(_hf_manifest_python)" || return 1

  HF_MANIFEST_STATUS_STATE="$state" "$py" - <<'PY'
import json
import os
from collections import Counter
from pathlib import Path

state = Path(os.environ["HF_MANIFEST_STATUS_STATE"])
if not state.is_dir():
    print(json.dumps({"exists": False, "state_dir": str(state), "active": False, "items": []}))
    raise SystemExit(0)

pid = 0
try:
    pid = int((state / "controller.pid").read_text().strip())
except Exception:
    pass
try:
    controller = json.loads((state / "controller.json").read_text())
except Exception:
    controller = {}

controller_running = False
if pid > 0 and controller.get("status") in {"prepared", "running"}:
    try:
        os.kill(pid, 0)
        controller_running = True
    except OSError:
        pass

def tree_bytes(path):
    root = Path(path)
    if not root.is_dir():
        return 0
    total = 0
    try:
        for p in root.rglob("*"):
            try:
                if p.is_file() and not p.name.endswith(".lock"):
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total

items = []
for item_path in sorted((state / "items").glob("*.json")):
    try:
        item = json.loads(item_path.read_text())
    except Exception:
        continue
    final = Path(item.get("path") or "")
    final_bytes = final.stat().st_size if final.is_file() else 0
    work_bytes = tree_bytes(item.get("work_dir") or "") if item.get("status") == "running" else 0
    if item.get("status") == "completed":
        observed = final_bytes
    elif item.get("status") in {"running", "failed"}:
        observed = work_bytes
    else:
        observed = 0
    expected = int(item.get("total_bytes") or 0)
    if expected > 0:
        observed = min(observed, expected)
        item_pct = round(observed * 100.0 / expected, 1)
    else:
        item_pct = 100.0 if item.get("status") == "completed" else 0.0
    display_dir = str(final.parent)
    comfy = os.environ.get("COMFY_HOME") or os.environ.get("COMFY") or ""
    if comfy and display_dir.startswith(comfy.rstrip("/") + "/"):
        display_dir = display_dir[len(comfy.rstrip("/")) + 1:]
    item.update({
        "final_bytes": final_bytes,
        "work_bytes": work_bytes,
        "observed_bytes": observed,
        "item_percent": item_pct,
        "display_dir": display_dir,
    })
    items.append(item)

counts = Counter(item.get("status", "unknown") for item in items)
known_total = sum(int(item.get("total_bytes") or 0) for item in items if int(item.get("total_bytes") or 0) > 0)
known_done = sum(
    int(item.get("observed_bytes") or 0)
    for item in items
    if int(item.get("total_bytes") or 0) > 0 and item.get("status") in {"running", "completed"}
)
percent = round(known_done * 100.0 / known_total, 1) if known_total else (
    round(counts.get("completed", 0) * 100.0 / len(items), 1) if items else 100.0
)
unfinished = counts.get("pending", 0) + counts.get("running", 0)
stalled = (not controller_running) and unfinished > 0
result = {
    "exists": True,
    "state_dir": str(state),
    "controller_pid": pid,
    "controller_running": controller_running,
    "controller": controller,
    "active": controller_running,
    "stalled": stalled,
    "total": len(items),
    "pending": counts.get("pending", 0),
    "running": counts.get("running", 0),
    "completed": counts.get("completed", 0),
    "failed": counts.get("failed", 0),
    "unknown": counts.get("unknown", 0),
    "known_total_bytes": known_total,
    "known_done_bytes": known_done,
    "unknown_size_items": sum(1 for item in items if int(item.get("total_bytes") or 0) <= 0),
    "percent": percent,
    "items": items,
}
print(json.dumps(result, separators=(",", ":")))
PY
}

hf_download_show_snapshot() {
  local state
  state="$(_hf_manifest_state_dir "${1:-}")"
  local status
  status="$(hf_download_status_json "$state")" || return 1

  if [[ "$(jq -r '.exists' <<<"$status")" != "true" ]]; then
    echo "[hf-manifest] No state available at $state"
    return 0
  fi

  local pending running completed failed total pct done_bytes total_bytes unknown_sizes active stalled
  read -r pending running completed failed total pct done_bytes total_bytes unknown_sizes active stalled < <(
    jq -r '[.pending,.running,.completed,.failed,.total,.percent,.known_done_bytes,.known_total_bytes,.unknown_size_items,.controller_running,.stalled] | @tsv' <<<"$status"
  )

  echo ""
  echo "================================================================================"
  echo "=== HF Manifest Downloader Snapshot @ $(date '+%Y-%m-%d %H:%M:%S')"
  echo "=== Pending: $pending   Running: $running   Completed: $completed   Failed: $failed"
  echo "=== Controller active: $active   State: $state"
  if ((total_bytes > 0)); then
    echo "=== Overall: ${pct}% ($(helpers_human_bytes "$done_bytes") / $(helpers_human_bytes "$total_bytes")); unknown-size items: $unknown_sizes"
  else
    echo "=== Overall: ${pct}% by file count; remote sizes unavailable"
  fi
  [[ "$stalled" == "true" ]] && echo "=== WARNING: unfinished items remain but the controller is not running"
  echo "================================================================================"

  local rows row name dir expected observed item_pct message

  echo ""
  echo "Pending"
  echo "--------------------------------------------------------------------------------"
  rows="$(jq -r '.items[] | select(.status=="pending") | [.name,.display_dir,(.total_bytes|tostring),(.message//"")] | @tsv' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    while IFS=$'\t' read -r name dir expected message; do
      printf '  ⏳ %-52s [%s]  %s%s\n' "$name" "$dir" \
        "$([[ "$expected" -gt 0 ]] && helpers_human_bytes "$expected" || echo 'size unknown')" \
        "$([[ -n "$message" ]] && printf ' — %s' "$message")"
    done <<<"$rows"
  fi

  echo ""
  echo "Running"
  echo "--------------------------------------------------------------------------------"
  rows="$(jq -r '.items[] | select(.status=="running") | [.name,.display_dir,(.observed_bytes|tostring),(.total_bytes|tostring),(.item_percent|tostring)] | @tsv' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    local width="${HF_MANIFEST_PROGRESS_BAR_WIDTH:-40}" bar_len bar
    while IFS=$'\t' read -r name dir observed expected item_pct; do
      local pct_int="${item_pct%.*}"
      [[ "$pct_int" =~ ^[0-9]+$ ]] || pct_int=0
      bar_len=$((width * pct_int / 100))
      printf -v bar '%*s' "$bar_len" ''
      bar=${bar// /#}
      printf -v bar '%-*s' "$width" "$bar"
      if ((expected > 0)); then
        printf ' %5s%% [%-*s] %s / %s  [%s] <- %s\n' "$item_pct" "$width" "$bar" \
          "$(helpers_human_bytes "$observed")" "$(helpers_human_bytes "$expected")" "$dir" "$name"
      else
        printf '   n/a  [%-*s] %s observed  [%s] <- %s\n' "$width" "$bar" \
          "$(helpers_human_bytes "$observed")" "$dir" "$name"
      fi
    done <<<"$rows"
  fi

  echo ""
  echo "Completed"
  echo "--------------------------------------------------------------------------------"
  rows="$(jq -r --argjson max "${HF_MANIFEST_COMPLETED_MAX:-20}" '
    [.items[] | select(.status=="completed")] as $done
    | ($done | reverse | .[:$max] | reverse)[]
    | [.name,.display_dir,(.final_bytes|tostring),(.message//"")] | @tsv
  ' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    while IFS=$'\t' read -r name dir observed message; do
      printf '  ✅ %-52s [%s]  %s%s\n' "$name" "$dir" "$(helpers_human_bytes "$observed")" \
        "$([[ -n "$message" ]] && printf ' — %s' "$message")"
    done <<<"$rows"
    if ((completed > HF_MANIFEST_COMPLETED_MAX)); then
      echo "  … showing the most recent ${HF_MANIFEST_COMPLETED_MAX}; JSON status contains all $completed"
    fi
  fi

  if ((failed > 0)); then
    echo ""
    echo "Failed"
    echo "--------------------------------------------------------------------------------"
    jq -r '.items[] | select(.status=="failed") | "  ❌ \(.name) [\(.display_dir)] — \(.message) — log: \(.log)"' <<<"$status"
  fi
  echo ""
}
