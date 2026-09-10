#!/usr/bin/env bash
# Friendly custom-node manifest addition helper.

: "${CUSTOM_NODE_ADD_TOOL:=${POD_RUNTIME_DIR:?POD_RUNTIME_DIR not set}/bin/custom_node_add.py}"

custom_node_add() {
  local python="${PY_BIN:-${PY:-python}}"
  "$python" "$CUSTOM_NODE_ADD_TOOL" "$@"
}
