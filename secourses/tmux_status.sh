#!/usr/bin/env bash
set -euo pipefail

: "${COMFY_PORT:=3000}"
: "${SWARMUI_PORT:=7861}"

echo ""
echo "=============================="
echo "  tmux sessions on this pod"
echo "=============================="
if command -v tmux >/dev/null 2>&1; then
  tmux ls 2>/dev/null || echo "(none)"
else
  echo "tmux not installed"
fi

echo ""
echo "=============================="
echo "  Ports (expected)"
echo "=============================="
echo "ComfyUI   : ${COMFY_PORT}    (http://localhost:${COMFY_PORT})"
echo "SwarmUI   : ${SWARMUI_PORT}  (http://localhost:${SWARMUI_PORT})"

echo ""
echo "=============================="
echo "  Attach commands"
echo "=============================="
echo "tmux attach -t comfyui            # if you run comfyui in tmux"
echo "tmux attach -t swarmui            # SwarmUI"
echo "tmux attach -t swarmui_downloader # Downloader"
echo ""
