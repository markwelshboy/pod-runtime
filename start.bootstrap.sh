#!/usr/bin/env bash
set -euo pipefail

log() { echo "[bootstrap] $*"; }

: "${WORKSPACE:=/workspace}"
export DEBIAN_FRONTEND=noninteractive

cd "$(dirname "$0")"  # pod-runtime root

# If you want the full "known-good" package set:
if ! dpkg -s tmux >/dev/null 2>&1; then
  log "Installing baseline packages..."
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl wget \
    git git-lfs \
    tmux jq unzip gawk coreutils \
    net-tools rsync ncurses-base bash-completion less nano \
    ninja-build aria2 vim \
    psmisc \
    openssh-server
  mkdir -p /run/sshd /var/run/sshd
  git lfs install --system || true
  apt-get clean
  rm -rf /var/lib/apt/lists/*
else
  log "Baseline packages already present; skipping apt."
fi

# Source helpers and run your ssh setup
if [[ -f "./helpers.sh" ]]; then
  # shellcheck disable=SC1091
  source "./helpers.sh"
else
  log "ERR: helpers.sh not found in pod-runtime root"
  exit 1
fi

if declare -F setup_ssh >/dev/null 2>&1; then
  log "Running setup_ssh..."
  setup_ssh
else
  log "ERR: setup_ssh not found after sourcing helpers.sh"
  exit 1
fi

log "Bootstrap done."
