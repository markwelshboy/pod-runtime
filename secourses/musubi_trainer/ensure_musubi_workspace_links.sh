#!/usr/bin/env bash
set -euo pipefail

print_info() { printf "[musubi-links] INFO: %s\n" "$*"; }
print_warn() { printf "[musubi-links] WARN: %s\n" "$*"; }

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

# Where the “zip-style” assets live in your repo
: "${MUSUBI_ASSETS_SRC:=${POD_RUNTIME_DIR}/secourses/musubi_trainer}"

# Where we want things staged for tutorial expectations
: "${MUSUBI_STAGE_DIR:=${WORKSPACE}}"

mkdir -p "${WORKSPACE}"

if [[ ! -d "${MUSUBI_ASSETS_SRC}" ]]; then
  print_warn "Assets dir not found: ${MUSUBI_ASSETS_SRC} (skipping)"
  exit 0
fi

# Helper: force a symlink at dst -> src
link_one() {
  local src="$1" dst="$2"
  if [[ -e "${dst}" || -L "${dst}" ]]; then
    rm -f "${dst}"
  fi
  ln -s "${src}" "${dst}"
}

print_info "Staging Musubi assets into ${MUSUBI_STAGE_DIR} (symlinks)"

# 1) Link all top-level *.toml files (tutorials often expect these in /workspace)
shopt -s nullglob
for f in "${MUSUBI_ASSETS_SRC}"/*.toml; do
  base="$(basename "$f")"
  link_one "${f}" "${MUSUBI_STAGE_DIR}/${base}"
  print_info "Linked TOML: ${MUSUBI_STAGE_DIR}/${base} -> ${f}"
done
shopt -u nullglob

# 2) Link “*_Training_Configs” folders (and any other config dirs you care about)
for d in "${MUSUBI_ASSETS_SRC}"/*_Training_Configs "${MUSUBI_ASSETS_SRC}"/*Training_Configs "${MUSUBI_ASSETS_SRC}"/Wan22_Training_Configs; do
  [[ -d "${d}" ]] || continue
  base="$(basename "$d")"
  link_one "${d}" "${MUSUBI_STAGE_DIR}/${base}"
  print_info "Linked DIR : ${MUSUBI_STAGE_DIR}/${base} -> ${d}"
done

# 3) Optional: a single “drop zone” link to the whole assets folder
link_one "${MUSUBI_ASSETS_SRC}" "${WORKSPACE}/musubi_trainer_zip_assets"
print_info "Linked: ${WORKSPACE}/musubi_trainer_zip_assets -> ${MUSUBI_ASSETS_SRC}"

print_info "Musubi workspace links ready."
