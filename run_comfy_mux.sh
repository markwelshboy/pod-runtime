#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/venv/bin:$PATH"
BASE=${COMFY_HOME}
LOGS=${COMFY_LOGS}

/usr/bin/printf "INFO: Available GPUs: "
python - <<'PY'
import torch; print(torch.cuda.device_count() if torch.cuda.is_available() else 0)
PY

health() {
  local name=$1 port=$2 $gvar=$3 out=$4 cache=$5
  local t=0
  until curl -fsS "http://127.0.0.1:${port}" >/dev/null 2>&1; do
    sleep 2; t=$((t+2))
    [ $t -ge 60 ] && echo "WARN: ${name} on ${port} not HTTP 200 after 60s. Check logs: ${LOGS}/comfyui-${port}.log" && exit 1
  done
  echo "🚀: ${name} is UP on :${port} (CUDA_VISIBLE_DEVICES=${gvar}, --use-sage-attention)"
  echo "       Output: $out"
  echo "   Temp/Cache: $cache"
  echo "          Log: ${LOGS}/comfyui-${port}.log"
  echo ""
}

start_one() {
  local sess=$1 port=$2 gvar=$3 out=$4 cache=$5
  tmux new-session -d -s "$sess" \
    "CUDA_VISIBLE_DEVICES=${gvar} PYTHONUNBUFFERED=1 \
     python ${BASE}/main.py --listen --port ${port} --use-sage-attention \
       --output-directory ${out} --temp-directory ${cache} \
       >> ${LOGS}/comfyui-${port}.log 2>&1"
  ( health "$sess" "$port" "$gvar" "$out" "$cache" ) || true
}

tmux new-session -d -s comfy-8188 \
  "PYTHONUNBUFFERED=1 python ${BASE}/main.py --listen --port 8188 --use-sage-attention \
   --output-directory ${BASE}/output --temp-directory ${BASE}/cache \
   >> ${LOGS}/comfyui-8188.log 2>&1"
( health "comfy-8188" 8188 "unset" "${BASE}/output" "${BASE}/cache") || true

gpus=$(python - <<'PY'
import torch
print(torch.cuda.device_count() if torch.cuda.is_available() else 0)
PY
)
if [ "$gpus" -ge 1 ]; then
  mkdir -p ${BASE}/output_gpu0 ${BASE}/cache_gpu0
  start_one comfy-8288 8288 0 ${BASE}/output_gpu0 ${BASE}/cache_gpu0
fi
if [ "$gpus" -ge 2 ]; then
  mkdir -p ${BASE}/output_gpu1 ${BASE}/cache_gpu1
  start_one comfy-8388 8388 1 ${BASE}/output_gpu1 ${BASE}/cache_gpu1
fi
if [ "$gpus" -ge 3 ]; then
  mkdir -p ${BASE}/output_gpu2 ${BASE}/cache_gpu2
  start_one comfy-8488 8488 2 ${BASE}/output_gpu2 ${BASE}/cache_gpu2
fi
if [ "$gpus" -ge 4 ]; then
  mkdir -p ${BASE}/output_gpu3 ${BASE}/cache_gpu3
  start_one comfy-8588 8588 3 ${BASE}/output_gpu3 ${BASE}/cache_gpu3
fi

sleep 5
tmux ls
