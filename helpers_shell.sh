#!/usr/bin/env bash
# Deprecated compatibility entrypoint.
#
# Older SL bootstrap clients used the presence of <runtime>/helpers_shell.sh as
# their runtime sentinel.  Keep this tiny forwarding shim during the layout
# migration; new callers should source helpers.sh, while helpers.d contains the
# implementation modules.

_runtime_compat_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
: "${POD_RUNTIME_DIR:=${_runtime_compat_root}}"
export POD_RUNTIME_DIR
# shellcheck source=/dev/null
source "${POD_RUNTIME_DIR}/helpers.d/helpers_shell.sh"
unset _runtime_compat_root
