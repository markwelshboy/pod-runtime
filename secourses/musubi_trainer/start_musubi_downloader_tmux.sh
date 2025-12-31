#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi-downloader] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-downloader] WARN: %s\n" "$*"; }
print_err()  { printf "[musubi-downloader] ERR : %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"

: "${MUSUBI_ASSETS_DIR:=${POD_RUNTIME_DIR}/secourses/musubi_trainer}"
: "${MUSUBI_DL_APP:=${MUSUBI_ASSETS_DIR}/Download_Train_Models.py}"

: "${MUSUBI_DL_LOGS_DIR:=${WORKSPACE}/logs}"
: "${MUSUBI_DL_SESSION:=musubi_downloader-interactive}"
: "${MUSUBI_DL_LOG:=${MUSUBI_DL_LOGS_DIR}/musubi_downloader-interactive.log}"
: "${MUSUBI_DL_ENABLE_LOG:=true}"
: "${MUSUBI_DL_RESTART_DELAY:=1}"

mkdir -p "${MUSUBI_DL_LOGS_DIR}"

command -v tmux >/dev/null 2>&1 || { print_err "tmux not found"; exit 1; }
[[ -d "${MUSUBI_TRAINER_DIR}" ]] || { print_err "Trainer dir not found: ${MUSUBI_TRAINER_DIR}"; exit 1; }
[[ -d "${MUSUBI_VENV}" ]] || { print_err "Trainer venv not found: ${MUSUBI_VENV}"; exit 1; }
[[ -f "${MUSUBI_DL_APP}" ]] || { print_err "Downloader not found: ${MUSUBI_DL_APP}"; exit 1; }

# Stage links into /workspace (non-fatal)
LINKER="${POD_RUNTIME_DIR}/secourses/musubi_trainer/ensure_musubi_workspace_links.sh"
if [[ -f "${LINKER}" ]]; then
  bash "${LINKER}" || print_warn "ensure_musubi_workspace_links.sh failed (non-fatal)"
fi

run_line="python ${MUSUBI_DL_APP@Q}"
if [[ "${MUSUBI_DL_ENABLE_LOG,,}" == "true" ]]; then
  run_line="python ${MUSUBI_DL_APP@Q} 2>&1 | tee -a ${MUSUBI_DL_LOG@Q}"
fi

cmd=$(
  cat <<EOF
set -euo pipefail
cd ${WORKSPACE@Q}
source ${MUSUBI_VENV@Q}/bin/activate
unset LD_LIBRARY_PATH || true
${run_line}
EOF
)

if tmux has-session -t "${MUSUBI_DL_SESSION}" >/dev/null 2>&1; then
  print_info "Restarting existing tmux session: ${MUSUBI_DL_SESSION}"
  tmux send-keys -t "${MUSUBI_DL_SESSION}" C-c || true
  sleep "${MUSUBI_DL_RESTART_DELAY}"
  tmux send-keys -t "${MUSUBI_DL_SESSION}" "bash -lc ${cmd@Q}" C-m
else
  print_info "Creating tmux session: ${MUSUBI_DL_SESSION}"
  tmux new-session -d -s "${MUSUBI_DL_SESSION}" "bash -lc ${cmd@Q}"
fi

print_info "Attach: tmux attach -t ${MUSUBI_DL_SESSION}"
[[ "${MUSUBI_DL_ENABLE_LOG,,}" == "true" ]] && print_info "Log   : ${MUSUBI_DL_LOG}"
