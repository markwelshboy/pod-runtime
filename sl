#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  SCRIPT_PATH="$(readlink -f -- "$SCRIPT_PATH")"
fi
ROOT="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd -P)"
SL_PY="$ROOT/bin/sl.py"

if [[ ! -f "$SL_PY" ]]; then
  echo "[sl] ERROR: bin/sl.py not found: $SL_PY" >&2
  exit 1
fi

export SL_VCP="${SL_VCP:-$ROOT/vcp}"
exec "${PYTHON:-python3}" "$SL_PY" "$@"
