#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi-dl] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-dl] WARN: %s\n" "$*"; }
print_err()  { printf "[musubi-dl] ERR : %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"

: "${MUSUBI_ASSETS_DIR:=${POD_RUNTIME_DIR}/secourses/musubi_tuner}"
: "${MUSUBI_DOWNLOADER:=${MUSUBI_ASSETS_DIR}/Download_Train_Models.py}"

: "${MUSUBI_DOWNLOADER_SESSION:=musubi-dl}"
: "${COMFY_LOGS:=/workspace/logs}"

mkdir -p "${COMFY_LOGS}"

# Ensure links (non-fatal)
if [[ -x "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" ]]; then
  "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" || true
fi

[[ -d "${MUSUBI_TRAINER_DIR}" ]] || { print_err "Trainer dir not found: ${MUSUBI_TRAINER_DIR}"; exit 1; }
[[ -d "${MUSUBI_VENV}" ]] || { print_err "Trainer venv not found: ${MUSUBI_VENV}"; exit 1; }
[[ -f "${MUSUBI_DOWNLOADER}" ]] || { print_err "Downloader not found: ${MUSUBI_DOWNLOADER}"; exit 1; }
command -v tmux >/dev/null 2>&1 || { print_err "tmux not found"; exit 1; }

log="${COMFY_LOGS}/musubi-downloader.log"

cmd=$(
  cat <<EOF
set -euo pipefail
cd "${WORKSPACE}"
source "${MUSUBI_VENV}/bin/activate"
unset LD_LIBRARY_PATH

python "${MUSUBI_DOWNLOADER}" >> "${log}" 2>&1
EOF
)

if tmux has-session -t "${MUSUBI_DOWNLOADER_SESSION}" >/dev/null 2>&1; then
  print_warn "tmux session ${MUSUBI_DOWNLOADER_SESSION} already exists; leaving it running."
  print_info "Log: ${log}"
  exit 0
fi

tmux new-session -d -s "${MUSUBI_DOWNLOADER_SESSION}" "${cmd}"
print_info "Started tmux session: ${MUSUBI_DOWNLOADER_SESSION}"
print_info "Downloader log: ${log}"
print_info "Note: if the downloader is interactive, attach with: tmux a -t ${MUSUBI_DOWNLOADER_SESSION}"
