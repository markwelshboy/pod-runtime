#!/usr/bin/env bash
set -euo pipefail
trap 'rc=$?; echo "[FATAL] start.comfy.sh exiting rc=$rc at $(date -Is)" | tee -a "${STARTUP_LOG:-/workspace/startup.log}"' EXIT

: "${WORKSPACE:=/workspace}"

: "${POD_RUNTIME_REPO_URL:=https://github.com/markwelshboy/pod-runtime.git}"
: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"
: "${POD_RUNTIME_ENV:=${POD_RUNTIME_DIR}/.env}"
: "${POD_RUNTIME_HELPERS:=${POD_RUNTIME_DIR}/helpers.sh}"

: "${COMFY_HOME:=/workspace/ComfyUI}"
: "${COMFY_VENV:=/workspace/ComfyUI/venv}"
: "${COMFY_LOGS:=/workspace/logs}"
: "${COMFY_LISTEN:=0.0.0.0}"
: "${COMFY_PORT:=3000}"

: "${ENABLE_SAGE:=false}"

# Optional Swarm bits (comfy image can enable these)
: "${SWARMUI_ENABLE:=false}"
: "${SWARMUI_DOWNLOADER_ENABLE:=false}"
: "${SWARMUI_PORT:=7861}"
: "${SWARMUI_DL_PORT:=7162}"

# Launchers (from pod-runtime secourses)
: "${SWARMUI_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_swarmui_tmux.sh}"
: "${SWARMUI_DOWNLOADER_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_downloader_tmux.sh}"

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

# -----------------------------------------------------------------------------
# Load pod-runtime env + helpers
# -----------------------------------------------------------------------------
# shellcheck source=/dev/null
source "${POD_RUNTIME_ENV}"
# shellcheck source=/dev/null
source "${POD_RUNTIME_DIR}/secourses/lib/runtime_common.sh"
# shellcheck source=/dev/null
source "${POD_RUNTIME_HELPERS}"

section 0 "Prepare logging"
start_logging

install_root_shell_dotfiles "${POD_RUNTIME_DIR}"

section 1 "Comfy role startup"
mkdir -p "${WORKSPACE}" "${COMFY_LOGS}"
require_cmd tmux
require_cmd curl

require_dir "${COMFY_HOME}"
require_file "${COMFY_HOME}/main.py"
require_file "${COMFY_VENV}/bin/activate"
require_file "${COMFY_VENV}/bin/python"

# Force venv for *all* subsequent helper calls (banner, ensure dirs, etc.)
export VIRTUAL_ENV="${COMFY_VENV}"
export PATH="${COMFY_VENV}/bin:${PATH}"
export PY="${COMFY_VENV}/bin/python"
export PIP="${COMFY_VENV}/bin/pip"

print_info "COMFY_HOME : ${COMFY_HOME}"
print_info "COMFY_VENV : ${COMFY_VENV}"
print_info "COMFY_PORT : ${COMFY_PORT}"
print_info "COMFY_LOGS : ${COMFY_LOGS}"

# Optional: do your normal comfy prep from helpers.sh (if present)
section 2 "Ensure comfy dirs / banner"
set +e
if command -v ensure_comfy_dirs >/dev/null 2>&1; then ensure_comfy_dirs; else print_warn "ensure_comfy_dirs missing"; fi
if command -v on_start_comfy_banner >/dev/null 2>&1; then on_start_comfy_banner; else print_warn "on_start_comfy_banner missing"; fi
set -e

section 3 "SSH (optional)"
if command -v setup_ssh >/dev/null 2>&1; then setup_ssh; else print_warn "setup_ssh missing"; fi

section 4 "Run ComfyUI (or handoff to SwarmUI)"
"${POD_RUNTIME_DIR}/secourses/run.comfy.sh" || print_warn "run.comfy.sh failed"

section 5 "(Optional) SwarmUI"
if [[ "${SWARMUI_ENABLE,,}" == "true" ]]; then
  if [[ -x "${SWARMUI_LAUNCHER}" ]]; then
    "${SWARMUI_LAUNCHER}" || print_warn "SwarmUI launcher failed (non-fatal)"
    print_local_urls "SwarmUI (forward this port locally)" "${SWARMUI_PORT}" "/"
  else
    print_warn "SWARMUI_ENABLE=true but launcher not executable: ${SWARMUI_LAUNCHER}"
  fi
else
  print_info "SWARMUI_ENABLE is not true; skipping SwarmUI"
fi

section 6 "(Optional) Swarm Downloader"
if [[ "${SWARMUI_DOWNLOADER_ENABLE,,}" == "true" ]]; then
  if [[ -x "${SWARMUI_DOWNLOADER_LAUNCHER}" ]]; then
    "${SWARMUI_DOWNLOADER_LAUNCHER}" || print_warn "Downloader launcher failed (non-fatal)"
    print_local_urls "Swarm Downloader (forward this port locally)" "${SWARMUI_DL_PORT}" "/"
  else
    print_warn "SWARMUI_DOWNLOADER_ENABLE=true but launcher not executable: ${SWARMUI_DOWNLOADER_LAUNCHER}"
  fi
else
  print_info "SWARMUI_DOWNLOADER_ENABLE is not true; skipping downloader"
fi

section 7 "Bootstrap complete"
print_info "Attach: tmux ls"
print_info "Log   : ${STARTUP_LOG:-/workspace/startup.log}"
echo "=== Comfy bootstrap done: $(date) ==="

sleep infinity
