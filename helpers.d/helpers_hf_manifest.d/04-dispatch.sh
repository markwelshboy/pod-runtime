hf_download_monitor_progress() {
  local interval="${1:-${HF_MANIFEST_PROGRESS_INTERVAL:-60}}"
  local log="${2:-${COMFY_LOGS:-/workspace/logs}/hf_manifest_progress.log}"
  local state
  state="$(_hf_manifest_state_dir "${3:-}")"
  mkdir -p -- "$(dirname -- "$log")"

  while :; do
    hf_download_show_snapshot "$state" | tee -a "$log"
    local status active
    status="$(hf_download_status_json "$state")" || return 1
    active="$(jq -r '.active // false' <<<"$status")"
    [[ "$active" == "true" ]] || break
    sleep "$interval"
  done

  local final failed stalled
  final="$(hf_download_status_json "$state")" || return 1
  failed="$(jq -r '.failed // 0' <<<"$final")"
  stalled="$(jq -r '.stalled // false' <<<"$final")"
  ((failed == 0)) && [[ "$stalled" != "true" ]]
}

hf_download_wait() {
  local state
  state="$(_hf_manifest_state_dir "${1:-}")"
  while hf_download_is_active "$state"; do
    sleep 1
  done
  local status
  status="$(hf_download_status_json "$state")" || return 1
  [[ "$(jq -r '.failed // 0' <<<"$status")" == "0" ]] \
    && [[ "$(jq -r '.stalled // false' <<<"$status")" != "true" ]]
}

hf_download_stop() {
  local state
  state="$(_hf_manifest_state_dir "${1:-}")"
  local pid=""
  [[ -f "$state/controller.pid" ]] && pid="$(cat "$state/controller.pid" 2>/dev/null || true)"
  if hf_download_is_active "$state"; then
    _hf_manifest_kill_tree "$pid" TERM
    _hf_manifest_set_controller_status "$state" stopped 0 "stopped by user"
    echo "[hf-manifest] Stopped controller pid=$pid"
  else
    echo "[hf-manifest] No active controller."
  fi
}

# ----------------------------------------------------------------------
# Compatibility dispatcher for the existing start.sh flow.
# The startup script can remain unchanged: HF_DOWNLOADER=true routes the
# model manifest to hf download, while CivitAI continues to use aria2.
# ----------------------------------------------------------------------
if declare -F aria2_download_from_manifest >/dev/null 2>&1 \
   && ! declare -F _aria2_download_from_manifest_backend >/dev/null 2>&1; then
  eval "$(declare -f aria2_download_from_manifest \
    | sed '1s/^aria2_download_from_manifest[[:space:]]*()/_aria2_download_from_manifest_backend ()/')"
fi
if declare -F aria2_show_download_snapshot >/dev/null 2>&1 \
   && ! declare -F _aria2_show_download_snapshot_backend >/dev/null 2>&1; then
  eval "$(declare -f aria2_show_download_snapshot \
    | sed '1s/^aria2_show_download_snapshot[[:space:]]*()/_aria2_show_download_snapshot_backend ()/')"
fi
if declare -F aria2_monitor_progress >/dev/null 2>&1 \
   && ! declare -F _aria2_monitor_progress_backend >/dev/null 2>&1; then
  eval "$(declare -f aria2_monitor_progress \
    | sed '1s/^aria2_monitor_progress[[:space:]]*()/_aria2_monitor_progress_backend ()/')"
fi

aria2_download_from_manifest() {
  if _hf_manifest_enabled; then
    hf_download_from_manifest "$@"
  else
    _aria2_download_from_manifest_backend "$@"
  fi
}

aria2_show_download_snapshot() {
  if _hf_manifest_enabled; then
    hf_download_show_snapshot || true
    if _hf_manifest_true "${ENABLE_CIVITAI_DOWNLOAD:-true}" \
       && helpers_have_aria2_rpc 2>/dev/null; then
      HF_DOWNLOADER=false _aria2_show_download_snapshot_backend "$@" || true
    fi
  else
    _aria2_show_download_snapshot_backend "$@"
  fi
}

aria2_monitor_progress() {
  if ! _hf_manifest_enabled; then
    _aria2_monitor_progress_backend "$@"
    return $?
  fi

  local rc=0
  hf_download_monitor_progress \
    "${1:-${HF_MANIFEST_PROGRESS_INTERVAL:-60}}" \
    "${COMFY_LOGS:-/workspace/logs}/hf_manifest_progress.log" || rc=1

  if helpers_have_aria2_rpc 2>/dev/null; then
    if ! helpers_queue_empty; then
      HF_DOWNLOADER=false _aria2_monitor_progress_backend "$@" || rc=1
    elif _hf_manifest_true "${ENABLE_CIVITAI_DOWNLOAD:-true}"; then
      HF_DOWNLOADER=false _aria2_show_download_snapshot_backend || true
    fi
  fi
  return "$rc"
}
