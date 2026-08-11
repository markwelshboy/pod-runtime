#!/usr/bin/env bash
# Explicit selection and reporting layer for the background HF manifest downloader.
#
# Public configuration is family-oriented:
#   HF_BASE_DOWNLOADS=wan22,krea
#   HF_LORA_DOWNLOADS=wan22,krea
#
# Startup resolves those to exact manifest sections (wan22_base, krea_base,
# wan22_loras, krea_loras) and passes the resulting CSV to
# hf_download_from_manifest as its third argument. Per-section download_* flags
# are intentionally no longer a supported interface.

if [[ -n "${__HF_MANIFEST_SELECTION_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
__HF_MANIFEST_SELECTION_LOADED=1

_hf_manifest_selection_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_hf_manifest_split_csv() {
  local raw="${1:-}"
  raw="${raw//,/ }"
  local token
  for token in $raw; do
    token="${token//[[:space:]]/}"
    [[ -n "$token" ]] && printf '%s\n' "$token"
  done
}

hf_manifest_sections_for_families() {
  local manifest_source="${1:-}" families="${2:-}" suffix="${3:?suffix}"
  [[ "$suffix" == "base" || "$suffix" == "loras" ]] || {
    echo "[hf-manifest] Invalid family suffix '$suffix'; expected base or loras." >&2
    return 2
  }

  local family section
  local -a resolved=()
  declare -A seen=()

  while IFS= read -r family; do
    [[ -n "$family" ]] || continue
    family="${family,,}"
    [[ "$family" =~ ^[a-z0-9_]+$ ]] || {
      echo "[hf-manifest] Invalid family '$family'. Use letters, numbers, and underscores only." >&2
      return 2
    }
    section="${family}_${suffix}"

    # If the caller supplied an already-local manifest, fail early on a typo.
    # Normal RunPod startup uses a remote MODEL_MANIFEST_URL, in which case the
    # exact section is validated after hf_download_from_manifest fetches it.
    if [[ -n "$manifest_source" && -f "$manifest_source" ]]; then
      command -v jq >/dev/null 2>&1 || {
        echo "[hf-manifest] jq is required to validate model families." >&2
        return 1
      }
      if ! jq -e --arg section "$section" '.sections[$section] != null' "$manifest_source" >/dev/null 2>&1; then
        echo "[hf-manifest] Requested family '$family' has no section '$section'." >&2
        echo "[hf-manifest] Available *_${suffix} sections:" >&2
        jq -r --arg suffix "_${suffix}" '.sections // {} | keys[] | select(endswith($suffix)) | "[hf-manifest]   " + .' "$manifest_source" >&2
        return 2
      fi
    fi

    [[ -n "${seen[$section]:-}" ]] && continue
    seen[$section]=1
    resolved+=("$section")
  done < <(_hf_manifest_split_csv "$families")

  if ((${#resolved[@]} == 0)); then
    printf '\n'
    return 0
  fi

  local IFS=,
  printf '%s\n' "${resolved[*]}"
}

_hf_manifest_clear_section_flags() {
  local manifest="${1:?manifest}"
  local section
  while IFS= read -r section; do
    [[ -n "$section" ]] || continue
    unset "$section" 2>/dev/null || true
    # Explicitly neutralize the old compatibility alias. This prevents a stale
    # download_<section>=true environment variable from selecting anything.
    unset "download_${section}" 2>/dev/null || true
  done < <(jq -r '.sections // {} | keys[]' "$manifest" 2>/dev/null)
}

_hf_manifest_export_selection() {
  local manifest="${1:?manifest}"
  local requested="${HF_MANIFEST_SECTIONS:-}"
  local section
  local -a matched=()

  _hf_manifest_clear_section_flags "$manifest"

  if [[ -z "${requested//[[:space:],]/}" ]]; then
    echo "[hf-manifest] No sections selected." >&2
    return 0
  fi

  while IFS= read -r section; do
    [[ -n "$section" ]] || continue
    if ! jq -e --arg section "$section" '.sections[$section] != null' "$manifest" >/dev/null 2>&1; then
      echo "[hf-manifest] Unknown requested section: $section" >&2
      echo "[hf-manifest] Available sections:" >&2
      jq -r '.sections // {} | keys[] | "[hf-manifest]   " + .' "$manifest" >&2
      return 2
    fi
    [[ "$section" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
      echo "[hf-manifest] Section '$section' is not a valid shell identifier." >&2
      return 2
    }
    export "$section=true"
    matched+=("$section")
  done < <(_hf_manifest_split_csv "$requested")

  echo "[hf-manifest] Selected sections (${#matched[@]}): ${matched[*]:-<none>}" >&2
  for section in "${matched[@]}"; do
    echo "[hf-manifest]   section=$section entries=$(jq -r --arg s "$section" '(.sections[$s] // []) | length' "$manifest")" >&2
  done
}

# Preserve the original Python planner and translate the explicit section list
# into the exact section flags expected by the existing planner/tree expander.
if declare -F _hf_manifest_plan >/dev/null 2>&1 \
   && ! declare -F _hf_manifest_plan_backend >/dev/null 2>&1; then
  eval "$(declare -f _hf_manifest_plan \
    | sed '1s/^_hf_manifest_plan[[:space:]]*()/_hf_manifest_plan_backend ()/')"
fi

_hf_manifest_plan() {
  local manifest="${1:?manifest}" state="${2:?state}"
  _hf_manifest_export_selection "$manifest" || return $?
  _hf_manifest_plan_backend "$manifest" "$state"
}

_hf_manifest_print_plan_items() {
  local state="${1:?state}"
  [[ -f "$state/items.list" ]] || return 0

  local item status section name path
  local queued=0 present=0
  while IFS= read -r item || [[ -n "$item" ]]; do
    [[ -f "$item" ]] || continue
    status="$(jq -r '.status // "unknown"' "$item")"
    section="$(jq -r '.section // "unknown"' "$item")"
    name="$(jq -r '.name // "unknown"' "$item")"
    path="$(jq -r '.path // ""' "$item")"
    if [[ "$status" == "pending" || "$status" == "running" ]]; then
      echo "[hf-manifest]   📥 queue section=$section file=$name -> $path" >&2
      queued=$((queued + 1))
    elif [[ "$status" == "completed" ]]; then
      present=$((present + 1))
    fi
  done <"$state/items.list"

  echo "[hf-manifest] Queue detail: new=$queued already-present=$present" >&2
}

# Preserve the public downloader, accept an explicit third argument containing
# a comma/space-separated section list, and append a detailed plan report.
if declare -F hf_download_from_manifest >/dev/null 2>&1 \
   && ! declare -F _hf_download_from_manifest_backend >/dev/null 2>&1; then
  eval "$(declare -f hf_download_from_manifest \
    | sed '1s/^hf_download_from_manifest[[:space:]]*()/_hf_download_from_manifest_backend ()/')"
fi

hf_download_from_manifest() {
  local src="${1:-${MODEL_MANIFEST_URL:-}}"
  local state
  state="$(_hf_manifest_state_dir "${2:-}")"
  local sections="${3:-${HF_MANIFEST_SECTIONS:-}}"
  local rc

  HF_MANIFEST_SECTIONS="$sections" _hf_download_from_manifest_backend "$src" "$state"
  rc=$?

  [[ -d "$state" ]] && _hf_manifest_print_plan_items "$state"
  return "$rc"
}
