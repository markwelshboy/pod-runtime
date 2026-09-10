#!/usr/bin/env bash
# Health checks and safe linking for filtered Hugging Face repository snapshots.

if [[ -n "${__HF_REPO_SYNC_HELPERS_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
__HF_REPO_SYNC_HELPERS_LOADED=1

_hf_repo_sync_info() {
  if declare -F _sync_info >/dev/null 2>&1; then
    _sync_info "$*"
  else
    printf 'ℹ️  %s\n' "$*"
  fi
}

_hf_repo_sync_warn() {
  if declare -F _sync_warn >/dev/null 2>&1; then
    _sync_warn "$*"
  else
    printf '⚠️  %s\n' "$*" >&2
  fi
}

# A filtered `hf download --include ... --local-dir ...` directory is healthy when:
#   1. the directory exists;
#   2. no Hugging Face partial-download files remain; and
#   3. at least one non-empty payload file exists outside the HF metadata cache.
#
# Do not require a particular model extension: valid filtered snapshots may contain
# only .pth files, tar archives, configuration files, or other asset types.
hf_repo_looks_good() {
  local dir="${1:-}"
  local incomplete=""
  local payload=""

  if [[ -z "$dir" || ! -d "$dir" ]]; then
    _hf_repo_sync_warn "HF repo directory is missing: ${dir:-<unset>}"
    return 1
  fi

  if [[ -d "$dir/.cache/huggingface/download" ]]; then
    incomplete="$(
      find "$dir/.cache/huggingface/download" \
        -type f \
        -name '*.incomplete' \
        -print -quit 2>/dev/null || true
    )"
    if [[ -n "$incomplete" ]]; then
      _hf_repo_sync_warn "HF repo contains an incomplete download: $incomplete"
      return 1
    fi
  fi

  payload="$(
    find "$dir" \
      -type f \
      ! -path "$dir/.cache/huggingface/*" \
      ! -name '.gitkeep' \
      ! -name '*.incomplete' \
      -size +0c \
      -print -quit 2>/dev/null || true
  )"

  if [[ -z "$payload" ]]; then
    _hf_repo_sync_warn "HF repo contains no non-empty payload files: $dir"
    return 1
  fi

  if [[ "${HF_REPO_HEALTH_DEBUG:-0}" == "1" ]]; then
    _hf_repo_sync_info "HF repo health passed; sample payload: $payload"
  fi

  return 0
}

# Link each immediate child of a source directory into a destination directory.
# Missing/empty source directories are valid for filtered snapshots. Optional
# remaining arguments are basenames to skip, such as an archive extracted first.
hf_repo_link_directory_contents() {
  local source_dir="${1:?source directory required}"
  local destination_dir="${2:?destination directory required}"
  shift 2

  if [[ ! -d "$source_dir" ]]; then
    _hf_repo_sync_info "HF source directory absent; skipping: $source_dir"
    return 0
  fi

  mkdir -p -- "$destination_dir"

  local item base skip should_skip count=0
  while IFS= read -r -d '' item; do
    base="$(basename -- "$item")"
    should_skip=0

    for skip in "$@"; do
      if [[ "$base" == "$skip" ]]; then
        should_skip=1
        break
      fi
    done
    (( should_skip == 1 )) && continue

    if ! ln -sfn -- "$item" "$destination_dir/$base"; then
      _hf_repo_sync_warn "Could not link $item into $destination_dir"
      return 1
    fi
    count=$((count + 1))
  done < <(
    find "$source_dir" \
      -mindepth 1 \
      -maxdepth 1 \
      ! -name '.gitkeep' \
      -print0 2>/dev/null
  )

  _hf_repo_sync_info "Linked $count item(s): $source_dir -> $destination_dir"
  return 0
}

hf_repo_extract_tar_if_present() {
  local archive="${1:?archive path required}"
  local destination_dir="${2:?destination directory required}"

  [[ -s "$archive" ]] || return 0
  mkdir -p -- "$destination_dir"

  _hf_repo_sync_info "Extracting $(basename -- "$archive") into $destination_dir"
  if ! tar -xf "$archive" -C "$destination_dir"; then
    _hf_repo_sync_warn "Failed to extract archive: $archive"
    return 1
  fi

  return 0
}

# Install the selected content from HF_MY_REPO_LOCAL into the normal ComfyUI model
# directories. This deliberately tolerates categories omitted by HF include globs.
hf_my_repo_sync_assets() {
  local repo_dir="${1:?HF repo local directory required}"
  local repo_id="${2:-${HF_MY_REPO_ID:-unknown}}"
  local comfy_home="${COMFY_HOME:-/workspace/ComfyUI}"
  local loras_dir="${LORAS_DIR:-$comfy_home/models/loras}"
  local checkpoints_dir="${CHECKPOINTS_DIR:-$comfy_home/models/checkpoints}"
  local ultralytics_dir="${ULTRALYTICS_DIR:-$comfy_home/models/ultralytics}"
  local upscale_dir="${UPSCALE_DIR:-$comfy_home/models/upscale_models}"
  local failed=0

  if ! hf_repo_looks_good "$repo_dir"; then
    _hf_repo_sync_warn "$repo_id repo not healthy at '$repo_dir' (skipping links)."
    return 1
  fi

  if declare -F rsync_or_symlink_source_to_destination >/dev/null 2>&1; then
    rsync_or_symlink_source_to_destination symlink "$repo_dir" /workspace || {
      _hf_repo_sync_warn "Could not expose $repo_dir under /workspace"
      failed=1
    }
  fi

  _hf_repo_sync_info "Linking selected files from $repo_dir into ComfyUI model directories..."

  hf_repo_link_directory_contents \
    "$repo_dir/models/loras" \
    "$loras_dir" || failed=1

  hf_repo_link_directory_contents \
    "$repo_dir/models/checkpoints" \
    "$checkpoints_dir" || failed=1

  hf_repo_extract_tar_if_present \
    "$repo_dir/models/ultralytics/ultralytics.tar" \
    "$ultralytics_dir" || failed=1

  hf_repo_link_directory_contents \
    "$repo_dir/models/ultralytics" \
    "$ultralytics_dir" \
    ultralytics.tar || failed=1

  hf_repo_extract_tar_if_present \
    "$repo_dir/models/upscale_models/upscalers.tar" \
    "$upscale_dir" || failed=1

  hf_repo_link_directory_contents \
    "$repo_dir/models/upscale_models" \
    "$upscale_dir" \
    upscalers.tar || failed=1

  if (( failed != 0 )); then
    _hf_repo_sync_warn "$repo_id synced, but one or more extract/link operations failed."
    return 1
  fi

  if declare -F tg >/dev/null 2>&1; then
    tg "📥 HuggingFace repo sync completed: $repo_id" || true
  fi
  _hf_repo_sync_info "HF repo assets ready: $repo_id"
  return 0
}
