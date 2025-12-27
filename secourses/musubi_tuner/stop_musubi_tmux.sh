#!/usr/bin/env bash
set -euo pipefail
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SESSION:=musubi-${MUSUBI_PORT}}"
: "${MUSUBI_DL_SESSION:=musubi_downloader-interactive}"

tmux kill-session -t "${MUSUBI_SESSION}" 2>/dev/null || true
tmux kill-session -t "${MUSUBI_DL_SESSION}" 2>/dev/null || true
echo "[musubi-*] stopped (if running)"
