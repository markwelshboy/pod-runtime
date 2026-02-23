#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- args ---
[[ $# -ge 1 ]] || die "usage: $0 <run_name_or_outdir>"
RUN_ARG="$1"; shift || true

# --- constants ---
AITK_ROOT="/app/ai-toolkit"
OUT_BASE="${AITK_ROOT}/output"

# FIX: ensure this matches your installed filename
STATUS_PY="/app/pod-runtime/aitoolkit/aitoolkit_status.py"

ensure_telegram_cfg() {
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

  command -v "$cmd" >/dev/null 2>&1 && return 0

  echo "[need_apt] missing: $cmd — attempting apt install: $pkg" >&2
  command -v apt-get >/dev/null 2>&1 || { echo "[need_apt] ERROR: apt-get not found" >&2; return 127; }

  local run=()
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    run=(bash -lc)
  else
    command -v sudo >/dev/null 2>&1 || { echo "[need_apt] ERROR: sudo not found" >&2; return 127; }
    run=(sudo -E bash -lc)
  fi

  local apt_env="export DEBIAN_FRONTEND=noninteractive;"

  "${run[@]}" "${apt_env} apt-get update" >/dev/null 2>&1 || \
  "${run[@]}" "${apt_env} apt-get update" >/dev/null 2>&1 || true

  "${run[@]}" "${apt_env} apt-get install -y --no-install-recommends $pkg" >/dev/null 2>&1 || true

  command -v "$cmd" >/dev/null 2>&1 && return 0

  echo "[need_apt] ERROR: required command not found after install: $cmd (pkg: $pkg)" >&2
  return 127
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

# --- normalize OUTDIR ---
if [[ "$RUN_ARG" = /* ]]; then
  OUTDIR="$RUN_ARG"
else
  OUTDIR="${OUT_BASE}/${RUN_ARG}"
fi
RUN_NAME="$(basename "$OUTDIR")"

# --- sanity checks ---
[[ -d "$AITK_ROOT" ]] || die "AITK_ROOT not found: $AITK_ROOT"
[[ -f "$STATUS_PY" ]] || die "Monitor script not found: $STATUS_PY"
mkdir -p "$OUTDIR"

cd "$AITK_ROOT"

# Ensure telegram-send exists if telegram enabled
: "${TELEGRAM_ENABLE:=1}"
if [[ "${TELEGRAM_ENABLE}" != "0" ]]; then
  need_pkg telegram-send telegram-send telegram-send || true
  ensure_telegram_cfg
fi

export TELEGRAM_PRE="${TELEGRAM_PRE:-1}"
export TELEGRAM_SEND_BIN="${TELEGRAM_SEND_BIN:-telegram-send}"

# --- status env ---
export AI_TOOLKIT_OUTPUT_DIR="$OUTDIR"
export AI_TOOLKIT_LOSS_DB="${AI_TOOLKIT_OUTPUT_DIR}/loss_log.db"
export AI_TOOLKIT_SAMPLES_DIR="$AI_TOOLKIT_OUTPUT_DIR/samples"
export RUN_TITLE="${RUN_TITLE:-$RUN_NAME}"

export MAX_STEPS="${TRAIN_STATUS_MAX_STEPS:-20000}"
export INTERVAL_MIN="${TRAIN_STATUS_INTERVAL_MIN:-30}"

# Alerting
export BAD_JUMP_FRAC="${TRAIN_STATUS_BAD_JUMP_FRAC:-0.25}"
export ALERT_MODE="${TRAIN_STATUS_ALERT_MODE:-always}"            # always|interesting|bad
export MIN_STEP_ADVANCE="${TRAIN_STATUS_MIN_STEP_ADVANCE:-500}"
export SPIKE_MULT="${TRAIN_STATUS_SPIKE_MULT:-2.0}"

# Stats
export ROLLING_N="${TRAIN_STATUS_ROLLING_N:-200}"
export EMA_ALPHA="${TRAIN_STATUS_EMA_ALPHA:-0.10}"
export SLOPE_N="${TRAIN_STATUS_SLOPE_N:-500}"
export SPEED_N="${TRAIN_STATUS_SPEED_N:-300}"
export PLATEAU_ABS_PER_1K="${TRAIN_STATUS_PLATEAU_ABS_PER_1K:-0.0015}"

export SLOPE_FLAT_PER_1K="${TRAIN_STATUS_SLOPE_FLAT_PER_1K:-0.0015}"
export SLOPE_BAD_PER_1K="${TRAIN_STATUS_SLOPE_BAD_PER_1K:-0.004}"

# Samples
export TELEGRAM_SAMPLES="${TRAIN_STATUS_TELEGRAM_SAMPLES:-0}"
export TELEGRAM_SAMPLES_EVERY="${TRAIN_STATUS_TELEGRAM_SAMPLES_EVERY:-auto}"
export TELEGRAM_SAMPLES_MAX="${TRAIN_STATUS_TELEGRAM_SAMPLES_MAX:-4}"
export TELEGRAM_SAMPLES_STEP="${TRAIN_STATUS_TELEGRAM_SAMPLES_STEP:-latest}"   # latest|nearest|exact
export TELEGRAM_SAMPLES_ON_STATUS="${TRAIN_STATUS_TELEGRAM_SAMPLES_ON_STATUS:-0}"
export TELEGRAM_SAMPLES_INCLUDE_PROMPTS="${TRAIN_STATUS_TELEGRAM_SAMPLES_INCLUDE_PROMPTS:-0}"
export TELEGRAM_SAMPLES_PROMPT_CHARS="${TRAIN_STATUS_TELEGRAM_SAMPLES_PROMPT_CHARS:-140}"

# --- cleanup handling ---
MON_PID=""
cleanup() {
  set +e
  if [[ -n "${MON_PID}" ]] && kill -0 "${MON_PID}" 2>/dev/null; then
    echo "Stopping monitor (pid=${MON_PID})..."
    kill "${MON_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Optional: wait up to 10 min for DB to appear (but don't fail hard unless you want to)
WAIT_FOR_DB="${WAIT_FOR_DB:-1}"         # 1=wait, 0=don't wait
WAIT_FOR_DB_FAIL="${WAIT_FOR_DB_FAIL:-0}" # 1=die if missing after wait

if [[ "$WAIT_FOR_DB" == "1" ]]; then
  for _ in {1..600}; do
    [[ -f "${AI_TOOLKIT_LOSS_DB}" ]] && break
    sleep 1
  done
  if [[ "$WAIT_FOR_DB_FAIL" == "1" && ! -f "${AI_TOOLKIT_LOSS_DB}" ]]; then
    die "loss DB did not appear after 10 minutes: ${AI_TOOLKIT_LOSS_DB}"
  fi
fi

# --- start monitor ---
echo "Starting monitor for ${RUN_NAME}..."
python "$STATUS_PY" --loop > "${OUTDIR}/status_monitor.log" 2>&1 &
MON_PID=$!
echo "$MON_PID" > "${OUTDIR}/status_monitor.pid"

wait "$MON_PID" || true
echo "Monitor exited."