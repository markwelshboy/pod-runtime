#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Defaults (match start.comfy.sh expectations)
# -----------------------------------------------------------------------------
: "${WORKSPACE:=/workspace}"

: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"
: "${POD_RUNTIME_ENV:=${POD_RUNTIME_DIR}/.env}"
: "${POD_RUNTIME_HELPERS:=${POD_RUNTIME_DIR}/helpers.sh}"

: "${COMFY_HOME:=/workspace/ComfyUI}"
: "${COMFY_VENV:=/workspace/ComfyUI/venv}"
: "${COMFY_LOGS:=/workspace/logs}"
: "${COMFY_LISTEN:=0.0.0.0}"
: "${COMFY_PORT:=3000}"

: "${ENABLE_SAGE:=false}"

# Swarm: when true, SwarmUI should manage ComfyUI lifecycle (do NOT start here)
: "${SWARMUI_ENABLE:=false}"

# Self-managed launch mode
: "${COMFY_USE_TMUX:=true}"          # if false -> run foreground
: "${TMUX_SESSION:=comfyui-${COMFY_PORT}}"
: "${COMFY_RESTART_DELAY:=1}"

# Per-instance dirs (override if you want)
: "${COMFY_OUT_DIR:=${COMFY_HOME}/output}"
: "${COMFY_CACHE_DIR:=${COMFY_HOME}/cache}"

# Optional: extra args (in addition to the standard ones)
: "${COMFY_EXTRA_ARGS:=}"

# -----------------------------------------------------------------------------
# Load pod-runtime env + helpers (for print_* / require_* / section / urls)
# -----------------------------------------------------------------------------
# shellcheck source=/dev/null
[[ -f "${POD_RUNTIME_ENV}" ]] && source "${POD_RUNTIME_ENV}" || true
# shellcheck source=/dev/null
[[ -f "${POD_RUNTIME_DIR}/secourses/lib/runtime_common.sh" ]] && source "${POD_RUNTIME_DIR}/secourses/lib/runtime_common.sh" || true
# shellcheck source=/dev/null
[[ -f "${POD_RUNTIME_HELPERS}" ]] && source "${POD_RUNTIME_HELPERS}" || true

# Fallback no-op printers if helpers weren’t sourced (keeps script usable standalone)
print_info() { echo "INFO: $*"; }
print_warn() { echo "WARN: $*" >&2; }
print_err()  { echo "ERR : $*" >&2; }
require_cmd(){ command -v "$1" >/dev/null 2>&1 || { print_err "Missing command: $1"; exit 1; }; }
require_dir(){ [[ -d "$1" ]] || { print_err "Missing dir: $1"; exit 1; }; }
require_file(){ [[ -f "$1" ]] || { print_err "Missing file: $1"; exit 1; }; }
print_local_urls(){ :; }

health() {
  local name="$1" port="$2" gvar="$3" logfile="$4"
  local t=0
  until curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; do
    sleep 2
    t=$((t+2))
    if [[ "${t}" -ge 60 ]]; then
      print_warn "${name} on ${port} not HTTP 200 after 60s. Check logs: ${logfile}"
      return 1
    fi
  done
  print_info "🚀 ${name} is UP on :${port} (CUDA_VISIBLE_DEVICES=${gvar})"
  print_info "Logs: ${logfile}"
  print_local_urls "ComfyUI (forward this port locally)" "${port}" "/"
  echo ""
}

build_comfy_command() {
  local port="$1" gvar="$2" out="$3" cache="$4" logfile="$5"

  local py="${COMFY_VENV}/bin/python"
  local sage=""
  if [[ "${ENABLE_SAGE,,}" == "true" ]]; then sage="--use-sage-attention"; fi

  cat <<EOF
set -euo pipefail
cd ${COMFY_HOME@Q}

# Keep env sane inside tmux/launcher
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

exec ${py@Q} ${COMFY_HOME@Q}/main.py --listen ${COMFY_LISTEN@Q} --port ${port@Q} \\
  ${sage} \\
  --output-directory ${out@Q} --temp-directory ${cache@Q} \\
  ${COMFY_EXTRA_ARGS} \\
  >> ${logfile@Q} 2>&1
EOF
}

start_comfy_tmux() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"

  mkdir -p "${out}" "${cache}" "${COMFY_LOGS}"

  local py="${COMFY_VENV}/bin/python"
  [[ -x "${py}" ]] || { print_err "Missing Comfy venv python: ${py}"; return 1; }

  local logfile="${COMFY_LOGS}/comfyui-${port}.log"
  local cmd; cmd="$(build_comfy_command "${port}" "${gvar}" "${out}" "${cache}" "${logfile}")"

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
  ( health "${sess}" "${port}" "${gvar}" "${logfile}" ) || true
}

start_comfy_foreground() {
  local port="$1" gvar="$2" out="$3" cache="$4"

  mkdir -p "${out}" "${cache}" "${COMFY_LOGS}"

  local py="${COMFY_VENV}/bin/python"
  [[ -x "${py}" ]] || { print_err "Missing Comfy venv python: ${py}"; return 1; }

  local logfile="${COMFY_LOGS}/comfyui-${port}.log"
  local cmd; cmd="$(build_comfy_command "${port}" "${gvar}" "${out}" "${cache}" "${logfile}")"

  print_info "ComfyUI launching in foreground (bare shell)"
  print_info "Logs: ${logfile}"
  # Show URLs once it comes up; foreground exec replaces shell
  bash -lc "${cmd}"
}

main() {
  require_cmd curl
  require_dir "${COMFY_HOME}"
  require_file "${COMFY_HOME}/main.py"
  require_file "${COMFY_VENV}/bin/python"
  mkdir -p "${WORKSPACE}" "${COMFY_LOGS}"

  print_info "COMFY_HOME      : ${COMFY_HOME}"
  print_info "COMFY_VENV      : ${COMFY_VENV}"
  print_info "COMFY_PORT      : ${COMFY_PORT}"
  print_info "COMFY_LOGS      : ${COMFY_LOGS}"
  print_info "COMFY_USE_TMUX  : ${COMFY_USE_TMUX}"
  print_info "SWARMUI_ENABLE  : ${SWARMUI_ENABLE}"
  print_info "ENABLE_SAGE     : ${ENABLE_SAGE}"
  print_info "COMFY_EXTRA_ARGS: ${COMFY_EXTRA_ARGS:-<none>}"
  echo ""

  if [[ "${SWARMUI_ENABLE,,}" == "true" ]]; then
    print_info "SWARMUI_ENABLE=true → Not starting ComfyUI here (SwarmUI should manage it)."
    print_info "Configure SwarmUI backend with:"
    print_info "  Path: ${COMFY_HOME}/main.py"
    print_info "  Args: --listen ${COMFY_LISTEN} --port ${COMFY_PORT} $([[ "${ENABLE_SAGE,,}" == "true" ]] && echo "--use-sage-attention") --output-directory ${COMFY_OUT_DIR} --temp-directory ${COMFY_CACHE_DIR} ${COMFY_EXTRA_ARGS}"
    print_info "If SwarmUI starts ComfyUI, it must use the same port (${COMFY_PORT})."
    return 0
  fi

  if [[ "${COMFY_USE_TMUX,,}" == "true" ]]; then
    require_cmd tmux
    start_comfy_tmux "${TMUX_SESSION}" "${COMFY_PORT}" "0" "${COMFY_OUT_DIR}" "${COMFY_CACHE_DIR}"
  else
    start_comfy_foreground "${COMFY_PORT}" "0" "${COMFY_OUT_DIR}" "${COMFY_CACHE_DIR}"
  fi
}

main "$@"
