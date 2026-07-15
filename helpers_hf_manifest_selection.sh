#!/usr/bin/env bash
# Compatibility and reporting layer for the background HF manifest downloader.
# Bash users commonly set manifest flags without `export`; the Python planner
# must receive those values explicitly.

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

_hf_manifest_export_selection() {
  local manifest="${1:?manifest}"
  local section legacy value
  local -a matched=()
  local -a unmatched_true=()

  while IFS= read -r section; do
    [[ -n "$section" ]] || continue
    legacy="download_${section}"
    value=""

    # Check ordinary Bash variables as well as exported environment values.
    if [[ -n "${!section+x}" ]]; then
      value="${!section}"
    elif [[ -n "${!legacy+x}" ]]; then
      value="${!legacy}"
    fi

    if _hf_manifest_selection_true "$value"; then
      export "$section=true"
      matched+=("$section")
    fi
  done < <(jq -r '.sections // {} | keys[]' "$manifest" 2>/dev/null)

  # Identify true-looking download_* variables that do not match a manifest tag.
  local var
  while IFS= read -r var; do
    [[ "$var" == download_* ]] || continue
    _hf_manifest_selection_true "${!var:-}" || continue
    if ! jq -e --arg key "$var" '.sections[$key] != null' "$manifest" >/dev/null 2>&1; then
      unmatched_true+=("$var")
    fi
  done < <(compgen -v)

  if ((${#matched[@]} == 0)); then
    echo "[hf-manifest] No matching enabled sections in manifest." >&2
    echo "[hf-manifest] Set one or more manifest tags to true, for example: download_wan22_svi_lite=true" >&2
    if ((${#unmatched_true[@]} > 0)); then
      echo "[hf-manifest] True variables with no exact manifest match: ${unmatched_true[*]}" >&2
    fi
    echo "[hf-manifest] Available section count: $(jq -r '.sections // {} | length' "$manifest" 2>/dev/null || echo 0)" >&2
    return 0
  fi

  echo "[hf-manifest] Enabled sections (${#matched[@]}): ${matched[*]}" >&2
  for section in "${matched[@]}"; do
    echo "[hf-manifest]   tag=$section entries=$(jq -r --arg s "$section" '(.sections[$s] // []) | length' "$manifest")" >&2
  done
}

# Preserve the original Python planner and export Bash-only flags before it runs.
if declare -F _hf_manifest_plan >/dev/null 2>&1 \
   && ! declare -F _hf_manifest_plan_backend >/dev/null 2>&1; then
  eval "$(declare -f _hf_manifest_plan \
    | sed '1s/^_hf_manifest_plan[[:space:]]*()/_hf_manifest_plan_backend ()/')"
fi

_hf_manifest_plan() {
  local manifest="${1:?manifest}" state="${2:?state}"
  _hf_manifest_export_selection "$manifest"
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
      echo "[hf-manifest]   📥 queue tag=$section file=$name -> $path" >&2
      queued=$((queued + 1))
    elif [[ "$status" == "completed" ]]; then
      present=$((present + 1))
    fi
  done <"$state/items.list"

  echo "[hf-manifest] Queue detail: new=$queued already-present=$present" >&2
}

# Preserve the public downloader and append a detailed plan report.
if declare -F hf_download_from_manifest >/dev/null 2>&1 \
   && ! declare -F _hf_download_from_manifest_backend >/dev/null 2>&1; then
  eval "$(declare -f hf_download_from_manifest \
    | sed '1s/^hf_download_from_manifest[[:space:]]*()/_hf_download_from_manifest_backend ()/')"
fi

hf_download_from_manifest() {
  local src="${1:-${MODEL_MANIFEST_URL:-}}"
  local state
  state="$(_hf_manifest_state_dir "${2:-}")"

  _hf_download_from_manifest_backend "$@"
  local rc=$?

  [[ -d "$state" ]] && _hf_manifest_print_plan_items "$state"
  return "$rc"
}
