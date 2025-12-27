#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi] WARN: %s\n" "$*"; }
print_err()  { printf "[musubi] ERR : %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"
: "${MUSUBI_GUI:=${MUSUBI_TRAINER_DIR}/gui.py}"

: "${MUSUBI_SESSION:=musubi}"
: "${MUSUBI_HOST:=0.0.0.0}"
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SHARE:=false}"

: "${COMFY_LOGS:=/workspace/logs}"

mkdir -p "${COMFY_LOGS}"

# Ensure links (non-fatal)
if [[ -x "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" ]]; then
  "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" || true
fi

[[ -d "${MUSUBI_TRAINER_DIR}" ]] || { print_err "Trainer dir not found: ${MUSUBI_TRAINER_DIR}"; exit 1; }
[[ -d "${MUSUBI_VENV}" ]] || { print_err "Trainer venv not found: ${MUSUBI_VENV}"; exit 1; }
[[ -f "${MUSUBI_GUI}" ]] || { print_err "gui.py not found: ${MUSUBI_GUI}"; exit 1; }
command -v tmux >/dev/null 2>&1 || { print_err "tmux not found"; exit 1; }

# Gradio tends to respect these env vars even when the app doesn't expose CLI flags
share_flag=""
if [[ "${MUSUBI_SHARE,,}" == "true" ]]; then
  share_flag="--share"
fi

log="${COMFY_LOGS}/musubi-${MUSUBI_PORT}.log"

cmd=$(
  cat <<EOF
set -euo pipefail
cd "${MUSUBI_TRAINER_DIR}"
source "${MUSUBI_VENV}/bin/activate"
unset LD_LIBRARY_PATH

export GRADIO_SERVER_NAME="${MUSUBI_HOST}"
export GRADIO_SERVER_PORT="${MUSUBI_PORT}"

python "${MUSUBI_GUI}" ${share_flag} >> "${log}" 2>&1
EOF
)

if tmux has-session -t "${MUSUBI_SESSION}" >/dev/null 2>&1; then
  print_warn "tmux session ${MUSUBI_SESSION} already exists; leaving it running."
  print_info "Log: ${log}"
  exit 0
fi

tmux new-session -d -s "${MUSUBI_SESSION}" "${cmd}"
print_info "Started tmux session: ${MUSUBI_SESSION}"
print_info "Musubi GUI log: ${log}"
