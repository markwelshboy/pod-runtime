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

# Prefer comfy venv python if present (downloader is just python)
: "${COMFY_VENV:=/workspace/ComfyUI/venv}"

mkdir -p "${SWARMUI_DL_LOG_DIR}"

[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

print_info() { printf "[swarmui-downloader] INFO: %s\n" "$*"; }
print_warn() { printf "[swarmui-downloader] WARN: %s\n" "$*"; }
print_err()  { printf "[swarmui-downloader] ERR : %s\n" "$*"; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || { print_err "Missing command: $1"; exit 1; }; }
require_cmd tmux
require_cmd bash

# Generate /workspace/Downloader_Gradio_App.patched.py
if [[ -x "${POD_RUNTIME_DIR}/secourses/swarmui/ensure_downloader_patched.sh" ]]; then
  "${POD_RUNTIME_DIR}/secourses/swarmui/ensure_downloader_patched.sh"
else
  # be resilient if exec bit gets lost
  bash "${POD_RUNTIME_DIR}/secourses/swarmui/ensure_downloader_patched.sh"
fi

DOWNLOADER_APP="${WORKSPACE}/Downloader_Gradio_App.patched.py"
if [[ ! -f "${DOWNLOADER_APP}" ]]; then
  print_err "Missing: ${DOWNLOADER_APP}"
  exit 1
fi

# Choose python
PY="python"
if [[ -x "${COMFY_VENV}/bin/python" ]]; then
  PY="${COMFY_VENV}/bin/python"
fi

# Ensure gradio is present in the selected python env (fast + idempotent)
if ! "${PY}" -c "import gradio" >/dev/null 2>&1; then
  print_warn "gradio not found in ${PY}. Installing into Comfy venv..."
  if [[ -x "${COMFY_VENV}/bin/pip" ]]; then
    "${COMFY_VENV}/bin/pip" install --no-cache-dir "gradio==6.2.0"
  else
    print_err "Missing pip in Comfy venv: ${COMFY_VENV}/bin/pip"
    exit 1
  fi
fi

# Runner script for tmux (avoids quoting bugs)
RUNNER="/tmp/run_swarmui_downloader_${SWARMUI_DL_PORT}.sh"
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ${SWARMUI_DL_LOG_DIR@Q}

# Breadcrumb first (forces log file existence if we got here)
echo "[swarmui-downloader] starting at \$(date -Is)" >> ${SWARMUI_DL_LOG@Q}

export WORKSPACE=${WORKSPACE@Q}
export SWARMUI_DL_PORT=${SWARMUI_DL_PORT@Q}
export SWARMUI_DL_HOST=${SWARMUI_DL_HOST@Q}
export SWARMUI_DL_SHARE=${SWARMUI_DL_SHARE@Q}

# Optional auth: prefer env var passed in from pod (.env) or runtime
# (do NOT hardcode tokens into scripts)
if [[ -n "\${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
  echo "[swarmui-downloader] HUGGING_FACE_HUB_TOKEN is set (length=\${#HUGGING_FACE_HUB_TOKEN})" >> ${SWARMUI_DL_LOG@Q}
fi

cd ${WORKSPACE@Q}

echo "[swarmui-downloader] python=$PY" >> ${SWARMUI_DL_LOG@Q}
echo "[swarmui-downloader] app=${DOWNLOADER_APP}" >> ${SWARMUI_DL_LOG@Q}
echo "[swarmui-downloader] host=\${SWARMUI_DL_HOST} port=\${SWARMUI_DL_PORT} share=\${SWARMUI_DL_SHARE}" >> ${SWARMUI_DL_LOG@Q}

exec ${PY@Q} ${DOWNLOADER_APP@Q} >> ${SWARMUI_DL_LOG@Q} 2>&1
EOF
chmod +x "${RUNNER}"

# Start / restart tmux session
if tmux has-session -t "${SWARMUI_DL_TMUX_SESSION}" 2>/dev/null; then
  print_info "Gradio Downloader restarting in existing tmux session: ${SWARMUI_DL_TMUX_SESSION}"
  tmux send-keys -t "${SWARMUI_DL_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${SWARMUI_DL_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" C-m
else
  print_info "Gradio Downloader launching in new tmux session: ${SWARMUI_DL_TMUX_SESSION}"
  tmux new-session -d -s "${SWARMUI_DL_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" 2>>"${SWARMUI_DL_TMUX_ERR}"
fi

# Verify tmux session exists
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
