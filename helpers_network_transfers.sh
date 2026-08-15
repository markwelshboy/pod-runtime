#!/usr/bin/env bash
# ======================================================================
# helpers_network_transfers.sh — scoped network-transfer worker waits
# ======================================================================
# These definitions override the transfer primitives from helpers_network.sh.
# A bare `wait` is unsafe in bootstrap scripts because process substitutions
# such as `exec > >(tee ...)` are also child processes and can live for the
# entire session. Track and wait only for curl workers created by each probe.

_network_measure_download_parallel() {
  # usage: _network_measure_download_parallel URL STREAMS BYTES_PER_STREAM TIMEOUT [CERT] [KEY]
  # Sets NETWORK_MEASURE_{BYTES,SECONDS,MBPS,HTTP_OK,STREAMS_OK}.
  local url="$1" streams="$2" bytes_per_stream="$3" timeout_s="$4"
  local cert="${5:-}" key="${6:-}"
  local tmp start_ns end_ns seconds i total=0 http_ok=0 streams_ok=0
  local range_end=$((bytes_per_stream - 1))
  local -a auth_args=()
  local -a worker_pids=()

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
    worker_pids+=("$!")
  done

  local worker_pid
  for worker_pid in "${worker_pids[@]}"; do
    wait "$worker_pid" || true
  done

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
  local -a worker_pids=()

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
    worker_pids+=("$!")
  done

  local worker_pid
  for worker_pid in "${worker_pids[@]}"; do
    wait "$worker_pid" || true
  done

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
