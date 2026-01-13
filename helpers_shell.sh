# helpers_shell.sh — minimal, portable helpers (LAN + pods)
# Intended to be sourced from ~/.bash_functions OR from helpers.sh on pods.

# Avoid double-loading
[[ -n "${__HELPERS_SHELL_LOADED:-}" ]] && return 0
__HELPERS_SHELL_LOADED=1

# ---- defaults for non-root machines ----
# Put ~/.local/bin on PATH (safe to do repeatedly)
if [[ -n "${HOME:-}" && ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
  export PATH="${HOME}/.local/bin:${PATH}"
fi

# Default venv / install locations (override via env if you want)
: "${HFF_VENV:=${HOME:-/tmp}/.venvs/hf-tools}"
: "${HFF_PY:=${HOME:-/tmp}/.local/bin/hff.py}"
: "${HFF_SRC_PY:=${POD_RUNTIME_DIR:-}/bin/hff.py}"

# Repo defaults (override in your shell rc if needed)
: "${HFF_REPO:=markwelshboyx/MyLoras}"
: "${HFF_REPO_TYPE:=model}"
: "${HFF_SNAPSHOT_DIR:=snapshot}"

_hff_info() { echo "[hff] $*" >&2; }
_hff_warn() { echo "[hff] WARN: $*" >&2; }
_hff_err()  { echo "[hff] ERROR: $*" >&2; }

# -------- venv bootstrap (LAN-friendly) --------
ensure_hf_tools_venv() {
  local venv="${HFF_VENV}"
  local py="${PYTHON:-python3}"

  if [[ ! -x "$venv/bin/python" ]]; then
    _hff_info "Creating venv: $venv"
    mkdir -p "$(dirname "$venv")" || true
    "$py" -m venv "$venv" || return 1
  fi

  export HFF_VENV="$venv"

  "$venv/bin/python" -m pip install -U pip >/dev/null || return 1

  # Keep it unpinned by default; you can pin by exporting HFF_PINNED=1 + versions below
  if [[ "${HFF_PINNED:-0}" == "1" ]]; then
    : "${HFF_HUB_VER:=1.3.1}"
    : "${HFF_XFER_VER:=0.1.9}"
    "$venv/bin/python" -m pip install -U \
      "huggingface-hub==${HFF_HUB_VER}" \
      "hf-transfer==${HFF_XFER_VER}" >/dev/null || return 1
  else
    "$venv/bin/python" -m pip install -U huggingface-hub hf-transfer >/dev/null || return 1
  fi

  _hff_info "Ready: $venv"
}

# -------- install/link hff.py from pod-runtime --------
install_hff_py() {
  local src="${1:-${HFF_SRC_PY}}"
  local dst="${2:-${HFF_PY}}"

  if [[ -z "$src" ]]; then
    _hff_err "install_hff_py: source not set. Export POD_RUNTIME_DIR or HFF_SRC_PY"
    return 1
  fi
  if [[ ! -f "$src" ]]; then
    _hff_err "hff.py not found: $src"
    return 1
  fi

  mkdir -p "$(dirname "$dst")" || true

  # Prefer symlink to keep “golden” file in sync; copy if HFF_INSTALL_MODE=copy
  if [[ "${HFF_INSTALL_MODE:-symlink}" == "copy" ]]; then
    install -m 0755 "$src" "$dst"
    _hff_info "Installed (copy): $dst"
  else
    ln -sfn "$src" "$dst"
    chmod 0755 "$src" 2>/dev/null || true
    _hff_info "Installed (symlink): $dst -> $src"
  fi
}

hf_tools_verify() {
  local venv="${HFF_VENV}"
  "$venv/bin/python" - <<'PY'
import os
try:
  import huggingface_hub
  print("huggingface_hub:", getattr(huggingface_hub, "__version__", "?"))
except Exception as e:
  print("huggingface_hub: ERROR:", e)

print("HF_HUB_ENABLE_HF_TRANSFER:", os.environ.get("HF_HUB_ENABLE_HF_TRANSFER"))

try:
  import hf_transfer
  print("hf_transfer:", getattr(hf_transfer, "__version__", "OK"))
except Exception as e:
  print("hf_transfer: missing/ERROR:", e)
PY

  # CLI is optional; report whether hf exists (newer default) or huggingface-cli exists
  if [[ -x "$venv/bin/hf" ]]; then
    echo "hf (cli): OK"
  elif [[ -x "$venv/bin/huggingface-cli" ]]; then
    echo "huggingface-cli: OK"
  else
    echo "cli: missing (OK if hff.py uses python APIs only)"
  fi
}

install_user_hff() {
  ensure_hf_tools_venv || return 1
  install_hff_py || return 1
  hf_tools_verify
}

# -------- main wrapper --------
hff() {
  set -euo pipefail

  local venv="${HFF_VENV}"
  local hff_py="${HFF_PY}"
  local repo_id="${HFF_REPO}"
  local repo_type="${HFF_REPO_TYPE}"
  local snapdir="${HFF_SNAPSHOT_DIR}"

  local cmd="${1:-}"; shift || true

  case "$cmd" in
    ensure|init|setup)
      install_user_hff
      ;;
    doctor)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" doctor "$@"
      ;;
    snapshot)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" snapshot --snapdir "$snapdir" "$@"
      ;;
    ls|mkdir|mv|rm|put|get)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" "$cmd" "$@"
      ;;
    help|-h|--help|"")
      cat <<EOF
hff — portable HF helper (user-mode)

Bootstrap:
  hff ensure

Defaults:
  HFF_VENV=$HFF_VENV
  HFF_PY=$HFF_PY
  POD_RUNTIME_DIR=${POD_RUNTIME_DIR:-<unset>}
  HFF_SRC_PY=$HFF_SRC_PY

Repo:
  HFF_REPO=$HFF_REPO
  HFF_REPO_TYPE=$HFF_REPO_TYPE
  HFF_SNAPSHOT_DIR=$HFF_SNAPSHOT_DIR

Commands:
  hff doctor
  hff ls [path]
  hff mkdir <path>
  hff mv <src> <dst>
  hff rm <path>
  hff put <local> <dst>
  hff get <src> [out]
  hff snapshot create --name "desc" <paths...>
  hff snapshot list
  hff snapshot show <id>
  hff snapshot get <id> [--extract-dir DIR] [--cache-dir DIR]
  hff snapshot destroy <id> [-y]

Pins:
  export HFF_PINNED=1
  export HFF_HUB_VER=1.3.1
  export HFF_XFER_VER=0.1.9

Install mode:
  export HFF_INSTALL_MODE=symlink   # default
  export HFF_INSTALL_MODE=copy
EOF
      ;;
    *)
      _hff_err "unknown command: ${cmd:-<none>} (try: hff help)"
      return 2
      ;;
  esac
}
