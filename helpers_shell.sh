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
  local mode="keep-top"   # keep-top | flatten
  local url=""
  local target=""

  # parse args
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --flatten)
        mode="flatten"
        shift
        ;;
      --help|-h)
        cat <<'EOF'
usage:
  download_gdrive_folder <url> <target_parent_dir>
  download_gdrive_folder --flatten <url> <target_dir>

default:
  Keeps the downloaded top-level folder (recommended).

--flatten:
  Moves contents directly into target (use only when explicitly required).
EOF
        return 0
        ;;
      *)
        if [[ -z "$url" ]]; then
          url="$1"
        elif [[ -z "$target" ]]; then
          target="$1"
        else
          echo "ERROR: unexpected arg: $1" >&2
          return 2
        fi
        shift
        ;;
    esac
  done

  [[ -n "$url" ]]    || { echo "ERROR: missing url" >&2; return 2; }
  [[ -n "$target" ]] || { echo "ERROR: missing target" >&2; return 2; }

  command -v gdown >/dev/null 2>&1 || {
    echo "ERROR: gdown not installed" >&2
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

  mkdir -p "$target" || {
    echo "ERROR: cannot create target: $target"
    rm -rf "$tmp"
    return 1
  }

  # What did we actually get?
  mapfile -t top_items < <(find "$tmp" -mindepth 1 -maxdepth 1)

  if [[ "${#top_items[@]}" -eq 0 ]]; then
    echo "ERROR: nothing downloaded?" >&2
    rm -rf "$tmp"
    return 1
  fi

  if [[ "$mode" == "flatten" ]]; then
    echo "[gdown] flattening into: $target"
    mv "$tmp"/* "$target"/
  else
    echo "[gdown] keeping top-level folder(s) in: $target"
    mv "${top_items[@]}" "$target"/
  fi

  rm -rf "$tmp"
  echo "[gdown] done"
}