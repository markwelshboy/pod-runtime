#!/usr/bin/env bash
# HFF bootstrap policy override.
# Loaded after helpers_core.sh so it replaces the legacy implementation from helpers_shell.sh.

_hff_pip() {
  # HFF has its own venv and must not inherit ComfyUI's stack constraints or pip.conf.
  env \
    -u PIP_CONSTRAINT \
    -u PIP_BUILD_CONSTRAINT \
    PIP_CONFIG_FILE=/dev/null \
    "${HFF_VENV}/bin/python" -m pip "$@"
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
  _hff_pip install -U pip >/dev/null || return 1

  if [[ -n "${HFF_HUB_VER:-}" ]]; then
    hub_spec="huggingface-hub==${HFF_HUB_VER}"
    install_mode="explicit pin"
  elif [[ "${HFF_PINNED:-0}" == "1" ]]; then
    HFF_HUB_VER="0.36.0"
    hub_spec="huggingface-hub==${HFF_HUB_VER}"
    install_mode="pod-compatible pin"
  elif _hff_is_home_network; then
    hub_spec="huggingface-hub"
    install_mode="latest stable (home/local)"
  else
    HFF_HUB_VER="0.36.0"
    hub_spec="huggingface-hub==${HFF_HUB_VER}"
    install_mode="conservative fallback"
  fi

  if [[ "$hub_spec" == huggingface-hub==0.* ]]; then
    : "${HFF_XFER_VER:=0.1.9}"
    _hff_pip install -U \
      "$hub_spec" \
      "hf-transfer==${HFF_XFER_VER}" >/dev/null || return 1
  else
    _hff_pip install -U "$hub_spec" >/dev/null || return 1
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
