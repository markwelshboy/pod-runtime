#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

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

  if _bool "${IMAGE_POD:-false}"; then
    : "${IMAGE_SE_VERSION:?IMAGE_POD=true but IMAGE_SE_VERSION is unset}"
    echo "[secourses] IMAGE_POD enabled -> ${IMAGE_SE_VERSION}"
    _flatten_rsync_to_workspace "${repo_dst%/}/${IMAGE_SE_VERSION}" "${WORKSPACE}"
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
: "${IMAGE_SE_VERSION:=${IMAGE_SE_VERSION:-ulti_image_process_v26}}"

: "${COMFY_POD:=${COMFY_POD:-false}}"
: "${SWARM_POD:=${SWARM_POD:-false}}"
: "${TRAIN_POD:=${TRAIN_POD:-false}}"
: "${IMAGE_POD:=${IMAGE_POD:-false}}"

: "${TMUX_SETUP_SCRIPT:=${POD_RUNTIME}/secourses/lib/ensure_tmux_conf.sh}"

: "${TRAIN_LOG_DIR:=${WORKSPACE}/logs}"
: "${TRAIN_TMUX_SESSION:=trainer}"
: "${TRAIN_TMUX_ERR:=${TRAIN_LOG_DIR}/trainer.tmux.err}"
: "${TRAIN_LOG:=${TRAIN_LOG_DIR}/trainer.log}"
: "${IMAGE_TMUX_SESSION:=image_processor}"
: "${IMAGE_TMUX_ERR:=${TRAIN_LOG_DIR}/image_processor.tmux.err}"
: "${IMAGE_LOG:=${TRAIN_LOG_DIR}/image_processor.log}"

: "${SECOURSES_DELETE:=${SECOURSES_DELETE:-0}}"  # 1=rsync --delete to make /workspace match exactly


print_info "Workspace : ${WORKSPACE}"
print_info "PodRuntime: ${POD_RUNTIME}"

mkdir -p "${WORKSPACE}"
chmod 755 "${WORKSPACE}" || true

cd "${WORKSPACE}"

# Optionally update pod-runtime itself (useful on long-lived volumes)
if [[ "${BOOTSTRAP_PULL_REPO}" == "1" && -d "${POD_RUNTIME}/.git" ]]; then
  print_info "Updating/refreshing pod-runtime repo..."
  git -C "${POD_RUNTIME}" pull --rebase --autostash || true
fi

# -------------------------------
# Baseline packages (idempotent)
# -------------------------------
if [[ "${BOOTSTRAP_INSTALL_BASELINE}" == "1" && ! -f "${BASELINE_STAMP}" ]]; then
  print_info "Installing baseline packages (first run)..."
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl wget \
    git git-lfs \
    jq unzip gawk coreutils \
    net-tools rsync ncurses-base bash-completion less nano \
    ninja-build aria2 vim tmux \
    psmisc
  git lfs install --system || true
  apt-get clean
  rm -rf /var/lib/apt/lists/*
  date -Is > "${BASELINE_STAMP}"
  print_info "Baseline install complete; wrote ${BASELINE_STAMP}"
else
  print_info "Baseline install skipped (already stamped or disabled)."
fi

#----------------------------------------------
# -1) Wire up .env and helpers
#----------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT="${ENVIRONMENT:-$SCRIPT_DIR/.env}"
HELPERS="${HELPERS:-$SCRIPT_DIR/helpers.sh}"

if [[ ! -f "$ENVIRONMENT" ]]; then
  print_err "[fatal] .env not found at: $ENVIRONMENT" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ENVIRONMENT"

if [[ ! -f "$HELPERS" ]]; then
  print_err "[fatal] helpers.sh not found at: $HELPERS" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$HELPERS"

if [[ ! -f "${TMUX_SETUP_SCRIPT}" ]]; then
  print_err "[fatal] tmux setup script not found at: $TMUX_SETUP_SCRIPT" >&2
  exit 1
fi

bash "$TMUX_SETUP_SCRIPT" || {
  print_err "[fatal] tmux setup script failed: $TMUX_SETUP_SCRIPT" >&2
  exit 1
}

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

#----------------------------------------------
# Launch training GUI and Image Processor in tmuxes (if enabled)

tmux_run_foreground_job() {
  local sess="$1" cmd="$2" errfile="$3"
  mkdir -p "$(dirname "$errfile")"

  # Helpful when something dies: pane stays visible
  tmux set-option -g remain-on-exit on >/dev/null 2>&1 || true

  if tmux has-session -t "$sess" >/dev/null 2>&1; then
    print_info "Respawning tmux pane: $sess"
    # Deterministic restart: always targets window 0, pane 0
    tmux respawn-pane -k -t "${sess}:0.0" "bash -c ${cmd@Q}" 2>>"$errfile" || true
  else
    print_info "Launching new tmux session: $sess"
    tmux new-session -d -s "$sess" "bash -c ${cmd@Q}" 2>>"$errfile" || true
  fi

  tmux has-session -t "$sess" >/dev/null 2>&1
}

stamp_run() {
  # Run a command only once per stamp file
  local stamp="$1"; shift
  if [[ -f "$stamp" ]]; then
    print_info "Skipping (stamp exists): $stamp"
    return 0
  fi
  print_info "Running once (creating stamp): $stamp"
  "$@"
  date -Is >"$stamp"
}

patch_trainer_installer_add_pip() {
  local src="${WORKSPACE}/RunPod_Install_Trainer.sh"
  local dst="${WORKSPACE}/RunPod_Install_Trainer.sh.patched"

  [[ -f "$src" ]] || { print_err "Missing $src"; return 1; }

  if [[ -f "$dst" && "$dst" -nt "$src" ]]; then
    print_info "Patched installer already up to date: $dst"
    return 0
  fi

  local patched="0"
  : >"$dst" || { print_err "Cannot write $dst"; return 1; }

  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*python(3)?[[:space:]]+-m[[:space:]]+venv[[:space:]]+venv[[:space:]]*$ ]]; then
      local indent="${line%%python*}"
      echo "${indent}python -m venv venv && (venv/bin/python -m pip install -q --disable-pip-version-check huggingface_hub requests hf_transfer || true)" >>"$dst"
      patched="1"
    else
      echo "$line" >>"$dst"
    fi
  done <"$src"

  chmod +x "$dst" || true

  if [[ "$patched" != "1" ]]; then
    print_warn "Did not find venv creation line to patch; using original installer."
    rm -f "$dst"
    return 2
  fi

  print_info "Created patched trainer installer: $dst"
  return 0
}

ensure_req_line() {
  local reqfile="$1" line="$2"
  [[ -f "$reqfile" ]] || return 0  # silently skip if file isn't there
  grep -qxF "$line" "$reqfile" && return 0
  echo "$line" >>"$reqfile"
}

if [[ "${TRAIN_POD,,}" == "true" ]]; then

  cd ${WORKSPACE}

  patch_trainer_installer_add_pip || true

RUNNER="/tmp/run_training_gui.sh"
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ${WORKSPACE@Q}/logs || true
echo "[training-gui] starting at \$(date -Is)" >> ${TRAIN_LOG@Q}

cd ${WORKSPACE@Q}

# Keep these per your requirements.
export WORKSPACE="/workspace"
export HF_HOME="/workspace"
export PYTHONUNBUFFERED=1
export HF_HUB_ENABLE_HF_TRANSFER=1

INSTALLER="./RunPod_Install_Trainer.sh"
if [[ -x "./RunPod_Install_Trainer.sh.patched" ]]; then
  INSTALLER="./RunPod_Install_Trainer.sh.patched"
fi
chmod +x "\${INSTALLER}" || true

exec stdbuf -oL -eL "\${INSTALLER}" >> ${TRAIN_LOG@Q} 2>&1
EOF

  chmod +x "${RUNNER}"

  if ! tmux_run_foreground_job "${TRAIN_TMUX_SESSION}" "${RUNNER}" "${TRAIN_TMUX_ERR}"; then
    print_err "tmux session was not created: ${TRAIN_TMUX_SESSION}"
    print_err "See: ${TRAIN_TMUX_ERR}"
    tmux ls || true
  fi

  print_info "Logs:         ${TRAIN_LOG}"
  print_info "tmux stderr:  ${TRAIN_TMUX_ERR}"
  print_info "Attach:       tmux attach -t ${TRAIN_TMUX_SESSION}"

else
  print_info "TRAIN_POD is not true; skipping training launch."
fi


if [[ "${IMAGE_POD,,}" == "true" ]]; then

  cd ${WORKSPACE}

  ensure_req_line "${WORKSPACE}/requirements_image_process.txt" "hf_transfer"

  # Run installer ONCE outside tmux (per your requirement)
  chmod +x "${WORKSPACE}/Runpod_Install_Img_Process.sh"

  # If you want the stamp to auto-refresh when the zip updates the installer:
  # IMG_SHA="$(sha256sum "${WORKSPACE}/Runpod_Install_Img_Process.sh" | awk '{print $1}')"
  # STAMP="/workspace/.imgproc_installed.${IMG_SHA}.stamp"
  STAMP="/workspace/.imgproc_installed.v1.stamp"

  stamp_run "${STAMP}" env HF_HOME="${WORKSPACE}" bash -lc "cd ${WORKSPACE} && ./Runpod_Install_Img_Process.sh"

  RUNNER="/tmp/run_image_processing_gui.sh"
  cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ${WORKSPACE@Q}/logs || true
echo "[image-processing-gui] starting at \$(date -Is)" >> ${IMAGE_LOG@Q}

cd ${WORKSPACE@Q}

# venv is built in /workspace for image processor
source ${WORKSPACE@Q}/venv/bin/activate

ulimit -n 65536 || true
export WORKSPACE="/workspace"
export HF_HOME="/workspace"
export PYTHONWARNINGS="ignore"
export HF_HUB_ENABLE_HF_TRANSFER=1
export PYTHONUNBUFFERED=1
export GRADIO_LOG_LEVEL=info
export LOGLEVEL=INFO

exec stdbuf -oL -eL python ./app.py --share 2>&1 | tee -a ${IMAGE_LOG@Q}
EOF

  chmod +x "${RUNNER}"

  if ! tmux_run_foreground_job "${IMAGE_TMUX_SESSION}" "${RUNNER}" "${IMAGE_TMUX_ERR}"; then
    print_err "tmux session was not created: ${IMAGE_TMUX_SESSION}"
    print_err "See: ${IMAGE_TMUX_ERR}"
    tmux ls || true
  fi

  print_info "Logs:         ${IMAGE_LOG}"
  print_info "tmux stderr:  ${IMAGE_TMUX_ERR}"
  print_info "Attach:       tmux attach -t ${IMAGE_TMUX_SESSION}"

else
  print_info "IMAGE_POD is not true; skipping image processing launch."
fi

#-- And we're done! ---------------------------

print_info "Bootstrap complete."

if [[ "${BOOTSTRAP_KEEPALIVE}" == "1" ]]; then
  print_info "Keeping container alive..."
  exec tail -f /dev/null
fi
