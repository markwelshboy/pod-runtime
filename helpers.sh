#!/usr/bin/env bash
# ======================================================================
# helpers.sh — runtime entrypoint
# ======================================================================

_helpers_entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_core.sh"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_hf_manifest.sh"
# shellcheck source=/dev/null
[[ -f "${_helpers_entry_dir}/custom_nodes.env" ]] && source "${_helpers_entry_dir}/custom_nodes.env"

: "${CUSTOM_NODES_MANIFEST_URL:=https://raw.githubusercontent.com/markwelshboy/pod-runtime/main/default_custom_nodes_manifest.json}"
: "${CUSTOM_NODE_SETS:=}"
: "${CUSTOM_NODES_TOOL:=${_helpers_entry_dir}/bin/custom_nodes.py}"
: "${CUSTOM_NODES_WORKFLOW_TOOL:=${_helpers_entry_dir}/bin/custom_nodes_from_workflow.py}"

custom_node_manifest() {
  local command="${1:-help}"
  shift || true

  case "$command" in
    validate)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" --manifest "$CUSTOM_NODES_MANIFEST_URL" validate "$@"
      ;;
    plan)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" --manifest "$CUSTOM_NODES_MANIFEST_URL" plan --sets "${CUSTOM_NODE_SETS:-}" "$@"
      ;;
    status)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" status "$@"
      ;;
    add)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" --manifest "$CUSTOM_NODES_MANIFEST_URL" add "$@"
      ;;
    from-workflow|resolve-workflow)
      [[ -f "$CUSTOM_NODES_WORKFLOW_TOOL" ]] || {
        echo "[custom-nodes] Workflow resolver not found: $CUSTOM_NODES_WORKFLOW_TOOL" >&2
        return 1
      }
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_WORKFLOW_TOOL" "$@"
      ;;
    help|-h|--help)
      cat <<'EOF'
custom_node_manifest commands:
  custom_node_manifest validate
  custom_node_manifest plan
  custom_node_manifest status [--json] [--file PATH]
  custom_node_manifest add --set SET --id ID --remote URL [options]
  custom_node_manifest from-workflow WORKFLOW.json -o OUTPUT.json [options]

Workflow resolver options:
  --comfy-url URL          Live ComfyUI URL (default http://127.0.0.1:8188)
  --accept-default         Select the first mapped provider and default branch
  --allow-unresolved       Write/accept a manifest even when mappings are missing
  --base-manifest SOURCE   Reuse known overrides from this manifest

Active-tab install:
  install_custom_nodes --comfy-url http://127.0.0.1:8288
  install_custom_nodes --current-tab --comfy-url URL [--output FILE]

Rollback install:
  install_custom_nodes [normal options] --enable-rollback --rollback FILE
  install_custom_nodes --perform-rollback --rollback FILE

Rollback safety options:
  --allow-dirty-snapshot   Permit snapshot with dirty Git repos (changes are not backed up)
  --force-dirty-restore    Reset dirty Git repos during restore
  --keep-added-nodes       Do not remove node directories added after the snapshot

Add options may be repeated:
  --clone-option VALUE
  --pip-option VALUE
  --remove-requirement NAME
  --add-requirement SPEC

The add command requires CUSTOM_NODES_MANIFEST_URL to name a local JSON file.
The status command reads the latest install report from CUSTOM_NODE_STATUS_FILE
or, by default, $CUSTOM_LOG_DIR/install_status.json.
EOF
      ;;
    *)
      echo "[custom-nodes] Unknown manifest command: $command" >&2
      return 2
      ;;
  esac
}

custom_node_add() {
  custom_node_manifest add "$@"
}

install_custom_nodes() {
  local source="${CUSTOM_NODES_MANIFEST_URL:-}"
  local selected_sets="${CUSTOM_NODE_SETS:-}"
  local workflow=""
  local generated=""
  local accept_default=0
  local allow_unresolved=0
  local comfy_url="${COMFY_URL:-http://127.0.0.1:8188}"
  local -a install_args=()

  # A normal first positional argument remains a manifest source.
  if [[ $# -gt 0 && "$1" != --* ]]; then
    source="$1"
    shift
  fi

  while (($#)); do
    case "$1" in
      --from-workflow)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --from-workflow requires a workflow path" >&2; return 2; }
        workflow="$2"
        shift
        ;;
      --output)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --output requires a path" >&2; return 2; }
        generated="$2"
        shift
        ;;
      --comfy-url)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --comfy-url requires a URL" >&2; return 2; }
        comfy_url="$2"
        shift
        ;;
      --accept-default)
        accept_default=1
        ;;
      --allow-unresolved)
        allow_unresolved=1
        ;;
      --plan|--dry-run)
        install_args+=("$1")
        ;;
      --sets)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --sets requires a value" >&2; return 2; }
        selected_sets="$2"
        shift
        ;;
      *)
        echo "[custom-nodes] Unknown installer option: $1" >&2
        return 2
        ;;
    esac
    shift
  done

  if [[ -n "$workflow" ]]; then
    [[ -f "$CUSTOM_NODES_WORKFLOW_TOOL" ]] || {
      echo "[custom-nodes] Workflow resolver not found: $CUSTOM_NODES_WORKFLOW_TOOL" >&2
      return 1
    }
    [[ -n "$generated" ]] || generated="${workflow%.*}.custom_nodes.json"
    local -a resolve_args=(
      "$workflow"
      --output "$generated"
      --comfy-url "$comfy_url"
      --base-manifest "$CUSTOM_NODES_MANIFEST_URL"
    )
    ((accept_default)) && resolve_args+=(--accept-default)
    ((allow_unresolved)) && resolve_args+=(--allow-unresolved)

    echo "[custom-nodes] Resolving missing live nodes from: $workflow"
    if ! "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_WORKFLOW_TOOL" "${resolve_args[@]}"; then
      echo "[custom-nodes] Workflow resolution did not complete cleanly." >&2
      return 1
    fi
    source="$generated"
    selected_sets=""
  fi

  if [[ -z "$source" ]]; then
    echo "[custom-nodes] No manifest source configured; nothing to install." >&2
    return 0
  fi

  if [[ "$source" == *"/default_custom_nodes_manifest.list" ]]; then
    source="${source%default_custom_nodes_manifest.list}default_custom_nodes_manifest.json"
  fi

  local -a args=(--manifest "$source" install --sets "$selected_sets")
  args+=("${install_args[@]}")

  echo "[custom-nodes] Manifest: $source"
  echo "[custom-nodes] Optional sets: ${selected_sets:-<none>} (default is always included)"
  "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" "${args[@]}"
}

# shellcheck source=/dev/null
[[ -f "${_helpers_entry_dir}/helpers_active_workflow.sh" ]] && source "${_helpers_entry_dir}/helpers_active_workflow.sh"
# shellcheck source=/dev/null
[[ -f "${_helpers_entry_dir}/helpers_custom_node_rollback.sh" ]] && source "${_helpers_entry_dir}/helpers_custom_node_rollback.sh"

unset _helpers_entry_dir
