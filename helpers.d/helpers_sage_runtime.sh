#!/usr/bin/env bash
# ======================================================================
# Runtime SageAttention overrides
#
# helpers_core.sh still contains the legacy Sage implementation. This module is
# sourced afterwards and deliberately overrides only the build/fetch/publish
# functions so existing bundle naming, restore logic, and callers remain stable.
# ======================================================================

_sage_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_sage_ensure_build_prereqs() {
  local missing=() cmd
  for cmd in gcc g++ cmake ninja curl tar; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done

  if ((${#missing[@]})); then
    echo "[sage] Missing build prerequisites: ${missing[*]}" >&2
    if command -v apt-get >/dev/null 2>&1; then
      echo "[sage] Installing generic build prerequisites..." >&2
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build curl ca-certificates python3-dev
    else
      echo "[sage] ERROR: apt-get unavailable; cannot install missing build prerequisites." >&2
      return 1
    fi
  fi

  if ! command -v nvcc >/dev/null 2>&1; then
    echo "[sage] ERROR: nvcc is missing. Sage source builds require a CUDA devel/toolkit image." >&2
    return 1
  fi
}

_sage_hf_python() {
  if [[ ! -x "${HFF_VENV:-}/bin/python" ]] && declare -F ensure_hf_tools_venv >/dev/null 2>&1; then
    ensure_hf_tools_venv >/dev/null || return 1
  fi

  if [[ -x "${HFF_VENV:-}/bin/python" ]]; then
    printf '%s\n' "${HFF_VENV}/bin/python"
    return 0
  fi

  echo "[sage-hf] ERROR: HFF tooling venv is unavailable." >&2
  return 1
}

_sage_hf_repo_id() {
  printf '%s\n' "${HFF_REPO:-${HF_REPO_ID:-}}"
}

_sage_hf_repo_type() {
  printf '%s\n' "${HFF_REPO_TYPE:-${HF_REPO_TYPE:-dataset}}"
}

_sage_hf_revision() {
  printf '%s\n' "${HFF_BRANCH:-${CN_BRANCH:-main}}"
}

install_sage_from_source() {
  local src="${SAGE_SOURCE_DIR:-/tmp/SageAttention}"
  local repo="${SAGE_REPO_URL:-https://github.com/thu-ml/SageAttention.git}"
  local archive_repo="${repo%.git}"
  local ref="${SAGE_COMMIT:-main}"
  local cc_bin="${SAGE_CC:-gcc}"
  local cxx_bin="${SAGE_CXX:-g++}"
  local compute_cap archive tmp_root build_log

  _sage_ensure_build_prereqs || return 1

  command -v "$cc_bin" >/dev/null 2>&1 || {
    echo "[sage] ERROR: requested compiler not found: $cc_bin" >&2
    return 1
  }
  command -v "$cxx_bin" >/dev/null 2>&1 || {
    echo "[sage] ERROR: requested C++ compiler not found: $cxx_bin" >&2
    return 1
  }

  compute_cap="$("$PY" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit(1)
maj, minor = torch.cuda.get_device_capability(0)
print(f"{maj}.{minor}")
PY
  )" || {
    echo "[sage] ERROR: could not determine CUDA compute capability with Torch." >&2
    return 1
  }

  export CC="$cc_bin"
  export CXX="$cxx_bin"
  export TORCH_CUDA_ARCH_LIST="${SAGE_TORCH_CUDA_ARCH_LIST:-$compute_cap}"

  echo "[sage] Building SageAttention ref=${ref} for compute capability ${compute_cap}" >&2
  echo "[sage] Toolchain: CC=$(command -v "$CC"), CXX=$(command -v "$CXX"), nvcc=$(command -v nvcc)" >&2
  echo "[sage] TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}" >&2

  rm -rf "$src"
  tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/sage-src.XXXXXX")" || return 1
  archive="${tmp_root}/sage.tar.gz"

  # Fetch the pinned source archive rather than cloning repository history. This
  # keeps fallback builds reproducible and avoids the large git/LFS-style fetch
  # path that used to dominate first boot.
  if ! curl -fL --retry 3 --retry-delay 2 \
      "${archive_repo}/archive/${ref}.tar.gz" -o "$archive"; then
    echo "[sage] ERROR: failed to download SageAttention source archive for ${ref}." >&2
    rm -rf "$tmp_root"
    return 1
  fi

  mkdir -p "$src"
  if ! tar -xzf "$archive" --strip-components=1 -C "$src"; then
    echo "[sage] ERROR: failed to extract SageAttention source archive." >&2
    rm -rf "$tmp_root" "$src"
    return 1
  fi
  rm -rf "$tmp_root"

  mkdir -p "${COMFY_LOGS:-/workspace/logs}"
  build_log="${COMFY_LOGS:-/workspace/logs}/sage_build.log"

  # Do not use editable installs: the resulting package/binaries must be
  # self-contained in the venv so the existing bundle snapshot is portable.
  if env \
      -u PIP_REQUIRE_HASHES \
      -u PIP_BUILD_CONSTRAINT \
      CC="$CC" CXX="$CXX" TORCH_CUDA_ARCH_LIST="$TORCH_CUDA_ARCH_LIST" \
      "$PIP" install --no-deps --no-build-isolation "$src" \
      2>&1 | tee "$build_log"; then
    echo "[sage] SageAttention source build completed successfully." >&2
    return 0
  fi

  echo "[sage] ERROR: SageAttention build failed; see ${build_log}." >&2
  return 1
}

hf_fetch_sage_bundle() {
  local key="${1:?SAGE_KEY}"
  local repo repo_type revision py filename local_tgz

  repo="$(_sage_hf_repo_id)"
  repo_type="$(_sage_hf_repo_type)"
  revision="$(_sage_hf_revision)"
  py="$(_sage_hf_python)" || return 1

  if [[ -z "$repo" ]]; then
    echo "[sage-hf] ERROR: HF_REPO_ID/HFF_REPO is not configured." >&2
    return 1
  fi

  filename="bundles/torch_sage_bundle_${key}.tgz"
  mkdir -p "$CACHE_DIR"
  local_tgz="${CACHE_DIR}/torch_sage_bundle_${key}.tgz"

  echo "[sage-hf] Fetching exact bundle ${repo}:${filename} via HFF/HfApi..." >&2
  if HF_SAGE_REPO="$repo" \
     HF_SAGE_REPO_TYPE="$repo_type" \
     HF_SAGE_REVISION="$revision" \
     HF_SAGE_FILENAME="$filename" \
     HF_SAGE_DEST="$local_tgz" \
     "$py" - <<'PY'
import os
import shutil
from huggingface_hub import hf_hub_download

src = hf_hub_download(
    repo_id=os.environ["HF_SAGE_REPO"],
    repo_type=os.environ["HF_SAGE_REPO_TYPE"],
    filename=os.environ["HF_SAGE_FILENAME"],
    revision=os.environ["HF_SAGE_REVISION"],
    token=os.environ.get("HF_TOKEN") or None,
)
shutil.copy2(src, os.environ["HF_SAGE_DEST"])
PY
  then
    echo "[sage-hf] Restored $(basename "$local_tgz") directly from Hub." >&2
    printf '%s\n' "$local_tgz"
    return 0
  fi

  rm -f "$local_tgz"
  echo "[sage-hf] Exact bundle not found for key=${key}." >&2
  return 1
}

push_sage_bundle_if_requested() {
  _sage_true "${PUSH_SAGE_BUNDLE:-0}" || {
    echo "[sage-hf] PUSH_SAGE_BUNDLE is disabled; skipping publish." >&2
    return 0
  }

  local key tarpath repo repo_type revision py filename
  key="$(torch_sage_key)" || return 1

  if ! "$PY" - <<'PY'
import importlib
for name in ("sageattention", "SageAttention", "sage_attention"):
    try:
        importlib.import_module(name)
        raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
PY
  then
    echo "[sage-hf] ERROR: SageAttention is not importable; refusing to publish a bundle." >&2
    return 1
  fi

  tarpath="$(build_sage_bundle_wrapper "$key")" || return 1
  repo="$(_sage_hf_repo_id)"
  repo_type="$(_sage_hf_repo_type)"
  revision="$(_sage_hf_revision)"
  py="$(_sage_hf_python)" || return 1
  filename="bundles/$(basename "$tarpath")"

  if [[ -z "$repo" ]]; then
    echo "[sage-hf] ERROR: HF_REPO_ID/HFF_REPO is not configured." >&2
    return 1
  fi

  echo "[sage-hf] Publishing ${filename} directly via HFF/HfApi..." >&2
  HF_SAGE_REPO="$repo" \
  HF_SAGE_REPO_TYPE="$repo_type" \
  HF_SAGE_REVISION="$revision" \
  HF_SAGE_FILENAME="$filename" \
  HF_SAGE_LOCAL="$tarpath" \
  HF_SAGE_COMMIT_MESSAGE="torch_sage bundle ${key}" \
  "$py" - <<'PY'
import os
from huggingface_hub import HfApi

HfApi(token=os.environ.get("HF_TOKEN") or None).upload_file(
    path_or_fileobj=os.environ["HF_SAGE_LOCAL"],
    path_in_repo=os.environ["HF_SAGE_FILENAME"],
    repo_id=os.environ["HF_SAGE_REPO"],
    repo_type=os.environ["HF_SAGE_REPO_TYPE"],
    revision=os.environ["HF_SAGE_REVISION"],
    commit_message=os.environ["HF_SAGE_COMMIT_MESSAGE"],
)
PY

  echo "[sage-hf] Uploaded $(basename "$tarpath") without cloning the Hub repository." >&2
}
