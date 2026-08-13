#!/usr/bin/env bash
set -euo pipefail

umask 0022
mkdir -p /workspace /workspace/logs
PROFILE_DIR=/opt/comfyui-minimax
source "${PROFILE_DIR}/src/.env.minimax"
source "${POD_RUNTIME_DIR}/helpers.sh"

STARTUP_LOG="${COMFY_LOGS}/startup-minimax.log"
exec > >(tee -a "${STARTUP_LOG}") 2>&1

echo "=== MiniMax-H3 bootstrap: $(date -Is) ==="
echo "Application: ${COMFY_APP}"
echo "State: ${COMFY_STATE}"

case "${MINIMAX_QUANT}" in
  fp8|int8|nvfp4) ;;
  *) echo "ERROR: MINIMAX_QUANT must be fp8, int8, or nvfp4; got '${MINIMAX_QUANT}'." >&2; exit 2 ;;
esac

minimax_tasks_normalized=""
IFS=',' read -r -a minimax_task_items <<<"${MINIMAX_TASKS}"
for minimax_task_item in "${minimax_task_items[@]}"; do
  minimax_task="${minimax_task_item,,}"
  minimax_task="${minimax_task//[[:space:]]/}"
  if [[ -z "${minimax_task}" ]]; then
    echo "ERROR: MINIMAX_TASKS contains an empty task entry: '${MINIMAX_TASKS}'." >&2
    exit 2
  fi
  case "${minimax_task}" in
    fl2va|ref2va) ;;
    *) echo "ERROR: MINIMAX_TASKS accepts fl2va and ref2va; got '${minimax_task_item}'." >&2; exit 2 ;;
  esac
  case ",${minimax_tasks_normalized}," in
    *",${minimax_task},"*) ;;
    *)
      if [[ -n "${minimax_tasks_normalized}" ]]; then
        minimax_tasks_normalized+=","
      fi
      minimax_tasks_normalized+="${minimax_task}"
      ;;
  esac
done
if [[ -z "${minimax_tasks_normalized}" ]]; then
  echo "ERROR: MINIMAX_TASKS must select fl2va, ref2va, or both." >&2
  exit 2
fi
export MINIMAX_TASKS="${minimax_tasks_normalized}"

gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true)"
compute_cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 || true)"
echo "GPU: ${gpu_name:-unknown}; compute capability: ${compute_cap:-unknown}"
echo "MiniMax quant: ${MINIMAX_QUANT}"
echo "MiniMax tasks: ${MINIMAX_TASKS}"
if [[ "${MINIMAX_QUANT}" == nvfp4 && ! "${compute_cap}" =~ ^12\. ]]; then
  echo "WARNING: nvfp4 is intended for Blackwell; FP8 is safer on compute capability '${compute_cap:-unknown}'."
fi

minimax_sections=""
append_minimax_section() {
  local section="${1:?section}"
  if [[ -n "$minimax_sections" ]]; then
    minimax_sections+=","
  fi
  minimax_sections+="$section"
}

if [[ "${DOWNLOAD_MINIMAX_MODELS}" == true ]]; then
  append_minimax_section download_minimax_h3_common

  minimax_transformer_quant="${MINIMAX_QUANT}"
  case "${MINIMAX_QUANT}" in
    fp8|int8)
      append_minimax_section download_minimax_h3_text_encoder_int8
      ;;
    nvfp4)
      minimax_transformer_quant=fp8
      append_minimax_section download_minimax_h3_text_encoder_nvfp4
      ;;
  esac

  IFS=',' read -r -a minimax_task_items <<<"${MINIMAX_TASKS}"
  for minimax_task in "${minimax_task_items[@]}"; do
    append_minimax_section "download_minimax_h3_${minimax_task}_${minimax_transformer_quant}"
  done
fi

mkdir -p /root/.secrets
chmod 700 /root/.secrets
{
  printf 'export POD_RUNTIME_DIR=%q\n' "${POD_RUNTIME_DIR}"
  printf 'export COMFY_APP=%q\n' "${COMFY_APP}"
  printf 'export COMFY_STATE=%q\n' "${COMFY_STATE}"
  printf 'export COMFY_HOME=%q\n' "${COMFY_HOME}"
  printf 'export MINIMAX_QUANT=%q\n' "${MINIMAX_QUANT}"
  printf 'export MINIMAX_TASKS=%q\n' "${MINIMAX_TASKS}"
  env | awk -F= '/^(HF_TOKEN|HUGGINGFACE_HUB_TOKEN|GIT_DEPLOY_KEY_|SSH_|TELEGRAM_)/ {print}' \
    | while IFS='=' read -r key value; do printf 'export %s=%q\n' "${key}" "${value}"; done
} > /root/.secrets/env.current
chmod 600 /root/.secrets/env.current

install_system_hff
install_root_shell_dotfiles || true
ensure_comfy_dirs
link_comfy_state_into_app
setup_ssh || true
git_auth_bootstrap || true
hf_transfer_tune
hf_transfer_install
hf_transfer_verify

# Install custom nodes before starting the bulk HF model downloader. With shallow
# clones and hardened installs this phase is now short enough that allowing Xet
# to saturate storage concurrently is more likely to hurt than help.
if [[ "${INSTALL_CUSTOM_NODES}" == true ]]; then
  node_manifest="${CUSTOM_NODES_MANIFEST_URL_OVERRIDE:-${CUSTOM_NODES_MANIFEST_URL}}"
  echo "[nodes] Installing set '${CUSTOM_NODE_SETS}' from ${node_manifest}"
  install_custom_nodes "${node_manifest}"
  snapshot_custom_nodes_state "after-minimax-install" || true

  if python - <<'PY'
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
    echo "[onnxruntime] CUDA provider intact; keeping baked onnxruntime-gpu installation."
  else
    echo "[onnxruntime] CUDA provider missing after custom-node install; repairing GPU runtime."
    pip uninstall -y onnxruntime onnxruntime-gpu >/dev/null 2>&1 || true
    pip install --constraint /opt/constraints.txt --force-reinstall onnxruntime-gpu
  fi
fi

model_download_started=false
MINIMAX_HF_STATE="${HF_MANIFEST_STATE_DIR}/base"
if [[ "${ENABLE_MODEL_MANIFEST_DOWNLOAD}" == true && "${DOWNLOAD_MINIMAX_MODELS}" == true ]]; then
  echo "[models] Starting manifest download: ${MODEL_MANIFEST_URL}"
  echo "[models] Sections: ${minimax_sections}"
  hf_download_from_manifest "${MODEL_MANIFEST_URL}" "$MINIMAX_HF_STATE" "$minimax_sections"
  model_download_started=true
else
  echo "[models] Model provisioning disabled."
fi

# Light setup can overlap the base model transfer now that pip/custom-node work
# is finished.
if [[ "${ENABLE_MY_WORKFLOWS_DOWNLOAD}" == true ]]; then
  echo "[workflows] Syncing ${GIT_MYWORKFLOWS_REPO_ID}"
  init_repo --git "${GIT_MYWORKFLOWS_REPO_ID}" "${GIT_MYWORKFLOWS_REPO_LOCAL}"
  mkdir -p "${WORKFLOW_DIR}/MyWorkflows"
  find "${WORKFLOW_DIR}/MyWorkflows" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  find "${GIT_MYWORKFLOWS_REPO_LOCAL}" -mindepth 1 -maxdepth 1 ! -name .git \
    -exec ln -sfn {} "${WORKFLOW_DIR}/MyWorkflows/" \;
fi

source "${PROFILE_DIR}/src/prepare_sage.sh"

if [[ "${model_download_started}" == true ]]; then
  echo "[models] Waiting for selected MiniMax-H3 weights..."
  hf_download_wait "$MINIMAX_HF_STATE"
  echo "[models] Selected weights are ready."
fi

python - <<'PY'
import onnxruntime as ort
import torch
import comfy_aimdo
import comfy_kitchen
assert torch.version.cuda and torch.version.cuda.startswith("13"), torch.version.cuda
assert torch.cuda.is_available(), "CUDA unavailable"
print("torch:", torch.__version__, "CUDA:", torch.version.cuda)
print("GPU:", torch.cuda.get_device_name(0))
print("onnxruntime providers:", ort.get_available_providers())
assert "CUDAExecutionProvider" in ort.get_available_providers()
print("comfy_aimdo:", getattr(comfy_aimdo, "__version__", "installed"))
print("comfy_kitchen:", getattr(comfy_kitchen, "__version__", "installed"))
PY

snapshot_custom_nodes_state --summary "before-minimax-launch" || true
confirm_stack_health_or_stop || true
if [[ -f "${COMFY_LOGS}/stack_broken" ]]; then
  echo "ERROR: stack health check failed; see ${COMFY_LOGS}/stack_health_report.txt" >&2
  tail -f /dev/null
fi

cd "${COMFY_APP}"
if "${POD_RUNTIME_DIR}/run_comfy_mux.sh" start; then
  echo "MiniMax-H3 ComfyUI is available on port 8188."
else
  echo "ERROR: ComfyUI failed to become healthy; see ${COMFY_LOGS}/comfyui-8188.log" >&2
  exit 1
fi

disk_watch_start --path / --log "${COMFY_LOGS}/disk_watch.log" || true
pod_nag --interval 3600 || true

echo "=== MiniMax-H3 bootstrap complete: $(date -Is) ==="
sleep infinity
