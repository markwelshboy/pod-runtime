# ~/.bash_functions - shared helpers for Vast pod shells

# Safely source a file if it exists
source_if_exists() {
  local f="$1"
  if [ -f "$f" ]; then
    echo "[helpers] Sourcing: $f"
    #shellcheck disable=SC1090
    source "$f"
  fi
}

# Load the "runtime env" so an SSH shell matches the autorun context
load_runtime_env() {
  
  secrets="/root/.secrets/env.current"

  # Tokens & session env
  source_if_exists "$secrets"

  # ComfyUI repo env + helpers
  source_if_exists "$repo_root/.env"
  source_if_exists "$repo_root/helpers.sh"

}

# Quick Git identity helper (does NOT run automatically)
git_identity() {
  cat <<'EOF'
git_identity usage:

  # One-time global setup:
  git config --global user.name  "Mark Richards"
  git config --global user.email "mark.david.richards@gmail.com"

  # Optional per-repo override (run inside repo):
  git config user.name  "Mark Richards"
  git config user.email "mark.david.richards@pgmail.com"

Current effective Git identity:
EOF
  git config --global user.name  2>/dev/null | sed 's/^/  global name:  /'  || true
  git config --global user.email 2>/dev/null | sed 's/^/  global email: /'   || true
}

# Small helper: show current git branch + status in a compact way
git_prompt_info() {
  command -v git >/dev/null 2>&1 || return 0
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  local branch dirty mark
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  if ! git diff --quiet --ignore-submodules -- 2>/dev/null; then
    dirty='*'
  else
    dirty=''
  fi
  printf '(%s%s)' "$branch" "$dirty"
}

hfd() {
  if [[ $# -lt 1 ]]; then
    echo "Usage: hfd <huggingface_url> [local_dir]"
    return 1
  fi

  local url="$1"
  local local_dir="${2:-.}"

  local path="${url#https://huggingface.co/}"
  path="${path#http://huggingface.co/}"

  IFS='/' read -r org repo mode branch rest <<< "$path"

  if [[ -z "$org" || -z "$repo" || -z "$rest" ]]; then
    echo "❌ Could not parse HuggingFace URL"
    return 1
  fi

  local filename="$rest"

  echo "→ hf download $org/$repo $filename --local-dir $local_dir"
  hf download "$org/$repo" "$filename" --local-dir "$local_dir"
}

cdlv() {
  local version_id="$1"
  local out="$2"

  curl -fL \
    -H "Authorization: Bearer $CIVITAI_TOKEN" \
    "https://civitai.com/api/download/models/${version_id}" \
    -o "$out"
}

download_civitai() {
  set -euo pipefail

  local model_id="${1:-}"
  local outdir="${2:-.}"
  local version_id="${3:-}"     # optional: force specific modelVersionId
  local want_file="${4:-}"      # optional: exact filename to fetch (e.g. realvisxlV50_v50LightningBakedvae.safetensors)

  # Behavior toggles
  local sanitize="${CIVITAI_SANITIZE:-0}"   # 1 => replace spaces with underscores
  local list_only="${CIVITAI_LIST_ONLY:-0}" # 1 => just list candidate files, no download

  if [[ -z "$model_id" ]]; then
    echo "usage: download_civitai <model_id> [outdir] [modelVersionId] [filename]"
    echo "  ex: download_civitai 139562 \"$COMFY/models/checkpoints\" 798204 realvisxlV50_v50LightningBakedvae.safetensors"
    return 2
  fi
  if [[ -z "${CIVITAI_TOKEN:-}" ]]; then
    echo "ERROR: CIVITAI_TOKEN is not set"
    return 2
  fi

  mkdir -p "$outdir"

  # Fetch model JSON once
  local json
  json="$(curl -fsSL "https://civitai.com/api/v1/models/${model_id}")" || {
    echo "ERROR: failed to fetch model metadata for id=${model_id}"
    return 1
  }

  # Pick version:
  # - If version_id provided: use it
  # - Else: pick newest by publishedAt (fallback createdAt)
  local chosen_vid
  if [[ -n "$version_id" ]]; then
    chosen_vid="$version_id"
  else
    chosen_vid="$(
      jq -r '
        .modelVersions
        | map(. + { _sort: ((.publishedAt // .createdAt // "1970-01-01T00:00:00.000Z")) })
        | sort_by(._sort)
        | last
        | .id
      ' <<<"$json"
    )"
  fi

  if [[ -z "$chosen_vid" || "$chosen_vid" == "null" ]]; then
    echo "ERROR: could not determine modelVersionId for model_id=${model_id}"
    return 1
  fi

  # Build manifest for chosen version: TSV name<tab>downloadUrl
  # - filter safetensors
  # - de-duplicate by (name, url)
  local manifest
  manifest="$(
    jq -r --argjson vid "$chosen_vid" '
      .modelVersions
      | map(select(.id == $vid))
      | .[0]
      | .files
      | map(select(.name | test("\\.safetensors$"; "i")))
      | map({name:.name, url:.downloadUrl})
      | unique_by(.name + "\u0000" + .url)
      | .[]
      | "\(.name)\t\(.url)"
    ' <<<"$json"
  )"

  if [[ -z "$manifest" ]]; then
    echo "WARNING: no .safetensors files found for modelVersionId=${chosen_vid}"
    return 0
  fi

  echo "[civitai] model_id=${model_id} modelVersionId=${chosen_vid}"
  echo "[civitai] outdir=${outdir}"

  # If a specific filename requested, validate it exists in this version manifest
  if [[ -n "$want_file" ]]; then
    local found=0
    while IFS=$'\t' read -r name url; do
      [[ -z "${name:-}" || -z "${url:-}" ]] && continue
      if [[ "$name" == "$want_file" ]]; then
        found=1
        break
      fi
    done <<<"$manifest"

    if [[ "$found" -ne 1 ]]; then
      echo "WARNING: requested file not found in modelVersionId=${chosen_vid}: $want_file"
      echo "Available .safetensors in this version:"
      awk -F'\t' '{print "  - " $1}' <<<"$manifest"
      return 3
    fi
  fi

  # Option: list-only
  if [[ "$list_only" == "1" ]]; then
    echo "Files:"
    awk -F'\t' '{print "  - " $1}' <<<"$manifest"
    return 0
  fi

  # Pass 2: download
  while IFS=$'\t' read -r name url; do
    [[ -z "${name:-}" || -z "${url:-}" ]] && continue

    # If user requested a specific file, skip others
    if [[ -n "$want_file" && "$name" != "$want_file" ]]; then
      continue
    fi

    local outname="$name"
    if [[ "$sanitize" == "1" ]]; then
      outname="${outname// /_}"
    fi

    local outpath="${outdir%/}/$outname"
    echo "[civitai] -> $outpath"

    curl -fL \
      -H "Authorization: Bearer ${CIVITAI_TOKEN}" \
      "$url" \
      -o "$outpath"
  done <<<"$manifest"

  echo "[civitai] done"
}
