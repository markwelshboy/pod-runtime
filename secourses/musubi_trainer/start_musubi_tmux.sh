#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi-trainer] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-trainer] WARN: %s\n" "$*"; }
print_err()  { printf "[musubi-trainer] ERR : %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"
: "${MUSUBI_GUI:=${MUSUBI_TRAINER_DIR}/gui.py}"

: "${MUSUBI_HOST:=0.0.0.0}"
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SHARE:=false}"
: "${MUSUBI_HEADLESS:=true}"

: "${MUSUBI_SESSION:=musubi-${MUSUBI_PORT}}"
: "${MUSUBI_LOGS_DIR:=${WORKSPACE}/logs}"
: "${MUSUBI_RESTART_DELAY:=1}"

mkdir -p "${MUSUBI_LOGS_DIR}"

command -v tmux >/dev/null 2>&1 || { print_err "tmux not found"; exit 1; }
[[ -d "${MUSUBI_TRAINER_DIR}" ]] || { print_err "Trainer dir not found: ${MUSUBI_TRAINER_DIR}"; exit 1; }
[[ -d "${MUSUBI_VENV}" ]] || { print_err "Trainer venv not found: ${MUSUBI_VENV}"; exit 1; }
[[ -f "${MUSUBI_GUI}" ]] || { print_err "gui.py not found: ${MUSUBI_GUI}"; exit 1; }

# Stage links into /workspace (non-fatal)
LINKER="${POD_RUNTIME_DIR}/secourses/musubi_trainer/ensure_musubi_workspace_links.sh"
if [[ -f "${LINKER}" ]]; then
  bash "${LINKER}" || print_warn "ensure_musubi_workspace_links.sh failed (non-fatal)"
fi

share_flag=""
if [[ "${MUSUBI_SHARE,,}" == "true" ]]; then share_flag="--share"; fi

headless_flag=""
if [[ "${MUSUBI_HEADLESS,,}" == "true" ]]; then headless_flag="--headless"; fi

log="${MUSUBI_LOGS_DIR}/musubi-${MUSUBI_PORT}.log"

# Runner script avoids quoting edge-cases
RUNNER="/tmp/run_musubi_${MUSUBI_PORT}.sh"
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
mkdir -p ${MUSUBI_LOGS_DIR@Q}
echo "[musubi-trainer] starting at \$(date -Is)" >> ${log@Q}

cd ${MUSUBI_TRAINER_DIR@Q}
source ${MUSUBI_VENV@Q}/bin/activate

unset LD_LIBRARY_PATH || true

exec python ${MUSUBI_GUI@Q} \
  --listen ${MUSUBI_HOST@Q} \
  --server_port ${MUSUBI_PORT@Q} \
  ${share_flag} \
  ${headless_flag} \
  >> ${log@Q} 2>&1
EOF
chmod +x "${RUNNER}"

if tmux has-session -t "${MUSUBI_SESSION}" >/dev/null 2>&1; then
  print_info "Restarting existing tmux session: ${MUSUBI_SESSION}"
  tmux send-keys -t "${MUSUBI_SESSION}" C-c || true
  sleep "${MUSUBI_RESTART_DELAY}"
  tmux send-keys -t "${MUSUBI_SESSION}" "bash -lc ${RUNNER@Q}" C-m
else
  print_info "Creating tmux session: ${MUSUBI_SESSION}"
  tmux new-session -d -s "${MUSUBI_SESSION}" "bash -lc ${RUNNER@Q}"
fi

print_info "Session: ${MUSUBI_SESSION}"
print_info "Log    : ${log}"
print_info "Attach : tmux attach -t ${MUSUBI_SESSION}"
print_info "URL    : http://localhost:${MUSUBI_PORT} (via SSH -L ${MUSUBI_PORT}:localhost:${MUSUBI_PORT})"
