#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${SWARMUI_DL_LOG_DIR:=${WORKSPACE}/logs}"

: "${SWARMUI_DL_PORT:=7862}"
: "${SWARMUI_DL_HOST:=0.0.0.0}"
: "${SWARMUI_DL_SHARE:=false}"

: "${SWARMUI_DL_TMUX_SESSION:=swarmui_downloader-${SWARMUI_DL_PORT}}"
: "${SWARMUI_DL_LOG:=${SWARMUI_DL_LOG_DIR}/swarmui_downloader-${SWARMUI_DL_PORT}.log}"

mkdir -p "${SWARMUI_DL_LOG_DIR}"

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

# Generate /workspace/Downloader_Gradio_App.patched.py
"${POD_RUNTIME_DIR}/secourses/swarmui/ensure_downloader_patched.sh" || true

DOWNLOADER_APP="${WORKSPACE}/Downloader_Gradio_App.patched.py"
if [[ ! -f "${DOWNLOADER_APP}" ]]; then
  print_err "Missing: ${DOWNLOADER_APP}"
  exit 1
fi


