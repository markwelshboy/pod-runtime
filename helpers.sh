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

custom_node_manifest() {
  local command="${1:-help}"
  shift || true

  if [[ ! -f "$CUSTOM_NODES_TOOL" ]]; then
    echo "[custom-nodes] Tool not found: $CUSTOM_NODES_TOOL" >&2
    return 1
  fi

  case "$command" in
    validate)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" \
        --manifest "$CUSTOM_NODES_MANIFEST_URL" validate "$@"
      ;;
    plan)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" \
        --manifest "$CUSTOM_NODES_MANIFEST_URL" plan \
        --sets "${CUSTOM_NODE_SETS:-}" "$@"
      ;;
    add)
      "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" \
        --manifest "$CUSTOM_NODES_MANIFEST_URL" add "$@"
      ;;
    help|-h|--help)
      cat <<'EOF'
custom_node_manifest commands:
  custom_node_manifest validate
  custom_node_manifest plan
  custom_node_manifest add --set SET --id ID --remote URL [options]

Add options may be repeated:
  --clone-option VALUE
  --pip-option VALUE
  --remove-requirement NAME
  --add-requirement SPEC

The add command requires CUSTOM_NODES_MANIFEST_URL to name a local JSON file.
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
  local source="${1:-${CUSTOM_NODES_MANIFEST_URL:-}}"
  shift || true

  if [[ -z "$source" ]]; then
    echo "[custom-nodes] No manifest source configured; nothing to install." >&2
    return 0
  fi

  # Transparent compatibility for pods carrying the former .list URL.
  if [[ "$source" == *"/default_custom_nodes_manifest.list" ]]; then
    source="${source%default_custom_nodes_manifest.list}default_custom_nodes_manifest.json"
  fi

  local -a args=(
    --manifest "$source"
    install
    --sets "${CUSTOM_NODE_SETS:-}"
  )

  while (($#)); do
    case "$1" in
      --plan|--dry-run)
        args+=("$1")
        ;;
      --sets)
        [[ -n "${2:-}" ]] || {
          echo "[custom-nodes] --sets requires a value" >&2
          return 2
        }
        args+=(--sets "$2")
        shift
        ;;
      *)
        echo "[custom-nodes] Unknown installer option: $1" >&2
        return 2
        ;;
    esac
    shift
  done

  echo "[custom-nodes] Manifest: $source"
  echo "[custom-nodes] Optional sets: ${CUSTOM_NODE_SETS:-<none>} (default is always included)"
  "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_TOOL" "${args[@]}"
}

unset _helpers_entry_dir
