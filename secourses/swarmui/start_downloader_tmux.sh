#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${SWARMUI_DL_LOG_DIR:=${WORKSPACE}/logs}"
: "${SWARMUI_DL_PORT:=7862}"
: "${SWARMUI_DL_HOST:=0.0.0.0}"
: "${SWARMUI_DL_SHARE:=false}"

: "${SWARMUI_DL_TMUX_SESSION:=swarmui_downloader-${SWARMUI_DL_PORT}}"
: "${SWARMUI_DL_LOG:=${SWARMUI_DL_LOG_DIR}/swarmui_downloader-${SWARMUI_DL_PORT}.log}"
: "${SWARMUI_DL_TMUX_ERR:=${SWARMUI_DL_LOG_DIR}/swarmui_downloader-${SWARMUI_DL_PORT}.tmux.err}"

: "${COMFY_VENV:=/workspace/ComfyUI/venv}"

BASE="${POD_RUNTIME_DIR}/secourses/swarmui"
SRC_UTIL="${BASE}/utilities"
DST_UTIL="${WORKSPACE}/utilities"

mkdir -p "${SWARMUI_DL_LOG_DIR}"

[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

print_info() { printf "[swarmui-downloader] INFO: %s\n" "$*"; }
print_warn() { printf "[swarmui-downloader] WARN: %s\n" "$*"; }
print_err()  { printf "[swarmui-downloader] ERR : %s\n" "$*"; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || { print_err "Missing command: $1"; exit 1; }; }
require_cmd tmux
require_cmd bash

# Choose python (prefer Comfy venv)
PY="python3"
if [[ -x "${COMFY_VENV}/bin/python" ]]; then
  PY="${COMFY_VENV}/bin/python"
fi

# Ensure Gradio is present in that env (idempotent)
if ! "${PY}" -c "import gradio" >/dev/null 2>&1; then
  print_warn "gradio missing in ${PY}; installing..."
  [[ -x "${COMFY_VENV}/bin/pip" ]] || { print_err "Missing pip at ${COMFY_VENV}/bin/pip"; exit 1; }
  "${COMFY_VENV}/bin/pip" install --no-cache-dir "gradio==6.2.0"
fi

# Stage patched app + utilities into /workspace
PATCHER="${POD_RUNTIME_DIR}/secourses/swarmui/ensure_downloader_patched.sh"
if [[ -x "${PATCHER}" ]]; then
  "${PATCHER}"
else
  bash "${PATCHER}"
fi

#-- Ensure that utilities are available
[[ -d "${SRC_UTIL}" ]] || { print_info "ERR: Missing ${SRC_UTIL}" >&2; exit 1; }

# Sync utilities so "import utilities.*" works from /workspace
# rsync if available, else fallback to cp -a
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${SRC_UTIL}/" "${DST_UTIL}/"
else
  rm -rf "${DST_UTIL}"
  cp -a "${SRC_UTIL}" "${DST_UTIL}"
fi

DOWNLOADER_APP="${WORKSPACE}/Downloader_Gradio_App.patched.py"
[[ -f "${DOWNLOADER_APP}" ]] || { print_err "Missing: ${DOWNLOADER_APP}"; exit 1; }
[[ -d "${WORKSPACE}/utilities" ]] || { print_err "Missing: ${WORKSPACE}/utilities"; exit 1; }

RUNNER="/tmp/run_swarmui_downloader_${SWARMUI_DL_PORT}.sh"
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ${SWARMUI_DL_LOG_DIR@Q}
echo "[swarmui-downloader] starting at \$(date -Is)" >> ${SWARMUI_DL_LOG@Q}

export WORKSPACE=${WORKSPACE@Q}
export HF_HOME=${WORKSPACE@Q}
export SWARMUI_DL_PORT=${SWARMUI_DL_PORT@Q}
export SWARMUI_DL_HOST=${SWARMUI_DL_HOST@Q}
export SWARMUI_DL_SHARE=${SWARMUI_DL_SHARE@Q}

cd ${WORKSPACE@Q}

echo "[swarmui-downloader] python=${PY}" >> ${SWARMUI_DL_LOG@Q}
echo "[swarmui-downloader] app=${DOWNLOADER_APP}" >> ${SWARMUI_DL_LOG@Q}
echo "[swarmui-downloader] host=\${SWARMUI_DL_HOST} port=\${SWARMUI_DL_PORT} share=\${SWARMUI_DL_SHARE}" >> ${SWARMUI_DL_LOG@Q}

# Optional: pass --share like their instructions (only if requested)
args=()
if [[ "\${SWARMUI_DL_SHARE,,}" == "true" ]]; then
  args+=(--share)
fi

exec ${PY@Q} ${DOWNLOADER_APP@Q} "\${args[@]}" >> ${SWARMUI_DL_LOG@Q} 2>&1
EOF
chmod +x "${RUNNER}"

if tmux has-session -t "${SWARMUI_DL_TMUX_SESSION}" 2>/dev/null; then
  print_info "Restarting existing tmux session: ${SWARMUI_DL_TMUX_SESSION}"
  tmux send-keys -t "${SWARMUI_DL_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${SWARMUI_DL_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" C-m
else
  print_info "Launching new tmux session: ${SWARMUI_DL_TMUX_SESSION}"
  tmux new-session -d -s "${SWARMUI_DL_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" 2>>"${SWARMUI_DL_TMUX_ERR}"
fi

if ! tmux has-session -t "${SWARMUI_DL_TMUX_SESSION}" 2>/dev/null; then
  print_err "tmux session was not created: ${SWARMUI_DL_TMUX_SESSION}"
  print_err "See: ${SWARMUI_DL_TMUX_ERR}"
  tmux ls || true
  exit 1
fi

print_info "Logs  : ${SWARMUI_DL_LOG}"
print_info "tmux stderr: ${SWARMUI_DL_TMUX_ERR}"
print_info "Attach: tmux attach -t ${SWARMUI_DL_TMUX_SESSION}"
print_info "URL   : http://localhost:${SWARMUI_DL_PORT} (via SSH -L ${SWARMUI_DL_PORT}:localhost:${SWARMUI_DL_PORT})"
