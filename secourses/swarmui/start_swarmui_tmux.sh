#!/usr/bin/env bash
set -euo pipefail

# ----------------------------
# Defaults (override via Vast env vars)
# ----------------------------
: "${SWARMUI_HOME:=/workspace/SwarmUI}"

# If SwarmUI uses cloudflared in your SECourses flow, keep this on.
: "${SWARMUI_ENABLE_CLOUDFLARED:=true}"
: "${SWARMUI_CLOUDFLARED_PATH:=/usr/local/bin/cloudflared}"

# Helps SwarmUI find/point at your backend install
: "${SWARMUI_COMFYUI_PATH:=/workspace/ComfyUI}"

# tmux + logging
: "${SWARMUI_PORT:=7861}"
: "${SWARMUI_HOST:=0.0.0.0}"
: "${SWARMUI_LOG_DIR:=/workspace/logs}"
: "${SWARMUI_TMUX_SESSION:=swarmui-${SWARMUI_PORT}}"
: "${SWARMUI_LOG:=${SWARMUI_LOG_DIR}/swarmui-${SWARMUI_PORT}.log}"

mkdir -p "${SWARMUI_LOG_DIR}"

# Source pod-runtime env/helpers (your layout)
POD_RUNTIME_DIR="${POD_RUNTIME_DIR:-/workspace/pod-runtime}"
[[ -f "${POD_RUNTIME_DIR}/.env" ]] && source "${POD_RUNTIME_DIR}/.env" || true
[[ -f "${POD_RUNTIME_DIR}/helpers.sh" ]] && source "${POD_RUNTIME_DIR}/helpers.sh" || true

# Fallbacks if helpers aren't loaded
print_info() { printf "[swarmui-gui] INFO: %s\n" "$*"; }
print_warn() { printf "[swarmui-gui] WARN: %s\n" "$*"; }
print_err()  { printf "[swarmui-gui] ERR : %s\n" "$*"; }

if ! command -v tmux >/dev/null 2>&1; then
  print_err "tmux not found. Install tmux in the image."
  exit 1
fi

if [[ ! -d "${SWARMUI_HOME}" ]]; then
  print_err "SWARMUI_HOME does not exist: ${SWARMUI_HOME}"
  exit 1
fi

# Optional: attempt to teach SwarmUI where ComfyUI lives (best-effort, non-fatal).
# SwarmUI config formats vary by version; we avoid brittle assumptions.
if [[ -d "${SWARMUI_COMFYUI_PATH}" ]]; then
  print_info "ComfyUI path exists: ${SWARMUI_COMFYUI_PATH}"
else
  print_warn "ComfyUI path not found: ${SWARMUI_COMFYUI_PATH} (SwarmUI may still run, but backend link may fail)"
fi

cloudflared_args=()
if [[ "${SWARMUI_ENABLE_CLOUDFLARED,,}" == "true" ]]; then
  cloudflared_args=(--cloudflared-path "${SWARMUI_CLOUDFLARED_PATH}")
fi

cmd="cd '${SWARMUI_HOME}' && \
  mkdir -p '${SWARMUI_LOG_DIR}' && \
  echo \"[swarmui-gui] starting at \$(date -Is)\" >> '${SWARMUI_LOG}' && \
  ./launch-linux.sh --launch_mode none ${cloudflared_args[*]} --port '${SWARMUI_PORT}' \
    2>&1 | tee -a '${SWARMUI_LOG}'"

# Start or restart session
if tmux has-session -t "${SWARMUI_TMUX_SESSION}" 2>/dev/null; then
  print_warn "tmux session '${SWARMUI_TMUX_SESSION}' already exists. Restarting it."
  tmux send-keys -t "${SWARMUI_TMUX_SESSION}" C-c || true
  sleep 1
  tmux send-keys -t "${SWARMUI_TMUX_SESSION}" "${cmd}" C-m
else
  print_info "Creating tmux session '${SWARMUI_TMUX_SESSION}'"
  tmux new-session -d -s "${SWARMUI_TMUX_SESSION}" "bash -lc ${cmd@Q}"
fi

print_info "SwarmUI is launching in tmux session: ${SWARMUI_TMUX_SESSION}"
print_info "Logs: ${SWARMUI_LOG}"
print_info "Attach: tmux attach -t ${SWARMUI_TMUX_SESSION}"
