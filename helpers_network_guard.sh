#!/usr/bin/env bash
# ======================================================================
# helpers_network_guard.sh — hard wall-clock guard for startup probes
# ======================================================================
# Individual curl transfers already have their own limits, but startup access
# must not depend on every child process behaving correctly. Run the complete
# qualification in a disposable child process and enforce a hard outer ceiling.
#
# The normal startup probe measures Hugging Face/CDN throughput. The PyPI probe
# below measures the separate files.pythonhosted.org route used by pip/uv when
# reconstructing Python environments. A pod can be excellent to HF and still be
# painfully slow to PyPI, so both routes matter for disposable development pods.

: "${NETWORK_TEST_TOTAL_TIMEOUT_SECONDS:=45}"
: "${NETWORK_PYPI_TEST_ENABLE:=true}"
: "${NETWORK_PYPI_TEST_PACKAGE:=onnxruntime-gpu}"
: "${NETWORK_PYPI_STREAM_BYTES:=67108864}"
: "${NETWORK_PYPI_TIMEOUT_SECONDS:=8}"
: "${NETWORK_PYPI_WARN_MBPS:=100}"
: "${NETWORK_PYPI_CRITICAL_MBPS:=25}"
: "${NETWORK_PYPI_RETEST_ON_WARN:=true}"
: "${NETWORK_PYPI_RETEST_DELAY_SECONDS:=1}"
: "${NETWORK_PYPI_LOG_FILE:=${COMFY_LOGS:-/workspace/logs}/network_probe_pypi.json}"

_network_pypi_resolve_wheel_url() {
  local package="${1:-$NETWORK_PYPI_TEST_PACKAGE}"
  command -v python3 >/dev/null 2>&1 || return 1

  python3 - "$package" <<'PY'
import json
import sys
import urllib.request

package = sys.argv[1]
req = urllib.request.Request(
    f"https://pypi.org/pypi/{package}/json",
    headers={"User-Agent": "pod-runtime-network-probe/1"},
)
with urllib.request.urlopen(req, timeout=5) as response:
    data = json.load(response)

files = [
    item for item in data.get("urls", [])
    if item.get("packagetype") == "bdist_wheel"
    and "x86_64" in item.get("filename", "")
    and ("manylinux" in item.get("filename", "") or "linux" in item.get("filename", ""))
]
if not files:
    files = [
        item for item in data.get("urls", [])
        if item.get("packagetype") == "bdist_wheel"
    ]
if not files:
    raise SystemExit(1)

print(max(files, key=lambda item: int(item.get("size") or 0))["url"])
PY
}

_network_pypi_write_json() {
  local path="$NETWORK_PYPI_LOG_FILE"
  mkdir -p "$(dirname "$path")"

  NETWORK_JSON_TIMESTAMP="$(date -Is)" \
  NETWORK_JSON_PYPI_PACKAGE="${NETWORK_PYPI_TEST_PACKAGE:-}" \
  NETWORK_JSON_PYPI_URL="${NETWORK_RESULT_PYPI_URL:-}" \
  NETWORK_JSON_PYPI_BYTES="${NETWORK_PYPI_STREAM_BYTES:-0}" \
  NETWORK_JSON_PYPI_TIMEOUT="${NETWORK_PYPI_TIMEOUT_SECONDS:-0}" \
  NETWORK_JSON_PYPI_FIRST="${NETWORK_RESULT_PYPI_FIRST_MBPS:-0}" \
  NETWORK_JSON_PYPI_RETEST="${NETWORK_RESULT_PYPI_RETEST_MBPS:-}" \
  NETWORK_JSON_PYPI_MBPS="${NETWORK_RESULT_PYPI_MBPS:-0}" \
  NETWORK_JSON_PYPI_CLASS="${NETWORK_RESULT_PYPI_CLASS:-skipped}" \
  NETWORK_JSON_PYPI_WARN="${NETWORK_PYPI_WARN_MBPS:-0}" \
  NETWORK_JSON_PYPI_CRITICAL="${NETWORK_PYPI_CRITICAL_MBPS:-0}" \
  NETWORK_JSON_PYPI_REPLACE="${NETWORK_RESULT_PYPI_REPLACE_RECOMMENDED:-false}" \
  python3 - "$path" <<'PY' || true
import json
import os
import sys


def f(name, default=0.0):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def i(name, default=0):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)

retest_raw = os.environ.get("NETWORK_JSON_PYPI_RETEST", "")
obj = {
    "schema_version": 1,
    "timestamp": os.environ.get("NETWORK_JSON_TIMESTAMP", ""),
    "package": os.environ.get("NETWORK_JSON_PYPI_PACKAGE", ""),
    "url": os.environ.get("NETWORK_JSON_PYPI_URL", ""),
    "stream_bytes": i("NETWORK_JSON_PYPI_BYTES"),
    "timeout_seconds": f("NETWORK_JSON_PYPI_TIMEOUT"),
    "first_mbps": f("NETWORK_JSON_PYPI_FIRST"),
    "retest_mbps": (f("NETWORK_JSON_PYPI_RETEST") if retest_raw else None),
    "mbps": f("NETWORK_JSON_PYPI_MBPS"),
    "classification": os.environ.get("NETWORK_JSON_PYPI_CLASS", "skipped"),
    "warn_threshold_mbps": f("NETWORK_JSON_PYPI_WARN"),
    "critical_threshold_mbps": f("NETWORK_JSON_PYPI_CRITICAL"),
    "replace_recommended": os.environ.get("NETWORK_JSON_PYPI_REPLACE", "false").lower()
        in {"1", "true", "yes", "on"},
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(obj, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

network_probe_pypi_startup() {
  NETWORK_RESULT_PYPI_URL=""
  NETWORK_RESULT_PYPI_FIRST_MBPS=0
  NETWORK_RESULT_PYPI_RETEST_MBPS=""
  NETWORK_RESULT_PYPI_MBPS=0
  NETWORK_RESULT_PYPI_CLASS=skipped
  NETWORK_RESULT_PYPI_REPLACE_RECOMMENDED=false

  if ! _network_bool_true "${NETWORK_PYPI_TEST_ENABLE:-true}"; then
    echo "[network] PyPI/CDN qualification disabled (NETWORK_PYPI_TEST_ENABLE=${NETWORK_PYPI_TEST_ENABLE})."
    _network_pypi_write_json
    return 0
  fi

  if ! declare -F _network_measure_download_parallel >/dev/null 2>&1; then
    echo "[network] WARN: network download measurement helper unavailable; skipping PyPI/CDN qualification." >&2
    NETWORK_RESULT_PYPI_CLASS=probe-failed
    _network_pypi_write_json
    return 0
  fi

  echo "[network] PyPI/CDN: resolving a real ${NETWORK_PYPI_TEST_PACKAGE} wheel from pypi.org..."
  if ! NETWORK_RESULT_PYPI_URL="$(_network_pypi_resolve_wheel_url "$NETWORK_PYPI_TEST_PACKAGE" 2>/dev/null)" \
      || [[ -z "$NETWORK_RESULT_PYPI_URL" ]]; then
    echo "[network] WARN: could not resolve a PyPI wheel URL; skipping package-route throughput test." >&2
    NETWORK_RESULT_PYPI_CLASS=probe-failed
    _network_pypi_write_json
    return 0
  fi

  echo "[network] PyPI/CDN: 1 stream, up to $((NETWORK_PYPI_STREAM_BYTES / 1048576)) MiB, ${NETWORK_PYPI_TIMEOUT_SECONDS}s ceiling"
  _network_measure_download_parallel \
    "$NETWORK_RESULT_PYPI_URL" 1 "$NETWORK_PYPI_STREAM_BYTES" "$NETWORK_PYPI_TIMEOUT_SECONDS" || true
  NETWORK_RESULT_PYPI_FIRST_MBPS="$NETWORK_MEASURE_MBPS"
  NETWORK_RESULT_PYPI_MBPS="$NETWORK_MEASURE_MBPS"

  echo "[network] PyPI/CDN first pass: ${NETWORK_RESULT_PYPI_FIRST_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_PYPI_FIRST_MBPS") MiB/s)"

  if _network_bool_true "$NETWORK_PYPI_RETEST_ON_WARN" \
      && { ! _network_num_ge "$NETWORK_RESULT_PYPI_MBPS" 0.01 \
           || _network_num_lt "$NETWORK_RESULT_PYPI_MBPS" "$NETWORK_PYPI_WARN_MBPS"; }; then
    echo "[network] PyPI/CDN result is below ${NETWORK_PYPI_WARN_MBPS} Mbps; retesting once..."
    sleep "$NETWORK_PYPI_RETEST_DELAY_SECONDS"
    _network_measure_download_parallel \
      "$NETWORK_RESULT_PYPI_URL" 1 "$NETWORK_PYPI_STREAM_BYTES" "$NETWORK_PYPI_TIMEOUT_SECONDS" || true
    NETWORK_RESULT_PYPI_RETEST_MBPS="$NETWORK_MEASURE_MBPS"
    if _network_num_ge "$NETWORK_RESULT_PYPI_RETEST_MBPS" "$NETWORK_RESULT_PYPI_MBPS"; then
      NETWORK_RESULT_PYPI_MBPS="$NETWORK_RESULT_PYPI_RETEST_MBPS"
    fi
    echo "[network] PyPI/CDN retest: ${NETWORK_RESULT_PYPI_RETEST_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_PYPI_RETEST_MBPS") MiB/s)"
  fi

  NETWORK_RESULT_PYPI_CLASS="$(_network_classify "$NETWORK_RESULT_PYPI_MBPS" "$NETWORK_PYPI_WARN_MBPS" "$NETWORK_PYPI_CRITICAL_MBPS")"

  if _network_num_ge "$NETWORK_RESULT_PYPI_MBPS" 0.01 \
      && _network_num_lt "$NETWORK_RESULT_PYPI_MBPS" "$NETWORK_PYPI_CRITICAL_MBPS"; then
    NETWORK_RESULT_PYPI_REPLACE_RECOMMENDED=true
  fi

  echo "[network] PyPI/CDN classification: ${NETWORK_RESULT_PYPI_CLASS}; replace_recommended=${NETWORK_RESULT_PYPI_REPLACE_RECOMMENDED}"
  if [[ "$NETWORK_RESULT_PYPI_REPLACE_RECOMMENDED" == true ]]; then
    echo "[network] WARNING: package-install route is critically slow; replacing this disposable pod is recommended." >&2
  elif _network_num_ge "$NETWORK_RESULT_PYPI_MBPS" 0.01 \
      && _network_num_lt "$NETWORK_RESULT_PYPI_MBPS" "$NETWORK_PYPI_WARN_MBPS"; then
    echo "[network] WARN: package-install route is slow; Python environment reconstruction may be painful." >&2
  fi

  _network_pypi_write_json
  echo "[network] PyPI result: ${NETWORK_PYPI_LOG_FILE}"
  return 0
}

network_probe_startup_guarded() {
  local limit="${NETWORK_TEST_TOTAL_TIMEOUT_SECONDS:-45}"
  local helper_dir
  helper_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

  if ! declare -F network_probe_startup >/dev/null 2>&1; then
    echo "[network] WARN: network_probe_startup is unavailable; skipping qualification." >&2
    return 0
  fi

  if ! command -v timeout >/dev/null 2>&1; then
    echo "[network] WARN: GNU timeout is unavailable; running probes with per-transfer limits only." >&2
    network_probe_startup || true
    network_probe_pypi_startup || true
    return 0
  fi

  [[ "$limit" =~ ^[1-9][0-9]*$ ]] || limit=45

  # Re-source helpers in the child so all network and Telegram functions are
  # available. RunPod/template variables are inherited through the environment.
  # timeout creates a separate process group; --kill-after also cleans up any
  # curl children that ignore the initial TERM.
  local rc=0
  timeout --kill-after=3s "${limit}s" \
    bash -c 'set +e; source "$1/helpers.sh"; network_probe_startup; network_probe_pypi_startup; exit 0' \
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
