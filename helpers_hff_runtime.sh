#!/usr/bin/env bash
# HFF bootstrap policy override.
# Loaded after helpers_core.sh so it replaces legacy logging/tooling functions.

_runtime_secret_preview() {
  # Show enough of a secret to identify which credential is loaded without
  # making logs useful for credential theft. Very short values get no preview.
  local value="${1:-}"
  local length=${#value}

  if (( length == 0 )); then
    printf '%s' '<unset>'
  elif (( length <= 12 )); then
    printf '<set:%d chars>' "$length"
  else
    printf '%s…%s' "${value:0:8}" "${value: -4}"
  fi
}

_runtime_env_name_is_sensitive() {
  local name="${1:-}"
  case "$name" in
    *_TOKEN|*_TOKEN_*|TOKEN_*|*_SECRET|*_SECRET_*|SECRET_*|*_PASSWORD|*_PASSWORD_*|PASSWORD_*|\
    *_CREDENTIAL|*_CREDENTIAL_*|CREDENTIAL_*|*_PRIVATE_KEY|*_PRIVATE_KEY_*|PRIVATE_KEY_*|\
    *_CLIENT_KEY|*_CLIENT_KEY_*|*_KEY_B64|*_KEY_B64_*|*_COOKIE|*_COOKIE_*|COOKIE_*|\
    *_BEARER|*_BEARER_*|BEARER_*) return 0 ;;
    *) return 1 ;;
  esac
}

# The legacy report printed HF_TOKEN verbatim. Keep the useful transfer tuning
# diagnostics but only log a non-reversible head/tail fingerprint for secrets.
hf_transfer_options_report() {
  local key value
  echo "=== hf_transfer / hub config ==="
  while IFS='=' read -r key value; do
    if _runtime_env_name_is_sensitive "$key"; then
      printf '%s=%s\n' "$key" "$(_runtime_secret_preview "$value")"
    else
      printf '%s=%s\n' "$key" "$value"
    fi
  done < <(env | grep -E '^HF_(HUB_|TOKEN|HUB_ENABLE|HUB_MAX_|SPLIT=|MCONN=|CHUNK=|AUTH_MODE=)' | sort)
  echo "==============================="
}

# Override the legacy show_env() from helpers_core.sh. Preserve its useful
# layout/status probes, but include only masked credential fingerprints.
show_env() {
  echo "========================================================================"
  echo "🧠 ComfyUI Environment Summary — $(date -Is)"
  echo "========================================================================"
  echo ""
  echo " COMFY_HOME:            ${COMFY_HOME:-<unset>}"
  echo " Comfy version:         $(probe_comfy_version || echo unknown)"
  echo ""
  echo " Custom nodes dir:      ${CUSTOM_DIR:-<unset>}"
  echo " Cache dir:             ${CACHE_DIR:-<unset>}"
  echo " Logs dir:              ${COMFY_LOGS:-<unset>}"
  echo " Output dir:            ${OUTPUT_DIR:-<unset>}"
  echo " Bundles dir:           ${BUNDLES_DIR:-<unset>}"
  echo " Bundle tag:            ${CUSTOM_NODES_BUNDLE_TAG:-<unset>}"
  echo " Workflow dir:          ${WORKFLOW_DIR:-<unset>}"
  echo " Model manifest URL:    ${MODEL_MANIFEST_URL:-<unset>}"
  echo ""
  echo " MODELS_DIR:            ${MODELS_DIR:-<unset>}"
  echo " DIFFUSION_MODELS_DIR:  ${DIFFUSION_MODELS_DIR:-<unset>}"
  echo " TEXT_ENCODERS_DIR:     ${TEXT_ENCODERS_DIR:-<unset>}"
  echo " CLIP_VISION_DIR:       ${CLIP_VISION_DIR:-<unset>}"
  echo " VAE_DIR:               ${VAE_DIR:-<unset>}"
  echo " LORAS_DIR:             ${LORAS_DIR:-<unset>}"
  echo " DETECTION_DIR:         ${DETECTION_DIR:-<unset>}"
  echo " CTRLNET_DIR:           ${CTRLNET_DIR:-<unset>}"
  echo " CTRLNET_UNION_DIR:     ${CTRLNET_UNION_DIR:-<unset>}"
  echo " UPSCALE_DIR:           ${UPSCALE_DIR:-<unset>}"
  echo " ULTRALYTICS_DIR:       ${ULTRALYTICS_DIR:-<unset>}"
  echo ""
  echo " HF_TOKEN:              $(hf_token_status) [$(_runtime_secret_preview "${HF_TOKEN:-}")]"
  echo " CIVITAI_TOKEN:         $(civitai_token_status) [$(_runtime_secret_preview "${CIVITAI_TOKEN:-}")]"
  echo " CHECKPOINT_IDS:        ${CHECKPOINT_IDS_TO_DOWNLOAD:-Empty}"
  echo " LORAS_IDS:             ${LORAS_IDS_TO_DOWNLOAD:-Empty}"
  echo ""
  echo "======================================="
  echo ""
  echo ""
}

_hff_pip_raw() {
  # HFF has its own venv and must not inherit ComfyUI's global pip constraints or pip.conf.
  env \
    -u PIP_CONSTRAINT \
    -u PIP_BUILD_CONSTRAINT \
    PIP_CONFIG_FILE=/dev/null \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "${HFF_VENV}/bin/python" -m pip "$@"
}

_hff_pip() {
  # Successful bootstrap installs are intentionally quiet: provision already
  # reports the stage and selected package versions, so pip's resolver/download
  # transcript is mostly noise. Preserve diagnostics by replaying the complete
  # captured pip output automatically if the command fails.
  #
  # Set HFF_PIP_VERBOSE=true to restore live pip output for troubleshooting.
  local log rc
  case "${HFF_PIP_VERBOSE:-false}" in
    1|true|TRUE|yes|YES|on|ON)
      _hff_pip_raw "$@"
      return $?
      ;;
  esac

  log="$(mktemp "${TMPDIR:-/tmp}/hff-pip.XXXXXX")" || {
    _hff_err "could not create temporary pip log; falling back to verbose pip"
    _hff_pip_raw "$@"
    return $?
  }

  if _hff_pip_raw "$@" >"$log" 2>&1; then
    rm -f "$log"
    return 0
  else
    rc=$?
    _hff_err "pip failed; full output follows:"
    cat "$log" >&2
    rm -f "$log"
    return "$rc"
  fi
}

ensure_hf_tools_venv() {
  local venv="${HFF_VENV}"
  local py="${PYTHON:-python3}"
  local hub_spec install_mode installed_version copy_support

  if [[ ! -x "$venv/bin/python" ]]; then
    _hff_info "Creating venv: $venv"
    mkdir -p "$(dirname "$venv")" || true
    "$py" -m venv "$venv" || return 1
  fi

  export HFF_VENV="$venv"
  _hff_info "Upgrading pip in HFF venv..."
  _hff_pip install -U pip || return 1

  if [[ -n "${HFF_HUB_VER:-}" ]]; then
    hub_spec="huggingface-hub==${HFF_HUB_VER}"
    install_mode="explicit pin"
  elif _hff_is_home_network; then
    hub_spec="huggingface-hub"
    install_mode="latest stable (home/local)"
  else
    HFF_HUB_VER="0.36.0"
    hub_spec="huggingface-hub==${HFF_HUB_VER}"
    install_mode="pod-compatible automatic pin"
  fi

  if [[ "$hub_spec" == huggingface-hub==0.* ]]; then
    : "${HFF_XFER_VER:=0.1.9}"
    _hff_info "Installing HFF packages: ${hub_spec} hf-transfer==${HFF_XFER_VER}"
    _hff_pip install -U \
      "$hub_spec" \
      "hf-transfer==${HFF_XFER_VER}" || return 1
  else
    _hff_info "Installing HFF package: ${hub_spec}"
    _hff_pip install -U "$hub_spec" || return 1
  fi

  installed_version="$(
    "$venv/bin/python" -c 'import huggingface_hub; print(huggingface_hub.__version__)'
  )" || return 1
  copy_support="$(
    "$venv/bin/python" -c 'from huggingface_hub import HfApi; print("yes" if callable(getattr(HfApi(), "copy_files", None)) else "no")'
  )" || return 1

  _hff_info "Ready: $venv"
  _hff_info "huggingface-hub: ${installed_version} (${install_mode})"
  _hff_info "Server-side repo copy support: ${copy_support}"
}

hf_tools_verify() {
  local venv="${HFF_VENV}"

  "$venv/bin/python" - <<'PY'
import os
try:
    import huggingface_hub
    print("huggingface_hub:", getattr(huggingface_hub, "__version__", "?"))
except Exception as exc:
    print("huggingface_hub: ERROR:", exc)

print("HF_XET_HIGH_PERFORMANCE:", os.environ.get("HF_XET_HIGH_PERFORMANCE"))

try:
    import hf_transfer
    print("hf_transfer:", getattr(hf_transfer, "__version__", "OK"))
except Exception as exc:
    print("hf_transfer: missing/ERROR:", exc)
PY

  if [[ -x "$venv/bin/hf" ]]; then
    if "$venv/bin/hf" --help >/dev/null 2>&1; then
      echo "hf (cli): OK"
    else
      _hff_err "hf CLI exists but failed its startup check"
      return 1
    fi
  elif [[ -x "$venv/bin/huggingface-cli" ]]; then
    if "$venv/bin/huggingface-cli" --help >/dev/null 2>&1; then
      echo "huggingface-cli: OK"
    else
      _hff_err "huggingface-cli exists but failed its startup check"
      return 1
    fi
  else
    _hff_err "Hugging Face CLI is missing"
    return 1
  fi
}

# Keep the normal hff dispatcher from helpers_shell.sh, then add one pod-runtime
# command without duplicating the rest of hff's command parsing here.
if declare -F hff >/dev/null 2>&1 && ! declare -F _hff_base_dispatch >/dev/null 2>&1; then
  eval "$(declare -f hff | sed '1s/^hff /_hff_base_dispatch /')"
fi

hff() {
  if [[ "${1:-}" == "telemetry" ]]; then
    shift || true

    local telemetry_py
    telemetry_py="${HFF_TELEMETRY_PY:-${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}/bin/hff_telemetry.py}"

    [[ $# -gt 0 ]] || {
      _hff_err "usage: hff telemetry <file> [--prefix PATH] [-m MESSAGE]"
      return 2
    }
    [[ -f "$telemetry_py" ]] || {
      _hff_err "telemetry helper not found: $telemetry_py"
      return 1
    }

    [[ -x "${HFF_VENV}/bin/python" ]] || install_user_hff || return $?

    "${HFF_VENV}/bin/python" "$telemetry_py" \
      --repo "${HFF_REPO}" \
      --type "${HFF_REPO_TYPE}" \
      "$@"
    return $?
  fi

  if declare -F _hff_base_dispatch >/dev/null 2>&1; then
    _hff_base_dispatch "$@"
    return $?
  fi

  _hff_err "base hff dispatcher is unavailable"
  return 1
}
