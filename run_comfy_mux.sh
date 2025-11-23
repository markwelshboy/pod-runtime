#!/usr/bin/env bash
set -euo pipefail

# ----- Required env vars -----
: "${COMFY_HOME:?COMFY_HOME must be set}"
: "${COMFY_LOGS:?COMFY_LOGS must be set}"

export PATH="/opt/venv/bin:${PATH}"
BASE="${COMFY_HOME}"
LOGS="${COMFY_LOGS}"

# ----- Optional SAGE attention flag -----
sage_attention=$({ [[ "${ENABLE_SAGE:-true}" == "true" ]] && printf '%s' --use-sage-attention; } || true)

# ----- Basic tool sanity -----
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python not found in PATH" >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "ERROR: tmux not found in PATH (required for multi-session launch)" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl not found in PATH (required for health checks)" >&2
  exit 1
fi

# ----- GPU count -----
gpus="$(python - <<'PY'
import torch
print(torch.cuda.device_count() if torch.cuda.is_available() else 0)
PY
)"

printf "INFO: Available GPUs: %s\n" "${gpus}"

# ----- Health check -----
health() {
  local name="$1" port="$2" gvar="$3" out="$4" cache="$5"
  local t=0

  until curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; do
    sleep 2
    t=$((t + 2))
    if [ "${t}" -ge 60 ]; then
      echo "WARN: ${name} on ${port} not HTTP 200 after 60s. Check logs: ${LOGS}/comfyui-${port}.log"
      exit 1
    fi
  done

  echo "🚀 ${name} is UP on :${port} (Runtime Options: ${sage_attention} CUDA_VISIBLE_DEVICES=${gvar})"
  echo "       Output: ${out}"
  echo "   Temp/Cache: ${cache}"
  echo "          Log: ${LOGS}/comfyui-${port}.log"
  echo ""
}

# ----- Start one Comfy session in tmux -----
start_one() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"

  mkdir -p "${out}" "${cache}"

  tmux new-session -d -s "${sess}" \
    "CUDA_VISIBLE_DEVICES=${gvar} PYTHONUNBUFFERED=1 \
     python \"${BASE}/main.py\" --listen --port ${port} \
       ${sage_attention} \
       --output-directory \"${out}\" --temp-directory \"${cache}\" \
       >> \"${LOGS}/comfyui-${port}.log\" 2>&1" \
    || echo "WARN: tmux session ${sess} may already exist; skipping creation"

  # Run health in a subshell so its exit doesn't kill the main script; we just log.
  ( health "${sess}" "${port}" "${gvar}" "${out}" "${cache}" ) || true
}

# ----- Primary / default session on 8188 -----
mkdir -p "${BASE}/output" "${BASE}/cache"

tmux new-session -d -s comfy-8188 \
  "PYTHONUNBUFFERED=1 \
   python \"${BASE}/main.py\" --listen --port 8188 ${sage_attention} \
     --output-directory \"${BASE}/output\" --temp-directory \"${BASE}/cache\" \
     >> \"${LOGS}/comfyui-8188.log\" 2>&1" \
  || echo "WARN: tmux session comfy-8188 may already exist; skipping creation"

( health "comfy-8188" 8188 "unset" "${BASE}/output" "${BASE}/cache" ) || true

# ----- GPU-bound sessions (one per GPU) -----
if [ "${gpus}" -ge 1 ]; then
  start_one comfy-8288 8288 0 "${BASE}/output_gpu0" "${BASE}/cache_gpu0"
fi
if [ "${gpus}" -ge 2 ]; then
  start_one comfy-8388 8388 1 "${BASE}/output_gpu1" "${BASE}/cache_gpu1"
fi
if [ "${gpus}" -ge 3 ]; then
  start_one comfy-8488 8488 2 "${BASE}/output_gpu2" "${BASE}/cache_gpu2"
fi
if [ "${gpus}" -ge 4 ]; then
  start_one comfy-8588 8588 3 "${BASE}/output_gpu3" "${BASE}/cache_gpu3"
fi

sleep 5
tmux ls || echo "INFO: tmux is not listing sessions (no server?)"
