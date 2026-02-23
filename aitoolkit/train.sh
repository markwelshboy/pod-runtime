#!/usr/bin/env bash
set -euo pipefail

OUTDIR="$1"            # e.g. /app/ai-toolkit/output/<run>
shift

cd /app/ai-toolkit

mkdir -p output
mkdir -p datasets
mkdir -p config

mkdir -p "output/$OUTDIR"

mkdir -p "/root/.config"
cat > "/root/.config/telegram-send.conf" <<EOF
[telegram]
token = $TELEGRAM_BOT_TOKEN
chat_id = $TELEGRAM_CHAT_ID
EOF

# Pull down data and config (if not already present)
if [ ! -d "datasets/5h1v" ]; then
  hff get training/5h1v.tar
  tar -xvf 5h1v.tar -C datasets
fi
if [ ! -d "datasets/5h1v_control_images" ]; then
  hff get training/5h1v_control_images.tar
  tar -xvf 5h1v_control_images.tar -C datasets
fi
if [ ! -f "config/config.yaml" ]; then
  hff get training/$OUTDIR.yaml
  mv $OUTDIR.yaml $OUTDIR/training_config.yaml
fi

export AI_TOOLKIT_OUTPUT_DIR="/app/ai-toolkit/output/$OUTDIR"
export AI_TOOLKIT_LOSS_DB="$AI_TOOLKIT_OUTPUT_DIR/loss_log.db"
export STATUS_MAX_STEPS="${STATUS_MAX_STEPS:-20000}"
export STATUS_INTERVAL_MIN="${STATUS_INTERVAL_MIN:-30}"
export STATUS_ALERT_MODE="${STATUS_ALERT_MODE:-always}"
export STATUS_MIN_STEP_ADVANCE="${STATUS_MIN_STEP_ADVANCE:-500}"
export STATUS_ROLLING_N="${STATUS_ROLLING_N:-100}"
export STATUS_EMA_ALPHA="${STATUS_EMA_ALPHA:-0.10}"
export STATUS_SLOPE_N="${STATUS_SLOPE_N:-300}"
export STATUS_SPEED_N="${STATUS_SPEED_N:-300}"

need_apt telegram-send

# Start monitor
python /app/pod-runtime/aitoolkit/ai_toolkit_status.py --loop \
  > "$OUTDIR/status_monitor.log" 2>&1 &
MON_PID=$!
echo "$MON_PID" > "$OUTDIR/status_monitor.pid"

# Start training (whatever your command is)
python run.py $OUTDIR/training_config.yaml &
TRAIN_PID=$!
echo "$TRAIN_PID" > "$OUTDIR/trainpid.txt"

# Wait for training, then stop monitor
wait "$TRAIN_PID" || true
kill "$MON_PID" 2>/dev/null || true