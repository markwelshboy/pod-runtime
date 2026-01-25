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

need_apt() {
  local cmd="$1"
  local pkg="${2:-$1}"

  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi

  echo "[need_apt] missing: $cmd — attempting apt install: $pkg"

  # Choose runner (root vs sudo)
  local run=()
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    run=(bash -lc)
  else
    if command -v sudo >/dev/null 2>&1; then
      run=(sudo -E bash -lc)
    else
      echo "ERROR: $cmd missing and not root; sudo not installed. Run as root or install sudo." >&2
      return 127
    fi
  fi

  # Install (best effort, then verify)
  "${run[@]}" "apt-get update -y" || true
  "${run[@]}" "apt-get install -y $pkg" || true

  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found after apt install: $cmd (pkg: $pkg)" >&2
    return 127
  fi
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
  local COMFY="${COMFY:-/workspace/ComfyUI}"  

  need_apt curl || {
    echo "ERROR: curl is required but could not be installed"
    return 127
  }
  need_apt jq || {
    echo "ERROR: jq is required but could not be installed"
    return 127
  }

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

civitai() {
  # civitai - Civitai downloader/listing helper (GNU-style)
  #
  # Examples:
  #   civitai --list 139562
  #   civitai 139562 --list
  #   civitai 139562 --out "$COMFY/models/checkpoints"
  #   civitai 139562 --out "$COMFY/models/checkpoints" --version 798204 --file realvisxlV50_v50LightningBakedvae.safetensors

  local model_id=""
  local outdir="."
  local version_id=""
  local want_file=""
  local mode="download"
  local sanitize="${CIVITAI_SANITIZE:-0}"
  local quiet=0

  _usage() {
    cat <<'EOF'
usage:
  civitai --list <model_id>
  civitai <model_id> [--out DIR] [--version ID] [--file NAME] [--sanitize] [--quiet]

options:
  --list               List available .safetensors grouped by version
  --out DIR            Output directory (default: .)
  --version ID         Force modelVersionId
  --file NAME          Download only this exact filename
  --sanitize           Replace spaces with underscores
  --quiet              Less output
  --help               Show this help

env:
  CIVITAI_TOKEN        Required for downloads (not for --list)

examples:
  civitai --list 139562
  civitai 139562 --out "$COMFY/models/checkpoints"
  civitai 139562 --out "$COMFY/models/checkpoints" --version 798204 \
         --file realvisxlV50_v50LightningBakedvae.safetensors
EOF
  }

  # ---------- parse args (order independent) ----------
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --list)
        mode="list"
        shift
        ;;
      --out)
        outdir="$2"
        shift 2
        ;;
      --version)
        version_id="$2"
        shift 2
        ;;
      --file)
        want_file="$2"
        shift 2
        ;;
      --sanitize)
        sanitize=1
        shift
        ;;
      --quiet)
        quiet=1
        shift
        ;;
      --help)
        _usage
        return 0
        ;;
      --*)
        echo "ERROR: unknown option: $1" >&2
        _usage
        return 2
        ;;
      *)
        # First non-flag = model_id
        if [[ -z "$model_id" ]]; then
          model_id="$1"
        else
          echo "ERROR: unexpected argument: $1" >&2
          _usage
          return 2
        fi
        shift
        ;;
    esac
  done

  if [[ -z "$model_id" ]]; then
    echo "ERROR: missing model_id" >&2
    _usage
    return 2
  fi

  # ---------- deps ----------
  need_apt curl || {
    echo "ERROR: curl is required but could not be installed"
    return 127
  }
  need_apt jq || {
    echo "ERROR: jq is required but could not be installed"
    return 127
  }

  # ---------- fetch metadata once ----------
  local json
  json="$(curl -fsSL "https://civitai.com/api/v1/models/${model_id}")"
  if [[ $? -ne 0 || -z "$json" ]]; then
    echo "ERROR: failed to fetch model metadata for id=${model_id}" >&2
    return 1
  fi

  # ---------- LIST MODE ----------
  if [[ "$mode" == "list" ]]; then
    jq -r '
      .modelVersions
      | map(. + { _sort: (.publishedAt // .createdAt // "1970-01-01T00:00:00.000Z") })
      | sort_by(._sort) | reverse
      | .[]
      | "Version: \(.id)  |  \(.name)  |  \(.publishedAt // .createdAt // "unknown")",
        (
          .files
          | map(select(.name | test("\\.safetensors$"; "i")))
          | map(.name)
          | unique
          | if length == 0 then "  (no .safetensors)"
            else .[] | "  - " + .
            end
        ),
        ""
    ' <<<"$json"
    return 0
  fi

  # ---------- DOWNLOAD MODE ----------
  if [[ -z "${CIVITAI_TOKEN:-}" ]]; then
    echo "ERROR: CIVITAI_TOKEN is not set (required for downloads)" >&2
    return 2
  fi

  mkdir -p "$outdir" 2>/dev/null || {
    echo "ERROR: cannot create outdir: $outdir" >&2
    return 1
  }

  # Choose modelVersionId
  local chosen_vid
  if [[ -n "$version_id" ]]; then
    chosen_vid="$version_id"
  else
    chosen_vid="$(jq -r '
      .modelVersions
      | map(. + { _sort: (.publishedAt // .createdAt // "1970-01-01T00:00:00.000Z") })
      | sort_by(._sort)
      | last
      | .id
    ' <<<"$json")"
  fi

  if [[ -z "$chosen_vid" || "$chosen_vid" == "null" ]]; then
    echo "ERROR: could not determine modelVersionId" >&2
    return 1
  fi

  [[ "$quiet" != 1 ]] && {
    echo "[civitai] model_id=${model_id} modelVersionId=${chosen_vid}"
    echo "[civitai] outdir=${outdir}"
  }

  # Build manifest
  local manifest
  manifest="$(
    jq -r --argjson vid "$chosen_vid" '
      .modelVersions
      | map(select(.id == $vid))
      | .[0].files
      | map(select(.name | test("\\.safetensors$"; "i")))
      | map({name:.name, url:.downloadUrl})
      | unique_by(.name + "\u0000" + .url)
      | .[]
      | "\(.name)\t\(.url)"
    ' <<<"$json"
  )"

  if [[ -z "$manifest" ]]; then
    echo "WARNING: no .safetensors files found" >&2
    return 0
  fi

  # Validate requested file
  if [[ -n "$want_file" ]]; then
    if ! awk -F'\t' -v f="$want_file" '$1==f{found=1} END{exit(found?0:1)}' <<<"$manifest"; then
      echo "WARNING: file not found: $want_file" >&2
      echo "Available:" >&2
      awk -F'\t' '{print "  - " $1}' <<<"$manifest" >&2
      return 3
    fi
  fi

  # Download loop
  local name url outname outpath
  while IFS=$'\t' read -r name url; do
    [[ -z "$name" || -z "$url" ]] && continue
    [[ -n "$want_file" && "$name" != "$want_file" ]] && continue

    outname="$name"
    [[ "$sanitize" == 1 ]] && outname="${outname// /_}"
    outpath="${outdir%/}/$outname"

    [[ "$quiet" != 1 ]] && echo "[civitai] -> $outpath"

    curl -fL \
      -H "Authorization: Bearer ${CIVITAI_TOKEN}" \
      "$url" \
      -o "$outpath" || {
        echo "ERROR: download failed for $name" >&2
        return 4
      }
  done <<<"$manifest"

  [[ "$quiet" != 1 ]] && echo "[civitai] done"
  return 0
}

download_gdrive_folder() {
  local url="$1"
  local target="$2"

  if [[ -z "$url" || -z "$target" ]]; then
    echo "usage: download_gdrive_folder <gdrive_url> <target_dir>"
    return 2
  fi

  need_apt gdown || {
    echo "ERROR: gdown is required but could not be installed"
    return 127
  }

  local tmp
  tmp="$(mktemp -d)"

  echo "[gdown] downloading into temp: $tmp"
  gdown --folder "$url" -O "$tmp" || {
    echo "ERROR: gdown failed"
    rm -rf "$tmp"
    return 1
  }

  mkdir -p "$target"
  echo "[gdown] moving contents to: $target"
  mv "$tmp"/* "$target"/
  rm -rf "$tmp"

  echo "[gdown] done"
}
