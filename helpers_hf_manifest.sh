#!/usr/bin/env bash
# Background Hugging Face manifest downloader entrypoint.

if [[ -n "${__HF_MANIFEST_HELPERS_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
__HF_MANIFEST_HELPERS_LOADED=1

_hf_manifest_lib_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/helpers_hf_manifest.d"
# shellcheck source=/dev/null
source "${_hf_manifest_lib_dir}/01-common.sh"
# shellcheck source=/dev/null
source "${_hf_manifest_lib_dir}/02-download.sh"
# shellcheck source=/dev/null
source "${_hf_manifest_lib_dir}/03-status.sh"
# shellcheck source=/dev/null
source "${_hf_manifest_lib_dir}/04-dispatch.sh"
unset _hf_manifest_lib_dir
