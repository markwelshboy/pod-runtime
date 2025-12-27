#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi-trainer] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-trainer] WARN: %s\n" "$*"; }
print_err()  { printf "[musubi-trainer] ERR : %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"
: "${MUSUBI_GUI:=${MUSUBI_TRAINER_DIR}/gui.py}"

: "${MUSUBI_HOST:=0.0.0.0}"
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SHARE:=false}"

: "${MUSUBI_SESSION:=musubi-${MUSUBI_PORT}}"
: "${MUSUBI_LOGS_DIR:=/workspace/logs}"
: "${MUSUBI_RESTART_DELAY:=1}"

mkdir -p "${MUSUBI_LOGS_DIR}"

# Ensure links (non-fatal)
if [[ -x "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" ]]; then
  "${POD_RUNTIME_DIR}/secourses/musubi_tuner/ensure_musubi_workspace_links.sh" || true
fi

[[ -d "${MUSUBI_TRAINER_DIR}" ]] || { print_err "Trainer dir not found: ${MUSUBI_TRAINER_DIR}"; exit 1; }
[[ -d "${MUSUBI_VENV}" ]] || { print_err "Trainer venv not found: ${MUSUBI_VENV}"; exit 1; }
[[ -f "${MUSUBI_GUI}" ]] || { print_err "gui.py not found: ${MUSUBI_GUI}"; exit 1; }
command -v tmux >/dev/null 2>&1 || { print_err "tmux not found"; exit 1; }

share_flag=""
if [[ "${MUSUBI_SHARE,,}" == "true" ]]; then
  share_flag="--share"
fi

log="${MUSUBI_LOGS_DIR}/musubi-${MUSUBI_PORT}.log"

cmd=$(
  cat <<EOF
set -euo pipefail
cd ${MUSUBI_TRAINER_DIR@Q}
source ${MUSUBI_VENV@Q}/bin/activate
unset LD_LIBRARY_PATH

export GRADIO_SERVER_NAME=${MUSUBI_HOST@Q}
export GRADIO_SERVER_PORT=${MUSUBI_PORT@Q}

python ${MUSUBI_GUI@Q} ${share_flag} >> ${log@Q} 2>&1
EOF
)

if tmux has-session -t "${MUSUBI_SESSION}" >/dev/null 2>&1; then
  print_info "Musubi GUI launching in existing tmux session: ${MUSUBI_SESSION}"
  tmux send-keys -t "${MUSUBI_SESSION}" C-c || true
  sleep "${MUSUBI_RESTART_DELAY}"
  tmux send-keys -t "${MUSUBI_SESSION}" "bash -lc ${cmd@Q}" C-m
else
  print_info "Musubi GUI launching in new tmux session: ${MUSUBI_SESSION}"
  tmux new-session -d -s "${MUSUBI_SESSION}" "bash -lc ${cmd@Q}"
fi

print_info "Started/updated tmux session: ${MUSUBI_SESSION}"
print_info "Log   : ${log}"
print_info "Attach: tmux attach -t ${MUSUBI_SESSION}"
print_info "URL   : http://localhost:${MUSUBI_PORT} (via SSH -L ${MUSUBI_PORT}:localhost:${MUSUBI_PORT})"

( sleep 2; curl -fsS "http://127.0.0.1:${MUSUBI_PORT}" >/dev/null && print_info "Musubi appears up on :${MUSUBI_PORT}" ) || true

