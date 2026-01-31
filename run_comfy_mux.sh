#!/usr/bin/env bash
set -euo pipefail

# run_comfy_mux.sh
#
# A small "service manager" for multi-port ComfyUI in tmux.
#
# Usage:
#   run_comfy_mux.sh start
#   run_comfy_mux.sh stop [--hard]
#   run_comfy_mux.sh restart
#   run_comfy_mux.sh hard-restart
#   run_comfy_mux.sh status
#
# Env (required):
#   COMFY_HOME    e.g. /workspace/ComfyUI
#   COMFY_LOGS    e.g. /workspace/logs
#
# Env (optional):
#   ENABLE_SAGE=true|false      (default true)
#   START_TIMEOUT=seconds       (default 60)  # wait for 8188
#   GPU_PORT_BASE=8288          (default 8288) # gpu0=8288, gpu1=8388, ...
#   MAX_GPU_SESSIONS=4          (default 4)    # how many gpu sessions to spawn max
#
# Output (on start):
#   Prints a machine-readable line:
#     COMFY_START_MASK=0x07 COMFY_START_BITS=00111
#
# Bit layout (LSB first):
#   bit0: 8188
#   bit1: 8288
#   bit2: 8388
#   bit3: 8488
#   bit4: 8588
# (So mask 0x07 means 8188+8288+8388 are up.)

ACTION="${1:-start}"

: "${COMFY_HOME:?COMFY_HOME must be set}"
: "${COMFY_LOGS:?COMFY_LOGS must be set}"

export PATH="/opt/venv/bin:${PATH}"

BASE="${COMFY_HOME}"
LOGS="${COMFY_LOGS}"
START_TIMEOUT="${START_TIMEOUT:-60}"
GPU_PORT_BASE="${GPU_PORT_BASE:-8288}"
MAX_GPU_SESSIONS="${MAX_GPU_SESSIONS:-4}"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 not found in PATH" >&2; exit 1; }; }
need_cmd python
need_cmd tmux
need_cmd curl
need_cmd ps
need_cmd awk

sage_attention=$({ [[ "${ENABLE_SAGE:-true}" == "true" ]] && printf '%s' --use-sage-attention; } || true)

gpus="$(python -c 'import torch; print(torch.cuda.device_count() if torch.cuda.is_available() else 0)')"
printf "INFO: Available GPUs: %s\n" "${gpus}"

# ---- bitmask helpers ----

mask_bit_is_set() {
  local m="$1"
  local b="$2"
  if (( m & 1 << b )); then
    return 0
  else
    return 1
  fi
}

mask_set_bit() {
  local m="$1"
  local b="$2"
  (( m |= 1 << b ))
  printf '%d\n' "$m"
}

mask_to_bits_5() {
  # 5-bit string with bit4..bit0 (human readable)
  local m="$1"
  local b4=$(( (m >> 4) & 1 ))
  local b3=$(( (m >> 3) & 1 ))
  local b2=$(( (m >> 2) & 1 ))
  local b1=$(( (m >> 1) & 1 ))
  local b0=$(( (m >> 0) & 1 ))
  echo "${b4}${b3}${b2}${b1}${b0}"
}

# ---- comfy process discovery ----
find_comfy_pids() {
  # Match python processes running "${COMFY_HOME}/main.py" with listen+port args.
  ps -eo pid=,args= \
    | awk -v base="${BASE}" '
        $0 ~ "python" && $0 ~ (base "/main.py") && $0 ~ "--listen" && $0 ~ "--port" { print $1 }
      ' \
    | tr '\n' ' ' || true
}

# ---- tmux sessions we manage ----
# Fixed list (we only care about 8188 + up to 4 GPU ports for the bitmask)
SESSIONS=(comfy-8188 comfy-8288 comfy-8388 comfy-8488 comfy-8588)
PORTS=(8188 8288 8388 8488 8588)

wait_http() {
  local port="$1"
  local seconds="${2:-45}"
  local i
  for ((i=0; i<seconds; i++)); do
    if curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

health_log() {
  local name="$1" port="$2" gvar="$3" out="$4" cache="$5"
  echo "🚀 ${name} is UP on :${port} (Runtime Options: ${sage_attention} CUDA_VISIBLE_DEVICES=${gvar})"
  echo "       Output: ${out}"
  echo "   Temp/Cache: ${cache}"
  echo "          Log: ${LOGS}/comfyui-${port}.log"
  echo ""
}

kill_tmux_sessions() {
  for s in "${SESSIONS[@]}"; do
    if tmux has-session -t "${s}" >/dev/null 2>&1; then
      tmux kill-session -t "${s}" || true
      echo "INFO: killed tmux session: ${s}"
    fi
  done
}

stop_processes() {
  local hard="${1:-false}"
  local pids
  pids="$(find_comfy_pids)"

  if [[ -n "${pids// /}" ]]; then
    echo "INFO: sending SIGTERM to ComfyUI python PIDs: ${pids}"
    kill ${pids} 2>/dev/null || true
    sleep 2
  fi

  pids="$(find_comfy_pids)"
  if [[ -n "${pids// /}" && "${hard}" == "true" ]]; then
    echo "WARN: still running; sending SIGKILL to: ${pids}"
    kill -9 ${pids} 2>/dev/null || true
    sleep 1
  fi
}

prestart_cleanup() {
  echo "INFO: pre-start cleanup (tmux + stray comfy procs)"
  kill_tmux_sessions
  stop_processes "true"
}

start_one() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"
  mkdir -p "${out}" "${cache}" "${LOGS}"

  if tmux has-session -t "${sess}" >/dev/null 2>&1; then
    tmux kill-session -t "${sess}" || true
  fi

  tmux new-session -d -s "${sess}" \
    "CUDA_VISIBLE_DEVICES=${gvar} PYTHONUNBUFFERED=1 \
     python \"${BASE}/main.py\" --listen --port ${port} \
       ${sage_attention} \
       --output-directory \"${out}\" --temp-directory \"${cache}\" \
       >> \"${LOGS}/comfyui-${port}.log\" 2>&1"
}

start_8188() {
  mkdir -p "${BASE}/output" "${BASE}/cache" "${LOGS}"

  if tmux has-session -t "comfy-8188" >/dev/null 2>&1; then
    tmux kill-session -t "comfy-8188" || true
  fi

  tmux new-session -d -s comfy-8188 \
    "PYTHONUNBUFFERED=1 \
     python \"${BASE}/main.py\" --listen --port 8188 ${sage_attention} \
       --output-directory \"${BASE}/output\" --temp-directory \"${BASE}/cache\" \
       >> \"${LOGS}/comfyui-8188.log\" 2>&1"
}

emit_start_mask_line() {
  local mask="$1"
  local bits
  bits="$(mask_to_bits_5 "${mask}")"
  printf "COMFY_START_MASK=0x%02X COMFY_START_BITS=%s\n" "${mask}" "${bits}"
}

do_start() {
  prestart_cleanup

  local start_mask=0

  echo "INFO: starting comfy-8188..."
  start_8188

  # Required: 8188
  if wait_http 8188 "${START_TIMEOUT}"; then
    start_mask="$(mask_set_bit "${start_mask}" 0)"
    health_log "comfy-8188" 8188 "unset" "${BASE}/output" "${BASE}/cache"
  else
    echo "ERROR: comfy-8188 did not come up on :8188 after ${START_TIMEOUT}s"
    echo "       Check: ${LOGS}/comfyui-8188.log"
  fi

  # GPU sessions: up to MAX_GPU_SESSIONS, best-effort. We only encode up to 4 ports in the mask.
  local gpu_to_spawn="${gpus}"
  [[ "${gpu_to_spawn}" -gt "${MAX_GPU_SESSIONS}" ]] && gpu_to_spawn="${MAX_GPU_SESSIONS}"

  # Ports: 8288 + (gpu_index * 100)
  # gpu0=8288, gpu1=8388, gpu2=8488, gpu3=8588
  if [[ "${gpu_to_spawn}" -ge 1 ]]; then
    echo "INFO: starting comfy-8288 (GPU0)..."
    start_one comfy-8288 8288 0 "${BASE}/output_gpu0" "${BASE}/cache_gpu0"
    if wait_http 8288 25; then
      start_mask="$(mask_set_bit "${start_mask}" 1)"
      health_log "comfy-8288" 8288 0 "${BASE}/output_gpu0" "${BASE}/cache_gpu0"
    else
      echo "WARN: comfy-8288 not reachable yet; check ${LOGS}/comfyui-8288.log"
    fi
  fi

  if [[ "${gpu_to_spawn}" -ge 2 ]]; then
    echo "INFO: starting comfy-8388 (GPU1)..."
    start_one comfy-8388 8388 1 "${BASE}/output_gpu1" "${BASE}/cache_gpu1"
    if wait_http 8388 25; then
      start_mask="$(mask_set_bit "${start_mask}" 2)"
      health_log "comfy-8388" 8388 1 "${BASE}/output_gpu1" "${BASE}/cache_gpu1"
    else
      echo "WARN: comfy-8388 not reachable yet; check ${LOGS}/comfyui-8388.log"
    fi
  fi

  if [[ "${gpu_to_spawn}" -ge 3 ]]; then
    echo "INFO: starting comfy-8488 (GPU2)..."
    start_one comfy-8488 8488 2 "${BASE}/output_gpu2" "${BASE}/cache_gpu2"
    if wait_http 8488 25; then
      start_mask="$(mask_set_bit "${start_mask}" 3)"
      health_log "comfy-8488" 8488 2 "${BASE}/output_gpu2" "${BASE}/cache_gpu2"
    else
      echo "WARN: comfy-8488 not reachable yet; check ${LOGS}/comfyui-8488.log"
    fi
  fi

  if [[ "${gpu_to_spawn}" -ge 4 ]]; then
    echo "INFO: starting comfy-8588 (GPU3)..."
    start_one comfy-8588 8588 3 "${BASE}/output_gpu3" "${BASE}/cache_gpu3"
    if wait_http 8588 25; then
      start_mask="$(mask_set_bit "${start_mask}" 4)"
      health_log "comfy-8588" 8588 3 "${BASE}/output_gpu3" "${BASE}/cache_gpu3"
    else
      echo "WARN: comfy-8588 not reachable yet; check ${LOGS}/comfyui-8588.log"
    fi
  fi

  echo "INFO: tmux sessions:"
  tmux ls 2>/dev/null || echo "(no tmux server / no sessions)"

  # Emit bitmask line for wrapper parsing
  emit_start_mask_line "${start_mask}"

  # Exit status: success if 8188 is up (bit0 set). GPU ports are optional.
  if mask_bit_is_set "${start_mask}" 0; then
    return 0
  else
    return 1
  fi
}

do_stop() {
  local hard="false"
  [[ "${2:-}" == "--hard" ]] && hard="true"

  echo "INFO: stopping comfy (tmux sessions + python procs)..."
  kill_tmux_sessions
  stop_processes "${hard}"

  local pids
  pids="$(find_comfy_pids)"
  if [[ -n "${pids// /}" ]]; then
    echo "WARN: ComfyUI python still running: ${pids}"
    return 1
  fi

  echo "INFO: stop complete."
  return 0
}

do_status() {
  echo "=== tmux sessions ==="
  tmux ls 2>/dev/null || echo "(no tmux server / no sessions)"

  echo ""
  echo "=== comfy python procs ==="
  local pids
  pids="$(find_comfy_pids)"
  if [[ -z "${pids// /}" ]]; then
    echo "(none)"
  else
    ps -fp ${pids} || true
  fi

  echo ""
  echo "=== ports (best-effort) ==="
  for p in "${PORTS[@]}"; do
    if curl -fsS "http://127.0.0.1:${p}" >/dev/null 2>&1; then
      echo "  :${p} UP"
    else
      echo "  :${p} down"
    fi
  done
}

case "${ACTION}" in
  start)
    do_start
    ;;
  stop)
    do_stop "$@"
    ;;
  restart)
    do_stop stop --hard || true
    do_start
    ;;
  hard-restart)
    do_stop stop --hard || true
    do_start
    ;;
  status)
    do_status
    ;;
  *)
    echo "Usage: $0 {start|stop [--hard]|restart|hard-restart|status}" >&2
    exit 2
    ;;
esac
