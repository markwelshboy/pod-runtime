#!/usr/bin/env bash
set -euo pipefail

log(){ echo "[bootstrap] $*"; }

export DEBIAN_FRONTEND=noninteractive
: "${WORKSPACE:=/workspace}"
: "${HF_HOME:=/workspace}"

# Where this script lives (pod-runtime root)
POD_RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stamp controls baseline install once per /workspace volume
: "${BASELINE_STAMP:=${WORKSPACE}/.podruntime_baseline_installed.v1}"

# Behaviour toggles
: "${BOOTSTRAP_INSTALL_BASELINE:=1}"     # 1=yes baseline apt, 0=skip
: "${BOOTSTRAP_ENABLE_SSH:=auto}"        # auto|1|0
: "${BOOTSTRAP_KEEPALIVE:=1}"            # 1=tail forever at end
: "${BOOTSTRAP_PULL_REPO:=0}"            # 1=pull pod-runtime (if it's a git repo)

log "Workspace : ${WORKSPACE}"
log "PodRuntime: ${POD_RUNTIME}"

mkdir -p "${WORKSPACE}"
chmod 755 "${WORKSPACE}" || true

# Optionally update pod-runtime itself (useful on long-lived volumes)
if [[ "${BOOTSTRAP_PULL_REPO}" == "1" && -d "${POD_RUNTIME}/.git" ]]; then
  log "Updating pod-runtime repo..."
  git -C "${POD_RUNTIME}" pull --rebase --autostash || true
fi

# -------------------------------
# Baseline packages (idempotent)
# -------------------------------
if [[ "${BOOTSTRAP_INSTALL_BASELINE}" == "1" && ! -f "${BASELINE_STAMP}" ]]; then
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
  date -Is > "${BASELINE_STAMP}"
  log "Baseline install complete; wrote ${BASELINE_STAMP}"
else
  log "Baseline install skipped (already stamped or disabled)."
fi

# -------------------------------
# Source env + helpers (your .env is a shell script)
# -------------------------------
ENV_SH="${POD_RUNTIME}/.env"
if [[ -f "${ENV_SH}" ]]; then
  log "Sourcing ${ENV_SH}"
  # shellcheck disable=SC1090
  source "${ENV_SH}"
else
  log "${ENV_SH} not found (OK)"
fi

HELPERS="${POD_RUNTIME}/helpers.sh"
if [[ -f "${HELPERS}" ]]; then
  log "Sourcing ${HELPERS}"
  # shellcheck disable=SC1090
  source "${HELPERS}"
else
  log "${HELPERS} not found (OK)"
fi

# -------------------------------
# SSH decision logic
# -------------------------------
have_authorized_keys() {
  [[ -s /root/.ssh/authorized_keys ]] || [[ -s "${HOME:-/root}/.ssh/authorized_keys" ]]
}

platform_provides_ssh() {
  # Heuristics: already connected by SSH, or keys already provisioned, or sshd already running
  [[ -n "${SSH_CONNECTION:-}" ]] && return 0
  have_authorized_keys && pgrep -x sshd >/dev/null 2>&1 && return 0
  return 1
}

enable_ssh=false
case "${BOOTSTRAP_ENABLE_SSH}" in
  1|true|yes) enable_ssh=true ;;
  0|false|no) enable_ssh=false ;;
  auto)
    if platform_provides_ssh; then
      enable_ssh=false
      log "SSH appears to be provided by platform; will not manage sshd."
    else
      enable_ssh=true
      log "SSH not detected; will install/start sshd if key provided."
    fi
    ;;
  *)
    log "WARN: BOOTSTRAP_ENABLE_SSH=${BOOTSTRAP_ENABLE_SSH} not recognized; defaulting to auto"
    enable_ssh=true
    ;;
esac

if $enable_ssh; then
  # Only bother if a key is provided; your setup_ssh already does this check too,
  # but we need openssh-server present first.
  if [[ -n "${SSH_PUBLIC_KEY:-${PUBLIC_KEY:-}}" ]]; then
    if ! command -v sshd >/dev/null 2>&1; then
      log "Installing openssh-server..."
      apt-get update
      apt-get install -y --no-install-recommends openssh-server
      mkdir -p /run/sshd /var/run/sshd
      apt-get clean
      rm -rf /var/lib/apt/lists/*
    fi

    if declare -F setup_ssh >/dev/null 2>&1; then
      log "Running setup_ssh..."
      setup_ssh
    else
      log "WARN: setup_ssh not found; skipping ssh setup."
    fi
  else
    log "No SSH_PUBLIC_KEY/PUBLIC_KEY set; skipping ssh setup."
  fi
fi

log "Bootstrap complete."

if [[ "${BOOTSTRAP_KEEPALIVE}" == "1" ]]; then
  log "Keeping container alive..."
  exec tail -f /dev/null
fi
