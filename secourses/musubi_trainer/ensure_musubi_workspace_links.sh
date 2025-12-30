#!/usr/bin/env bash
set -euo pipefail

# Minimal fallbacks (helpers.sh may override)
print_info() { printf "[musubi-links] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-links] WARN: %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${MUSUBI_ASSETS_SRC:=${POD_RUNTIME_DIR}/secourses/musubi_trainer}"
: "${MUSUBI_ASSETS_LINK:=${WORKSPACE}/musubi_trainer_zip_assets}"

: "${MUSUBI_TRAINER_DIR:=${WORKSPACE}/SECourses_Musubi_Trainer}"
: "${MUSUBI_TRAINER_DIR_ASSETS_LINK:=${MUSUBI_TRAINER_DIR}/musubi_trainer_assets}"

# Ensure workspace exists
mkdir -p "${WORKSPACE}"

if [[ ! -d "${MUSUBI_ASSETS_SRC}" ]]; then
  print_warn "Assets dir not found at: ${MUSUBI_ASSETS_SRC} (skipping)"
  exit 0
fi

# Link into /workspace for "drop zone" convenience
if [[ -e "${MUSUBI_ASSETS_LINK}" && ! -L "${MUSUBI_ASSETS_LINK}" ]]; then
  print_warn "${MUSUBI_ASSETS_LINK} exists and is not a symlink; leaving alone."
else
  ln -sfn "${MUSUBI_ASSETS_SRC}" "${MUSUBI_ASSETS_LINK}"
  print_info "Linked: ${MUSUBI_ASSETS_LINK} -> ${MUSUBI_ASSETS_SRC}"
fi

# Optional: also link into the trainer repo (handy for relative paths)
if [[ -d "${MUSUBI_TRAINER_DIR}" ]]; then
  if [[ -e "${MUSUBI_TRAINER_DIR_ASSETS_LINK}" && ! -L "${MUSUBI_TRAINER_DIR_ASSETS_LINK}" ]]; then
    print_warn "${MUSUBI_TRAINER_DIR_ASSETS_LINK} exists and is not a symlink; leaving alone."
  else
    ln -sfn "${MUSUBI_ASSETS_SRC}" "${MUSUBI_TRAINER_DIR_ASSETS_LINK}"
    print_info "Linked: ${MUSUBI_TRAINER_DIR_ASSETS_LINK} -> ${MUSUBI_ASSETS_SRC}"
  fi
else
  print_warn "Trainer dir not found at: ${MUSUBI_TRAINER_DIR} (skipping trainer link)"
fi
