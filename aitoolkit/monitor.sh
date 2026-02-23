#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- args ---
[[ $# -ge 1 ]] || die "usage: $0 <run_name_or_outdir>"
RUN_ARG="$1"; shift || true

# Optional: keep shell attached
FOREGROUND="${FOREGROUND:-0}"   # 1 = stay in foreground; 0 = daemonize (recommended)

# --- constants ---
AITK_ROOT="/app/ai-toolkit"
OUT_BASE="${AITK_ROOT}/output"
STATUS_PY="/app/pod-runtime/aitoolkit/aitoolkit_status.py"

# Optional: allow installs (default off to avoid hangs)
MONITOR_ALLOW_INSTALL="${MONITOR_ALLOW_INSTALL:-0}"   # 1 = may apt/apk install missing deps

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
  [[ "$MONITOR_ALLOW_INSTALL" == "1" ]] || return 127

  echo "[need_apt] missing: $cmd — attempting apt install: $pkg" >&2
  command -v apt-get >/dev/null 2>&1 || { echo "[need_apt] ERROR: apt-get not found" >&2; return 127; }

  local run=()
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    run=(bash -c)          # IMPORTANT: no -l (login) to avoid sourcing profiles
  else
    command -v sudo >/dev/null 2>&1 || { echo "[need_apt] ERROR: sudo not found" >&2; return 127; }
    run=(sudo -E bash -c)
  fi

  local apt_env="export DEBIAN_FRONTEND=noninteractive;"

  # Put a hard timeout on apt so we never wedge your interactive shell
  local tmo="${APT_TIMEOUT_SEC:-120}"

  timeout "${tmo}"s "${run[@]}" "${apt_env} apt-get update" >/dev/null 2>&1 || true
  timeout "${tmo}"s "${run[@]}" "${apt_env} apt-get install -y --no-install-recommends $pkg" >/dev/null 2>&1 || true

  command -v "$cmd" >/dev/null 2>&1 && return 0
  echo "[need_apt] WARN: $cmd still missing after apt attempt (pkg: $pkg)" >&2
  return 127
}

need_pkg() {
  local cmd="$1"
  local pkg_deb="${2:-$1}"
  local pkg_apk="${3:-$pkg_deb}"

  command -v "$cmd" >/dev/null 2>&1 && return 0
  [[ "$MONITOR_ALLOW_INSTALL" == "1" ]] || return 127

  if command -v apt-get >/dev/null 2>&1; then
    need_apt "$cmd" "$pkg_deb"
    return $?
  fi

  if command -v apk >/dev/null 2>&1; then
    echo "[need_pkg] missing: $cmd — attempting apk add: $pkg_apk" >&2
    timeout "${APT_TIMEOUT_SEC:-120}"s apk add --no-cache $pkg_apk >/dev/null 2>&1 || true
    command -v "$cmd" >/dev/null 2>&1 && return 0
  fi

  echo "[need_pkg] WARN: cannot install $cmd (no apt-get/apk or install disabled)" >&2
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

# --- wrapper logs (so you can debug hangs) ---
WRAP_LOG="${OUTDIR}/status_wrapper.log"
exec 3>>"$WRAP_LOG"
echo "[wrapper] $(date) starting monitor.sh for $RUN_NAME (pid=$$)" >&3
echo "[wrapper] FOREGROUND=$FOREGROUND MONITOR_ALLOW_INSTALL=$MONITOR_ALLOW_INSTALL" >&3

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
export TELEGRAM_SAMPLES_STEP="${TRAIN_STATUS_TELEGRAM_SAMPLES_STEP:-latest}"
export TELEGRAM_SAMPLES_ON_STATUS="${TRAIN_STATUS_TELEGRAM_SAMPLES_ON_STATUS:-0}"
export TELEGRAM_SAMPLES_INCLUDE_PROMPTS="${TRAIN_STATUS_TELEGRAM_SAMPLES_INCLUDE_PROMPTS:-0}"
export TELEGRAM_SAMPLES_PROMPT_CHARS="${TRAIN_STATUS_TELEGRAM_SAMPLES_PROMPT_CHARS:-140}"

# Telegram config (non-blocking)
export TELEGRAM_ENABLE="${TELEGRAM_ENABLE:-1}"
export TELEGRAM_PRE="${TELEGRAM_PRE:-1}"
export TELEGRAM_SEND_BIN="${TELEGRAM_SEND_BIN:-telegram-send}"

if [[ "${TELEGRAM_ENABLE}" != "0" ]]; then
  ensure_telegram_cfg
  if ! command -v telegram-send >/dev/null 2>&1; then
    echo "[wrapper] telegram-send missing" >&3
    need_pkg telegram-send telegram-send telegram-send || true
  fi
fi

# Optional: wait up to 10 min for DB to appear (but don’t wedge your shell)
WAIT_FOR_DB="${WAIT_FOR_DB:-0}"         # default 0 because Python can self-wait + heartbeat
WAIT_FOR_DB_FAIL="${WAIT_FOR_DB_FAIL:-0}"

if [[ "$WAIT_FOR_DB" == "1" ]]; then
  echo "[wrapper] waiting for DB: ${AI_TOOLKIT_LOSS_DB}" >&3
  for _ in {1..600}; do
    [[ -f "${AI_TOOLKIT_LOSS_DB}" ]] && break
    sleep 1
  done
  if [[ "$WAIT_FOR_DB_FAIL" == "1" && ! -f "${AI_TOOLKIT_LOSS_DB}" ]]; then
    die "loss DB did not appear after 10 minutes: ${AI_TOOLKIT_LOSS_DB}"
  fi
fi

echo "Starting monitor for ${RUN_NAME}..."
echo "[wrapper] starting python monitor @ $(date)" >&3

MON_PID=""
cleanup() {
  set +e
  if [[ -n "${MON_PID}" ]] && kill -0 "${MON_PID}" 2>/dev/null; then
    echo "[wrapper] stopping monitor pid=${MON_PID} @ $(date)" >&3
    kill "${MON_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

python "$STATUS_PY" --loop > "${OUTDIR}/status_monitor.log" 2>&1 &
MON_PID=$!
echo "$MON_PID" > "${OUTDIR}/status_monitor.pid"
echo "[wrapper] monitor pid=${MON_PID}" >&3

if [[ "$FOREGROUND" == "1" ]]; then
  wait "$MON_PID" || true
  echo "Monitor exited."
  echo "[wrapper] monitor exited @ $(date)" >&3
else
  echo "[wrapper] daemonized (foreground=0). tail -f ${OUTDIR}/status_monitor.log" >&3
  disown "$MON_PID" 2>/dev/null || true
fi
