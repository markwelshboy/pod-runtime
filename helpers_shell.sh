# helpers_shell.sh — minimal, portable helpers (LAN + pods)
# Intended to be sourced from ~/.bash_functions OR from helpers.sh on pods.

# Avoid double-loading
#[[ -n "${__HELPERS_SHELL_LOADED:-}" ]] && return 0
#__HELPERS_SHELL_LOADED=1

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
: "${HFF_REPO:=${HF_MY_REPO_ID:-markwelshboyx/diffusionetc}}"
: "${HFF_REPO_TYPE:=${HF_MY_REPO_TYPE:-model}}"
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
  # Preserve caller's errexit; prevent failures from nuking interactive sessions
  local __had_e=0
  case $- in *e*) __had_e=1 ;; esac
  set +e
  set -uo pipefail

  local venv="${HFF_VENV}"
  local hff_py="${HFF_PY}"
  local repo_id="${HFF_REPO}"
  local repo_type="${HFF_REPO_TYPE}"
  local snapdir="${HFF_SNAPSHOT_DIR}"

  local cmd="${1:-}"; shift || true
  local rc=0

  case "$cmd" in
    ensure|init|setup)
      install_user_hff; rc=$?
      ;;
    doctor)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" doctor "$@"; rc=$?
      ;;
    snapshot)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" snapshot --snapdir "$snapdir" "$@"; rc=$?
      ;;
    ls|mkdir|mv|rm|put|get)
      [[ -x "$venv/bin/python" && -x "$hff_py" ]] || install_user_hff
      "$venv/bin/python" "$hff_py" --repo "$repo_id" --type "$repo_type" "$cmd" "$@"; rc=$?
      ;;
    help|-h|--help|"")
      # ... your existing help text ...
      rc=0
      ;;
    *)
      _hff_err "unknown command: ${cmd:-<none>} (try: hff help)"
      rc=2
      ;;
  esac

  # Restore errexit if it was set in the caller
  if [[ "$__had_e" -eq 1 ]]; then
    set -e
  fi
  return "$rc"
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
  # New:
  #   civitai --id urn:air:sdxl:checkpoint:civitai:1837476@2607296
  #   civitai urn:air:sdxl:checkpoint:civitai:1837476@2607296
  #
  # Behavior:
  #   - Default download: .safetensors only
  #   - If an explicit version is provided (URN with @, or --version): download ALL files in that version
  #     unless you narrow with --download-files or --file.
  #
  # List:
  #   - --list defaults to .safetensors
  #   - --list --list-files "zip json" shows .safetensors + .zip + .json (etc)

  local model_id=""
  local outdir="."
  local version_id=""
  local want_file=""
  local mode="download"
  local sanitize="${CIVITAI_SANITIZE:-0}"
  local quiet=0
  local urn_id=""

  local list_files=""           # e.g. "zip json"
  local download_files=""       # e.g. "zip json safetensors"
  local explicit_version=0      # set when URN had @ or user passed --version
  local strict=0
  local interactive=0
  [[ $- == *i* ]] && interactive=1

  _usage() {
    cat <<'EOF'
usage:
  civitai --list <model_id> [--list-files "zip json"] [--quiet]
  civitai <model_id> [--out DIR] [--version ID] [--file NAME] [--download-files "zip json"] [--sanitize] [--quiet]
  civitai --id <civitai_urn> [--out DIR] [--file NAME] [--download-files "zip json"] [--sanitize] [--quiet]
  civitai <civitai_urn> [--out DIR] [--file NAME] [--download-files "zip json"] [--sanitize] [--quiet]

options:
  --list                  List available files grouped by version (defaults: .safetensors)
  --list-files "exts"     Extra extensions to include in --list (space-separated, no dots)
                          Example: --list-files "zip json"

  --id, -id URN           CivitAI URN (e.g. urn:air:sdxl:checkpoint:civitai:1837476@2607296)
  --out DIR               Output directory (default: .)
  --version ID            Force modelVersionId (also makes download default to ALL files in that version)
  --file NAME             Download only this exact filename (overrides extension filtering)

  --download-files "exts" Extra extensions to include in download when not explicitly version-pinned.
                          Example: --download-files "zip json"
                          Note: if you explicitly pin a version (URN @ or --version), default is ALL files anyway.

  --sanitize              Replace spaces with underscores
  --quiet                 Less output
  --strict                In interactive shells, return non-zero on errors (otherwise errors return 0 to avoid killing SSH)
  --help                  Show this help

env:
  CIVITAI_TOKEN           Required for downloads (not for --list)

examples:
  civitai --list 139562
  civitai --list 139562 --list-files "zip json"

  civitai 139562 --out "$COMFY/models/checkpoints"
  civitai 139562 --out "$COMFY/models/checkpoints" --version 798204  # downloads ALL files in that version
  civitai 139562 --out "$COMFY/models/checkpoints" --download-files "zip json"
  civitai 139562 --out "$COMFY/models/checkpoints" --version 798204 --file some_bundle.zip

  civitai --id urn:air:sdxl:checkpoint:civitai:1837476@2607296 --out "$COMFY/models/checkpoints"
EOF
  }

  _fail() {
    local rc="$1"; shift
    echo "ERROR: $*" >&2
    # In interactive shells, avoid killing session if user has `set -e`, unless --strict.
    if [[ "$interactive" == 1 && "$strict" == 0 ]]; then
      return 0
    fi
    return "$rc"
  }

  _parse_urn() {
    # Extract model_id + (optional) version_id from a civitai URN.
    # Accepts @ or %40 for version separator.
    local urn="$1"

    # Trim whitespace + CR (copy/paste)
    urn="${urn//$'\r'/}"
    urn="${urn#"${urn%%[![:space:]]*}"}"
    urn="${urn%"${urn##*[![:space:]]}"}"

    if [[ "$urn" =~ civitai:([0-9]+)((@|%40)([0-9]+))? ]]; then
      model_id="${BASH_REMATCH[1]}"
      local vid="${BASH_REMATCH[4]}"

      if [[ -n "$vid" ]]; then
        explicit_version=1
        # Only set version_id from URN if user didn't explicitly provide --version
        if [[ -z "$version_id" ]]; then
          version_id="$vid"
        fi
      fi
      return 0
    fi

    return 1
  }

  _ext_regex_from_list() {
    # Build a regex for file extensions from:
    #  - always includes safetensors
    #  - plus extra exts provided as space-separated tokens, no dots
    # Output example: \.(safetensors|zip|json)$
    local extra="$1"
    local tok
    local exts="safetensors"

    for tok in $extra; do
      tok="${tok#.}"
      tok="${tok,,}"
      [[ -z "$tok" ]] && continue
      # basic validation: letters/numbers only
      if [[ "$tok" =~ ^[a-z0-9]+$ ]]; then
        exts="$exts|$tok"
      fi
    done

    printf '\\.(%s)$' "$exts"
  }

  # ---------- pre-scan: allow URN as first arg (positional) ----------
  if [[ $# -gt 0 ]]; then
    case "$1" in
      urn:air:*|*":civitai:"*)
        urn_id="$1"
        shift
        ;;
    esac
  fi

  # ---------- parse args (order independent) ----------
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --list)
        mode="list"
        shift
        ;;
      --list-files)
        list_files="$2"
        shift 2
        ;;
      --download-files)
        download_files="$2"
        shift 2
        ;;
      --id|-id)
        urn_id="$2"
        shift 2
        ;;
      --out)
        outdir="$2"
        shift 2
        ;;
      --version)
        version_id="$2"
        explicit_version=1
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
      --strict)
        strict=1
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
        if [[ -z "$model_id" ]]; then
          if [[ "$1" == urn:air:* || "$1" == *":civitai:"* ]]; then
            urn_id="$1"
          else
            model_id="$1"
          fi
        else
          echo "ERROR: unexpected argument: $1" >&2
          _usage
          return 2
        fi
        shift
        ;;
    esac
  done

  # ---------- if URN provided, extract model/version ----------
  if [[ -n "$urn_id" ]]; then
    _parse_urn "$urn_id" || { _fail 2 "invalid civitai URN: $urn_id"; return $?; }
  fi

  if [[ -z "$model_id" ]]; then
    echo "ERROR: missing model_id" >&2
    _usage
    return 2
  fi

  # ---------- deps ----------
  need_apt curl || { _fail 127 "curl is required but could not be installed"; return $?; }
  need_apt jq   || { _fail 127 "jq is required but could not be installed"; return $?; }

  # ---------- fetch metadata once ----------
  local json
  json="$(curl -fsSL "https://civitai.com/api/v1/models/${model_id}")" \
    || { _fail 1 "failed to fetch model metadata for id=${model_id}"; return $?; }
  [[ -z "$json" ]] && { _fail 1 "empty response fetching model metadata for id=${model_id}"; return $?; }

  # ---------- LIST MODE ----------
  if [[ "$mode" == "list" ]]; then
    local rx
    rx="$(_ext_regex_from_list "$list_files")"

    # Show versions newest-first, and only matching files by extension.
    jq -r --arg rx "$rx" '
      .modelVersions
      | map(. + { _sort: (.publishedAt // .createdAt // "1970-01-01T00:00:00.000Z") })
      | sort_by(._sort) | reverse
      | .[]
      | "Version: \(.id)  |  \(.name)  |  \(.publishedAt // .createdAt // "unknown")",
        (
          .files
          | map(select(.name | test($rx; "i")))
          | map(.name)
          | unique
          | if length == 0 then "  (no matching files)"
            else .[] | "  - " + .
            end
        ),
        ""
    ' <<<"$json"
    return 0
  fi

  # ---------- DOWNLOAD MODE ----------
  if [[ -z "${CIVITAI_TOKEN:-}" ]]; then
    _fail 2 "CIVITAI_TOKEN is not set (required for downloads)"; return $?
  fi

  mkdir -p "$outdir" 2>/dev/null || { _fail 1 "cannot create outdir: $outdir"; return $?; }

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
    _fail 1 "could not determine modelVersionId"; return $?
  fi

  [[ "$quiet" != 1 ]] && {
    echo "[civitai] model_id=${model_id} modelVersionId=${chosen_vid}"
    [[ -n "$urn_id" ]] && echo "[civitai] urn=${urn_id}"
    echo "[civitai] outdir=${outdir}"
  }

  # Decide what to include by default:
  # - If want_file is set: download exactly that file.
  # - Else if explicit_version: download ALL files in that version.
  # - Else: download .safetensors + any --download-files extras.
  local rx=""
  if [[ -z "$want_file" ]]; then
    if [[ "$explicit_version" == 1 ]]; then
      rx=".*"  # ALL files
    else
      rx="$(_ext_regex_from_list "$download_files")"
    fi
  fi

  # Build manifest: name + downloadUrl
  local manifest
  if [[ -n "$want_file" ]]; then
    manifest="$(
      jq -r --argjson vid "$chosen_vid" --arg want "$want_file" '
        .modelVersions
        | map(select(.id == $vid))
        | .[0].files
        | map(select(.name == $want))
        | map({name:.name, url:.downloadUrl})
        | unique_by(.name + "\u0000" + .url)
        | .[]
        | "\(.name)\t\(.url)"
      ' <<<"$json"
    )"
  else
    manifest="$(
      jq -r --argjson vid "$chosen_vid" --arg rx "$rx" '
        .modelVersions
        | map(select(.id == $vid))
        | .[0].files
        | map(select(.name | test($rx; "i")))
        | map({name:.name, url:.downloadUrl})
        | unique_by(.name + "\u0000" + .url)
        | .[]
        | "\(.name)\t\(.url)"
      ' <<<"$json"
    )"
  fi

  if [[ -z "$manifest" ]]; then
    if [[ -n "$want_file" ]]; then
      _fail 3 "file not found in version ${chosen_vid}: $want_file"; return $?
    fi
    echo "WARNING: no matching files found" >&2
    return 0
  fi

  # Download loop
  local name url outname outpath
  while IFS=$'\t' read -r name url; do
    [[ -z "$name" || -z "$url" ]] && continue

    outname="$name"
    [[ "$sanitize" == 1 ]] && outname="${outname// /_}"
    outpath="${outdir%/}/$outname"

    [[ "$quiet" != 1 ]] && echo "[civitai] -> $outpath"

    curl -fL \
      -H "Authorization: Bearer ${CIVITAI_TOKEN}" \
      "$url" \
      -o "$outpath" || { _fail 4 "download failed for $name"; return $?; }
  done <<<"$manifest"

  [[ "$quiet" != 1 ]] && echo "[civitai] done"
  return 0
}

# ---------------------------
# Google Drive folder downloader
# ---------------------------
_extract_gdrive_folder_id() {
  # pulls the folder id out of typical URLs:
  # https://drive.google.com/drive/folders/<ID>?usp=...
  local url="$1"
  local id=""
  id="$(sed -nE 's#.*drive\.google\.com/drive/folders/([^?/]+).*#\1#p' <<<"$url")"
  [[ -n "$id" ]] || id="$(sed -nE 's#.*folders/([^?/]+).*#\1#p' <<<"$url")"
  printf "%s" "$id"
}

download_gdrive_folder() {
  # NEW DEFAULT: keep everything inside ONE wrapper folder in target
  # so downloads never “flatten” into /models unless you request --flatten.
  #
  # usage:
  #   download_gdrive_folder <url> <target_parent_dir>              # creates target_parent_dir/gdrive_<id>/
  #   download_gdrive_folder --top-name BiRefNet <url> <target_parent_dir>  # creates .../BiRefNet/
  #   download_gdrive_folder --flatten <url> <target_dir>            # moves items directly into target_dir

  local mode="wrap"     # wrap | flatten
  local url=""
  local target=""
  local top_name=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --flatten)
        mode="flatten"
        shift
        ;;
      --top-name)
        top_name="$2"
        shift 2
        ;;
      --help|-h)
        cat <<'EOF'
usage:
  download_gdrive_folder <url> <target_parent_dir>
  download_gdrive_folder --top-name NAME <url> <target_parent_dir>
  download_gdrive_folder --flatten <url> <target_dir>

default:
  Creates a single wrapper folder inside <target_parent_dir> and moves everything into it.
  This prevents “flattening” into ComfyUI/models by accident.

--flatten:
  Moves contents directly into target (only when explicitly required).
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

  if [[ "$mode" == "flatten" ]]; then
    echo "[gdown] flattening into: $target"
    # Move everything downloaded into target dir
    shopt -s dotglob nullglob
    mv "$tmp"/* "$target"/
    shopt -u dotglob nullglob
    rm -rf "$tmp"
    echo "[gdown] done"
    return 0
  fi

  # WRAP mode: create deterministic wrapper folder
  if [[ -z "$top_name" ]]; then
    local fid
    fid="$(_extract_gdrive_folder_id "$url")"
    if [[ -n "$fid" ]]; then
      top_name="gdrive_${fid}"
    else
      top_name="gdrive_$(date +%Y%m%d_%H%M%S)"
    fi
  fi

  local outdir="${target%/}/${top_name}"
  mkdir -p "$outdir" || {
    echo "ERROR: cannot create outdir: $outdir" >&2
    rm -rf "$tmp"
    return 1
  }

  echo "[gdown] wrapping into: $outdir"
  shopt -s dotglob nullglob
  mv "$tmp"/* "$outdir"/
  shopt -u dotglob nullglob
  rm -rf "$tmp"
  echo "[gdown] done (wrapped)"
}


log_if_exists() {
  local path="$1"
  local source="${2:-unknown}"
  local ref="${3:-}"
  if [[ -f "$path" ]]; then manifest_add_file "$path" "$source" "$ref"; fi
  if [[ -d "$path" ]]; then manifest_add_dir  "$path" "$source" "$ref"; fi
}

# ---------------------------
# Manifest logging
# ---------------------------
manifest_init() {
  # usage: manifest_init <workflow_slug> [manifest_dir]
  local wf="${1:-}"
  local dir="${2:-/workspace/manifests}"
  [[ -n "$wf" ]] || { echo "usage: manifest_init <workflow_slug> [manifest_dir]" >&2; return 2; }

  mkdir -p "$dir" 2>/dev/null || true
  export WF_SLUG="$wf"
  export WF_MANIFEST="$dir/${wf}_downloads.jsonl"
  echo "[manifest] WF_SLUG=$WF_SLUG"
  echo "[manifest] WF_MANIFEST=$WF_MANIFEST"
}

manifest_log_path() {
  # usage: manifest_log_path <kind:file|dir> <path> <source> <ref> [extra_json]
  local kind="$1"
  local path="$2"
  local source="$3"   # hf|civitai|gdrive|manual
  local ref="$4"      # repo_id+path, model_id, url, etc
  local extra="${5:-{}}"

  [[ -n "${WF_MANIFEST:-}" ]] || { echo "ERROR: WF_MANIFEST not set (run manifest_init)" >&2; return 2; }

  local size=0
  if [[ "$kind" == "file" && -f "$path" ]]; then
    size="$(stat -c '%s' "$path" 2>/dev/null || echo 0)"
  elif [[ "$kind" == "dir" && -d "$path" ]]; then
    size="$(du -sb "$path" 2>/dev/null | awk '{print $1}' || echo 0)"
  fi

  # optional hash for files (expensive on multi-GB; toggle with MANIFEST_SHA=1)
  local sha="null"
  if [[ "${MANIFEST_SHA:-0}" == "1" && "$kind" == "file" && -f "$path" && -x "$(command -v sha256sum)" ]]; then
    sha="\"$(sha256sum "$path" | awk '{print $1}')\""
  fi

  printf '{"ts":"%s","workflow":"%s","kind":"%s","source":"%s","ref":"%s","path":"%s","bytes":%s,"sha256":%s,"extra":%s}\n' \
    "$(date -Is)" \
    "${WF_SLUG:-unknown}" \
    "$kind" \
    "$source" \
    "$(printf '%s' "$ref" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$path" | sed 's/"/\\"/g')" \
    "$size" \
    "$sha" \
    "$extra" >>"$WF_MANIFEST"
}

manifest_add_file() {
  local path="$1"
  local source="${2:-unknown}"   # hf|civitai|gdrive|manual
  local ref="${3:-}"
  [[ -n "${WF_MANIFEST:-}" ]] || { echo "ERROR: WF_MANIFEST not set (run manifest_init)"; return 2; }

  [[ -f "$path" ]] || { echo "WARN: manifest_add_file: not a file: $path" >&2; return 1; }
  local bytes; bytes="$(stat -c '%s' "$path" 2>/dev/null || echo 0)"

  printf '{"ts":"%s","workflow":"%s","kind":"file","source":"%s","ref":"%s","path":"%s","bytes":%s}\n' \
    "$(date -Is)" "${WF_SLUG:-unknown}" "$source" \
    "$(printf '%s' "$ref" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$path" | sed 's/"/\\"/g')" \
    "$bytes" >>"$WF_MANIFEST"
}

manifest_add_dir() {
  local path="$1"
  local source="${2:-unknown}"
  local ref="${3:-}"
  [[ -n "${WF_MANIFEST:-}" ]] || { echo "ERROR: WF_MANIFEST not set (run manifest_init)"; return 2; }

  [[ -d "$path" ]] || { echo "WARN: manifest_add_dir: not a dir: $path" >&2; return 1; }
  local bytes; bytes="$(du -sb "$path" 2>/dev/null | awk '{print $1}' || echo 0)"

  printf '{"ts":"%s","workflow":"%s","kind":"dir","source":"%s","ref":"%s","path":"%s","bytes":%s}\n' \
    "$(date -Is)" "${WF_SLUG:-unknown}" "$source" \
    "$(printf '%s' "$ref" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$path" | sed 's/"/\\"/g')" \
    "$bytes" >>"$WF_MANIFEST"
}

manifest_prune() {
  # usage: manifest_prune <manifest_file>
  local mf="$1"
  [[ -f "$mf" ]] || { echo "ERROR: manifest not found: $mf" >&2; return 2; }

  echo "[prune] reading: $mf"
  jq -r 'select(.kind=="file") | .path' "$mf" | while read -r p; do
    [[ -n "$p" ]] || continue
    if [[ -f "$p" ]]; then
      echo "[rm] $p"
      rm -f "$p"
    fi
  done

  jq -r 'select(.kind=="dir") | .path' "$mf" \
    | awk '{ print length($0) "\t" $0 }' | sort -rn | cut -f2- \
    | while read -r d; do
      [[ -n "$d" ]] || continue
      if [[ -d "$d" ]]; then
        echo "[rm -rf] $d"
        rm -rf "$d"
      fi
    done

  echo "[prune] done"
}

rm_logged() {
  # usage: rm_logged <path>...
  for p in "$@"; do
    [[ -e "$p" ]] || continue
    echo "[rm] $p"
    rm -rf "$p"
  done
}

mv_logged() {
  # usage: mv_logged <src> <dst> [--source hf] [--ref "repo:path"]
  local src="$1"
  local dst="$2"
  shift 2

  local source="unknown"
  local ref=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --source) source="$2"; shift 2 ;;
      --ref) ref="$2"; shift 2 ;;
      *) break ;;
    esac
  done

  mv -f "$src" "$dst" || return $?

  if [[ -f "$dst" ]]; then
    manifest_add_file "$dst" "$source" "$ref"
  elif [[ -d "$dst" ]]; then
    manifest_add_dir "$dst" "$source" "$ref"
  fi
}

# Logged wrapper: create wrapper folder then log it (robust, no guessing)
gdrive_folder_logged() {
  # usage:
  #   gdrive_folder_logged <url> <target_parent_dir> [--top-name NAME]
  local url="$1"
  local target="$2"
  shift 2 || true

  local top_name=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --top-name) top_name="$2"; shift 2 ;;
      *) break ;;
    esac
  done

  download_gdrive_folder ${top_name:+--top-name "$top_name"} "$url" "$target" || return $?

  # Determine the folder we created (same logic as download_gdrive_folder)
  if [[ -z "$top_name" ]]; then
    local fid
    fid="$(_extract_gdrive_folder_id "$url")"
    if [[ -n "$fid" ]]; then
      top_name="gdrive_${fid}"
    else
      # fallback: can't reliably detect; log target itself
      manifest_log_path dir "$target" gdrive "$url" "{\"note\":\"wrapped_but_name_unknown\"}"
      return 0
    fi
  fi

  local outdir="${target%/}/${top_name}"
  if [[ -d "$outdir" ]]; then
    manifest_log_path dir "$outdir" gdrive "$url" "{}"
  else
    manifest_log_path dir "$target" gdrive "$url" "{\"note\":\"expected_wrapper_missing\",\"expected\":\"$outdir\"}"
  fi
}

hf_download_logged() {
  # usage: hf_download_logged <repo_id> [hf args...]
  local repo="$1"; shift
  local out
  out="$(hf download "$repo" "$@" 2>&1)"
  local rc=$?
  echo "$out"
  [[ $rc -eq 0 ]] || return $rc

  # log any absolute paths printed by hf
  # (hf usually prints one path per line, often absolute)
  while IFS= read -r line; do
    if [[ "$line" == /* && ( -f "$line" || -d "$line" ) ]]; then
      if [[ -f "$line" ]]; then
        manifest_log_path file "$line" hf "$repo" "{}"
      else
        manifest_log_path dir "$line" hf "$repo" "{}"
      fi
    fi
  done <<<"$out"

  return 0
}

# Logged wrapper: create wrapper folder then log it (robust, no guessing)
gdrive_folder_logged() {
  # usage:
  #   gdrive_folder_logged <url> <target_parent_dir> [--top-name NAME]
  local url="$1"
  local target="$2"
  shift 2 || true

  local top_name=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --top-name) top_name="$2"; shift 2 ;;
      *) break ;;
    esac
  done

  download_gdrive_folder ${top_name:+--top-name "$top_name"} "$url" "$target" || return $?

  # Determine the folder we created (same logic as download_gdrive_folder)
  if [[ -z "$top_name" ]]; then
    local fid
    fid="$(_extract_gdrive_folder_id "$url")"
    if [[ -n "$fid" ]]; then
      top_name="gdrive_${fid}"
    else
      # fallback: can't reliably detect; log target itself
      manifest_log_path dir "$target" gdrive "$url" "{\"note\":\"wrapped_but_name_unknown\"}"
      return 0
    fi
  fi

  local outdir="${target%/}/${top_name}"
  if [[ -d "$outdir" ]]; then
    manifest_log_path dir "$outdir" gdrive "$url" "{}"
  else
    manifest_log_path dir "$target" gdrive "$url" "{\"note\":\"expected_wrapper_missing\",\"expected\":\"$outdir\"}"
  fi
}

civitai_logged() {
  # usage: civitai_logged <model_id> --out DIR [other civitai args...]
  local model_id="$1"; shift

  # extract --out DIR from args (so we can scan it)
  local outdir="."
  local args=("$@")
  for ((i=0; i<${#args[@]}; i++)); do
    if [[ "${args[$i]}" == "--out" && $((i+1)) -lt ${#args[@]} ]]; then
      outdir="${args[$((i+1))]}"
      break
    fi
  done

  mkdir -p "$outdir" 2>/dev/null || true
  local before
  before="$(find "$outdir" -maxdepth 1 -type f -name '*.safetensors' -printf '%f\n' 2>/dev/null | sort)"

  civitai "$model_id" "$@" || return $?

  local after
  after="$(find "$outdir" -maxdepth 1 -type f -name '*.safetensors' -printf '%f\n' 2>/dev/null | sort)"

  # diff to find new files
  comm -13 <(printf "%s\n" "$before") <(printf "%s\n" "$after") | while read -r fn; do
    [[ -n "$fn" ]] || continue
    manifest_log_path file "$outdir/$fn" civitai "model:${model_id}" "{}"
  done
}

install_gdrive_folder_as() {
  # usage: install_gdrive_folder_as <gdrive_folder_url> <dest_parent_dir> <name>
  # result: <dest_parent_dir>/<name>/...
  local url="$1"
  local parent="$2"
  local name="$3"

  [[ -n "$url" && -n "$parent" && -n "$name" ]] || {
    echo "usage: install_gdrive_folder_as <url> <dest_parent_dir> <name>" >&2
    return 2
  }

  need_apt gdown gdown || return 127

  local tmp; tmp="$(mktemp -d)"
  echo "[gdown] downloading into temp: $tmp"
  gdown --folder "$url" -O "$tmp" || { rm -rf "$tmp"; return 1; }

  mkdir -p "$parent" || { rm -rf "$tmp"; return 1; }

  # What did we get at top level?
  mapfile -t top_items < <(find "$tmp" -mindepth 1 -maxdepth 1)

  if [[ "${#top_items[@]}" -eq 0 ]]; then
    echo "ERROR: nothing downloaded?" >&2
    rm -rf "$tmp"
    return 1
  fi

  local dest="$parent/$name"
  rm -rf "$dest" 2>/dev/null || true
  mkdir -p "$dest"

  if [[ "${#top_items[@]}" -eq 1 && -d "${top_items[0]}" ]]; then
    # single folder: move its contents into dest (avoids double nesting)
    echo "[gdown] single folder detected; installing contents into: $dest"
    mv "${top_items[0]}"/* "$dest"/ 2>/dev/null || true
  else
    # many items: move them all under dest
    echo "[gdown] multiple top-level items; installing into: $dest"
    mv "$tmp"/* "$dest"/
  fi

  rm -rf "$tmp"
  echo "[gdown] done -> $dest"

  # Print the final path (useful for logging)
  printf '%s\n' "$dest"
}

hf_download_from_manifest() {
  _helpers_need curl; _helpers_need jq; _helpers_need awk
  _helpers_need hf

  # Optional arg: manifest source; if empty, fall back to MODEL_MANIFEST_URL.
  # Source can be:
  #   - local file path (JSON)
  #   - URL (http/https)
  local src="${1:-${MODEL_MANIFEST_URL:-}}"
  if [[ -z "$src" ]]; then
    echo "hf_download_from_manifest: no manifest source given and MODEL_MANIFEST_URL is not set." >&2
    return 1
  fi

  local MAN tmp=""
  if [[ -f "$src" ]]; then
    MAN="$src"
  else
    MAN="$(mktemp)"
    tmp="$MAN"
    if ! curl -fsSL "$src" -o "$MAN"; then
      echo "hf_download_from_manifest: failed to fetch manifest: $src" >&2
      rm -f "$tmp"
      return 1
    fi
  fi

  # ---- (Optional but useful) export manifest vars/paths into env if not already set ----
  # This makes {COMFY_HOME}, {DIFFUSION_MODELS_DIR}, etc resolvable even if caller didn't export them.
  # Two-pass: vars first, then paths (paths may reference vars).
  _hf_manifest_export_kv_block() {
    local jq_expr="$1"
    jq -r "$jq_expr" "$MAN" | while IFS=$'\t' read -r k v; do
      [[ -z "$k" ]] && continue
      [[ "$k" =~ ^[A-Z0-9_]+$ ]] || continue
      # don't overwrite existing env
      if [[ -z "${!k+x}" ]]; then
        # resolve any {TOKENS} inside the value
        local vv
        vv="$(helpers_resolve_placeholders "$v")" || vv="$v"
        export "$k=$vv"
      fi
    done
  }

  _hf_manifest_export_kv_block '.vars  // {} | to_entries[] | [.key, (.value|tostring)] | @tsv'
  _hf_manifest_export_kv_block '.paths // {} | to_entries[] | [.key, (.value|tostring)] | @tsv'

  # ---- find enabled sections (matches aria2_download_from_manifest logic) ----
  local SECTIONS_ALL ENABLED sec dl_var
  SECTIONS_ALL="$(jq -r '.sections | keys[]' "$MAN")"
  ENABLED=()
  while read -r sec; do
    dl_var="download_${sec}"
    if [[ "${!sec:-}" == "true" || "${!sec:-}" == "1" || \
          "${!dl_var:-}" == "true" || "${!dl_var:-}" == "1" ]]; then
      ENABLED+=("$sec")
    fi
  done <<<"$SECTIONS_ALL"

  if ((${#ENABLED[@]} == 0)); then
    echo "hf_download_from_manifest: no sections enabled in manifest '$src'." >&2
    echo 0
    [[ -n "$tmp" ]] && rm -f "$tmp"
    return 0
  fi
  mapfile -t ENABLED < <(printf '%s\n' "${ENABLED[@]}" | awk '!seen[$0]++')

  # ---- helper: parse HF URL into repo_id, revision, repo_file_path ----
  _hf_parse_url() {
    local url="$1"
    local p org repo mode rev rest

    p="${url#https://huggingface.co/}"
    p="${p#http://huggingface.co/}"

    IFS='/' read -r org repo mode rev rest <<<"$p"

    if [[ -z "$org" || -z "$repo" || -z "$mode" || -z "$rev" || -z "$rest" ]]; then
      return 1
    fi

    # mode usually: resolve|blob|raw
    # rev: main|<commit_sha>|<tag>
    # rest: path/to/file.ext
    printf '%s\t%s\t%s\n' "${org}/${repo}" "$rev" "$rest"
  }

  # ---- helper: download ONE entry via hf download into temp dir then move to desired path ----
  _hf_manifest_download_one() {
    local url="$1" raw_path="$2"
    local path dir out
    local repo_id rev repo_file
    local tmpdir srcfile

    path="$(helpers_resolve_placeholders "$raw_path")" || return 1
    dir="$(dirname -- "$path")"
    out="$(basename -- "$path")"
    mkdir -p -- "$dir"

    if [[ -f "$path" ]]; then
      echo " - ⏭️ SKIPPING: $out (file exists)" >&2
      return 2   # special: skipped
    fi

    local parsed
    if ! parsed="$(_hf_parse_url "$url")"; then
      echo "ERROR: Could not parse HF URL: $url" >&2
      return 1
    fi
    IFS=$'\t' read -r repo_id rev repo_file <<<"$parsed"

    # Encourage hf_transfer if available
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}"

    # temp download dir (keeps your model dirs clean even when repo_file has subfolders)
    tmpdir="$(mktemp -d -p "$dir" ".hf_tmp_${out}.XXXXXX")" || return 1

    echo " - 📥 Download: $out" >&2
    # NOTE: repo_file may contain slashes; hf download will create those dirs under tmpdir.
    if ! hf download "$repo_id" "$repo_file" --revision "$rev" --local-dir "$tmpdir"; then
      echo "ERROR: hf download failed for $repo_id@$rev:$repo_file" >&2
      rm -rf -- "$tmpdir"
      return 1
    fi

    srcfile="$tmpdir/$repo_file"
    if [[ ! -f "$srcfile" ]]; then
      # fallback: locate by basename if hf moved/linked unexpectedly
      srcfile="$(find "$tmpdir" -type f -name "$out" -print -quit 2>/dev/null || true)"
    fi
    if [[ ! -f "$srcfile" ]]; then
      echo "ERROR: Download succeeded but could not locate file under temp dir for: $out" >&2
      rm -rf -- "$tmpdir"
      return 1
    fi

    # Move into final flattened destination
    mv -f -- "$srcfile" "$path"
    rm -rf -- "$tmpdir"
    return 0
  }

  # ---- parallel job control ----
  local max_jobs="${HF_MANIFEST_JOBS:-2}"
  [[ "$max_jobs" =~ ^[0-9]+$ ]] || max_jobs=2
  (( max_jobs < 1 )) && max_jobs=1

  local any=0
  local failures=0

  for sec in "${ENABLED[@]}"; do
    echo ">>> Download section: $sec" >&2

    local tsv
    tsv="$(
      jq -r --arg sec "$sec" '
        def as_obj:
          if   type=="object" then {url:(.url//""), path:(.path // ((.dir // "") + (if .out then "/" + .out else "" end)))}
          elif type=="array"  then {url:(.[0]//""), path:(.[1]//"")}
          elif type=="string" then {url:., path:""}
          else {url:"", path:""} end;
        (.sections[$sec] // [])[] | as_obj | select(.url|length>0)
        | [.url, (if (.path|length)>0 then .path else (.url|sub("^.*/";"")) end)] | @tsv
      ' "$MAN"
    )"

    [[ -z "$tsv" ]] && continue

    while IFS=$'\t' read -r url raw_path; do
      # throttle
      while (( $(jobs -rp | wc -l) >= max_jobs )); do
        sleep 0.2
      done

      (
        _hf_manifest_download_one "$url" "$raw_path"
        rc=$?
        # 0 = downloaded, 2 = skipped, else = failure
        exit "$rc"
      ) &

      any=1
    done <<<"$tsv"
  done

  # wait for all jobs, count failures (ignore skips=2)
  local pid rc
  for pid in $(jobs -rp); do
    if wait "$pid"; then
      :
    else
      rc=$?
      if [[ "$rc" -ne 2 ]]; then
        failures=$((failures+1))
      fi
    fi
  done

  [[ -n "$tmp" ]] && rm -f "$tmp"

  if [[ "$any" == "0" ]]; then
    echo "hf_download_from_manifest: nothing new to download from '$src'." >&2
  fi

  if (( failures > 0 )); then
    echo "hf_download_from_manifest: completed with $failures failure(s)." >&2
    printf '%s\n' "$any"
    return 1
  fi

  printf '%s\n' "$any"
  return 0
}
