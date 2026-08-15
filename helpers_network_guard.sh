#!/usr/bin/env bash
# ======================================================================
# helpers_network_guard.sh — hard wall-clock guard for startup probe
# ======================================================================
# Individual curl transfers already have their own limits, but startup access
# must not depend on every child process behaving correctly. Run the complete
# probe in a disposable child process and enforce a hard outer ceiling.

: "${NETWORK_TEST_TOTAL_TIMEOUT_SECONDS:=45}"

network_probe_startup_guarded() {
  local limit="${NETWORK_TEST_TOTAL_TIMEOUT_SECONDS:-45}"
  local helper_dir
  helper_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

  if ! declare -F network_probe_startup >/dev/null 2>&1; then
    echo "[network] WARN: network_probe_startup is unavailable; skipping qualification." >&2
    return 0
  fi

  if ! command -v timeout >/dev/null 2>&1; then
    echo "[network] WARN: GNU timeout is unavailable; running probe with per-transfer limits only." >&2
    network_probe_startup || true
    return 0
  fi

  [[ "$limit" =~ ^[1-9][0-9]*$ ]] || limit=45

  # Re-source helpers in the child so all network and Telegram functions are
  # available. RunPod/template variables are inherited through the environment.
  # timeout creates a separate process group; --kill-after also cleans up any
  # curl children that ignore the initial TERM.
  local rc=0
  timeout --kill-after=3s "${limit}s" \
    bash -c 'set +e; source "$1/helpers.sh"; network_probe_startup; exit 0' \
    _ "$helper_dir" || rc=$?

  case "$rc" in
    0)
      return 0
      ;;
    124|137)
      echo "[network] WARN: startup network qualification exceeded ${limit}s; killed it and continuing bootstrap." >&2
      ;;
    *)
      echo "[network] WARN: startup network qualification exited rc=${rc}; continuing bootstrap." >&2
      ;;
  esac

  return 0
}
