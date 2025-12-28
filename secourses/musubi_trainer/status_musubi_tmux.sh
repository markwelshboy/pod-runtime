#!/usr/bin/env bash
set -euo pipefail
: "${MUSUBI_PORT:=7863}"
: "${MUSUBI_SESSION:=musubi-${MUSUBI_PORT}}"
: "${MUSUBI_DL_SESSION:=musubi_downloader-interactive}"

tmux ls 2>/dev/null | grep -E "^(${MUSUBI_SESSION}|${MUSUBI_DL_SESSION}):" || true
