#!/usr/bin/env bash
set -euo pipefail

log() { echo "[bootstrap] $*"; }

export DEBIAN_FRONTEND=noninteractive
: "${WORKSPACE:=/workspace}"

log "Starting pod-runtime bootstrap"
log "Workspace: ${WORKSPACE}"

# Ensure we're running from pod-runtime root
cd "$(dirname "$0")"

# --------------------------------------------------------------------
# Baseline packages (NO SSH – Vast already provides it)
# Guarded so restarts are fast.
# --------------------------------------------------------------------
if ! command -v tmux >/dev/null 2>&1; then
  log "Installing baseline packages..."
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl wget \
    git git-lfs \
    tmux jq unzip gawk coreutils \
    net-tools rsync ncurses-base bash-completion less nano \
    ninja-build aria2 vim \
    psmisc
  git lfs install --system || true
  apt-get clean
  rm -rf /var/lib/apt/lists/*
else
  log "Baseline packages already installed; skipping apt."
fi

# --------------------------------------------------------------------
# Optional: source helpers (for env, aliases, functions, etc.)
# --------------------------------------------------------------------
if [[ -f "./helpers.sh" ]]; then
  log "Sourcing helpers.sh"
  # shellcheck disable=SC1091
  source "./helpers.sh"
else
  log "helpers.sh not found (this is OK for playground use)"
fi

# --------------------------------------------------------------------
# Workspace sanity
# --------------------------------------------------------------------
mkdir -p "${WORKSPACE}"
chmod 755 "${WORKSPACE}" || true

log "Bootstrap complete."
