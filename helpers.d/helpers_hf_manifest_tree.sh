#!/usr/bin/env bash
# Expand mode=tree Hugging Face manifest declarations into ordinary file items.

if [[ -n "${__HF_MANIFEST_TREE_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
__HF_MANIFEST_TREE_LOADED=1

_hf_manifest_tree_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
: "${HF_MANIFEST_TREE_EXPANDER:=${_hf_manifest_tree_root}/bin/hf_manifest_expand.py}"
export HF_MANIFEST_TREE_EXPANDER

_hf_manifest_expand_trees() {
  local manifest="${1:?manifest}" output="${2:?output}"
  local py
  py="$(_hf_manifest_python)" || {
    echo "[hf-manifest] No Python interpreter available for tree expansion." >&2
    return 1
  }
  [[ -f "$HF_MANIFEST_TREE_EXPANDER" ]] || {
    echo "[hf-manifest] Tree expander not found: $HF_MANIFEST_TREE_EXPANDER" >&2
    return 1
  }
  "$py" "$HF_MANIFEST_TREE_EXPANDER" "$manifest" "$output"
}

# Wrap the selection-aware planner. Tree entries are expanded only for sections
# enabled by their existing section-name/download_* environment flags.
if declare -F _hf_manifest_plan >/dev/null 2>&1 \
   && ! declare -F _hf_manifest_plan_without_tree >/dev/null 2>&1; then
  eval "$(declare -f _hf_manifest_plan \
    | sed '1s/^_hf_manifest_plan[[:space:]]*()/_hf_manifest_plan_without_tree ()/')"
fi

_hf_manifest_plan() {
  local manifest="${1:?manifest}" state="${2:?state}"
  local expanded="${state}/manifest.expanded.json"

  # Export Bash-only section flags before the Python expander inspects them.
  if declare -F _hf_manifest_export_selection >/dev/null 2>&1; then
    _hf_manifest_export_selection "$manifest"
  fi

  _hf_manifest_expand_trees "$manifest" "$expanded" || return $?
  _hf_manifest_plan_without_tree "$expanded" "$state"
}

unset _hf_manifest_tree_root
