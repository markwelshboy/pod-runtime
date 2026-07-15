#!/usr/bin/env bash
# ======================================================================
# helpers.sh — runtime entrypoint
#
# The full helper library lives in helpers_core.sh. This thin entrypoint
# keeps the public helpers.sh path stable while overriding selected runtime
# functions that need stricter failure propagation and diagnostics.
# ======================================================================

_helpers_entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_core.sh"
# shellcheck source=/dev/null
source "${_helpers_entry_dir}/helpers_hf_manifest.sh"
unset _helpers_entry_dir

_custom_nodes_debug_enabled() {
  case "${CUSTOM_NODE_DEBUG:-true}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_custom_nodes_debug_log() {
  local log="${CUSTOM_NODE_COORDINATOR_LOG:-${CUSTOM_LOG_DIR:-${COMFY_LOGS:-/workspace/logs}/custom_nodes}/_coordinator.log}"
  mkdir -p -- "$(dirname -- "$log")"
  printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$log" >&2
}

_custom_nodes_process_snapshot() {
  local reason="${1:-snapshot}"
  shift || true
  local -a pids=("$@")
  local log="${CUSTOM_NODE_COORDINATOR_LOG:-${CUSTOM_LOG_DIR:-${COMFY_LOGS:-/workspace/logs}/custom_nodes}/_coordinator.log}"

  {
    printf '[%s] SNAPSHOT reason=%s workers=%s\n' "$(date -Is)" "$reason" "${#pids[@]}"
    printf 'installer_pid=%s installer_ppid=%s shell_flags=%s\n' "$$" "$PPID" "$-"
    printf 'loadavg: '; cat /proc/loadavg 2>/dev/null || true
    printf 'disk: '; df -h /workspace 2>/dev/null | tail -n 1 || true
    printf 'memory: '; free -h 2>/dev/null | awk 'NR==2{print}' || true

    local pid stat etime cmd children
    for pid in "${pids[@]}"; do
      [[ "$pid" =~ ^[0-9]+$ ]] || continue
      stat="$(ps -o stat= -p "$pid" 2>/dev/null | awk '{print $1}')"
      etime="$(ps -o etime= -p "$pid" 2>/dev/null | xargs 2>/dev/null || true)"
      cmd="$(ps -o args= -p "$pid" 2>/dev/null || true)"
      children="$(ps -o pid= --ppid "$pid" 2>/dev/null | xargs 2>/dev/null || true)"
      printf 'worker pid=%s stat=%s elapsed=%s children=[%s] cmd=%s\n' \
        "$pid" "${stat:-gone}" "${etime:-gone}" "$children" "${cmd:-gone}"
      if [[ -n "$children" ]]; then
        ps -o pid,ppid,stat,etime,wchan:24,args -p ${children} 2>/dev/null || true
      fi
    done

    printf '%s\n' '--- relevant process tree ---'
    ps -eo pid,ppid,stat,etime,wchan:24,args --forest 2>/dev/null \
      | grep -E '(^[[:space:]]*PID|custom_nodes|pip( |$)|python.*install\.py|git (clone|fetch|pull|checkout|reset)|helpers\.sh)' \
      || true
    printf '%s\n' '--- end snapshot ---'
  } >>"$log" 2>&1

  _custom_nodes_debug_log "debug snapshot appended: reason=$reason log=$log"
}

# build_node: install one custom node and propagate failures to the
# parallel manifest coordinator. Logs remain per-node in CUSTOM_LOG_DIR.
build_node() {
  local dst="${1:?dst}"
  local name log state_file
  name="$(basename "$dst")"
  log="${CUSTOM_LOG_DIR}/${name}.log"
  state_file="${CUSTOM_LOG_DIR}/${name}.state"

  mkdir -p "${CUSTOM_LOG_DIR}"

  local rc_req=0 rc_py=0 final_rc=0

  {
    echo "==> [$name] $(date -Is) start pid=$$ bashexec=$BASHPID ppid=$PPID"
    echo "dst=$dst"
    echo "PY_BIN=${PY_BIN:-python}"
    echo "PIP_BIN=${PIP_BIN:-pip}"
    echo "shell_flags=$-"
    echo "PATH=$PATH"
    printf 'phase=start pid=%s bashexec=%s time=%s\n' "$$" "$BASHPID" "$(date -Is)" >"$state_file"

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
      printf 'phase=requirements pid=%s bashexec=%s time=%s\n' "$$" "$BASHPID" "$(date -Is)" >"$state_file"
      if [[ -f "/opt/constraints.txt" ]]; then
        "$PIP_BIN" install \
          --verbose \
          --upgrade-strategy only-if-needed \
          -c "$PIP_CONSTRAINT" \
          -r "$dst/requirements.txt" || rc_req=$?
      else
        "$PIP_BIN" install \
          --verbose \
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
      printf 'phase=install.py pid=%s bashexec=%s time=%s\n' "$$" "$BASHPID" "$(date -Is)" >"$state_file"
      "$PY_BIN" -u "$dst/install.py" || rc_py=$?
      echo "install_py_rc=$rc_py"
    else
      echo "(no install.py)"
    fi

    # ---- Summary ----
    if [[ $rc_req -ne 0 || $rc_py -ne 0 ]]; then
      final_rc=1
      echo "==> [$name] RESULT=FAIL requirements_rc=$rc_req install_py_rc=$rc_py"
      printf 'phase=failed requirements_rc=%s install_py_rc=%s time=%s\n' \
        "$rc_req" "$rc_py" "$(date -Is)" >"$state_file"
      if [[ -n "${CUSTOM_LOG_DIR:-}" ]]; then
        echo "$name requirements_rc=$rc_req install_py_rc=$rc_py" \
          >> "${CUSTOM_LOG_DIR}/_failures.txt" || true
      fi
    else
      echo "==> [$name] RESULT=OK"
      printf 'phase=completed time=%s\n' "$(date -Is)" >"$state_file"
    fi

    echo "==> [$name] $(date -Is) done"
  } >"$log" 2>&1

  return "$final_rc"
}

# Poll only the known custom-node worker PIDs. A completed child can remain as
# a zombie until reaped, so STAT=Z is treated as ready and then wait is called
# for exactly that PID. This avoids unrestricted wait -n behavior entirely.
_custom_nodes_wait_one() {
  local pids_name="${1:?pids array name}"
  local names_name="${2:?names array name}"
  local starts_name="${3:?starts array name}"
  local failed_name="${4:?failure flag name}"
  local -n _pids="$pids_name"
  local -n _names="$names_name"
  local -n _starts="$starts_name"
  local -n _failed="$failed_name"

  ((${#_pids[@]} > 0)) || return 0

  local poll="${CUSTOM_NODE_WAIT_POLL_SECONDS:-1}"
  local report="${CUSTOM_NODE_DEBUG_INTERVAL:-30}"
  local timeout="${CUSTOM_NODE_WORKER_TIMEOUT:-0}"
  local kill_on_timeout="${CUSTOM_NODE_KILL_ON_TIMEOUT:-false}"
  local next_report=$((SECONDS + report))
  local pid name stat idx now age rc

  while :; do
    for idx in "${!_pids[@]}"; do
      pid="${_pids[$idx]}"
      name="${_names[$idx]}"
      stat="$(ps -o stat= -p "$pid" 2>/dev/null | awk '{print $1}')"

      if [[ -z "$stat" || "$stat" == Z* ]]; then
        rc=0
        wait "$pid" || rc=$?
        ((rc == 0)) || _failed=1
        _custom_nodes_debug_log "reaped worker name=$name pid=$pid rc=$rc stat=${stat:-gone} remaining_before=${#_pids[@]}"
        unset '_pids[idx]' '_names[idx]' '_starts[idx]'
        _pids=("${_pids[@]}")
        _names=("${_names[@]}")
        _starts=("${_starts[@]}")
        return 0
      fi

      if [[ "$timeout" =~ ^[0-9]+$ ]] && ((timeout > 0)); then
        now=$SECONDS
        age=$((now - _starts[$idx]))
        if ((age >= timeout)); then
          _failed=1
          _custom_nodes_process_snapshot "worker-timeout name=$name pid=$pid age=${age}s" "${_pids[@]}"
          _custom_nodes_debug_log "TIMEOUT name=$name pid=$pid age=${age}s kill_on_timeout=$kill_on_timeout"
          if [[ "$kill_on_timeout" == "true" || "$kill_on_timeout" == "1" ]]; then
            kill -TERM "$pid" 2>/dev/null || true
            sleep 2
            kill -KILL "$pid" 2>/dev/null || true
          fi
          # Prevent repeated timeout reports while preserving the worker.
          _starts[$idx]=$SECONDS
        fi
      fi
    done

    if _custom_nodes_debug_enabled && ((SECONDS >= next_report)); then
      _custom_nodes_process_snapshot "periodic-wait" "${_pids[@]}"
      next_report=$((SECONDS + report))
    fi

    sleep "$poll"
  done
}

# install_custom_nodes: manifest installer with bounded parallelism,
# PID-scoped polling, and durable diagnostics.
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
  export CUSTOM_LOG_DIR="$log_dir"
  export CUSTOM_NODE_COORDINATOR_LOG="${CUSTOM_NODE_COORDINATOR_LOG:-${log_dir}/_coordinator.log}"
  mkdir -p "$custom_dir" "$log_dir"
  : >"$CUSTOM_NODE_COORDINATOR_LOG"
  rm -f "${log_dir}/_failures.txt" "${log_dir}"/*.state 2>/dev/null || true

  local max_jobs="${MAX_CUSTOM_NODE_JOBS:-8}"
  if ! [[ "$max_jobs" =~ ^[0-9]+$ ]] || ((max_jobs < 1)); then
    max_jobs=8
  fi

  local failed=0
  local -a worker_pids=()
  local -a worker_names=()
  local -a worker_starts=()

  export GIT_TERMINAL_PROMPT=0
  export GIT_ASKPASS=/bin/echo
  export PIP_NO_INPUT=1

  _custom_nodes_debug_log "BEGIN src=$src manifest=$man custom_dir=$custom_dir max_jobs=$max_jobs bash=$BASH_VERSION pid=$$"
  _custom_nodes_debug_log "debug=${CUSTOM_NODE_DEBUG:-true} interval=${CUSTOM_NODE_DEBUG_INTERVAL:-30}s timeout=${CUSTOM_NODE_WORKER_TIMEOUT:-0}s kill_on_timeout=${CUSTOM_NODE_KILL_ON_TIMEOUT:-false}"
  _custom_nodes_debug_log "python=${PY_BIN:-python} pip=${PIP_BIN:-pip} git=$(git --version 2>/dev/null || true)"

  cd "$custom_dir"

  local line url dst rest name pid
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    url=""
    dst=""
    rest=""
    read -r url dst rest <<<"$line"

    if [[ -z "$url" || -z "$dst" ]]; then
      _custom_nodes_debug_log "skip malformed line=$line"
      continue
    fi

    local -a extra=()
    if [[ -n "${rest:-}" ]]; then
      # shellcheck disable=SC2206
      extra=($rest)
    fi

    name="$(basename "$dst")"
    (
      echo "[custom-nodes] → $dst  (from $url ${extra[*]:+${extra[*]}})"
      _custom_nodes_debug_log "worker-enter name=$name bashexec=$BASHPID parent=$PPID dst=$dst"

      if ! clone_or_pull "$url" "$dst" "${extra[@]}"; then
        _custom_nodes_debug_log "worker-clone-failed name=$name bashexec=$BASHPID"
        echo "[custom-nodes] ❌ Clone/update ERROR $name" >&2
        exit 1
      fi

      _custom_nodes_debug_log "worker-build-start name=$name bashexec=$BASHPID"
      if ! CUSTOM_LOG_DIR="$log_dir" build_node "$dst"; then
        _custom_nodes_debug_log "worker-build-failed name=$name bashexec=$BASHPID"
        echo "[custom-nodes] ❌ Install ERROR $name (see ${log_dir}/${name}.log)" >&2
        exit 1
      fi

      _custom_nodes_debug_log "worker-complete name=$name bashexec=$BASHPID"
      echo "[custom-nodes] ✅ Completed install for: $name" >&2
    ) &

    pid=$!
    worker_pids+=("$pid")
    worker_names+=("$name")
    worker_starts+=("$SECONDS")
    _custom_nodes_debug_log "launched name=$name pid=$pid running=${#worker_pids[@]}/$max_jobs"

    if ((${#worker_pids[@]} >= max_jobs)); then
      _custom_nodes_debug_log "throttle-enter running=${#worker_pids[@]}"
      _custom_nodes_wait_one worker_pids worker_names worker_starts failed
      _custom_nodes_debug_log "throttle-exit running=${#worker_pids[@]} failed=$failed"
    fi
  done <"$man"

  _custom_nodes_debug_log "manifest-read-complete remaining=${#worker_pids[@]}"
  while ((${#worker_pids[@]} > 0)); do
    _custom_nodes_wait_one worker_pids worker_names worker_starts failed
    _custom_nodes_debug_log "drain-progress remaining=${#worker_pids[@]} failed=$failed"
  done

  [[ -n "$tmp" ]] && rm -f "$tmp"

  if ((failed != 0)); then
    _custom_nodes_debug_log "END result=FAIL"
    echo "[custom-nodes] Completed with one or more errors." >&2
    echo "[custom-nodes] Coordinator log: $CUSTOM_NODE_COORDINATOR_LOG" >&2
    echo ""
    return 1
  fi

  _custom_nodes_debug_log "END result=OK"
  echo "[custom-nodes] Manifest install completed successfully."
  echo "[custom-nodes] Coordinator log: $CUSTOM_NODE_COORDINATOR_LOG"
  echo ""
  return 0
}
