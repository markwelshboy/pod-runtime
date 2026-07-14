#!/usr/bin/env bash
# ======================================================================
# helpers.sh — runtime entrypoint
#
# The full helper library lives in helpers_core.sh. This thin entrypoint
# keeps the public helpers.sh path stable while overriding build_node() so
# parallel custom-node workers return a real failure status to wait -n.
# ======================================================================

_helpers_entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_core.sh"
unset _helpers_entry_dir

# build_node: install one custom node and propagate failures to the
# parallel manifest coordinator. Logs remain per-node in CUSTOM_LOG_DIR.
build_node() {
  local dst="${1:?dst}"
  local name log
  name="$(basename "$dst")"
  log="${CUSTOM_LOG_DIR}/${name}.log"

  mkdir -p "${CUSTOM_LOG_DIR}"

  local rc_req=0 rc_py=0 final_rc=0

  {
    echo "==> [$name] $(date -Is) start"
    echo "dst=$dst"
    echo "PY_BIN=${PY_BIN:-python}"
    echo "PIP_BIN=${PIP_BIN:-pip}"

    # ---- Constraints (export for everything, including install.py) ----
    if [[ -f "/opt/constraints.txt" ]]; then
      export PIP_CONSTRAINT="/opt/constraints.txt"
      export PIP_BUILD_CONSTRAINT="/opt/constraints.txt"
      echo "PIP_BUILD_CONSTRAINT set"
      echo "PIP_CONSTRAINT set"
      echo "constraints=/opt/constraints.txt"
    else
      echo "constraints=none"
    fi

    # ---- requirements.txt ----
    if [[ -f "$dst/requirements.txt" ]]; then
      echo "--- pip install -r requirements.txt ---"
      if [[ -f "/opt/constraints.txt" ]]; then
        "$PIP_BIN" install \
          --upgrade-strategy only-if-needed \
          -c "$PIP_CONSTRAINT" \
          -r "$dst/requirements.txt" || rc_req=$?
      else
        "$PIP_BIN" install \
          --upgrade-strategy only-if-needed \
          -r "$dst/requirements.txt" || rc_req=$?
      fi
      echo "requirements_rc=$rc_req"
    else
      echo "(no requirements.txt)"
    fi

    # ---- install.py ----
    if [[ -f "$dst/install.py" ]]; then
      echo "--- python install.py ---"
      "$PY_BIN" "$dst/install.py" || rc_py=$?
      echo "install_py_rc=$rc_py"
    else
      echo "(no install.py)"
    fi

    # ---- Summary ----
    if [[ $rc_req -ne 0 || $rc_py -ne 0 ]]; then
      final_rc=1
      echo "==> [$name] RESULT=FAIL requirements_rc=$rc_req install_py_rc=$rc_py"
      if [[ -n "${CUSTOM_LOG_DIR:-}" ]]; then
        echo "$name requirements_rc=$rc_req install_py_rc=$rc_py" \
          >> "${CUSTOM_LOG_DIR}/_failures.txt" || true
      fi
    else
      echo "==> [$name] RESULT=OK"
    fi

    echo "==> [$name] $(date -Is) done"
  } >"$log" 2>&1

  return "$final_rc"
}
