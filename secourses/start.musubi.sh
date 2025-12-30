#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"

: "${POD_RUNTIME_REPO_URL:=https://github.com/markwelshboy/pod-runtime.git}"
: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"
: "${POD_RUNTIME_ENV:=${POD_RUNTIME_DIR}/.env}"
: "${POD_RUNTIME_HELPERS:=${POD_RUNTIME_DIR}/helpers.sh}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_VENV:=${MUSUBI_TRAINER_DIR}/venv}"
: "${MUSUBI_GUI:=${MUSUBI_TRAINER_DIR}/gui.py}"

: "${MUSUBI_HOST:=0.0.0.0}"
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SHARE:=false}"
: "${MUSUBI_SESSION:=musubi-${MUSUBI_PORT}}"
: "${MUSUBI_LOGS_DIR:=/workspace/logs}"

: "${MUSUBI_DOWNLOADER_ENABLE:=false}"
: "${MUSUBI_DL_APP:=${POD_RUNTIME_DIR}/secourses/musubi_trainer/Download_Train_Models.py}" # interactive script path if you want
: "${MUSUBI_DL_SESSION:=musubi_downloader-${MUSUBI_DL_PORT}}"

install_root_shell_dotfiles() {
  local repo_root="${1:-/workspace/pod-runtime}"   # pass POD_RUNTIME_DIR if you like
  local target_home="/root"
  local ts; ts="$(date +%Y%m%d_%H%M%S)"

  mkdir -p "$target_home"

  # Backups (if files already exist)
  for f in .bashrc .bash_aliases .bash_functions; do
    if [[ -f "${target_home}/${f}" ]]; then
      cp -a "${target_home}/${f}" "${target_home}/${f}.bak.${ts}"
    fi
  done

  # Render .bashrc with precise placeholder substitution (atomic)
  local src_bashrc="${repo_root}/.bashrc"
  local tmp; tmp="$(mktemp "${target_home}/.bashrc.tmp.XXXXXX")"

  awk -v rr="$repo_root" '
    BEGIN {done=0}
    /^[[:space:]]*REPO_ROOT=<CHANGEME>[[:space:]]*$/ {
      print "REPO_ROOT=" rr
      done=1
      next
    }
    {print}
    END {
      if (!done) {
        # If you want strict mode, uncomment:
        print "ERROR: REPO_ROOT=<CHANGEME> placeholder not found" > "/dev/stderr"
        exit 2
      }
    }
  ' "$src_bashrc" > "$tmp"

  chmod 0644 "$tmp"
  mv -f "$tmp" "${target_home}/.bashrc"

  # Copy the others
  install -m 0644 "${repo_root}/.bash_aliases"   "${target_home}/.bash_aliases"
  install -m 0644 "${repo_root}/.bash_functions" "${target_home}/.bash_functions"

  echo "[dotfiles] Installed bash dotfiles into ${target_home} (repo_root=${repo_root})"
}

start_musubi_gui() {
  local sess="${MUSUBI_SESSION}"
  local log="${MUSUBI_LOGS_DIR}/musubi-${MUSUBI_PORT}.log"
  local py="${MUSUBI_VENV}/bin/python"
  local share_flag=""
  if [[ "${MUSUBI_SHARE,,}" == "true" ]]; then share_flag="--share"; fi

  local cmd
  cmd=$(
    cat <<EOF
set -euo pipefail
cd ${MUSUBI_TRAINER_DIR@Q}

# Keep env sane inside tmux
unset PYTHONPATH PYTHONHOME || true
unset LD_LIBRARY_PATH || true
export PYTHONNOUSERSITE=1

source ${MUSUBI_VENV@Q}/bin/activate

exec ${py@Q} ${MUSUBI_GUI@Q} --listen ${MUSUBI_HOST@Q} --server_port ${MUSUBI_PORT@Q} ${share_flag} \
  >> ${log@Q} 2>&1
EOF
  )

  if tmux has-session -t "${sess}" >/dev/null 2>&1; then
    print_info "Musubi GUI restarting in existing tmux session: ${sess}"
    tmux send-keys -t "${sess}" C-c || true
    sleep 1
    tmux send-keys -t "${sess}" "bash -lc ${cmd@Q}" C-m
  else
    print_info "Musubi GUI launching in new tmux session: ${sess}"
    tmux new-session -d -s "${sess}" "bash -lc ${cmd@Q}"
  fi

  print_info "Logs  : ${log}"
  print_info "Attach: tmux attach -t ${sess}"
  print_local_urls "Musubi GUI (forward this port locally)" "${MUSUBI_PORT}" "/"
}

# shellcheck source=/dev/null
source "${POD_RUNTIME_ENV}"
# shellcheck source=/dev/null
source "${POD_RUNTIME_DIR}/secourses/lib/runtime_common.sh"
# shellcheck source=/dev/null
source "${POD_RUNTIME_HELPERS}"

section 0 "Prepare logging"
start_logging

install_root_shell_dotfiles "${POD_RUNTIME_DIR}"

section 1 "Musubi role startup"
mkdir -p "${WORKSPACE}" "${MUSUBI_LOGS_DIR}"
require_cmd tmux

require_dir "${MUSUBI_TRAINER_DIR}"
require_file "${MUSUBI_GUI}"
require_file "${MUSUBI_VENV}/bin/activate"
require_file "${MUSUBI_VENV}/bin/python"

print_info "MUSUBI_TRAINER_DIR: ${MUSUBI_TRAINER_DIR}"
print_info "MUSUBI_VENV       : ${MUSUBI_VENV}"
print_info "MUSUBI_PORT       : ${MUSUBI_PORT}"
print_info "MUSUBI_LOGS_DIR   : ${MUSUBI_LOGS_DIR}"

section 2 "SSH (optional)"
if command -v setup_ssh >/dev/null 2>&1; then setup_ssh; else print_warn "setup_ssh missing"; fi

section 3 "Create workspace links (optional)"
if [[ -x "${POD_RUNTIME_DIR}/secourses/musubi_trainer/ensure_musubi_workspace_links.sh" ]]; then
  "${POD_RUNTIME_DIR}/secourses/musubi_trainer/ensure_musubi_workspace_links.sh" || true
else
  print_warn "No ensure_musubi_workspace_links.sh found; skipping"
fi

section 4 "Run Musubi GUI..."
start_musubi_gui

section 5 "(Optional) Auto-launch Musubi Downloader tmux"
if [[ "${MUSUBI_DOWNLOADER_ENABLE,,}" == "true" ]]; then
  ${POD_RUNTIME_DIR}/secourses/musubi_trainer/start_musubi_downloader_tmux.sh || true
else
  print_info "MUSUBI_DOWNLOADER_ENABLE is not true; skipping Musubi Downloader launch."
fi

section 6 "Bootstrap complete"
print_info "Attach: tmux ls"
print_info "Log   : ${STARTUP_LOG:-/workspace/startup.log}"
echo "=== Musubi bootstrap done: $(date) ==="

sleep infinity
