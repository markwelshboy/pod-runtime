#!/usr/bin/env bash
set -euo pipefail

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
: "${SWARMUI_DL_PORT:=7163}"

# Launchers (from pod-runtime secourses)
: "${SWARMUI_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_swarmui_tmux.sh}"
: "${SWARMUI_DOWNLOADER_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_downloader_tmux.sh}"

health() {
  local name="$1" port="$2" gvar="$3" out="$4" cache="$5"
  local t=0
  until curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; do
    sleep 2
    t=$((t+2))
    if [[ "${t}" -ge 60 ]]; then
      print_warn "${name} on ${port} not HTTP 200 after 60s. Check logs: ${COMFY_LOGS}/comfyui-${port}.log"
      return 1
    fi
  done
  print_info "🚀 ${name} is UP on :${port} (CUDA_VISIBLE_DEVICES=${gvar})"
  print_info "Logs: ${COMFY_LOGS}/comfyui-${port}.log"
  print_local_urls "ComfyUI (forward this port locally)" "${port}" "/"
  echo ""
}

start_one() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"
  : "${COMFY_RESTART_DELAY:=1}"

  mkdir -p "${out}" "${cache}" "${COMFY_LOGS}"

  local py="${COMFY_VENV}/bin/python"
  [[ -x "${py}" ]] || { print_err "Missing Comfy venv python: ${py}"; return 1; }

  local logfile="${COMFY_LOGS}/comfyui-${port}.log"
  local sage=""
  if [[ "${ENABLE_SAGE,,}" == "true" ]]; then sage="--use-sage-attention"; fi

  local cmd
  cmd=$(
    cat <<EOF
set -euo pipefail
cd ${COMFY_HOME@Q}

# Keep env sane inside tmux
unset PYTHONPATH PYTHONHOME || true
unset LD_LIBRARY_PATH || true
export PYTHONNOUSERSITE=1

# Force venv usage (ComfyUI-Manager installs, custom_nodes, etc.)
export VIRTUAL_ENV=${COMFY_VENV@Q}
export PATH=${COMFY_VENV@Q}/bin:"\$PATH"

# Refuse global pip installs (prevents /usr/local/dist-packages growth)
export PIP_REQUIRE_VIRTUALENV=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_CACHE_DIR=1

# If user already set CUDA_VISIBLE_DEVICES, do NOT override it.
if [[ -z "\${CUDA_VISIBLE_DEVICES:-}" ]]; then
  export CUDA_VISIBLE_DEVICES=${gvar@Q}
fi

export PYTHONUNBUFFERED=1

exec ${py@Q} ${COMFY_HOME@Q}/main.py --listen ${COMFY_LISTEN@Q} --port ${port@Q} \
  ${sage} \
  --output-directory ${out@Q} --temp-directory ${cache@Q} \
  >> ${logfile@Q} 2>&1
EOF
  )
  
  if tmux has-session -t "${sess}" >/dev/null 2>&1; then
    print_info "ComfyUI restarting in existing tmux session: ${sess}"
    tmux send-keys -t "${sess}" C-c || true
    sleep "${COMFY_RESTART_DELAY}"
    tmux send-keys -t "${sess}" "bash -lc ${cmd@Q}" C-m
  else
    print_info "ComfyUI launching in new tmux session: ${sess}"
    tmux new-session -d -s "${sess}" "bash -lc ${cmd@Q}"
  fi

  print_info "Logs  : ${logfile}"
  print_info "Attach: tmux attach -t ${sess}"
  ( health "${sess}" "${port}" "${gvar}" "${out}" "${cache}" ) || true
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

section 1 "Comfy role startup"
mkdir -p "${WORKSPACE}" "${COMFY_LOGS}"
require_cmd tmux
require_cmd curl

require_dir "${COMFY_HOME}"
require_file "${COMFY_HOME}/main.py"
require_file "${COMFY_VENV}/bin/activate"
require_file "${COMFY_VENV}/bin/python"

print_info "COMFY_HOME : ${COMFY_HOME}"
print_info "COMFY_VENV : ${COMFY_VENV}"
print_info "COMFY_PORT : ${COMFY_PORT}"
print_info "COMFY_LOGS : ${COMFY_LOGS}"

# Optional: do your normal comfy prep from helpers.sh (if present)
section 2 "Ensure comfy dirs / banner"
if command -v ensure_comfy_dirs >/dev/null 2>&1; then ensure_comfy_dirs; else print_warn "ensure_comfy_dirs missing"; fi
if command -v on_start_comfy_banner >/dev/null 2>&1; then on_start_comfy_banner; else print_warn "on_start_comfy_banner missing"; fi

section 3 "SSH (optional)"
if command -v setup_ssh >/dev/null 2>&1; then setup_ssh; else print_warn "setup_ssh missing"; fi

section 4 "Run ComfyUI"
start_one "comfy-${COMFY_PORT}" "${COMFY_PORT}" "0" "${COMFY_HOME}/output" "${COMFY_HOME}/cache"

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
