#!/usr/bin/env bash
# ======================================================================
# helpers.sh — runtime entrypoint
#
# The full helper library lives in helpers_core.sh. This thin entrypoint
# keeps the public helpers.sh path stable while overriding the custom-node
# worker and coordinator so failures propagate and waits are PID-scoped.
# ======================================================================

_helpers_entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_core.sh"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_hf_manifest.sh"
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

# Wait for one PID from a named worker array. Passing the worker PIDs to
# wait -n prevents unrelated long-lived bootstrap children (tee, aria2, etc.)
# from being counted as completed custom-node jobs.
_custom_nodes_wait_one() {
  local pids_name="${1:?pids array name}"
  local failed_name="${2:?failure flag name}"
  local -n _pids="$pids_name"
  local -n _failed="$failed_name"
  local done_pid=""
  local -a remaining=()

  ((${#_pids[@]} > 0)) || return 0

  if ! wait -n -p done_pid "${_pids[@]}"; then
    _failed=1
  fi

  # Defensive fallback: avoid looping forever if wait could not identify a PID.
  if [[ -z "$done_pid" ]]; then
    done_pid="${_pids[0]}"
    if ! wait "$done_pid" 2>/dev/null; then
      _failed=1
    fi
  fi

  local pid
  for pid in "${_pids[@]}"; do
    [[ "$pid" == "$done_pid" ]] || remaining+=("$pid")
  done
  _pids=("${remaining[@]}")
}

# install_custom_nodes: manifest installer with bounded parallelism and
# PID-scoped waits. Returns nonzero after all workers finish if any failed.
install_custom_nodes() {
  _helpers_need curl

  local src="${1:-${CUSTOM_NODES_MANIFEST_URL:-}}"

  if [[ -z "$src" ]]; then
    echo "[custom-nodes] No manifest source and CUSTOM_NODES_MANIFEST_URL not set; nothing to install." >&2
    return 0
  fi

  local man tmp=""
  if [[ -f "$src" ]]; then
    man="$src"
  else
    man="$(mktemp -p "${CACHE_DIR:-/tmp}" custom_nodes_manifest.XXXXXX)"
    tmp="$man"
    if ! curl -fsSL "$src" -o "$man"; then
      echo "[custom-nodes] Failed to fetch manifest: $src" >&2
      [[ -n "$tmp" ]] && rm -f "$tmp"
      return 1
    fi
  fi

  local custom_dir="${CUSTOM_DIR:-${COMFY_HOME:-/workspace/ComfyUI}/custom_nodes}"
  local log_dir="${CUSTOM_LOG_DIR:-${COMFY_LOGS:-/workspace/logs}/custom_nodes}"
  mkdir -p "$custom_dir" "$log_dir"

  local max_jobs="${MAX_CUSTOM_NODE_JOBS:-8}"
  if ! [[ "$max_jobs" =~ ^[0-9]+$ ]] || ((max_jobs < 1)); then
    max_jobs=8
  fi

  local failed=0
  local -a worker_pids=()

  # Never allow git authentication prompts to masquerade as installer hangs.
  export GIT_TERMINAL_PROMPT=0
  export GIT_ASKPASS=/bin/echo

  echo "[custom-nodes] Using manifest: $src"
  echo "[custom-nodes] Installing custom nodes into: $custom_dir"
  echo "[custom-nodes] Using concurrency: ${max_jobs}. Change with MAX_CUSTOM_NODE_JOBS env var."
  cd "$custom_dir"

  local line url dst rest
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    url=""
    dst=""
    rest=""
    # shellcheck disable=SC2086
    read -r url dst rest <<<"$line"

    if [[ -z "$url" || -z "$dst" ]]; then
      echo "[custom-nodes] Skipping malformed line: $line" >&2
      continue
    fi

    local -a extra=()
    if [[ -n "${rest:-}" ]]; then
      # shellcheck disable=SC2206
      extra=($rest)
    fi

    (
      local name
      name="$(basename "$dst")"

      echo "[custom-nodes] → $dst  (from $url ${extra[*]:+${extra[*]}})"

      if ! clone_or_pull "$url" "$dst" "${extra[@]}"; then
        echo "[custom-nodes] ❌ Clone/update ERROR $name" >&2
        exit 1
      fi

      if ! CUSTOM_LOG_DIR="$log_dir" build_node "$dst"; then
        echo "[custom-nodes] ❌ Install ERROR $name (see ${log_dir}/${name}.log)" >&2
        exit 1
      fi

      echo "[custom-nodes] ✅ Completed install for: $name" >&2
    ) &

    worker_pids+=("$!")

    if ((${#worker_pids[@]} >= max_jobs)); then
      _custom_nodes_wait_one worker_pids failed
    fi
  done <"$man"

  echo "[custom-nodes] Waiting for ${#worker_pids[@]} remaining node install(s)…" >&2
  while ((${#worker_pids[@]} > 0)); do
    _custom_nodes_wait_one worker_pids failed
  done

  [[ -n "$tmp" ]] && rm -f "$tmp"

  if ((failed != 0)); then
    echo "[custom-nodes] Completed with one or more errors." >&2
    echo ""
    return 1
  fi

  echo "[custom-nodes] Manifest install completed successfully."
  echo ""
  return 0
}
