#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Minimal fallbacks (helpers.sh can override these)
# -----------------------------------------------------------------------------
print_info() { printf "[start.secourses] INFO: %s\n" "$*"; }
print_warn() { printf "[start.secourses] WARN: %s\n" "$*"; }
print_err()  { printf "[start.secourses] ERR : %s\n" "$*"; }

section() {
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    printf "\n================================================================================\n"
    printf "=== %s: %s\n" "${1}" "${2:-}"
    printf "================================================================================\n"
  else
    printf "\n================================================================================\n"
    printf "=== %s\n" "${1:-}"
    printf "================================================================================\n"
  fi
}

# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------
health() {
  local name="$1" port="$2" gvar="$3" out="$4" cache="$5"
  local t=0

  until curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; do
    sleep 2
    t=$((t + 2))
    if [[ "${t}" -ge 60 ]]; then
      print_warn "${name} on ${port} not HTTP 200 after 60s. Check logs: ${COMFY_LOGS}/comfyui-${port}.log"
      return 1
    fi
  done

  print_info "🚀 ${name} is UP on :${port} (Runtime Options: ${SAGE_ATTENTION:-} CUDA_VISIBLE_DEVICES=${gvar})"
  print_info "       Output: ${out}"
  print_info "   Temp/Cache: ${cache}"
  print_info "       Log(s): ${COMFY_LOGS}/comfyui-${port}.log"
  echo ""
  return 0
}

# -----------------------------------------------------------------------------
# Start one Comfy session in tmux
# -----------------------------------------------------------------------------
start_one() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"

  mkdir -p "${out}" "${cache}" "${COMFY_LOGS}"

  local cmd
  cmd=$(
    cat <<EOF
set -euo pipefail
cd "${COMFY_HOME}"
if [[ -z "\${CUDA_VISIBLE_DEVICES:-}" ]]; then
  export CUDA_VISIBLE_DEVICES="${gvar}"
fi
export PYTHONUNBUFFERED=1
python "${COMFY_HOME}/main.py" --listen "${COMFY_LISTEN}" --port "${port}" \
  ${SAGE_ATTENTION:-} \
  --output-directory "${out}" --temp-directory "${cache}" \
  >> "${COMFY_LOGS}/comfyui-${port}.log" 2>&1
EOF
  )

  if tmux has-session -t "${sess}" >/dev/null 2>&1; then
    print_warn "tmux session ${sess} already exists; leaving it running."
  else
    tmux new-session -d -s "${sess}" "${cmd}"
    print_info "Started tmux session: ${sess} (port ${port})"
  fi

  ( health "${sess}" "${port}" "${gvar}" "${out}" "${cache}" ) || true
}

# -----------------------------------------------------------------------------
# SwarmUI workspace links
# -----------------------------------------------------------------------------
ensure_swarmui_workspace_links() {
  local src_dir="${POD_RUNTIME_DIR}/secourses/swarmui"
  local ws="/workspace"

  [[ -d "${src_dir}" ]] || { print_warn "SwarmUI dir not present at ${src_dir}; skipping links."; return 0; }

  if [[ -d "${src_dir}/utilities" ]]; then
    if [[ -e "${ws}/utilities" && ! -L "${ws}/utilities" ]]; then
      print_warn "${ws}/utilities exists and is not a symlink; leaving it alone."
    else
      ln -sfn "${src_dir}/utilities" "${ws}/utilities"
      print_info "Linked: ${ws}/utilities -> ${src_dir}/utilities"
    fi
  else
    print_warn "No utilities dir found at: ${src_dir}/utilities"
  fi

  #-- JSON Presets for SwarmUI

  if [[ -f "${src_dir}/Amazing_SwarmUI_Presets_${JSON_PRESET_VERSION}.json" ]]; then
    local target="${ws}/Amazing_SwarmUI_Presets_${JSON_PRESET_VERSION}.json"
    if [[ -e "${target}" && ! -L "${target}" ]]; then
      print_warn "${target} exists and is not a symlink; leaving it alone."
    else
      ln -sfn "${src_dir}/Amazing_SwarmUI_Presets_${JSON_PRESET_VERSION}.json" "${target}"
      print_info "Linked: ${target} -> ${src_dir}/Amazing_SwarmUI_Presets_${JSON_PRESET_VERSION}.json"
    fi
  else
    print_warn "No presets file found at: ${src_dir}/Amazing_SwarmUI_Presets_${JSON_PRESET_VERSION}.json"
  fi

}

# -----------------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------------
: "${WORKSPACE:=/workspace}"

: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"
: "${POD_RUNTIME_ENV:=${POD_RUNTIME_DIR}/.env}"
: "${POD_RUNTIME_HELPERS:=${POD_RUNTIME_DIR}/helpers.sh}"

: "${COMFY_HOME:=/workspace/ComfyUI}"
: "${COMFY_LOGS:=/workspace/logs}"
: "${COMFY_DOWNLOADS:=/workspace/downloads}"
: "${COMFY_VENV:=/workspace/ComfyUI/venv}"
: "${COMFY_LISTEN:=0.0.0.0}"
: "${COMFY_PORT:=3000}"

: "${ENABLE_SAGE:=true}"
: "${RUNTIME_ENSURE_INSTALL:=false}"

: "${SWARMUI_ENABLE:=true}"
: "${SWARMUI_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_swarmui_tmux.sh}"

: "${SWARMUI_DOWNLOADER_ENABLE:=true}"
: "${SWARMUI_DOWNLOADER_LAUNCHER:=${POD_RUNTIME_DIR}/secourses/swarmui/start_downloader_tmux.sh}"

: "${JSON_PRESET_VERSION:=v40}"

: "${MUSUBI_ENABLE:=false}"
: "${MUSUBI_DOWNLOADER_ENABLE:=false}"

mkdir -p "${WORKSPACE}" "${COMFY_LOGS}" "${COMFY_DOWNLOADS}"

cd ${WORKSPACE}

# Source env + helpers if present (non-fatal if missing)
if [[ -f "${POD_RUNTIME_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${POD_RUNTIME_ENV}"
else
  print_warn ".env not found at ${POD_RUNTIME_ENV} (continuing)"
fi

if [[ -f "${POD_RUNTIME_HELPERS}" ]]; then
  # shellcheck disable=SC1090
  source "${POD_RUNTIME_HELPERS}"
else
  print_warn "helpers.sh not found at ${POD_RUNTIME_HELPERS} (continuing)"
fi

# Override defaults with SECourses environment specifics

PY=${COMFY_VENV}/bin/python
PIP=${COMFY_VENV}/bin/pip

# -----------------------------------------------------------------------------
# Startup logging
# -----------------------------------------------------------------------------
section 0 "Prepare Session Logging..."
STARTUP_LOG="${WORKSPACE}/startup.log"
exec > >(tee -a "${STARTUP_LOG}") 2>&1
print_info "Logging to: ${STARTUP_LOG}"

# -----------------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------------
section 1 "Container startup..."
print_info "Workspace dropzone  : ${WORKSPACE} (logs=${COMFY_LOGS}, downloads=${COMFY_DOWNLOADS})"
print_info "POD_RUNTIME_DIR     : ${POD_RUNTIME_DIR}"

# Ensure ComfyUI exists
if [[ ! -d "${COMFY_HOME}" ]]; then
  print_warn "ComfyUI not found at ${COMFY_HOME}."
  if [[ "${RUNTIME_ENSURE_INSTALL,,}" == "true" ]]; then
    /opt/install_secourses_comfyui.sh
  else
    print_err "Image was expected to be build-baked. Exiting."
    exit 1
  fi
else
  print_info "ComfyUI found at ${COMFY_HOME}."
  [[ -d "${COMFY_VENV}" ]] || { print_err "Comfy venv not found at ${COMFY_VENV}"; exit 1; }
fi

# Helpers from pod-runtime (optional)
command -v ensure_comfy_dirs >/dev/null 2>&1 && ensure_comfy_dirs || true
command -v on_start_comfy_banner >/dev/null 2>&1 && on_start_comfy_banner || true

# -----------------------------------------------------------------------------
# Enable SSH for the container (optiona)
# -----------------------------------------------------------------------------

section 2 "SSH"
command -v setup_ssh >/dev/null 2>&1 && setup_ssh || print_warn "setup_ssh not found; skipping."

# -----------------------------------------------------------------------------
# Enable SwarmUI links
# -----------------------------------------------------------------------------

section 3 "SwarmUI workspace link setup"
ensure_swarmui_workspace_links || true

# -----------------------------------------------------------------------------
# Launch ComfyUI.....
# -----------------------------------------------------------------------------

section 4 "Run ComfyUI"
# shellcheck disable=SC1090
source "${COMFY_VENV}/bin/activate"

SAGE_ATTENTION="$({ [[ "${ENABLE_SAGE,,}" == "true" ]] && printf '%s' --use-sage-attention; } || true)"

print_info "Launching ComfyUI (tmux session: comfy-${COMFY_PORT})"
cd "${COMFY_HOME}"

mkdir -p "output" "cache"
start_one "comfy-${COMFY_PORT}" "${COMFY_PORT}" "0" "output" "cache"

# -----------------------------------------------------------------------------
# Enable Optional SwarmUI launchers
# -----------------------------------------------------------------------------

section 5 "(Optional) Auto-launch SwarmUI tmux"
if [[ "${SWARMUI_ENABLE,,}" == "true" ]]; then
  [[ -x "${SWARMUI_LAUNCHER}" ]] && "${SWARMUI_LAUNCHER}" || print_warn "SwarmUI launcher not runnable: ${SWARMUI_LAUNCHER}"
else
  print_info "SWARMUI_ENABLE is not true; skipping SwarmUI launch."
fi

section 6 "(Optional) Auto-launch Downloader tmux"
if [[ "${SWARMUI_DOWNLOADER_ENABLE,,}" == "true" ]]; then
  [[ -x "${SWARMUI_DOWNLOADER_LAUNCHER}" ]] && "${SWARMUI_DOWNLOADER_LAUNCHER}" || print_warn "Downloader launcher not runnable: ${SWARMUI_DOWNLOADER_LAUNCHER}"
else
  print_info "SWARMUI_DOWNLOADER_ENABLE is not true; skipping SwarmUI downloader launch."
fi

# -----------------------------------------------------------------------------
# Musubi Trainer/Tuner
# -----------------------------------------------------------------------------

# Ensure trainer/tuner workspace links
${POD_RUNTIME_DIR}/secourses/musubi_trainer/ensure_musubi_workspace_links.sh || true

section 7 "(Optional) Auto-launch Musubi Trainer/Tuner tmux"

if [[ "${MUSUBI_ENABLE,,}" == "true" ]]; then
  ${POD_RUNTIME_DIR}/secourses/musubi_trainer/start_musubi_tmux.sh || true
else
  print_info "MUSUBI_ENABLE is not true; skipping Musubi Trainer/Tuner launch."
fi

section 8 "(Optional) Auto-launch Musubi Downloader tmux"

if [[ "${MUSUBI_DOWNLOADER_ENABLE,,}" == "true" ]]; then
  ${POD_RUNTIME_DIR}/secourses/musubi_trainer/start_musubi_downloader_tmux.sh || true
else
  print_info "MUSUBI_DOWNLOADER_ENABLE is not true; skipping Musubi Downloader launch."
fi

# -----------------------------------------------------------------------------
# Bootstrap complete....
# -----------------------------------------------------------------------------

echo ""
print_info "Bootstrap complete. Bootstrap log: ${STARTUP_LOG}"
print_info "General ComfyUI logs: ${COMFY_LOGS}"
echo ""
print_info "=== Bootstrap done: $(date) ==="

sleep infinity
