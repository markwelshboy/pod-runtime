#!/usr/bin/env bash
# Thin helper overlay for the converged inference image. Keep the normal helper
# library authoritative and add only compatibility repairs that are useful to
# more than one workload.

: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"
source "${POD_RUNTIME_DIR}/helpers.sh"

inference_repair_onnxruntime_gpu() {
  local pip_bin="${PIP:-/opt/venv/bin/pip}"
  local python_bin="${PY:-/opt/venv/bin/python}"

  if "${python_bin}" - <<'PY'
try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
except Exception as exc:
    print(f"[onnxruntime] provider probe failed: {exc}")
    raise SystemExit(1)
print("[onnxruntime] providers after custom-node install:", providers)
raise SystemExit(0 if "CUDAExecutionProvider" in providers else 1)
PY
  then
    echo "[onnxruntime] CUDA provider intact; no repair required."
    return 0
  fi

  echo "[onnxruntime] CUDA provider missing; reasserting baked GPU runtime without dependency churn."
  "${pip_bin}" uninstall -y onnxruntime onnxruntime-gpu >/dev/null 2>&1 || true
  "${pip_bin}" install --constraint /opt/constraints.txt --no-deps --force-reinstall onnxruntime-gpu

  "${python_bin}" - <<'PY'
import onnxruntime as ort
providers = ort.get_available_providers()
print("[onnxruntime] providers after repair:", providers)
assert "CUDAExecutionProvider" in providers, providers
PY
}

# Generic start.sh already calls confirm_stack_health_or_stop after custom-node
# installation and before ComfyUI launch. Wrap that existing hook rather than
# copying the whole bootstrap just to add the ONNX GPU repair.
if declare -F confirm_stack_health_or_stop >/dev/null 2>&1; then
  eval "$(declare -f confirm_stack_health_or_stop | sed '1s/confirm_stack_health_or_stop/confirm_stack_health_or_stop_inference_base/')"

  confirm_stack_health_or_stop() {
    inference_repair_onnxruntime_gpu || {
      echo "WARNING: ONNX Runtime GPU repair failed; continuing into the normal stack health check." >&2
    }
    confirm_stack_health_or_stop_inference_base "$@"
  }
fi
