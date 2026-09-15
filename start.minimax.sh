#!/usr/bin/env bash
set -euo pipefail

umask 0022
mkdir -p /workspace /workspace/logs
PROFILE_DIR=/opt/comfyui-minimax
source "${PROFILE_DIR}/src/.env.minimax"
source "${POD_RUNTIME_DIR}/helpers.sh"

# MiniMax uses its pod-runtime model catalog. The profile intentionally contains
# no model-size, task, or quantization knowledge; HF_BASE_DOWNLOADS and
# HF_LORA_DOWNLOADS select ordinary manifest families from that catalog.
export MODEL_MANIFEST_URL="${MINIMAX_MODEL_MANIFEST_URL:-${POD_RUNTIME_DIR}/model_manifest.minimax.json}"

STARTUP_LOG="${COMFY_LOGS}/startup-minimax.log"
exec > >(tee -a "${STARTUP_LOG}") 2>&1

echo "=== MiniMax bootstrap: $(date -Is) ==="
echo "Application: ${COMFY_APP}"
echo "State: ${COMFY_STATE}"

# SSH is the recovery path. It must be available before any diagnostic or bulk
# network activity so a broken probe/download cannot make the pod inaccessible.
echo "[bootstrap] Bringing up SSH recovery access before network qualification..."
setup_ssh || true

# Qualify network performance before hf-tools, custom nodes, Sage, or models.
# The guarded helper has a hard outer wall-clock ceiling and never aborts startup.
network_probe_startup_guarded || true

gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true)"
compute_cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 || true)"
echo "GPU: ${gpu_name:-unknown}; compute capability: ${compute_cap:-unknown}"
echo "HF base families  : ${HF_BASE_DOWNLOADS:-<none>}"
echo "HF LoRA families  : ${HF_LORA_DOWNLOADS:-<none>}"
echo "Model manifest    : ${MODEL_MANIFEST_URL}"
echo "Sage available    : ${ENABLE_SAGE:-false}"
echo "Global Sage launch: ${COMFY_USE_SAGE_ATTENTION:-false}"

mkdir -p /root/.secrets
chmod 700 /root/.secrets
{
  printf 'export POD_RUNTIME_DIR=%q\n' "${POD_RUNTIME_DIR}"
  printf 'export COMFY_APP=%q\n' "${COMFY_APP}"
  printf 'export COMFY_STATE=%q\n' "${COMFY_STATE}"
  printf 'export COMFY_HOME=%q\n' "${COMFY_HOME}"
  printf 'export HF_BASE_DOWNLOADS=%q\n' "${HF_BASE_DOWNLOADS:-}"
  printf 'export HF_LORA_DOWNLOADS=%q\n' "${HF_LORA_DOWNLOADS:-}"
  printf 'export ENABLE_SAGE=%q\n' "${ENABLE_SAGE:-false}"
  printf 'export COMFY_USE_SAGE_ATTENTION=%q\n' "${COMFY_USE_SAGE_ATTENTION:-false}"
  env | awk -F= '/^(HF_TOKEN|HUGGINGFACE_HUB_TOKEN|GIT_DEPLOY_KEY_|SSH_|TELEGRAM_)/ {print}' \
    | while IFS='=' read -r key value; do printf 'export %s=%q\n' "${key}" "${value}"; done
} > /root/.secrets/env.current
chmod 600 /root/.secrets/env.current

# Optional recovery hold for inspecting first-boot state before HFF modifies it.
# Normal startup is unchanged unless MINIMAX_DEBUG_HOLD=1 is explicitly set.
if [[ "${MINIMAX_DEBUG_HOLD:-0}" == "1" ]]; then
  echo "[debug] MINIMAX_DEBUG_HOLD=1 — holding before HFF bootstrap"
  echo "[debug] SSH is available; create /tmp/minimax-continue to resume"
  while [[ ! -e /tmp/minimax-continue ]]; do
    sleep 2
  done
  echo "[debug] Continuing startup..."
fi

install_system_hff
install_root_shell_dotfiles || true
ensure_comfy_dirs
link_comfy_state_into_app
git_auth_bootstrap || true
hf_transfer_tune
hf_transfer_install
hf_transfer_verify

# Install custom nodes before bulk model transfers. The generic resolver always
# includes the shared default set and then adds CUSTOM_NODE_SETS=minimax.
if [[ "${INSTALL_CUSTOM_NODES}" == true ]]; then
  node_manifest="${CUSTOM_NODES_MANIFEST_URL_OVERRIDE:-${CUSTOM_NODES_MANIFEST_URL}}"
  echo "[nodes] Installing set '${CUSTOM_NODE_SETS}' from ${node_manifest}"
  install_custom_nodes "${node_manifest}"
  snapshot_custom_nodes_state "after-minimax-install" || true

  # A custom-node requirement can install CPU onnxruntime after the image's GPU
  # package. Reassert the GPU package only when provider enumeration proves it
  # was displaced.
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

# SageAttention is an optional runtime capability, not an image dependency.
# Reuse the normal pod-runtime architecture/Torch keyed bundle cache; build and
# optionally publish a bundle only when no compatible artifact already exists.
sage_ready=false
if [[ "${ENABLE_SAGE:-true}" == "true" ]]; then
  echo "[sage] Ensuring SageAttention bundle or source build..."
  if ensure_sage_from_bundle_or_build; then
    sage_ready=true
    push_sage_bundle_if_requested || true
  else
    echo "WARNING: SageAttention setup failed; continuing with Comfy Kitchen/default attention." >&2
  fi
else
  echo "[sage] ENABLE_SAGE=false — SageAttention availability setup skipped."
fi

# Never request the global ComfyUI Sage backend if availability setup failed.
# KJ's Patch Sage Attention node remains usable whenever sage_ready=true while
# COMFY_USE_SAGE_ATTENTION=false.
if [[ "${COMFY_USE_SAGE_ATTENTION:-false}" == "true" && "${sage_ready}" != "true" ]]; then
  echo "WARNING: COMFY_USE_SAGE_ATTENTION=true but SageAttention is unavailable; disabling global Sage for this launch." >&2
  export COMFY_USE_SAGE_ATTENTION=false
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
import os
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
try:
    import sageattention
    print("sageattention:", getattr(sageattention, "__version__", "installed"))
except Exception as exc:
    print("sageattention: unavailable", repr(exc))
print("COMFY_USE_SAGE_ATTENTION:", os.environ.get("COMFY_USE_SAGE_ATTENTION", "false"))
PY

snapshot_custom_nodes_state --summary "before-minimax-launch" || true
confirm_stack_health_or_stop || true
if [[ -f "${COMFY_LOGS}/stack_broken" ]]; then
  echo "ERROR: stack health check failed; see ${COMFY_LOGS}/stack_health_report.txt" >&2
  tail -f /dev/null
fi

cd "${COMFY_APP}"
if "${POD_RUNTIME_DIR}/run_comfy_mux.sh" start; then
  echo "MiniMax ComfyUI is available on port 8188."
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

echo "=== MiniMax bootstrap complete: $(date -Is) ==="
sleep infinity
