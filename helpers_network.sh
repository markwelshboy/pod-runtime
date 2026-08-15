#!/usr/bin/env bash
# ======================================================================
# helpers_network.sh — early pod network qualification
# ======================================================================
# Best-effort startup probe. It never blocks pod startup on a probe/tool error.
#
# Primary signal: Hugging Face CDN download throughput. This is the keep/ditch
# signal because model provisioning and hff downloads dominate pod traffic.
#
# Secondary signal: optional mTLS HTTPS transfer to the home network. This is
# intended to answer "will a direct browser/app file transfer be painful?" and
# never recommends replacing a pod by itself.
#
# Template variables (all optional):
#   NETWORK_TEST_ENABLE=true
#   NETWORK_HF_TEST_ENABLE=true
#   NETWORK_HF_TEST_URL=https://aws.cdn.hf.co/fast/5gb
#   NETWORK_HF_STREAMS=8
#   NETWORK_HF_STREAM_BYTES=268435456       # 256 MiB each, 2 GiB max total
#   NETWORK_HF_TIMEOUT_SECONDS=10
#   NETWORK_HF_WARN_MBPS=100
#   NETWORK_HF_CRITICAL_MBPS=50
#   NETWORK_HF_RETEST_ON_WARN=true
#   NETWORK_HF_RETEST_DELAY_SECONDS=2
#
#   NETWORK_HOME_TEST_ENABLE=auto           # auto|true|false
#   NETWORK_HOME_TEST_URL=https://nettest.example.com
#   NETWORK_HOME_CLIENT_CERT_B64=...
#   NETWORK_HOME_CLIENT_KEY_B64=...
#   NETWORK_HOME_STREAMS=1                  # single HTTP flow matches app upload
#   NETWORK_HOME_TEST_BYTES=536870912       # 512 MiB ceiling per stream
#   NETWORK_HOME_TIMEOUT_SECONDS=6
#   NETWORK_HOME_WARN_MBPS=25
#   NETWORK_HOME_CRITICAL_MBPS=10
#   NETWORK_HOME_KEEP_CLIENT_FILES=false
#
#   NETWORK_LOG_FILE=/workspace/logs/network_probe.json

: "${NETWORK_TEST_ENABLE:=true}"
: "${NETWORK_HF_TEST_ENABLE:=true}"
: "${NETWORK_HF_TEST_URL:=https://aws.cdn.hf.co/fast/5gb}"
: "${NETWORK_HF_STREAMS:=8}"
: "${NETWORK_HF_STREAM_BYTES:=268435456}"
: "${NETWORK_HF_TIMEOUT_SECONDS:=10}"
: "${NETWORK_HF_WARN_MBPS:=100}"
: "${NETWORK_HF_CRITICAL_MBPS:=50}"
: "${NETWORK_HF_RETEST_ON_WARN:=true}"
: "${NETWORK_HF_RETEST_DELAY_SECONDS:=2}"

: "${NETWORK_HOME_TEST_ENABLE:=auto}"
: "${NETWORK_HOME_TEST_URL:=}"
: "${NETWORK_HOME_CLIENT_CERT_B64:=}"
: "${NETWORK_HOME_CLIENT_KEY_B64:=}"
: "${NETWORK_HOME_CLIENT_CERT:=}"
: "${NETWORK_HOME_CLIENT_KEY:=}"
: "${NETWORK_HOME_STREAMS:=1}"
: "${NETWORK_HOME_TEST_BYTES:=536870912}"
: "${NETWORK_HOME_TIMEOUT_SECONDS:=6}"
: "${NETWORK_HOME_WARN_MBPS:=25}"
: "${NETWORK_HOME_CRITICAL_MBPS:=10}"
: "${NETWORK_HOME_KEEP_CLIENT_FILES:=false}"

: "${NETWORK_LOG_FILE:=${COMFY_LOGS:-/workspace/logs}/network_probe.json}"

_network_bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_network_num_ge() {
  awk -v a="${1:-0}" -v b="${2:-0}" 'BEGIN { exit !(a >= b) }'
}

_network_num_lt() {
  awk -v a="${1:-0}" -v b="${2:-0}" 'BEGIN { exit !(a < b) }'
}

_network_mbps_to_mib_s() {
  awk -v mbps="${1:-0}" 'BEGIN { printf "%.1f", (mbps * 1000000 / 8) / 1048576 }'
}

_network_classify() {
  local mbps="${1:-0}" warn="${2:-100}" critical="${3:-50}"
  if ! _network_num_ge "$mbps" 0.01; then
    printf 'failed'
  elif _network_num_lt "$mbps" "$critical"; then
    printf 'very-slow'
  elif _network_num_lt "$mbps" "$warn"; then
    printf 'slow'
  elif _network_num_ge "$mbps" 500; then
    printf 'excellent'
  elif _network_num_ge "$mbps" 200; then
    printf 'good'
  else
    printf 'acceptable'
  fi
}

_network_now_ns() {
  date +%s%N 2>/dev/null || printf '%s000000000\n' "$(date +%s)"
}

_network_elapsed_seconds() {
  local start_ns="$1" end_ns="$2"
  awk -v s="$start_ns" -v e="$end_ns" 'BEGIN { d=(e-s)/1000000000; if (d <= 0) d=0.001; printf "%.6f", d }'
}

_network_measure_download_parallel() {
  # usage: _network_measure_download_parallel URL STREAMS BYTES_PER_STREAM TIMEOUT [CERT] [KEY]
  # Sets NETWORK_MEASURE_{BYTES,SECONDS,MBPS,HTTP_OK,STREAMS_OK}.
  local url="$1" streams="$2" bytes_per_stream="$3" timeout_s="$4"
  local cert="${5:-}" key="${6:-}"
  local tmp start_ns end_ns seconds i total=0 http_ok=0 streams_ok=0
  local range_end=$((bytes_per_stream - 1))
  local -a auth_args=()

  NETWORK_MEASURE_BYTES=0
  NETWORK_MEASURE_SECONDS=0
  NETWORK_MEASURE_MBPS=0
  NETWORK_MEASURE_HTTP_OK=0
  NETWORK_MEASURE_STREAMS_OK=0

  [[ "$streams" =~ ^[1-9][0-9]*$ ]] || streams=1
  [[ "$bytes_per_stream" =~ ^[1-9][0-9]*$ ]] || return 1

  if [[ -n "$cert" && -n "$key" ]]; then
    auth_args=(--cert "$cert" --key "$key")
  fi

  tmp="$(mktemp -d /tmp/network-download.XXXXXX)" || return 1
  start_ns="$(_network_now_ns)"

  for ((i=1; i<=streams; i++)); do
    (
      curl -L -sS \
        --connect-timeout 5 \
        --max-time "$timeout_s" \
        --range "0-${range_end}" \
        "${auth_args[@]}" \
        -o /dev/null \
        -w '%{size_download}\n%{http_code}\n' \
        "$url" \
        >"$tmp/$i.out" 2>"$tmp/$i.err" || true
    ) &
  done
  wait || true

  end_ns="$(_network_now_ns)"
  seconds="$(_network_elapsed_seconds "$start_ns" "$end_ns")"

  for ((i=1; i<=streams; i++)); do
    local bytes code
    bytes="$(sed -n '1p' "$tmp/$i.out" 2>/dev/null || true)"
    code="$(sed -n '2p' "$tmp/$i.out" 2>/dev/null || true)"
    [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
    total=$((total + bytes))
    case "$code" in
      200|206) http_ok=$((http_ok + 1)) ;;
    esac
    (( bytes > 0 )) && streams_ok=$((streams_ok + 1))
  done

  NETWORK_MEASURE_BYTES="$total"
  NETWORK_MEASURE_SECONDS="$seconds"
  NETWORK_MEASURE_MBPS="$(awk -v b="$total" -v s="$seconds" 'BEGIN { if (s <= 0) print "0.0"; else printf "%.1f", (b*8)/(s*1000000) }')"
  NETWORK_MEASURE_HTTP_OK="$http_ok"
  NETWORK_MEASURE_STREAMS_OK="$streams_ok"
  rm -rf "$tmp"
  return 0
}

_network_measure_upload_parallel() {
  # usage: _network_measure_upload_parallel URL STREAMS BYTES_PER_STREAM TIMEOUT CERT KEY
  # Sets NETWORK_MEASURE_{BYTES,SECONDS,MBPS,HTTP_OK,STREAMS_OK}.
  local url="$1" streams="$2" bytes_per_stream="$3" timeout_s="$4" cert="$5" key="$6"
  local tmp start_ns end_ns seconds i total=0 http_ok=0 streams_ok=0

  NETWORK_MEASURE_BYTES=0
  NETWORK_MEASURE_SECONDS=0
  NETWORK_MEASURE_MBPS=0
  NETWORK_MEASURE_HTTP_OK=0
  NETWORK_MEASURE_STREAMS_OK=0

  [[ "$streams" =~ ^[1-9][0-9]*$ ]] || streams=1
  [[ "$bytes_per_stream" =~ ^[1-9][0-9]*$ ]] || return 1

  tmp="$(mktemp -d /tmp/network-upload.XXXXXX)" || return 1
  start_ns="$(_network_now_ns)"

  for ((i=1; i<=streams; i++)); do
    (
      # head exits on SIGPIPE when curl reaches its timeout; that is expected.
      (head -c "$bytes_per_stream" /dev/zero 2>/dev/null | \
        curl -L -sS \
          --connect-timeout 5 \
          --max-time "$timeout_s" \
          --cert "$cert" --key "$key" \
          --data-binary @- \
          -o /dev/null \
          -w '%{size_upload}\n%{http_code}\n' \
          "$url" \
          >"$tmp/$i.out" 2>"$tmp/$i.err") || true
    ) &
  done
  wait || true

  end_ns="$(_network_now_ns)"
  seconds="$(_network_elapsed_seconds "$start_ns" "$end_ns")"

  for ((i=1; i<=streams; i++)); do
    local bytes code
    bytes="$(sed -n '1p' "$tmp/$i.out" 2>/dev/null || true)"
    code="$(sed -n '2p' "$tmp/$i.out" 2>/dev/null || true)"
    [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
    total=$((total + bytes))
    [[ "$code" == 200 ]] && http_ok=$((http_ok + 1))
    (( bytes > 0 )) && streams_ok=$((streams_ok + 1))
  done

  NETWORK_MEASURE_BYTES="$total"
  NETWORK_MEASURE_SECONDS="$seconds"
  NETWORK_MEASURE_MBPS="$(awk -v b="$total" -v s="$seconds" 'BEGIN { if (s <= 0) print "0.0"; else printf "%.1f", (b*8)/(s*1000000) }')"
  NETWORK_MEASURE_HTTP_OK="$http_ok"
  NETWORK_MEASURE_STREAMS_OK="$streams_ok"
  rm -rf "$tmp"
  return 0
}

_network_prepare_home_client() {
  NETWORK_HOME_CERT_PATH="${NETWORK_HOME_CLIENT_CERT:-}"
  NETWORK_HOME_KEY_PATH="${NETWORK_HOME_CLIENT_KEY:-}"
  NETWORK_HOME_CLIENT_FILES_CREATED=false

  if [[ -n "$NETWORK_HOME_CERT_PATH" && -n "$NETWORK_HOME_KEY_PATH" \
        && -r "$NETWORK_HOME_CERT_PATH" && -r "$NETWORK_HOME_KEY_PATH" ]]; then
    return 0
  fi

  [[ -n "${NETWORK_HOME_CLIENT_CERT_B64:-}" && -n "${NETWORK_HOME_CLIENT_KEY_B64:-}" ]] || return 1
  command -v base64 >/dev/null 2>&1 || return 1

  mkdir -p /root/.secrets
  chmod 700 /root/.secrets
  NETWORK_HOME_CERT_PATH=/root/.secrets/network-test-client.crt
  NETWORK_HOME_KEY_PATH=/root/.secrets/network-test-client.key

  umask 077
  if ! printf '%s' "$NETWORK_HOME_CLIENT_CERT_B64" | base64 -d >"$NETWORK_HOME_CERT_PATH" 2>/dev/null; then
    rm -f "$NETWORK_HOME_CERT_PATH" "$NETWORK_HOME_KEY_PATH"
    umask 0022
    return 1
  fi
  if ! printf '%s' "$NETWORK_HOME_CLIENT_KEY_B64" | base64 -d >"$NETWORK_HOME_KEY_PATH" 2>/dev/null; then
    rm -f "$NETWORK_HOME_CERT_PATH" "$NETWORK_HOME_KEY_PATH"
    umask 0022
    return 1
  fi
  chmod 600 "$NETWORK_HOME_CERT_PATH" "$NETWORK_HOME_KEY_PATH"
  umask 0022
  NETWORK_HOME_CLIENT_FILES_CREATED=true
  return 0
}

_network_cleanup_home_client() {
  if [[ "${NETWORK_HOME_CLIENT_FILES_CREATED:-false}" == true ]] \
      && ! _network_bool_true "${NETWORK_HOME_KEEP_CLIENT_FILES:-false}"; then
    rm -f "${NETWORK_HOME_CERT_PATH:-}" "${NETWORK_HOME_KEY_PATH:-}"
  fi
  # Do not leave the private key duplicated in descendants' environment.
  unset NETWORK_HOME_CLIENT_CERT_B64 NETWORK_HOME_CLIENT_KEY_B64
}

_network_write_json() {
  local path="$NETWORK_LOG_FILE"
  mkdir -p "$(dirname "$path")"

  NETWORK_JSON_TIMESTAMP="$(date -Is)" \
  NETWORK_JSON_HOSTNAME="$(hostname 2>/dev/null || true)" \
  NETWORK_JSON_HF_ENABLED="${NETWORK_RESULT_HF_ENABLED:-false}" \
  NETWORK_JSON_HF_URL="${NETWORK_HF_TEST_URL:-}" \
  NETWORK_JSON_HF_STREAMS="${NETWORK_HF_STREAMS:-0}" \
  NETWORK_JSON_HF_STREAM_BYTES="${NETWORK_HF_STREAM_BYTES:-0}" \
  NETWORK_JSON_HF_TIMEOUT="${NETWORK_HF_TIMEOUT_SECONDS:-0}" \
  NETWORK_JSON_HF_FIRST="${NETWORK_RESULT_HF_FIRST_MBPS:-0}" \
  NETWORK_JSON_HF_RETEST="${NETWORK_RESULT_HF_RETEST_MBPS:-}" \
  NETWORK_JSON_HF_MBPS="${NETWORK_RESULT_HF_MBPS:-0}" \
  NETWORK_JSON_HF_CLASS="${NETWORK_RESULT_HF_CLASS:-skipped}" \
  NETWORK_JSON_HF_WARN="${NETWORK_HF_WARN_MBPS:-0}" \
  NETWORK_JSON_HF_CRITICAL="${NETWORK_HF_CRITICAL_MBPS:-0}" \
  NETWORK_JSON_HOME_ENABLED="${NETWORK_RESULT_HOME_ENABLED:-false}" \
  NETWORK_JSON_HOME_URL="${NETWORK_HOME_TEST_URL:-}" \
  NETWORK_JSON_HOME_STREAMS="${NETWORK_HOME_STREAMS:-0}" \
  NETWORK_JSON_HOME_BYTES="${NETWORK_HOME_TEST_BYTES:-0}" \
  NETWORK_JSON_HOME_TIMEOUT="${NETWORK_HOME_TIMEOUT_SECONDS:-0}" \
  NETWORK_JSON_HOME_DOWN="${NETWORK_RESULT_HOME_DOWN_MBPS:-0}" \
  NETWORK_JSON_HOME_UP="${NETWORK_RESULT_HOME_UP_MBPS:-0}" \
  NETWORK_JSON_HOME_DOWN_CLASS="${NETWORK_RESULT_HOME_DOWN_CLASS:-skipped}" \
  NETWORK_JSON_HOME_UP_CLASS="${NETWORK_RESULT_HOME_UP_CLASS:-skipped}" \
  NETWORK_JSON_HOME_WARN="${NETWORK_HOME_WARN_MBPS:-0}" \
  NETWORK_JSON_HOME_CRITICAL="${NETWORK_HOME_CRITICAL_MBPS:-0}" \
  NETWORK_JSON_OVERALL="${NETWORK_RESULT_OVERALL:-unknown}" \
  NETWORK_JSON_REPLACE="${NETWORK_RESULT_REPLACE_RECOMMENDED:-false}" \
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


def b(name):
    return os.environ.get(name, "false").lower() in {"1", "true", "yes", "on"}

retest_raw = os.environ.get("NETWORK_JSON_HF_RETEST", "")
obj = {
    "schema_version": 1,
    "timestamp": os.environ.get("NETWORK_JSON_TIMESTAMP", ""),
    "hostname": os.environ.get("NETWORK_JSON_HOSTNAME", ""),
    "pod": {
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID", ""),
        "runpod_public_ip": os.environ.get("RUNPOD_PUBLIC_IP", ""),
    },
    "huggingface": {
        "enabled": b("NETWORK_JSON_HF_ENABLED"),
        "url": os.environ.get("NETWORK_JSON_HF_URL", ""),
        "streams": i("NETWORK_JSON_HF_STREAMS"),
        "stream_bytes": i("NETWORK_JSON_HF_STREAM_BYTES"),
        "timeout_seconds": f("NETWORK_JSON_HF_TIMEOUT"),
        "first_mbps": f("NETWORK_JSON_HF_FIRST"),
        "retest_mbps": (f("NETWORK_JSON_HF_RETEST") if retest_raw else None),
        "mbps": f("NETWORK_JSON_HF_MBPS"),
        "classification": os.environ.get("NETWORK_JSON_HF_CLASS", "skipped"),
        "warn_threshold_mbps": f("NETWORK_JSON_HF_WARN"),
        "critical_threshold_mbps": f("NETWORK_JSON_HF_CRITICAL"),
    },
    "home": {
        "enabled": b("NETWORK_JSON_HOME_ENABLED"),
        "url": os.environ.get("NETWORK_JSON_HOME_URL", ""),
        "streams": i("NETWORK_JSON_HOME_STREAMS"),
        "bytes_per_stream": i("NETWORK_JSON_HOME_BYTES"),
        "timeout_seconds": f("NETWORK_JSON_HOME_TIMEOUT"),
        "download_mbps": f("NETWORK_JSON_HOME_DOWN"),
        "upload_mbps": f("NETWORK_JSON_HOME_UP"),
        "download_classification": os.environ.get("NETWORK_JSON_HOME_DOWN_CLASS", "skipped"),
        "upload_classification": os.environ.get("NETWORK_JSON_HOME_UP_CLASS", "skipped"),
        "warn_threshold_mbps": f("NETWORK_JSON_HOME_WARN"),
        "critical_threshold_mbps": f("NETWORK_JSON_HOME_CRITICAL"),
    },
    "overall": {
        "classification": os.environ.get("NETWORK_JSON_OVERALL", "unknown"),
        "replace_recommended": b("NETWORK_JSON_REPLACE"),
    },
}

with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(obj, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

_network_send_warning() {
  local hf_bad=false home_bad=false msg=""
  local hf_mib home_down_mib home_up_mib

  if [[ "${NETWORK_RESULT_HF_ENABLED:-false}" == true ]] \
      && _network_num_ge "${NETWORK_RESULT_HF_MBPS:-0}" 0.01 \
      && _network_num_lt "${NETWORK_RESULT_HF_MBPS:-0}" "$NETWORK_HF_WARN_MBPS"; then
    hf_bad=true
  fi

  if [[ "${NETWORK_RESULT_HOME_ENABLED:-false}" == true ]]; then
    if ! _network_num_ge "${NETWORK_RESULT_HOME_DOWN_MBPS:-0}" 0.01 \
        || ! _network_num_ge "${NETWORK_RESULT_HOME_UP_MBPS:-0}" 0.01 \
        || _network_num_lt "${NETWORK_RESULT_HOME_DOWN_MBPS:-0}" "$NETWORK_HOME_WARN_MBPS" \
        || _network_num_lt "${NETWORK_RESULT_HOME_UP_MBPS:-0}" "$NETWORK_HOME_WARN_MBPS"; then
      home_bad=true
    fi
  fi

  hf_mib="$(_network_mbps_to_mib_s "${NETWORK_RESULT_HF_MBPS:-0}")"
  home_down_mib="$(_network_mbps_to_mib_s "${NETWORK_RESULT_HOME_DOWN_MBPS:-0}")"
  home_up_mib="$(_network_mbps_to_mib_s "${NETWORK_RESULT_HOME_UP_MBPS:-0}")"

  if [[ "$hf_bad" == true ]]; then
    msg="🚨🚨 VERY SLOW POD NETWORK 🚨🚨

HF/CDN download: ${NETWORK_RESULT_HF_MBPS} Mbps (~${hf_mib} MiB/s)
Warning threshold: ${NETWORK_HF_WARN_MBPS} Mbps

This will significantly affect model downloads, custom-node installs and hff transfers.

RECOMMENDATION: replace this pod."
    if [[ "${NETWORK_RESULT_HOME_ENABLED:-false}" == true ]]; then
      msg+="

Direct home route:
Home → Pod: ${NETWORK_RESULT_HOME_DOWN_MBPS} Mbps (~${home_down_mib} MiB/s)
Pod → Home: ${NETWORK_RESULT_HOME_UP_MBPS} Mbps (~${home_up_mib} MiB/s)"
    fi
    tg "$msg" || true
    return 0
  fi

  if [[ "$home_bad" == true ]]; then
    msg="⚠️ SLOW DIRECT HOME ↔ POD ROUTE

Home → Pod: ${NETWORK_RESULT_HOME_DOWN_MBPS} Mbps (~${home_down_mib} MiB/s)
Pod → Home: ${NETWORK_RESULT_HOME_UP_MBPS} Mbps (~${home_up_mib} MiB/s)
Warning threshold: ${NETWORK_HOME_WARN_MBPS} Mbps

HF/CDN: ${NETWORK_RESULT_HF_MBPS} Mbps (~${hf_mib} MiB/s)
The pod Internet connection itself is not being rejected. Direct browser/app transfers may be painful."
    tg "$msg" || true
  fi
}

network_probe_startup() {
  local home_enabled=false home_ready=false

  NETWORK_RESULT_HF_ENABLED=false
  NETWORK_RESULT_HF_FIRST_MBPS=0
  NETWORK_RESULT_HF_RETEST_MBPS=""
  NETWORK_RESULT_HF_MBPS=0
  NETWORK_RESULT_HF_CLASS=skipped
  NETWORK_RESULT_HOME_ENABLED=false
  NETWORK_RESULT_HOME_DOWN_MBPS=0
  NETWORK_RESULT_HOME_UP_MBPS=0
  NETWORK_RESULT_HOME_DOWN_CLASS=skipped
  NETWORK_RESULT_HOME_UP_CLASS=skipped
  NETWORK_RESULT_OVERALL=healthy
  NETWORK_RESULT_REPLACE_RECOMMENDED=false

  if ! _network_bool_true "$NETWORK_TEST_ENABLE"; then
    echo "[network] Startup qualification disabled (NETWORK_TEST_ENABLE=${NETWORK_TEST_ENABLE})."
    _network_write_json
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "[network] WARN: curl is unavailable; skipping startup qualification." >&2
    NETWORK_RESULT_OVERALL=probe-failed
    _network_write_json
    return 0
  fi

  echo ""
  echo "=== Startup network qualification ==="

  if _network_bool_true "$NETWORK_HF_TEST_ENABLE"; then
    NETWORK_RESULT_HF_ENABLED=true
    echo "[network] HF/CDN: ${NETWORK_HF_STREAMS} parallel streams, up to $((NETWORK_HF_STREAM_BYTES / 1048576)) MiB each, ${NETWORK_HF_TIMEOUT_SECONDS}s ceiling"
    _network_measure_download_parallel \
      "$NETWORK_HF_TEST_URL" "$NETWORK_HF_STREAMS" "$NETWORK_HF_STREAM_BYTES" "$NETWORK_HF_TIMEOUT_SECONDS" || true
    NETWORK_RESULT_HF_FIRST_MBPS="$NETWORK_MEASURE_MBPS"
    NETWORK_RESULT_HF_MBPS="$NETWORK_MEASURE_MBPS"

    echo "[network] HF/CDN first pass: ${NETWORK_RESULT_HF_FIRST_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_HF_FIRST_MBPS") MiB/s)"

    if _network_bool_true "$NETWORK_HF_RETEST_ON_WARN" \
        && { ! _network_num_ge "$NETWORK_RESULT_HF_MBPS" 0.01 \
             || _network_num_lt "$NETWORK_RESULT_HF_MBPS" "$NETWORK_HF_WARN_MBPS"; }; then
      echo "[network] HF/CDN result is below ${NETWORK_HF_WARN_MBPS} Mbps; retesting once..."
      sleep "$NETWORK_HF_RETEST_DELAY_SECONDS"
      _network_measure_download_parallel \
        "$NETWORK_HF_TEST_URL" "$NETWORK_HF_STREAMS" "$NETWORK_HF_STREAM_BYTES" "$NETWORK_HF_TIMEOUT_SECONDS" || true
      NETWORK_RESULT_HF_RETEST_MBPS="$NETWORK_MEASURE_MBPS"
      # A single poor transient sample should not cause a discard warning.
      if _network_num_ge "$NETWORK_RESULT_HF_RETEST_MBPS" "$NETWORK_RESULT_HF_MBPS"; then
        NETWORK_RESULT_HF_MBPS="$NETWORK_RESULT_HF_RETEST_MBPS"
      fi
      echo "[network] HF/CDN retest: ${NETWORK_RESULT_HF_RETEST_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_HF_RETEST_MBPS") MiB/s)"
    fi

    NETWORK_RESULT_HF_CLASS="$(_network_classify "$NETWORK_RESULT_HF_MBPS" "$NETWORK_HF_WARN_MBPS" "$NETWORK_HF_CRITICAL_MBPS")"
    if _network_num_ge "$NETWORK_RESULT_HF_MBPS" 0.01 \
        && _network_num_lt "$NETWORK_RESULT_HF_MBPS" "$NETWORK_HF_WARN_MBPS"; then
      NETWORK_RESULT_OVERALL=slow-pod-network
      NETWORK_RESULT_REPLACE_RECOMMENDED=true
    elif ! _network_num_ge "$NETWORK_RESULT_HF_MBPS" 0.01; then
      NETWORK_RESULT_OVERALL=probe-failed
    fi
  fi

  case "$NETWORK_HOME_TEST_ENABLE" in
    auto|AUTO)
      [[ -n "$NETWORK_HOME_TEST_URL" ]] && home_enabled=true
      ;;
    *)
      _network_bool_true "$NETWORK_HOME_TEST_ENABLE" && home_enabled=true
      ;;
  esac

  if [[ "$home_enabled" == true ]]; then
    NETWORK_RESULT_HOME_ENABLED=true
    if _network_prepare_home_client; then
      home_ready=true
      local home_base="${NETWORK_HOME_TEST_URL%/}"
      echo "[network] Home HTTPS: ${NETWORK_HOME_STREAMS} stream(s), up to $((NETWORK_HOME_TEST_BYTES / 1048576)) MiB each, ${NETWORK_HOME_TIMEOUT_SECONDS}s per direction"

      _network_measure_download_parallel \
        "${home_base}/download?bytes=${NETWORK_HOME_TEST_BYTES}" \
        "$NETWORK_HOME_STREAMS" "$NETWORK_HOME_TEST_BYTES" "$NETWORK_HOME_TIMEOUT_SECONDS" \
        "$NETWORK_HOME_CERT_PATH" "$NETWORK_HOME_KEY_PATH" || true
      NETWORK_RESULT_HOME_DOWN_MBPS="$NETWORK_MEASURE_MBPS"
      NETWORK_RESULT_HOME_DOWN_CLASS="$(_network_classify "$NETWORK_RESULT_HOME_DOWN_MBPS" "$NETWORK_HOME_WARN_MBPS" "$NETWORK_HOME_CRITICAL_MBPS")"
      echo "[network] Home → Pod: ${NETWORK_RESULT_HOME_DOWN_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_HOME_DOWN_MBPS") MiB/s)"

      _network_measure_upload_parallel \
        "${home_base}/upload" \
        "$NETWORK_HOME_STREAMS" "$NETWORK_HOME_TEST_BYTES" "$NETWORK_HOME_TIMEOUT_SECONDS" \
        "$NETWORK_HOME_CERT_PATH" "$NETWORK_HOME_KEY_PATH" || true
      NETWORK_RESULT_HOME_UP_MBPS="$NETWORK_MEASURE_MBPS"
      NETWORK_RESULT_HOME_UP_CLASS="$(_network_classify "$NETWORK_RESULT_HOME_UP_MBPS" "$NETWORK_HOME_WARN_MBPS" "$NETWORK_HOME_CRITICAL_MBPS")"
      echo "[network] Pod → Home: ${NETWORK_RESULT_HOME_UP_MBPS} Mbps ($(_network_mbps_to_mib_s "$NETWORK_RESULT_HOME_UP_MBPS") MiB/s)"
    else
      echo "[network] WARN: home test configured but mTLS client certificate/key are unavailable or invalid; skipping it." >&2
      NETWORK_RESULT_HOME_DOWN_CLASS=probe-failed
      NETWORK_RESULT_HOME_UP_CLASS=probe-failed
    fi
  else
    echo "[network] Home HTTPS test not configured; skipping secondary route check."
  fi

  if [[ "$home_ready" == true && "$NETWORK_RESULT_REPLACE_RECOMMENDED" != true ]]; then
    if ! _network_num_ge "$NETWORK_RESULT_HOME_DOWN_MBPS" 0.01 \
        || ! _network_num_ge "$NETWORK_RESULT_HOME_UP_MBPS" 0.01 \
        || _network_num_lt "$NETWORK_RESULT_HOME_DOWN_MBPS" "$NETWORK_HOME_WARN_MBPS" \
        || _network_num_lt "$NETWORK_RESULT_HOME_UP_MBPS" "$NETWORK_HOME_WARN_MBPS"; then
      NETWORK_RESULT_OVERALL=home-route-slow
    fi
  fi

  echo "[network] HF/CDN classification: ${NETWORK_RESULT_HF_CLASS}"
  if [[ "${NETWORK_RESULT_HOME_ENABLED}" == true ]]; then
    echo "[network] Home route classification: down=${NETWORK_RESULT_HOME_DOWN_CLASS} up=${NETWORK_RESULT_HOME_UP_CLASS}"
  fi
  echo "[network] Overall: ${NETWORK_RESULT_OVERALL}; replace_recommended=${NETWORK_RESULT_REPLACE_RECOMMENDED}"

  _network_write_json
  _network_send_warning
  _network_cleanup_home_client
  echo "[network] Result: ${NETWORK_LOG_FILE}"
  echo "=== Network qualification complete ==="
  echo ""
  return 0
}
