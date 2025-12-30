#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Shared runtime helpers used by start.comfy.sh and start.musubi.sh
# -----------------------------------------------------------------------------

print_info() { printf "[runtime] INFO: %s\n" "$*"; }
print_warn() { printf "[runtime] WARN: %s\n" "$*" >&2; }
print_err()  { printf "[runtime] ERR : %s\n" "$*" >&2; }

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

require_cmd() { command -v "$1" >/dev/null 2>&1 || { print_err "Missing required command: $1"; return 1; }; }
require_dir() { [[ -d "$1" ]] || { print_err "Missing required directory: $1"; return 1; }; }
require_file() { [[ -f "$1" ]] || { print_err "Missing required file: $1"; return 1; }; }

clone_or_update() {
  local url="$1" dir="$2"
  if [[ -d "${dir}/.git" ]]; then
    print_info "Updating $(basename "$dir") in ${dir}..."
    git -C "${dir}" pull --rebase --autostash || print_warn "git pull failed; continuing with existing checkout"
  else
    print_info "Cloning $(basename "$dir") from ${url} into ${dir}..."
    rm -rf "${dir}"
    git clone --depth 1 "${url}" "${dir}"
  fi
}

start_logging() {
  : "${WORKSPACE:=/workspace}"
  : "${STARTUP_LOG:=${WORKSPACE}/startup.log}"
  mkdir -p "${WORKSPACE}"
  exec > >(tee -a "${STARTUP_LOG}") 2>&1
  print_info "Logging to: ${STARTUP_LOG}"
}

# Helpful “clickable URLs” for ChromeOS/WSL terminals
print_local_urls() {
  local label="$1" port="$2" path="${3:-/}"
  print_info "${label}: http://127.0.0.1:${port}${path}"
}

# “Clean env” for app processes (reduces “leaks” across sessions)
clean_runtime_env() {
  unset PYTHONPATH PYTHONHOME || true
  unset LD_LIBRARY_PATH || true
  export PYTHONNOUSERSITE=1
}
