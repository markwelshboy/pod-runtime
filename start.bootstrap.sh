#!/usr/bin/env bash
set -euo pipefail

log() { echo "[bootstrap] $*"; }

export DEBIAN_FRONTEND=noninteractive
: "${WORKSPACE:=/workspace}"
: "${HF_HOME:=/workspace}"

# pod-runtime root = where this script lives
POD_RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="${WORKSPACE}/.podruntime_baseline_installed.v1"

log "Starting pod-runtime bootstrap"
log "Workspace : ${WORKSPACE}"
log "PodRuntime: ${POD_RUNTIME}"

# Workspace must exist before stamp + your env script side-effects
mkdir -p "${WORKSPACE}"
chmod 755 "${WORKSPACE}" || true

# --------------------------------------------------------------------
# Baseline packages (first run per /workspace volume)
# --------------------------------------------------------------------
if [[ ! -f "${STAMP}" ]]; then
  log "Installing baseline packages (first run)..."
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl wget \
    git git-lfs \
    jq unzip gawk coreutils \
    net-tools rsync ncurses-base bash-completion less nano \
    ninja-build aria2 vim \
    psmisc
  git lfs install --system || true
  apt-get clean
  rm -rf /var/lib/apt/lists/*
  date -Is > "${STAMP}"
  log "Baseline install complete; wrote ${STAMP}"
else
  log "Baseline already installed (stamp exists): ${STAMP}"
fi

# --------------------------------------------------------------------
# Source your "env.sh" (it's named .env but it's a shell script)
# --------------------------------------------------------------------
ENV_SH="${POD_RUNTIME}/.env"
if [[ -f "${ENV_SH}" ]]; then
  log "Sourcing ${ENV_SH}"
  # shellcheck disable=SC1090
  source "${ENV_SH}"
else
  log "${ENV_SH} not found (OK for playground)"
fi

# --------------------------------------------------------------------
# Helpers (optional)
# --------------------------------------------------------------------
HELPERS="${POD_RUNTIME}/helpers.sh"
if [[ -f "${HELPERS}" ]]; then
  log "Sourcing ${HELPERS}"
  # shellcheck disable=SC1090
  source "${HELPERS}"
else
  log "${HELPERS} not found (OK for playground)"
fi

cd "${WORKSPACE}"
log "Bootstrap complete."
