#!/usr/bin/env bash
set -euo pipefail
: "${MUSUBI_SESSION:=musubi}"
: "${MUSUBI_DOWNLOADER_SESSION:=musubi-dl}"

tmux kill-session -t "${MUSUBI_SESSION}" 2>/dev/null || true
tmux kill-session -t "${MUSUBI_DOWNLOADER_SESSION}" 2>/dev/null || true
echo "[musubi] stopped (if running)"
