#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# pod_tmux.sh — Pod-friendly tmux bootstrap + attach/run wrapper
#
# Requires: ensure_tmux_conf.sh alongside this file
#
# Usage:
#   pod_tmux.sh                    # attach/create session, drop into shell
#   pod_tmux.sh -- run <cmd...>     # run command inside session
#   pod_tmux.sh --session NAME -- run <cmd...>
#
# Env:
#   POD_RUNTIME=/path/to/pod-runtime
#   TMUX_SESSION=downloader
# ------------------------------------------------------------

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENSURE="${ENSURE_TMUX_CONF:-$HERE/ensure_tmux_conf.sh}"

TMUX_SESSION="${TMUX_SESSION:-downloader}"
DO_RUN="0"
CMD=()

log() { echo "[pod-tmux] $*"; }

need_root_if_writing_system_conf() {
  # ensure_tmux_conf writes /etc/tmux.conf; must be root
  if [[ "$(id -u)" -ne 0 ]]; then
    log "Not root. Will attempt to run ensure script via sudo."
    if ! command -v sudo >/dev/null 2>&1; then
      log "ERROR: sudo not available; run as root or install sudo."
      exit 1
    fi
  fi
}

install_tmux_if_missing() {
  if command -v tmux >/dev/null 2>&1; then
    return 0
  fi
  log "tmux not found; installing..."
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y tmux
  else
    log "ERROR: apt-get not found; install tmux manually."
    exit 1
  fi
}

ensure_conf_loaded() {
  if [[ ! -x "$ENSURE" ]]; then
    log "ERROR: ensure script not found or not executable: $ENSURE"
    exit 1
  fi

  need_root_if_writing_system_conf

  if [[ "$(id -u)" -eq 0 ]]; then
    "$ENSURE"
  else
    sudo "$ENSURE"
  fi
}

health_summary() {
  log "tmux version: $(tmux -V 2>/dev/null || echo 'unknown')"
  log "TERM before attach: ${TERM:-unset}"

  # If no server running, show a note; otherwise print key state
  if ! tmux ls >/dev/null 2>&1; then
    log "tmux server: not running yet (will start now)"
    return 0
  fi

  local mouse wheel
  mouse="$(tmux show -gv mouse 2>/dev/null || true)"
  wheel="$(tmux list-keys -T root 2>/dev/null | grep -E 'WheelUpPane|WheelDownPane' || true)"

  log "tmux mouse: ${mouse:-unknown}"
  if echo "$wheel" | grep -q 'send -M'; then
    log "WARNING: Wheel binding still uses send -M (may cause ^[[ junk)"
  else
    log "Wheel bindings look OK (no send -M)."
  fi
}

start_or_attach() {
  # Make TERM sane for tmux sessions
  export TERM="tmux-256color"

  if [[ "$DO_RUN" == "1" ]]; then
    # Start detached and run command in first window; then attach
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
      log "Session exists: $TMUX_SESSION (will run command in a new window)"
      tmux new-window -t "$TMUX_SESSION" -n run -- "${CMD[@]}"
    else
      log "Creating session: $TMUX_SESSION (running command)"
      tmux new-session -d -s "$TMUX_SESSION" -n run -- "${CMD[@]}"
    fi
    exec tmux attach -t "$TMUX_SESSION"
  else
    # Normal attach/create
    exec tmux new -A -s "$TMUX_SESSION"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --session) TMUX_SESSION="${2:?missing session name}"; shift 2 ;;
      --run|run) DO_RUN="1"; shift; CMD=("$@"); break ;;
      -h|--help)
        cat <<EOF
Usage:
  pod_tmux.sh
  pod_tmux.sh --session NAME
  pod_tmux.sh -- run <cmd...>
  pod_tmux.sh --session NAME -- run <cmd...>

Env:
  TMUX_SESSION=downloader
  ENSURE_TMUX_CONF=/path/to/ensure_tmux_conf.sh
EOF
        exit 0
        ;;
      --) shift; ;;
      *)  log "Unknown arg: $1"; exit 1 ;;
    esac
  done
}

main() {
  parse_args "$@"
  install_tmux_if_missing
  ensure_conf_loaded
  health_summary
  start_or_attach
}

main "$@"
