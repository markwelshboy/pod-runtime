#!/usr/bin/env bash
set -euo pipefail

# ----------------------------
# Defaults (override via env vars)
# ----------------------------
: "${WORKSPACE:=/workspace}"
: "${SWARMUI_HOME:=/workspace/SwarmUI}"

: "${SWARMUI_ENABLE_CLOUDFLARED:=true}"
: "${SWARMUI_CLOUDFLARED_PATH:=/usr/local/bin/cloudflared}"

: "${SWARMUI_COMFYUI_PATH:=/workspace/ComfyUI}"

: "${SWARMUI_PORT:=7861}"
: "${SWARMUI_HOST:=0.0.0.0}"

: "${SWARMUI_LOG_DIR:=/workspace/logs}"
: "${SWARMUI_TMUX_SESSION:=swarmui-${SWARMUI_PORT}}"
: "${SWARMUI_LOG:=${SWARMUI_LOG_DIR}/swarmui-${SWARMUI_PORT}.log}"
: "${SWARMUI_TMUX_ERR:=${SWARMUI_LOG_DIR}/swarmui-${SWARMUI_PORT}.tmux.err}"

: "${DOTNET_ROOT:=/opt/dotnet}"

mkdir -p "${SWARMUI_LOG_DIR}"

# Source pod-runtime env/helpers (your layout)
POD_RUNTIME_DIR="${POD_RUNTIME_DIR:-/workspace/pod-runtime}"
[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

# Fallbacks if helpers aren't loaded
print_info() { printf "[swarmui-gui] INFO: %s\n" "$*"; }
print_warn() { printf "[swarmui-gui] WARN: %s\n" "$*"; }
print_err()  { printf "[swarmui-gui] ERR : %s\n" "$*"; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || { print_err "Missing command: $1"; exit 1; }; }

require_cmd tmux
require_cmd bash

if [[ ! -d "${SWARMUI_HOME}" ]]; then
  print_err "SWARMUI_HOME does not exist: ${SWARMUI_HOME}"
  exit 1
fi

if [[ -d "${SWARMUI_COMFYUI_PATH}" ]]; then
  print_info "ComfyUI path exists: ${SWARMUI_COMFYUI_PATH}"
else
  print_warn "ComfyUI path not found: ${SWARMUI_COMFYUI_PATH} (SwarmUI may still run, but backend link may fail)"
fi

# Build cloudflared args as a *string* (safe to embed)
cloudflared_arg_str=""
if [[ "${SWARMUI_ENABLE_CLOUDFLARED,,}" == "true" ]]; then
  cloudflared_arg_str="--cloudflared-path ${SWARMUI_CLOUDFLARED_PATH@Q}"
fi

# -----------------------------------------------------------------------------
# Stage / link presets into /workspace (zip-style layout expected by tutorials)
# -----------------------------------------------------------------------------
PRESETS_VERSION="v41"
PRESETS_SRC="${POD_RUNTIME_DIR}/secourses/swarmui/Amazing_SwarmUI_Presets_${PRESETS_VERSION}.json"
PRESETS_DST="${WORKSPACE}/Amazing_SwarmUI_Presets_${PRESETS_VERSION}.json"

# If you ever switch versions, just change PRESETS_VERSION.
if [[ -f "${PRESETS_SRC}" ]]; then
  ln -sf "${PRESETS_SRC}" "${PRESETS_DST}"
  print_info "Linked presets: ${PRESETS_DST} -> ${PRESETS_SRC}"
else
  print_warn "Presets source missing: ${PRESETS_SRC}"
fi

# Write a small runner script that tmux executes.
RUNNER="/tmp/run_swarmui_${SWARMUI_PORT}.sh"
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ${SWARMUI_LOG_DIR@Q}

# Breadcrumb first: ensures log exists if we got this far
echo "[swarmui-gui] starting at \$(date -Is)" >> ${SWARMUI_LOG@Q}

cd ${SWARMUI_HOME@Q}

export DOTNET_ROOT=${DOTNET_ROOT@Q}
export PATH="\${DOTNET_ROOT}:\${DOTNET_ROOT}/tools:\${PATH}"

{
  echo "[swarmui-gui] whoami=\$(whoami)"
  echo "[swarmui-gui] pwd=\$(pwd)"
  echo "[swarmui-gui] DOTNET_ROOT=\${DOTNET_ROOT}"
  echo "[swarmui-gui] PATH=\${PATH}"
  echo "[swarmui-gui] dotnet=\$(command -v dotnet || echo MISSING)"
  /bin/ls -la "\${DOTNET_ROOT}/dotnet" 2>/dev/null || true
  dotnet --info >/dev/null 2>&1 || echo "[swarmui-gui] WARN: dotnet not working"
  [[ -x ./launch-linux.sh ]] || { echo "[swarmui-gui] ERR: ./launch-linux.sh missing or not executable"; exit 1; }
  [[ -d .git ]] || echo "[swarmui-gui] WARN: .git missing (may affect SwarmUI launch/build logic)"
} >> ${SWARMUI_LOG@Q} 2>&1

# Launch
./launch-linux.sh --launch_mode none ${cloudflared_arg_str} --port ${SWARMUI_PORT@Q} 2>&1 | tee -a ${SWARMUI_LOG@Q}
EOF
chmod +x "${RUNNER}"

# Start or restart tmux session
if tmux has-session -t "${SWARMUI_TMUX_SESSION}" 2>/dev/null; then
  print_warn "tmux session '${SWARMUI_TMUX_SESSION}' already exists. Restarting it."
  tmux send-keys -t "${SWARMUI_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${SWARMUI_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" C-m
else
  print_info "Creating tmux session '${SWARMUI_TMUX_SESSION}'"
  tmux new-session -d -s "${SWARMUI_TMUX_SESSION}" "bash -lc ${RUNNER@Q}" 2>>"${SWARMUI_TMUX_ERR}"
fi

# Verify tmux session exists
if ! tmux has-session -t "${SWARMUI_TMUX_SESSION}" 2>/dev/null; then
  print_err "tmux session was not created: ${SWARMUI_TMUX_SESSION}"
  print_err "See: ${SWARMUI_TMUX_ERR}"
  tmux ls || true
  exit 1
fi

print_info "SwarmUI is launching in tmux session: ${SWARMUI_TMUX_SESSION}"
print_info "Logs: ${SWARMUI_LOG}"
print_info "tmux stderr: ${SWARMUI_TMUX_ERR}"
print_info "Attach: tmux attach -t ${SWARMUI_TMUX_SESSION}"
