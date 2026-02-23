#!/usr/bin/env bash
set -euo pipefail

export MAX_STEPS=20000
export INTERVAL_MIN=30
export ALERT_MODE=always      # or always
export MIN_STEP_ADVANCE=500
export ROLLING_N=100
export EMA_ALPHA=0.10
export SLOPE_N=300
export SPEED_N=300

nohup python /app/pod-runtime/ai_toolkit_status.py --loop \
  > status_monitor.log 2>&1 &
echo $! > status_monitor.pid