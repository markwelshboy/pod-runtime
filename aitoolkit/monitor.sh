#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

# --- args ---
[[ $# -ge 1 ]] || die "usage: $0 <run_name_or_outdir>"
RUN_ARG="$1"; shift || true

# --- constants ---
AITK_ROOT="/app/ai-toolkit"
OUT_BASE="${AITK_ROOT}/output"

STATUS_PY="/app/pod-runtime/aitoolkit/aitoolkit_status.py"

ensure_telegram_cfg() {
  # Create telegram-send.conf only if env vars exist
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    mkdir -p /root/.config
    cat > /root/.config/telegram-send.conf <<EOF
[telegram]
token = ${TELEGRAM_BOT_TOKEN}
chat_id = ${TELEGRAM_CHAT_ID}
EOF
    chmod 600 /root/.config/telegram-send.conf
  fi
}

need_apt() {
  local cmd="$1"
  local pkg="${2:-$1}"

  # Allow: need_apt cmd "pkg1 pkg2 ..."
  # Allow: need_apt cmd pkg1 (simple)
  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi

  echo "[need_apt] missing: $cmd — attempting apt install: $pkg" >&2

  # Bail early if apt-get doesn't exist (alpine/scratch/etc)
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "[need_apt] ERROR: apt-get not found. Base image is not Debian/Ubuntu (try apk add / yum / dnf)." >&2
    return 127
  fi

  # Choose runner (root vs sudo)
  local run=()
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    run=(bash -lc)
  else
    if command -v sudo >/dev/null 2>&1; then
      run=(sudo -E bash -lc)
    else
      echo "[need_apt] ERROR: $cmd missing and not root; sudo not installed. Run as root or install sudo." >&2
      return 127
    fi
  fi

  # Non-interactive apt
  local apt_env="export DEBIAN_FRONTEND=noninteractive;"

  # Update (retry once)
  "${run[@]}" "${apt_env} apt-get update" >/dev/null 2>&1 || \
  "${run[@]}" "${apt_env} apt-get update" >/dev/null 2>&1 || true

  # Install best-effort
  "${run[@]}" "${apt_env} apt-get install -y --no-install-recommends $pkg" >/dev/null 2>&1 || true

  # Verify
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[need_apt] ERROR: required command not found after apt install: $cmd (pkg: $pkg)" >&2
    echo "[need_apt] Debug info:" >&2
    "${run[@]}" "cat /etc/os-release 2>/dev/null | sed -n '1,20p' >&2 || true"
    "${run[@]}" "ls -l /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null >&2 || true"
    "${run[@]}" "grep -Rhs '^[^#].*deb ' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null >&2 || true"
    return 127
  fi

  return 0
}

need_pkg() {
  local cmd="$1"
  local pkg_deb="${2:-$1}"
  local pkg_apk="${3:-$pkg_deb}"

  command -v "$cmd" >/dev/null 2>&1 && return 0

  if command -v apt-get >/dev/null 2>&1; then
    need_apt "$cmd" "$pkg_deb"
    return $?
  fi

  if command -v apk >/dev/null 2>&1; then
    echo "[need_pkg] missing: $cmd — attempting apk add: $pkg_apk" >&2
    apk add --no-cache $pkg_apk >/dev/null 2>&1 || true
    command -v "$cmd" >/dev/null 2>&1 && return 0
  fi

  echo "[need_pkg] ERROR: cannot install $cmd (no apt-get/apk found)" >&2
  return 127
}

maybe_need_apt() {
  # Optional: install telegram-send if need_apt helper exists
  if have need_apt; then
    need_apt telegram-send
  elif ! have telegram-send; then
    echo "WARN: telegram-send not found and need_apt not available; monitor will print to stdout unless TELEGRAM_ENABLE=0" >&2
  fi
}

# --- normalize OUTDIR ---
# Allow user to pass "5H1V_runname" or "/app/ai-toolkit/output/5H1V_runname"
if [[ "$RUN_ARG" = /* ]]; then
  OUTDIR="$RUN_ARG"
else
  OUTDIR="${OUT_BASE}/${RUN_ARG}"
fi
RUN_NAME="$(basename "$OUTDIR")"

# --- status env ---
export AI_TOOLKIT_OUTPUT_DIR="$OUTDIR"
export AI_TOOLKIT_LOSS_DB="${AI_TOOLKIT_OUTPUT_DIR}/loss_log.db"

export MAX_STEPS="${TRAIN_STATUS_MAX_STEPS:-20000}"
export INTERVAL_MIN="${TRAIN_STATUS_INTERVAL_MIN:-30}"
export ALERT_MODE="${TRAIN_STATUS_ALERT_MODE:-always}"
export MIN_STEP_ADVANCE="${TRAIN_STATUS_MIN_STEP_ADVANCE:-500}"
export ROLLING_N="${TRAIN_STATUS_ROLLING_N:-100}"
export EMA_ALPHA="${TRAIN_STATUS_EMA_ALPHA:-0.10}"
export SLOPE_N="${TRAIN_STATUS_SLOPE_N:-300}"
export SPEED_N="${TRAIN_STATUS_SPEED_N:-300}"

# wait up to 10 min for DB to appear
for i in {1..600}; do
  [[ -f "${AI_TOOLKIT_LOSS_DB}" ]] && break
  sleep 1
done

# --- start monitor ---
echo "Starting monitor..."
python "$STATUS_PY" --loop > "${OUTDIR}/status_monitor.log" 2>&1 &
MON_PID=$!
echo "$MON_PID" > "${OUTDIR}/status_monitor.pid"
