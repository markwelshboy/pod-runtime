#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export POD_RUNTIME_DIR="${POD_RUNTIME_DIR:-${SCRIPT_DIR}}"
export COMFY_WORKLOAD="${COMFY_WORKLOAD:-generic}"
export ENVIRONMENT="${ENVIRONMENT:-${POD_RUNTIME_DIR}/profiles/inference.env}"
export HELPERS="${HELPERS:-${POD_RUNTIME_DIR}/profiles/helpers.inference.sh}"

case "${COMFY_WORKLOAD}" in
  generic|krea2|minimax|imagedit) ;;
  *)
    echo "[fatal] Unsupported COMFY_WORKLOAD='${COMFY_WORKLOAD}'. Use generic, krea2, minimax, or imagedit." >&2
    exit 2
    ;;
esac

echo "[inference] workload=${COMFY_WORKLOAD} cuda=${CUDA_VARIANT:-unknown}"
exec "${POD_RUNTIME_DIR}/start.sh"
