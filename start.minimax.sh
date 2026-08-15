#!/usr/bin/env bash
set -euo pipefail

umask 0022
mkdir -p /workspace /workspace/logs
PROFILE_DIR=/opt/comfyui-minimax
source "${PROFILE_DIR}/src/.env.minimax"
source "${POD_RUNTIME_DIR}/helpers.sh"

# MiniMax uses the model catalog from the checked-out pod-runtime revision.
# The image-local manifest is retained only for older images and is not used by
# this launcher. MINIMAX_MODEL_MANIFEST_URL remains an escape hatch for testing.
export MODEL_MANIFEST_URL="${MINIMAX_MODEL_MANIFEST_URL:-${POD_RUNTIME_DIR}/model_manifest.json}"

STARTUP_LOG="${COMFY_LOGS}/startup-minimax.log"
exec > >(tee -a "${STARTUP_LOG}") 2>&1

echo "=== MiniMax-H3 bootstrap: $(date -Is) ==="
echo "Application: ${COMFY_APP}"
echo "State: ${COMFY_STATE}"

# Qualify network performance before hf-tools, custom nodes, or model weights.
# This is advisory only; the helper sends warnings and never aborts startup.
network_probe_startup || true

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

# HF_BASE_DOWNLOADS normally contains concrete model families whose manifest
# sections are <family>_base. MiniMax additionally accepts the deliberately
# non-manifest meta-family "minimax_h3_meta" and expands it here according to
# MINIMAX_QUANT and MINIMAX_TASKS before handing the result to the generic
# family resolver.
minimax_requested_base_families="${HF_BASE_DOWNLOADS:-minimax_h3_meta}"
minimax_expanded_base_families=""

append_minimax_base_family() {
  local family="${1:?family}"
  case ",${minimax_expanded_base_families}," in
    *",${family},"*) return 0 ;;
  esac
  if [[ -n "${minimax_expanded_base_families}" ]]; then
    minimax_expanded_base_families+=","
  fi
  minimax_expanded_base_families+="${family}"
}

minimax_transformer_quant="${MINIMAX_QUANT}"
case "${MINIMAX_QUANT}" in
  fp8|int8)
    minimax_text_encoder_family="minimax_h3_text_encoder_int8"
    ;;
  nvfp4)
    # Current NVFP4 profile uses the NVFP4 text encoder with FP8 transformers.
    minimax_text_encoder_family="minimax_h3_text_encoder_nvfp4"
    minimax_transformer_quant=fp8
    ;;
esac

for minimax_family in ${minimax_requested_base_families//,/ }; do
  minimax_family="${minimax_family,,}"
  minimax_family="${minimax_family//[[:space:]]/}"
  [[ -n "${minimax_family}" ]] || continue

  if [[ "${minimax_family}" != "minimax_h3_meta" ]]; then
    append_minimax_base_family "${minimax_family}"
    continue
  fi

  append_minimax_base_family minimax_h3_common
  append_minimax_base_family "${minimax_text_encoder_family}"

  IFS=',' read -r -a minimax_task_items <<<"${MINIMAX_TASKS}"
  for minimax_task in "${minimax_task_items[@]}"; do
    append_minimax_base_family "minimax_h3_${minimax_task}_${minimax_transformer_quant}"
  done
done

export HF_BASE_DOWNLOADS="${minimax_expanded_base_families}"
echo "HF base request   : ${minimax_requested_base_families:-<none>}"
echo "HF base expanded  : ${HF_BASE_DOWNLOADS:-<none>}"
echo "HF LoRA families  : ${HF_LORA_DOWNLOADS:-<none>}"
echo "Model manifest    : ${MODEL_MANIFEST_URL}"

mkdir -p /root/.secrets
chmod 700 /root/.secrets
{
  printf 'export POD_RUNTIME_DIR=%q\n' "${POD_RUNTIME_DIR}"
  printf 'export COMFY_APP=%q\n' "${COMFY_APP}"
  printf 'export COMFY_STATE=%q\n' "${COMFY_STATE}"
  printf 'export COMFY_HOME=%q\n' "${COMFY_HOME}"
  printf 'export MINIMAX_QUANT=%q\n' "${MINIMAX_QUANT}"
  printf 'export MINIMAX_TASKS=%q\n' "${MINIMAX_TASKS}"
  printf 'export HF_BASE_DOWNLOADS=%q\n' "${HF_BASE_DOWNLOADS}"
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

base_download_started=false
MINIMAX_HF_STATE="${HF_MANIFEST_STATE_DIR}/base"
if [[ "${ENABLE_MODEL_MANIFEST_DOWNLOAD}" == true ]]; then
  if [[ -n "${HF_BASE_DOWNLOADS:-}" ]]; then
    base_sections="$(hf_manifest_sections_for_families "${MODEL_MANIFEST_URL}" "${HF_BASE_DOWNLOADS}" base)" || {
      echo "ERROR: Could not resolve HF_BASE_DOWNLOADS='${HF_BASE_DOWNLOADS}'." >&2
      exit 2
    }
    echo "[models] Starting manifest download: ${MODEL_MANIFEST_URL}"
    echo "[models] Base families: ${HF_BASE_DOWNLOADS}"
    echo "[models] Base sections: ${base_sections}"
    if hf_download_from_manifest "${MODEL_MANIFEST_URL}" "$MINIMAX_HF_STATE" "$base_sections"; then
      base_download_started=true
    else
      echo "WARNING: Base manifest download failed to start; see logs." >&2
    fi
  else
    echo "[models] HF_BASE_DOWNLOADS is empty; no base models requested."
  fi
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

if [[ "${base_download_started}" == true ]]; then
  echo "[models] Waiting for selected base weights..."
  if hf_download_wait "$MINIMAX_HF_STATE"; then
    echo "[models] Selected base weights are ready."
  else
    echo "WARNING: One or more base model downloads failed; continuing for diagnosis." >&2
    hf_download_show_snapshot "$MINIMAX_HF_STATE" || true
  fi
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

# Optional LoRA families use the same generic family resolver and start only
# after ComfyUI is healthy, so they never delay time-to-ready.
MINIMAX_LORA_HF_STATE="${HF_MANIFEST_STATE_DIR}/loras"
if [[ "${ENABLE_MODEL_MANIFEST_DOWNLOAD}" == true && -n "${HF_LORA_DOWNLOADS:-}" ]]; then
  lora_sections="$(hf_manifest_sections_for_families "${MODEL_MANIFEST_URL}" "${HF_LORA_DOWNLOADS}" loras)" || {
    echo "WARNING: Could not resolve HF_LORA_DOWNLOADS='${HF_LORA_DOWNLOADS}'; optional LoRAs will not be downloaded." >&2
    lora_sections=""
  }
  if [[ -n "$lora_sections" ]]; then
    echo "[loras] Families: ${HF_LORA_DOWNLOADS}"
    echo "[loras] Sections: ${lora_sections}"
    if hf_download_from_manifest "$MODEL_MANIFEST_URL" "$MINIMAX_LORA_HF_STATE" "$lora_sections"; then
      echo "[loras] Optional LoRA provisioning is running in the background."
      hf_download_show_snapshot "$MINIMAX_LORA_HF_STATE" || true
    else
      echo "WARNING: Optional LoRA downloader failed to start." >&2
    fi
  fi
else
  echo "[loras] No optional LoRA families requested."
fi

disk_watch_start --path / --log "${COMFY_LOGS}/disk_watch.log" || true
pod_nag --interval 3600 || true

echo "=== MiniMax-H3 bootstrap complete: $(date -Is) ==="
sleep infinity
