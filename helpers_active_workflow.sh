#!/usr/bin/env bash
# Active-browser-tab workflow bridge helpers. Sourced after helpers.sh defines
# the standard custom-node installer so this file can extend that interface.

_active_workflow_helpers_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
: "${CUSTOM_NODES_CURRENT_WORKFLOW_TOOL:=${POD_RUNTIME_DIR:-${_active_workflow_helpers_dir}}/bin/current_comfy_workflow.py}"

custom_node_workflow_bridge_install() {
  local runtime_dir="${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}"
  local src="${runtime_dir}/custom_nodes/pod_runtime_workflow_bridge"
  local custom_dir="${CUSTOM_DIR:-${COMFY_HOME:-/workspace/ComfyUI}/custom_nodes}"
  local dst="${custom_dir}/pod_runtime_workflow_bridge"

  [[ -d "$src" ]] || {
    echo "[custom-nodes] Workflow bridge source not found: $src" >&2
    return 1
  }
  mkdir -p "$custom_dir"
  if [[ -e "$dst" && ! -L "$dst" ]]; then
    echo "[custom-nodes] Workflow bridge destination exists and is not a symlink: $dst" >&2
    return 1
  fi
  ln -sfn "$src" "$dst"
  echo "[custom-nodes] Workflow bridge: $dst -> $src"
}

# Install the bridge into the persistent custom-node directory during bootstrap
# or whenever helpers are sourced. ComfyUI must be restarted to load a newly
# installed bridge.
custom_node_workflow_bridge_install >/dev/null 2>&1 || true

install_custom_nodes() {
  local source="${CUSTOM_NODES_MANIFEST_URL:-}"
  local selected_sets="${CUSTOM_NODE_SETS:-}"
  local workflow=""
  local generated=""
  local accept_default=0
  local allow_unresolved=0
  local comfy_url="${COMFY_URL:-http://127.0.0.1:8188}"
  local explicit_source=0
  local explicit_comfy_url=0
  local current_tab=0
  local -a install_args=()

  if [[ $# -gt 0 && "$1" != --* ]]; then
    source="$1"
    explicit_source=1
    shift
  fi

  while (($#)); do
    case "$1" in
      --from-workflow)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --from-workflow requires a workflow path" >&2; return 2; }
        workflow="$2"
        shift
        ;;
      --current-workflow|--current-tab)
        current_tab=1
        ;;
      --output)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --output requires a path" >&2; return 2; }
        generated="$2"
        shift
        ;;
      --comfy-url)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --comfy-url requires a URL" >&2; return 2; }
        comfy_url="$2"
        explicit_comfy_url=1
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

  # An explicitly supplied ComfyUI URL with no manifest or workflow means
  # "use that server's active browser tab".
  if ((explicit_comfy_url)) && ((explicit_source == 0)) && [[ -z "$workflow" ]]; then
    current_tab=1
  fi

  local temporary_workflow=""
  if ((current_tab)); then
    [[ -f "$CUSTOM_NODES_CURRENT_WORKFLOW_TOOL" ]] || {
      echo "[custom-nodes] Current-workflow fetcher not found: $CUSTOM_NODES_CURRENT_WORKFLOW_TOOL" >&2
      return 1
    }
    temporary_workflow="$(mktemp -p "${CACHE_DIR:-/tmp}" current_comfy_workflow.XXXXXX.json)" || return 1
    echo "[custom-nodes] Reading active browser tab from: $comfy_url"
    if ! "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_CURRENT_WORKFLOW_TOOL" \
      --comfy-url "$comfy_url" --output "$temporary_workflow"; then
      rm -f "$temporary_workflow"
      return 1
    fi
    workflow="$temporary_workflow"
    [[ -n "$generated" ]] || generated="${PWD}/current_tab.custom_nodes.json"
  fi

  if [[ -n "$workflow" ]]; then
    [[ -f "$CUSTOM_NODES_WORKFLOW_TOOL" ]] || {
      echo "[custom-nodes] Workflow resolver not found: $CUSTOM_NODES_WORKFLOW_TOOL" >&2
      rm -f "$temporary_workflow"
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

    local workflow_label="$workflow"
    ((current_tab)) && workflow_label="active browser tab"
    echo "[custom-nodes] Resolving missing live nodes from: $workflow_label"
    if ! "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_WORKFLOW_TOOL" "${resolve_args[@]}"; then
      echo "[custom-nodes] Workflow resolution did not complete cleanly." >&2
      rm -f "$temporary_workflow"
      return 1
    fi
    rm -f "$temporary_workflow"
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

unset _active_workflow_helpers_dir
