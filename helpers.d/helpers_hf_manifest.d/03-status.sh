: "${HF_BASE_STATE:=${HF_MANIFEST_STATE_DIR}/base}"
: "${HF_LORA_STATE:=${HF_MANIFEST_STATE_DIR}/loras}"
export HF_BASE_STATE HF_LORA_STATE

_hf_manifest_scope_state_dir() {
  case "${1:-}" in
    base) printf '%s\n' "${HF_BASE_STATE:-${HF_MANIFEST_STATE_DIR}/base}" ;;
    loras) printf '%s\n' "${HF_LORA_STATE:-${HF_MANIFEST_STATE_DIR}/loras}" ;;
    *) return 2 ;;
  esac
}

_hf_manifest_resolve_states() {
  local target="${1:-base,loras}" scope

  # Preserve the historical explicit-state-directory interface.
  if [[ "$target" == */* || "$target" == .* ]]; then
    printf '%s\t%s\n' "$(basename -- "$target")" "$target"
    return 0
  fi

  local -a requested=()
  local -A seen=()
  IFS=',' read -ra requested <<<"$target"
  for scope in "${requested[@]}"; do
    scope="${scope#"${scope%%[![:space:]]*}"}"
    scope="${scope%"${scope##*[![:space:]]}"}"
    [[ -n "$scope" ]] || continue
    case "$scope" in
      base|loras) ;;
      *)
        echo "[hf-manifest] Unknown scope: $scope (expected base, loras, or base,loras)" >&2
        return 2
        ;;
    esac
    [[ -z "${seen[$scope]:-}" ]] || continue
    seen[$scope]=1
    printf '%s\t%s\n' "$scope" "$(_hf_manifest_scope_state_dir "$scope")"
  done
}

_hf_download_status_json_state() {
  local state="${1:?state directory}"
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

_hf_download_snapshot_aggregate() {
  jq -sc '
    def scope_state:
      if ((.exists // false) | not) then "not-started"
      elif ((.total // 0) == 0 and ((.controller // {}) | length) == 0) then "not-started"
      elif (.controller_running // false) then "running"
      elif ((.failed // 0) > 0 or (.controller.status // "") == "failed") then "failed"
      elif (.stalled // false) then "stalled"
      elif ((.total // 0) > 0 and (.pending // 0) == 0 and (.running // 0) == 0 and (.failed // 0) == 0) then "completed"
      elif (.controller.status // "") == "completed" then "completed"
      elif (.controller.status // "") == "stopped" then "stopped"
      elif (.controller.status // "") == "prepared" then "prepared"
      else (.controller.status // "idle")
      end;

    . as $states
    | {
        scopes: [$states[] | {name:.scope,status:scope_state,state_dir:.state_dir}],
        pending: ([$states[] | (.pending // 0)] | add // 0),
        running: ([$states[] | (.running // 0)] | add // 0),
        completed: ([$states[] | (.completed // 0)] | add // 0),
        failed: ([$states[] | (.failed // 0)] | add // 0),
        total: ([$states[] | (.total // 0)] | add // 0),
        known_total_bytes: ([$states[] | (.known_total_bytes // 0)] | add // 0),
        known_done_bytes: ([$states[] | (.known_done_bytes // 0)] | add // 0),
        unknown_size_items: ([$states[] | (.unknown_size_items // 0)] | add // 0),
        controller_running: any($states[]; (.controller_running // false)),
        active: any($states[]; (.controller_running // false)),
        stalled: any($states[]; (.stalled // false)),
        items: [$states[] | .items[]?]
      }
    | .percent = (
        if .known_total_bytes > 0 then
          ((.known_done_bytes * 1000.0 / .known_total_bytes | round) / 10.0)
        elif .total > 0 then
          ((.completed * 1000.0 / .total | round) / 10.0)
        else
          0.0
        end
      )
  '
}

_hf_download_status_json_scopes() {
  local target="${1:-base,loras}" scope state status
  local -a statuses=()

  while IFS=$'\t' read -r scope state; do
    [[ -n "$state" ]] || continue
    status="$(_hf_download_status_json_state "$state")" || return 1
    status="$(jq -c --arg scope "$scope" '
      . + {scope:$scope}
      | .items = ((.items // []) | map(. + {scope:$scope}))
    ' <<<"$status")" || return 1
    statuses+=("$status")
  done < <(_hf_manifest_resolve_states "$target")

  if ((${#statuses[@]} == 0)); then
    echo "[hf-manifest] No scopes selected." >&2
    return 2
  fi

  printf '%s\n' "${statuses[@]}" | _hf_download_snapshot_aggregate
}

hf_download_status_json() {
  local target="${1:-base,loras}"
  if [[ "$target" == */* || "$target" == .* ]]; then
    _hf_download_status_json_state "$target"
  else
    _hf_download_status_json_scopes "$target"
  fi
}

_hf_download_show_snapshot_usage() {
  cat <<'EOF_USAGE'
Usage:
  hf_download_show_snapshot [SCOPES] [OPTIONS]

Scopes:
  base              Base model downloads
  loras             Optional LoRA downloads
  base,loras        Multiple scopes

Default:
  base,loras

Options:
  --all             Show all completed downloads instead of the latest 20
  -h, --help        Show this help
EOF_USAGE
}

_hf_download_show_snapshot_render() {
  local status="${1:?status json}" show_all="${2:-false}"
  local pending running completed failed total pct done_bytes total_bytes unknown_sizes stalled scope_summary

  read -r pending running completed failed total pct done_bytes total_bytes unknown_sizes stalled < <(
    jq -r '[.pending,.running,.completed,.failed,.total,.percent,.known_done_bytes,.known_total_bytes,.unknown_size_items,.stalled] | @tsv' <<<"$status"
  )
  scope_summary="$(jq -r '[.scopes[] | "\(.name)=\(.status)"] | join("   ")' <<<"$status")"

  echo ""
  echo "================================================================================"
  echo "=== HF Manifest Downloader Snapshot @ $(date '+%Y-%m-%d %H:%M:%S')"
  echo "=== Scopes: $scope_summary"
  echo "=== Pending: $pending   Running: $running   Completed: $completed   Failed: $failed"
  if ((total == 0)); then
    echo "=== Overall: no planned items in selected scopes"
  elif ((total_bytes > 0)); then
    echo "=== Overall: ${pct}% ($(helpers_human_bytes "$done_bytes") / $(helpers_human_bytes "$total_bytes")); unknown-size items: $unknown_sizes"
  else
    echo "=== Overall: ${pct}% by file count; remote sizes unavailable"
  fi
  [[ "$stalled" == "true" ]] && echo "=== WARNING: unfinished items remain but a controller is not running"
  echo "================================================================================"

  local rows scope name dir expected observed item_pct message

  echo ""
  echo "Pending"
  echo "--------------------------------------------------------------------------------"
  rows="$(jq -r '.items[] | select(.status=="pending") | [.scope,.name,.display_dir,(.total_bytes|tostring),(.message//"")] | @tsv' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    while IFS=$'\t' read -r scope name dir expected message; do
      printf '  %-8s ⏳ %-43s [%s]  %s%s\n' "$scope" "$name" "$dir" \
        "$([[ "$expected" -gt 0 ]] && helpers_human_bytes "$expected" || echo 'size unknown')" \
        "$([[ -n "$message" ]] && printf ' — %s' "$message")"
    done <<<"$rows"
  fi

  echo ""
  echo "Running"
  echo "--------------------------------------------------------------------------------"
  rows="$(jq -r '.items[] | select(.status=="running") | [.scope,.name,.display_dir,(.observed_bytes|tostring),(.total_bytes|tostring),(.item_percent|tostring)] | @tsv' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    local width="${HF_MANIFEST_PROGRESS_BAR_WIDTH:-40}" bar_len bar
    while IFS=$'\t' read -r scope name dir observed expected item_pct; do
      local pct_int="${item_pct%.*}"
      [[ "$pct_int" =~ ^[0-9]+$ ]] || pct_int=0
      bar_len=$((width * pct_int / 100))
      printf -v bar '%*s' "$bar_len" ''
      bar=${bar// /#}
      printf -v bar '%-*s' "$width" "$bar"
      if ((expected > 0)); then
        printf ' %-8s %5s%% [%-*s] %s / %s  [%s] <- %s\n' "$scope" "$item_pct" "$width" "$bar" \
          "$(helpers_human_bytes "$observed")" "$(helpers_human_bytes "$expected")" "$dir" "$name"
      else
        printf ' %-8s   n/a  [%-*s] %s observed  [%s] <- %s\n' "$scope" "$width" "$bar" \
          "$(helpers_human_bytes "$observed")" "$dir" "$name"
      fi
    done <<<"$rows"
  fi

  echo ""
  echo "Completed"
  echo "--------------------------------------------------------------------------------"
  local completed_max="${HF_MANIFEST_COMPLETED_MAX:-20}"
  [[ "$completed_max" =~ ^[0-9]+$ ]] || completed_max=20
  ((completed_max > 0)) || completed_max=20
  [[ "$show_all" == "true" ]] && completed_max=0

  rows="$(jq -r --argjson max "$completed_max" '
    [.items[] | select(.status=="completed")]
    | sort_by(.finished_at // .created_at // "")
    | reverse
    | (if $max > 0 then .[:$max] else . end)[]
    | [.scope,.name,.display_dir,(.final_bytes|tostring),(.message//"")] | @tsv
  ' <<<"$status")"
  if [[ -z "$rows" ]]; then
    echo "  (none)"
  else
    while IFS=$'\t' read -r scope name dir observed message; do
      printf '  %-8s ✅ %-43s [%s]  %s%s\n' "$scope" "$name" "$dir" "$(helpers_human_bytes "$observed")" \
        "$([[ -n "$message" ]] && printf ' — %s' "$message")"
    done <<<"$rows"
    if [[ "$show_all" != "true" ]] && ((completed > completed_max)); then
      echo "  … showing latest $completed_max of $completed; use --all to show all $completed"
    fi
  fi

  if ((failed > 0)); then
    echo ""
    echo "Failed"
    echo "--------------------------------------------------------------------------------"
    jq -r '.items[] | select(.status=="failed") | "  ❌ \(.scope)  \(.name) [\(.display_dir)] — \(.message) — log: \(.log)"' <<<"$status"
  fi
  echo ""
}

hf_download_show_snapshot() {
  local scopes="base,loras" show_all=false scope_arg_set=false arg

  while (($# > 0)); do
    arg="$1"
    case "$arg" in
      --all) show_all=true ;;
      -h|--help)
        _hf_download_show_snapshot_usage
        return 0
        ;;
      --)
        shift
        if (($# > 0)); then
          [[ "$scope_arg_set" == "false" ]] || {
            echo "[hf-manifest] Only one scope list may be supplied." >&2
            return 2
          }
          scopes="$1"
          scope_arg_set=true
          shift
          (($# == 0)) || {
            echo "[hf-manifest] Unexpected argument: $1" >&2
            return 2
          }
        fi
        break
        ;;
      -*)
        echo "[hf-manifest] Unknown option: $arg" >&2
        _hf_download_show_snapshot_usage >&2
        return 2
        ;;
      *)
        [[ "$scope_arg_set" == "false" ]] || {
          echo "[hf-manifest] Only one scope list may be supplied." >&2
          return 2
        }
        scopes="$arg"
        scope_arg_set=true
        ;;
    esac
    shift
  done

  local status raw_scope
  if [[ "$scope_arg_set" == "true" && ( "$scopes" == */* || "$scopes" == .* ) ]]; then
    status="$(_hf_download_status_json_state "$scopes")" || return 1
    raw_scope="$(basename -- "$scopes")"
    status="$(jq -c --arg scope "$raw_scope" '
      . + {scope:$scope}
      | .items = ((.items // []) | map(. + {scope:$scope}))
    ' <<<"$status" | _hf_download_snapshot_aggregate)" || return 1
  else
    status="$(_hf_download_status_json_scopes "$scopes")" || return 1
  fi

  _hf_download_show_snapshot_render "$status" "$show_all"
}
