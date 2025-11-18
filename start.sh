#!/usr/bin/env bash
set -euo pipefail

echo "=== ComfyUI bootstrap: $(date) ==="

# --------------------------------------------------
# 0) Wire up .env and helpers
# --------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT="${ENVIRONMENT:-$SCRIPT_DIR/.env}"
HELPERS="${HELPERS:-$SCRIPT_DIR/helpers.sh}"

if [[ ! -f "$ENVIRONMENT" ]]; then
  echo "[fatal] .env not found at: $ENVIRONMENT" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ENVIRONMENT"

if [[ ! -f "$HELPERS" ]]; then
  echo "[fatal] helpers.sh not found at: $HELPERS" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$HELPERS"

# --------------------------------------------------
# 0) Sanity: make sure dirs exist (Comfy home, models, logs, etc.)
# --------------------------------------------------

ensure_dirs

# --------------------------------------------------
# 1) Move 4xLSDIR.pth into upscale_models if present
# --------------------------------------------------

if [[ -f "/4xLSDIR.pth" && ! -f "$UPSCALE_DIR/4xLSDIR.pth" ]]; then
  echo "Moving 4xLSDIR.pth into $UPSCALE_DIR..."
  mv /4xLSDIR.pth "$UPSCALE_DIR/4xLSDIR.pth"
elif [[ -f "$UPSCALE_DIR/4xLSDIR.pth" ]]; then
  echo "4xLSDIR.pth already in place, skipping move."
else
  echo "4xLSDIR.pth not found; skipping."
fi

# --------------------------------------------------
# 2) Models via model_manifest.json + aria2
# --------------------------------------------------

helpers_have_aria2_rpc || aria2_start_daemon
aria2_clear_results >/dev/null 2>&1 || true

if [[ "${ENABLE_MODEL_MANIFEST_DOWNLOAD:-1}" == "1" ]]; then
  echo "Using model manifest: $MODEL_MANIFEST_URL"
  if ! aria2_download_from_manifest; then
    echo "⚠️ aria2_download_from_manifest failed; see logs."
  fi
else
  echo "ENABLE_MODEL_MANIFEST_DOWNLOAD=0 → skipping model downloader."
fi

if [[ "${ENABLE_CIVITAI_DOWNLOAD:-1}" == "1" ]]; then
  echo "Attempting to download CivitAI assets from env IDs... "
  echo "LORAS:${LORAS_IDS_TO_DOWNLOAD}, CHECKPOINTS:${CHECKPOINT_IDS_TO_DOWNLOAD}"
  if ! aria2_download_civitai_from_environment_vars; then
    echo "⚠️ aria2_download_civitai_from_environment_vars reported issues; see CivitAI log."
  fi
else
  echo "ENABLE_CIVITAI_DOWNLOAD=0 → skipping CivitAI downloader."
fi

aria2_show_download_snapshot || true

# --------------------------------------------------
# 3) SageAttention (bundle or build)
# --------------------------------------------------

if [[ "${ENABLE_SAGE:-1}" == "1" ]]; then
  echo "Ensuring SageAttention (bundle or build)..."
  if ! ensure_sage_from_bundle_or_build; then
    echo "⚠️ SageAttention failed; check logs. Continuing without aborting."
  fi
else
  echo "ENABLE_SAGE=0 → skipping SageAttention setup."
fi

aria2_show_download_snapshot || true

# --------------------------------------------------
# 4) Extra custom nodes on top of baked-in ones
# --------------------------------------------------
if [[ "${INSTALL_EXTRA_CUSTOM_NODES:-1}" == "1" ]]; then
  echo "Installing extra custom nodes. Trying ${CUSTOM_NODES_MANIFEST_URL}..."
  if ! install_custom_nodes; then
    echo "⚠️ install_custom_nodes reported errors; custom-node extras may be incomplete."
  fi
else
  echo "INSTALL_EXTRA_CUSTOM_NODES=0 → skipping extra custom node installation."
fi

aria2_show_download_snapshot || true

# --------------------------------------------------
# 5) Optional Hearmeman workflows/assets sync
# --------------------------------------------------

copy_hearmeman_assets_if_any || true

# --------------------------------------------------
# 6) Wait for all downloads to complete
# --------------------------------------------------

echo "[aria2-downloads-progress] Checking download progress..."

aria2_monitor_progress \
  "${ARIA2_PROGRESS_INTERVAL:-15}" \
  "${ARIA2_PROGRESS_BAR_WIDTH:-40}" \
  "${COMFY_LOGS:-/workspace/logs}/aria2_progress.log"

aria2_clear_results >/dev/null 2>&1 || true

# --------------------------------------------------
# 7) Start Jupyter
# --------------------------------------------------

if [[ "${LAUNCH_JUPYTER:-0}" == "1" ]]; then
  echo "Launching Jupyter. Trying from port 8888"
  jupyter-lab --ip=0.0.0.0 --allow-root --no-browser --NotebookApp.token='' --NotebookApp.password='' --ServerApp.allow_origin='*' --ServerApp.allow_credentials=True --notebook-dir=/workspace &
else
  echo "LAUNCH_JUPYTER=0 → skipping Jupyter launch..."
fi

# --------------------------------------------------
# 8) Start ComfyUI
# --------------------------------------------------

cd "${COMFY_HOME:-/workspace/ComfyUI}"

echo "▶️  Starting ComfyUI"

if ${SCRIPT_DIR}/run_comfy_mux.sh; then
  tg "✅ ComfyUI up on 8188, 8288 (GPU0), 8388 (GPU1 if present)."
else
  tg "⚠️ ComfyUI launch had warnings. Check ${COMFY_LOGS}."
fi

echo "Bootstrap complete. General logs: ${COMFY_LOGS}"
echo "=== Bootstrap done: $(date) ==="

sleep infinity