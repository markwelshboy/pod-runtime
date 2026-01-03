#!/usr/bin/env bash
set -euo pipefail

log(){ echo "[bootstrap] $*"; }

# -----------------------------------------------------------------------------
# Minimal fallbacks (helpers.sh can override these)
# -----------------------------------------------------------------------------
print_info() { printf "[bootstrap] INFO: %s\n" "$*"; }
print_warn() { printf "[bootstrap] WARN: %s\n" "$*"; }
print_err()  { printf "[bootstrap] ERR : %s\n" "$*"; }

section() {
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    printf "\n================================================================================\n"
    printf "=== %s: %s\n" "${1}" "${2:-}"
    printf "================================================================================\n"
  else
    printf "\n================================================================================\n"
    printf "=== %s\n" "${1:-}"
    printf "================================================================================\n"
  fi
}

# -----------------------------------------------------------------------------
# Start (or restart) one Comfy session in tmux
# -----------------------------------------------------------------------------
start_one() {
  local sess="$1" port="$2" gvar="$3" out="$4" cache="$5"

  : "${COMFY_RESTART_DELAY:=1}"   # seconds; override if needed

  mkdir -p "${out}" "${cache}" "${COMFY_LOGS}"

  local py="${COMFY_VENV}/bin/python"
  if [[ ! -x "${py}" ]]; then
    print_err "Missing Comfy venv python: ${py}"
    return 1
  fi

  local logfile="${COMFY_LOGS}/comfyui-${port}.log"

  local cmd
  cmd=$(
    cat <<EOF
set -euo pipefail
cd ${COMFY_HOME@Q}

# If user already set CUDA_VISIBLE_DEVICES, do NOT override it.
if [[ -z "\${CUDA_VISIBLE_DEVICES:-}" ]]; then
  export CUDA_VISIBLE_DEVICES=${gvar@Q}
fi

export PYTHONUNBUFFERED=1

exec ${py@Q} ${COMFY_HOME@Q}/main.py --listen ${COMFY_LISTEN@Q} --port ${port@Q} \
  ${SAGE_ATTENTION:-} \
  --output-directory ${out@Q} --temp-directory ${cache@Q} \
  >> ${logfile@Q} 2>&1
EOF
  )

  if tmux has-session -t "${sess}" >/dev/null 2>&1; then
    print_info "ComfyUI launching in existing tmux session: ${sess}"
    # Best-effort stop whatever is running in that pane
    tmux send-keys -t "${sess}" C-c || true
    sleep "${COMFY_RESTART_DELAY}"
    # Relaunch
    tmux send-keys -t "${sess}" "bash -lc ${cmd@Q}" C-m
  else
    print_info "ComfyUI launching in new tmux session: ${sess}"
    tmux new-session -d -s "${sess}" "bash -lc ${cmd@Q}"
  fi

  print_info "Logs  : ${logfile}"
  print_info "Attach: tmux attach -t ${sess}"

  ( health "${sess}" "${port}" "${gvar}" "${out}" "${cache}" ) || true
}

# -----------------------------------------------------------------------------
# src-secourses: clone + flatten selected version dir into /workspace
#
# Inputs (env):
#   WORKSPACE=/workspace
#   SECOURSES_REPO=https://github.com/markwelshboy/src-secourses.git
#   COMFY_SE_VERSION=comfyui_v71
#   SWARM_SE_VERSION=swarmui_v119
#   TRAIN_SE_VERSION=musubi_trainer_v26
#   COMFY_POD=true/false
#   SWARM_POD=true/false
#   TRAIN_POD=true/false
#
# Optional:
#   SECOURSES_REF=main
#   SECOURSES_DIR_NAME=.src-secourses   (where the repo is cloned under /workspace)
#   SECOURSES_DELETE=0/1                (if 1, rsync --delete to make /workspace match exactly)
# -----------------------------------------------------------------------------

_bool() { case "${1,,}" in 1|true|yes|y|on) return 0 ;; *) return 1 ;; esac; }

_flatten_rsync_to_workspace() {
  local src_dir="${1:?src_dir}"
  local workspace="${2:-/workspace}"

  [[ -d "$src_dir" ]] || { echo "[secourses] FATAL: missing dir: $src_dir" >&2; return 1; }
  mkdir -p "$workspace"

  local -a rsync_args=(
    -a
    --info=stats2
    --exclude ".git/"
    --exclude ".git"
    --exclude "**/.git/**"
    --exclude "**/.git"
    --exclude ".gitmodules"
    --exclude ".DS_Store"
  )

  if _bool "${SECOURSES_DELETE:-0}"; then
    rsync_args+=(--delete)
  fi

  echo "[secourses] Flatten rsync: ${src_dir}/  ->  ${workspace}/"
  rsync "${rsync_args[@]}" "${src_dir}/" "${workspace}/"
}

stage_src_secourses_into_workspace() {
  : "${WORKSPACE:=/workspace}"
  : "${SECOURSES_REPO:=https://github.com/markwelshboy/src-secourses.git}"
  : "${SECOURSES_REF:=main}"
  : "${SECOURSES_DIR_NAME:=.src-secourses}"

  # Where we keep the repo clone
  local repo_dst="${WORKSPACE%/}/${SECOURSES_DIR_NAME}"

  echo "[secourses] Ensuring repo clone: ${SECOURSES_REPO} -> ${repo_dst} (ref=${SECOURSES_REF})"

  # NOTE: clone_or_pull hard-resets to origin/main (or origin/master) in your helper.
  # Passing --branch main keeps it aligned with how clone_or_pull resets.
  clone_or_pull "${SECOURSES_REPO}" "${repo_dst}" false --branch main

  # Determine which payload(s) to stage
  local staged_any=0

  if _bool "${COMFY_POD:-false}"; then
    : "${COMFY_SE_VERSION:?COMFY_POD=true but COMFY_SE_VERSION is unset}"
    echo "[secourses] COMFY_POD enabled -> ${COMFY_SE_VERSION}"
    _flatten_rsync_to_workspace "${repo_dst%/}/${COMFY_SE_VERSION}" "${WORKSPACE}"
    staged_any=1
  fi

  if _bool "${SWARM_POD:-false}"; then
    : "${SWARM_SE_VERSION:?SWARM_POD=true but SWARM_SE_VERSION is unset}"
    echo "[secourses] SWARM_POD enabled -> ${SWARM_SE_VERSION}"
    _flatten_rsync_to_workspace "${repo_dst%/}/${SWARM_SE_VERSION}" "${WORKSPACE}"
    staged_any=1
  fi

  if _bool "${TRAIN_POD:-false}"; then
    : "${TRAIN_SE_VERSION:?TRAIN_POD=true but TRAIN_SE_VERSION is unset}"
    echo "[secourses] TRAIN_POD enabled -> ${TRAIN_SE_VERSION}"
    _flatten_rsync_to_workspace "${repo_dst%/}/${TRAIN_SE_VERSION}" "${WORKSPACE}"
    staged_any=1
  fi

  if [[ "$staged_any" -eq 0 ]]; then
    echo "[secourses] NOTE: no *_POD flags were true; nothing staged into ${WORKSPACE}"
  fi
}

# -----------------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------------
: "${WORKSPACE:=/workspace}"
: "${HF_HOME:=/workspace}"

: "${POD_RUNTIME_DIR:=${WORKSPACE}/pod-runtime}"
: "${POD_RUNTIME_ENV:=${POD_RUNTIME_DIR}/.env}"
: "${POD_RUNTIME_HELPERS:=${POD_RUNTIME_DIR}/helpers.sh}"

: "${COMFY_HOME:=/workspace/ComfyUI}"
: "${COMFY_LOGS:=/workspace/logs}"
: "${COMFY_VENV:=/workspace/ComfyUI/venv}"

: "${ENABLE_SAGE:=true}"

export DEBIAN_FRONTEND=noninteractive

# Where this script lives (pod-runtime root)
POD_RUNTIME=${POD_RUNTIME_DIR}

# Stamp controls baseline install once per /workspace volume
: "${BASELINE_STAMP:=${WORKSPACE}/.podruntime_baseline_installed.v1}"

# Behaviour toggles
: "${BOOTSTRAP_INSTALL_BASELINE:=1}"     # 1=yes baseline apt, 0=skip
: "${BOOTSTRAP_ENABLE_SSH:=auto}"        # auto|1|0
: "${BOOTSTRAP_KEEPALIVE:=1}"            # 1=tail forever at end
: "${BOOTSTRAP_PULL_REPO:=1}"            # 1=pull pod-runtime (if it's a git repo)

: "${SECOURSES_REPO:=https://github.com/markwelshboy/src-secourses.git}"

: "${COMFY_SE_VERSION:=${COMFY_SE_VERSION:-comfyui_v71}}"
: "${SWARM_SE_VERSION:=${SWARM_SE_VERSION:-swarmui_v119}}"
: "${TRAIN_SE_VERSION:=${TRAIN_SE_VERSION:-musubi_trainer_v26}}"
: "${COMFY_POD:=${COMFY_POD:-false}}"
: "${SWARM_POD:=${SWARM_POD:-false}}"
: "${TRAIN_POD:=${TRAIN_POD:-false}}"

: "${SECOURSES_DELETE:=${SECOURSES_DELETE:-1}}"  # 1=rsync --delete to make /workspace match exactly


log "Workspace : ${WORKSPACE}"
log "PodRuntime: ${POD_RUNTIME}"

mkdir -p "${WORKSPACE}"
chmod 755 "${WORKSPACE}" || true

cd "${WORKSPACE}"

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

#----------------------------------------------
# -1) Wire up .env and helpers
#----------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT="${ENVIRONMENT:-$SCRIPT_DIR/.env}"
HELPERS="${HELPERS:-$SCRIPT_DIR/helpers.sh}"

if [[ ! -f "$ENVIRONMENT" ]]; then
  echo "[fatal] .env not found at: $ENVIRONMENT" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ENVIRONMENT"

if [[ ! -f "$HELPERS" ]]; then
  echo "[fatal] helpers.sh not found at: $HELPERS" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$HELPERS"

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

#----------------------------------------------
# Copy contents of SECourses zip files to /workspace
#----------------------------------------------

stage_src_secourses_into_workspace

#-- And we're done! --------------------------------

log "Bootstrap complete."

if [[ "${BOOTSTRAP_KEEPALIVE}" == "1" ]]; then
  log "Keeping container alive..."
  exec tail -f /dev/null
fi
