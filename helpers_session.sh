#!/usr/bin/env bash
# ======================================================================
# helpers_session.sh — pod-session clock and usage-summary overrides
# ======================================================================
# Pods can run inside hosts whose kernel uptime predates the pod by days or
# weeks. For runtime notifications, session age is the useful lifetime.
#
# POD_TIMEZONE defaults to America/Los_Angeles so date output follows PDT/PST
# automatically instead of using a fixed UTC offset.

: "${POD_TIMEZONE:=America/Los_Angeles}"
export POD_TIMEZONE
export TZ="${POD_TIMEZONE}"

# Launchers set this at their first executable lines. Keep a fallback so any
# other pod-runtime launcher that sources helpers.sh also gets session timing.
if [[ -z "${POD_SESSION_STARTED_AT_EPOCH:-}" ]]; then
  export POD_SESSION_STARTED_AT_EPOCH="$(date +%s)"
fi

if [[ -z "${POD_SESSION_STARTED_AT:-}" ]]; then
  export POD_SESSION_STARTED_AT="$(date -d "@${POD_SESSION_STARTED_AT_EPOCH}" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S %Z')"
fi

pod_session_age_seconds() {
  local now started
  now="$(date +%s)"
  started="${POD_SESSION_STARTED_AT_EPOCH:-$now}"
  [[ "$started" =~ ^[0-9]+$ ]] || started="$now"
  if (( now < started )); then
    printf '0\n'
  else
    printf '%s\n' "$((now - started))"
  fi
}

pod_session_age_human() {
  local total days hours minutes seconds
  total="$(pod_session_age_seconds)"
  days=$((total / 86400))
  hours=$(((total % 86400) / 3600))
  minutes=$(((total % 3600) / 60))
  seconds=$((total % 60))

  if (( days > 0 )); then
    printf '%dd %dh %dm\n' "$days" "$hours" "$minutes"
  elif (( hours > 0 )); then
    printf '%dh %dm\n' "$hours" "$minutes"
  elif (( minutes > 0 )); then
    printf '%dm %ds\n' "$minutes" "$seconds"
  else
    printf '%ds\n' "$seconds"
  fi
}

# Override the legacy helpers_core.sh implementation. The disk watcher and
# pod_nag already call pod_usage_summary(), so both automatically gain the
# session clock without duplicating their notification logic.
pod_usage_summary() {
  local models_dir="${1:-${MODELS_DIR:-${COMFY_HOME:-/workspace/ComfyUI}/models}}"

  local host now session_started session_age
  host="$(hostname)"
  now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  session_started="${POD_SESSION_STARTED_AT:-$(date -d "@${POD_SESSION_STARTED_AT_EPOCH}" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || printf 'unknown')}"
  session_age="$(pod_session_age_human)"

  local root_use root_avail
  local ws_use ws_avail
  local models_total

  root_use="$(df -hP / 2>/dev/null | awk 'NR==2{print $5}')"
  root_avail="$(df -hP / 2>/dev/null | awk 'NR==2{print $4}')"

  ws_use="$(df -hP /workspace 2>/dev/null | awk 'NR==2{print $5}')"
  ws_avail="$(df -hP /workspace 2>/dev/null | awk 'NR==2{print $4}')"

  if [[ -d "$models_dir" ]]; then
    models_total="$(du -sh "$models_dir" 2>/dev/null | awk '{print $1}')"
  else
    models_total="n/a"
  fi

  cat <<EOF
Host:         ${host}
Time:         ${now}
Session start:${session_started:+ }${session_started:-unknown}
Session age:  ${session_age:-unknown}
root:         ${root_use:-?} used, ${root_avail:-?} free
workspace:    ${ws_use:-?} used, ${ws_avail:-?} free
Models total: ${models_total}
EOF
}
