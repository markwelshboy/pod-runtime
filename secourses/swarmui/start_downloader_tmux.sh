#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"
: "${LOG_DIR:=/workspace/logs}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${DL_TMUX_SESSION:=swarmui_downloader}"
: "${DL_LOG:=${LOG_DIR}/swarmui_downloader.log}"

mkdir -p "${LOG_DIR}"

[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

print_info() { printf "[swarmui-downloader] INFO: %s\n" "$*"; }
print_warn() { printf "[swarmui-downloader] WARN: %s\n" "$*"; }
print_err()  { printf "[swarmui-downloader] ERR : %s\n" "$*"; }

section() {
  printf "\n================================================================================\n"
  printf "=== %s\n" "${1:-}"
  printf "================================================================================\n"
}

if ! command -v tmux >/dev/null 2>&1; then
  print_err "tmux not found."
  exit 1
fi

DOWNLOADER_APP="${WORKSPACE}/Downloader_Gradio_App.py"
if [[ ! -f "${DOWNLOADER_APP}" ]]; then
  print_err "Missing: ${DOWNLOADER_APP}"
  exit 1
fi

cmd="cd '${WORKSPACE}' && \
  echo \"[swarmui-downloader] starting at \$(date -Is)\" >> '${DL_LOG}' && \
  export HF_HOME=\"/workspace\" && \
  set HUGGING_FACE_HUB_TOKEN=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 && \
  python -W ignore '${DOWNLOADER_APP}' --share 2>&1 | tee -a '${DL_LOG}'"

if tmux has-session -t "${DL_TMUX_SESSION}" 2>/dev/null; then
  print_info "Gradio Downloader launching in existing tmux session: ${DL_TMUX_SESSION}"
  tmux send-keys -t "${DL_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${DL_TMUX_SESSION}" "${cmd}" C-m
else
  print_info "Gradio Downloader launching in new tmux session: ${DL_TMUX_SESSION}"
  tmux new-session -d -s "${DL_TMUX_SESSION}" "bash -lc ${cmd@Q}"
fi

print_info "Logs: ${DL_LOG}"
print_info "Attach: tmux attach -t ${DL_TMUX_SESSION}"
