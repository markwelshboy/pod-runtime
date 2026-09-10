#!/usr/bin/env bash
# Transaction-style rollback support for install_custom_nodes.

: "${CUSTOM_NODES_ROLLBACK_TOOL:=${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}/bin/custom_nodes_rollback.py}"

if declare -F install_custom_nodes >/dev/null 2>&1 && ! declare -F _install_custom_nodes_without_rollback >/dev/null 2>&1; then
  eval "$(declare -f install_custom_nodes | sed '1s/^install_custom_nodes /_install_custom_nodes_without_rollback /')"
fi

custom_node_rollback_create() {
  local output="${1:?rollback path required}"
  shift || true
  local custom_dir="${CUSTOM_DIR:-${COMFY_HOME:-/workspace/ComfyUI}/custom_nodes}"
  local python="${PY_BIN:-${PY:-/opt/venv/bin/python}}"
  "${python}" "$CUSTOM_NODES_ROLLBACK_TOOL" create \
    --output "$output" \
    --custom-dir "$custom_dir" \
    --python "$python" \
    "$@"
}

custom_node_rollback_perform() {
  local snapshot="${1:?rollback path required}"
  shift || true
  local python="${PY_BIN:-${PY:-/opt/venv/bin/python}}"
  "${python}" "$CUSTOM_NODES_ROLLBACK_TOOL" restore \
    --snapshot "$snapshot" \
    --python "$python" \
    "$@"
}

install_custom_nodes() {
  local enable_rollback=0
  local perform_rollback=0
  local rollback_path=""
  local accept_default=0
  local allow_dirty_snapshot=0
  local strict_dirty_snapshot=0
  local preserve_dirty_restore=0
  local keep_added_nodes=0
  local verbose_rollback=0
  local -a forwarded=()

  while (($#)); do
    case "$1" in
      --enable-rollback)
        enable_rollback=1
        ;;
      --perform-rollback)
        perform_rollback=1
        ;;
      --rollback)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --rollback requires a path" >&2; return 2; }
        rollback_path="$2"
        shift
        ;;
      --accept-default)
        accept_default=1
        forwarded+=("$1")
        ;;
      --allow-dirty-snapshot|--snapshot-dirty)
        allow_dirty_snapshot=1
        ;;
      --strict-dirty-snapshot)
        strict_dirty_snapshot=1
        ;;
      --force-dirty-restore)
        # Kept for compatibility. Restores now reset dirty checkouts by default.
        ;;
      --preserve-dirty-restore)
        preserve_dirty_restore=1
        ;;
      --keep-added-nodes)
        keep_added_nodes=1
        ;;
      --rollback-verbose)
        verbose_rollback=1
        ;;
      *)
        forwarded+=("$1")
        ;;
    esac
    shift
  done

  if ((perform_rollback)); then
    [[ -n "$rollback_path" ]] || {
      echo "[custom-nodes] --perform-rollback requires --rollback FILE" >&2
      return 2
    }
    local -a restore_args=()
    ((preserve_dirty_restore)) && restore_args+=(--preserve-dirty)
    ((keep_added_nodes)) && restore_args+=(--keep-added-nodes)
    ((verbose_rollback)) && restore_args+=(--verbose)
    custom_node_rollback_perform "$rollback_path" "${restore_args[@]}"
    return $?
  fi

  if ((enable_rollback)); then
    [[ -n "$rollback_path" ]] || {
      echo "[custom-nodes] --enable-rollback requires --rollback FILE" >&2
      return 2
    }
    local -a create_args=()
    ((accept_default)) && create_args+=(--accept-default)
    ((allow_dirty_snapshot)) && create_args+=(--allow-dirty)
    ((strict_dirty_snapshot)) && create_args+=(--strict-dirty)
    ((verbose_rollback)) && create_args+=(--verbose)
    echo "[custom-nodes] Capturing pre-install rollback snapshot: $rollback_path"
    custom_node_rollback_create "$rollback_path" "${create_args[@]}" || return $?
  elif [[ -n "$rollback_path" ]]; then
    echo "[custom-nodes] --rollback was supplied without --enable-rollback or --perform-rollback" >&2
    return 2
  fi

  _install_custom_nodes_without_rollback "${forwarded[@]}"
}
