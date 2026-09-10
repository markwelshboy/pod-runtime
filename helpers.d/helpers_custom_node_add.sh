#!/usr/bin/env bash
# Friendly custom-node manifest addition helper.

: "${CUSTOM_NODE_ADD_TOOL:=${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}/bin/custom_node_add.py}"

custom_node_add() {
  local python="${PY_BIN:-${PY:-python}}"
  "$python" "$CUSTOM_NODE_ADD_TOOL" "$@"
}
