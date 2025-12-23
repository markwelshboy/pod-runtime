#!/usr/bin/env bash
set -euo pipefail

: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"
: "${DL_TMUX_SESSION:=swarmui_downloader}"
: "${DL_PORT:=7862}"
: "${LOG_DIR:=/workspace/logs}"
: "${DL_LOG:=${LOG_DIR}/swarmui_downloader.log}"

mkdir -p "${LOG_DIR}"

[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

section() { printf "\n================================================================================\n=== %s\n================================================================================\n" "${1:-}"; }
print_info() { printf "INFO: %s\n" "$*"; }
print_err()  { printf "ERR : %s\n" "$*"; }

section "SwarmUI Model Downloader tmux launcher"

if ! command -v tmux >/dev/null 2>&1; then
  print_err "tmux not found."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${SCRIPT_DIR}/Downloader_Gradio_App.py"
if [[ ! -f "${APP}" ]]; then
  print_err "Missing: ${APP}"
  exit 1
fi

cmd="cd '${SCRIPT_DIR}' && \
  echo \"[downloader] starting at \$(date -Is)\" >> '${DL_LOG}' && \
  python '${APP}' --port '${DL_PORT}' 2>&1 | tee -a '${DL_LOG}'"

if tmux has-session -t "${DL_TMUX_SESSION}" 2>/dev/null; then
  tmux send-keys -t "${DL_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${DL_TMUX_SESSION}" "${cmd}" C-m
else
  tmux new-session -d -s "${DL_TMUX_SESSION}" "bash -lc ${cmd@Q}"
fi

print_info "Downloader launching in tmux session: ${DL_TMUX_SESSION}"
print_info "Logs: ${DL_LOG}"
print_info "Attach: tmux attach -t ${DL_TMUX_SESSION}"
