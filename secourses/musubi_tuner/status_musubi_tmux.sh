#!/usr/bin/env bash
set -euo pipefail
: "${MUSUBI_SESSION:=musubi}"
: "${MUSUBI_DOWNLOADER_SESSION:=musubi-dl}"

tmux ls 2>/dev/null | grep -E "^(${MUSUBI_SESSION}|${MUSUBI_DOWNLOADER_SESSION}):" || true
