#!/usr/bin/env bash
# Manifest set/tag management layered over install_custom_nodes.

: "${CUSTOM_NODES_MANIFEST_MANAGE_TOOL:=${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}/bin/custom_node_manifest_manage.py}"

_custom_nodes_local_manifest_default() {
  local runtime_dir="${POD_RUNTIME_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}"
  if [[ -f "$runtime_dir/default_custom_nodes_manifest.json" ]]; then
    printf '%s\n' "$runtime_dir/default_custom_nodes_manifest.json"
  elif [[ "${CUSTOM_NODES_MANIFEST_URL:-}" != http://* && "${CUSTOM_NODES_MANIFEST_URL:-}" != https://* ]]; then
    printf '%s\n' "${CUSTOM_NODES_MANIFEST_URL:-}"
  else
    printf '%s\n' "$runtime_dir/default_custom_nodes_manifest.json"
  fi
}

_custom_nodes_manage() {
  "${PY_BIN:-${PY:-python}}" "$CUSTOM_NODES_MANIFEST_MANAGE_TOOL" "$@"
}

_custom_nodes_install_help() {
  cat <<'EOF'
Usage:
  install_custom_nodes [MANIFEST] [options]
  install_custom_nodes --comfy-url URL [workflow options]
  install_custom_nodes --list-tags [--verbose] [--target-manifest FILE]

Install/workflow options:
  --comfy-url URL              Use the active browser tab on this ComfyUI server
  --current-tab                Explicitly select the active browser-tab workflow
  --from-workflow FILE         Resolve missing nodes from a saved workflow
  --output FILE                Save the generated workflow manifest
  --accept-default             Accept the first provider/default ref and confirmations
  --allow-unresolved           Permit a partial generated manifest
  --sets NAMES                 Install optional manifest sets (default is always included)
  --plan                       Show the install plan without installing
  --dry-run                    Run pip dependency resolution without changing packages

Rollback options:
  --enable-rollback            Capture state before installation
  --rollback FILE              Rollback snapshot file
  --perform-rollback           Restore a previous snapshot
  --strict-dirty-snapshot      Abort snapshot creation for dirty Git repositories
  --rollback-verbose           Show individual snapshot/restore commands
  --preserve-dirty-restore     Refuse to reset repositories dirty at restore time
  --keep-added-nodes           Keep node directories added after the snapshot

Manifest retention and tag options:
  --write-manifest SET         After a successful install, merge nodes into SET
                               (creates SET when needed)
  --target-manifest FILE       Writable manifest to update or inspect; defaults to the
                               checked-out default_custom_nodes_manifest.json
  --manifest FILE              Alias for --target-manifest in management operations
  --write-only                 Merge an existing generated manifest without installing
  --update-existing            Replace existing definitions while merging; by default
                               existing target definitions/overrides win
  --list-tags                  List sets and node counts
  --show-tag SET               Print definitions in one set
  --rename-tag OLD NEW         Rename a set
  --delete-tag SET             Delete a set (node definitions are retained)
  --verbose                    With --list-tags, show every member and repository

Examples:
  # Install missing nodes from the active ComfyUI tab
  install_custom_nodes \
      --comfy-url http://127.0.0.1:8288

  # Generate/preview only
  install_custom_nodes \
      --comfy-url http://127.0.0.1:8288 \
      --plan \
      --output workflow.json

  # Install with rollback protection
  install_custom_nodes \
      --comfy-url http://127.0.0.1:8288 \
      --enable-rollback \
      --rollback ./pre.rollback

  # Restore the rollback snapshot
  install_custom_nodes \
      --perform-rollback \
      --rollback ./pre.rollback

  # Install and retain the resolved nodes in the existing/new krea2 set
  install_custom_nodes \
      --comfy-url http://127.0.0.1:8288 \
      --accept-default \
      --write-manifest krea2

  # Install and retain nodes in a separate manifest
  install_custom_nodes \
      --comfy-url http://127.0.0.1:8288 \
      --accept-default \
      --write-manifest lonecat-workflows \
      --target-manifest /workspace/pod-runtime/lonecat.json

  # Merge a previously generated manifest without reinstalling
  install_custom_nodes \
      ./test-v4.json \
      --write-manifest wan-painter \
      --write-only

  # List available sets, then include their members
  install_custom_nodes --list-tags
  install_custom_nodes --list-tags --verbose

  # Inspect, rename, or remove a set
  install_custom_nodes --show-tag krea2
  install_custom_nodes --rename-tag krea2 krea2-video
  install_custom_nodes --delete-tag old-workflow

  # Future pod: install default plus retained workflow sets
  CUSTOM_NODE_SETS="krea2,wan-painter" install_custom_nodes
EOF
}

if declare -F install_custom_nodes >/dev/null 2>&1 && ! declare -F _install_custom_nodes_without_manifest_management >/dev/null 2>&1; then
  eval "$(declare -f install_custom_nodes | sed '1s/^install_custom_nodes /_install_custom_nodes_without_manifest_management /')"
fi

install_custom_nodes() {
  local write_set=""
  local target_manifest=""
  local write_only=0
  local update_existing=0
  local list_tags=0
  local show_tag=""
  local rename_old="" rename_new=""
  local delete_tag=""
  local verbose=0
  local explicit_source=""
  local generated_output=""
  local saw_plan=0
  local -a forwarded=()

  if [[ $# -gt 0 && "$1" != --* ]]; then
    explicit_source="$1"
    forwarded+=("$1")
    shift
  fi

  while (($#)); do
    case "$1" in
      --help|-h)
        _custom_nodes_install_help
        return 0
        ;;
      --write-manifest)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --write-manifest requires a set name" >&2; return 2; }
        write_set="$2"; shift
        ;;
      --target-manifest|--manifest)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] $1 requires a path" >&2; return 2; }
        target_manifest="$2"; shift
        ;;
      --write-only) write_only=1 ;;
      --update-existing) update_existing=1 ;;
      --list-tags) list_tags=1 ;;
      --show-tag)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --show-tag requires a set name" >&2; return 2; }
        show_tag="$2"; shift
        ;;
      --rename-tag)
        [[ -n "${2:-}" && -n "${3:-}" ]] || { echo "[custom-nodes] --rename-tag requires OLD NEW" >&2; return 2; }
        rename_old="$2"; rename_new="$3"; shift 2
        ;;
      --delete-tag)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --delete-tag requires a set name" >&2; return 2; }
        delete_tag="$2"; shift
        ;;
      --verbose) verbose=1 ;;
      --output)
        [[ -n "${2:-}" ]] || { echo "[custom-nodes] --output requires a path" >&2; return 2; }
        generated_output="$2"
        forwarded+=(--output "$2")
        shift
        ;;
      --plan)
        saw_plan=1
        forwarded+=("$1")
        ;;
      *) forwarded+=("$1") ;;
    esac
    shift
  done

  [[ -n "$target_manifest" ]] || target_manifest="$(_custom_nodes_local_manifest_default)"

  if ((list_tags)); then
    local -a args=(list-sets --manifest "$target_manifest")
    ((verbose)) && args+=(--verbose)
    _custom_nodes_manage "${args[@]}"
    return $?
  fi
  if [[ -n "$show_tag" ]]; then
    _custom_nodes_manage show-set "$show_tag" --manifest "$target_manifest"
    return $?
  fi
  if [[ -n "$rename_old" ]]; then
    _custom_nodes_manage rename-set "$rename_old" "$rename_new" --manifest "$target_manifest"
    return $?
  fi
  if [[ -n "$delete_tag" ]]; then
    _custom_nodes_manage delete-set "$delete_tag" --manifest "$target_manifest"
    return $?
  fi

  if ((write_only)); then
    [[ -n "$write_set" ]] || { echo "[custom-nodes] --write-only requires --write-manifest SET" >&2; return 2; }
    [[ -n "$explicit_source" ]] || { echo "[custom-nodes] --write-only requires a source manifest as the first argument" >&2; return 2; }
    local -a merge_args=(merge "$explicit_source" --into "$target_manifest" --set "$write_set")
    ((update_existing)) && merge_args+=(--update-existing)
    _custom_nodes_manage "${merge_args[@]}"
    return $?
  fi

  if [[ -n "$write_set" && -z "$explicit_source" && -z "$generated_output" ]]; then
    generated_output="${CACHE_DIR:-/tmp}/custom_nodes_retained_$(date +%Y%m%d_%H%M%S).json"
    forwarded+=(--output "$generated_output")
  fi

  _install_custom_nodes_without_manifest_management "${forwarded[@]}"
  local rc=$?
  ((rc == 0)) || {
    [[ -z "$write_set" ]] || echo "[custom-nodes] Target manifest not updated because installation failed." >&2
    return "$rc"
  }

  if [[ -n "$write_set" ]]; then
    if ((saw_plan)); then
      echo "[custom-nodes] Plan completed; target manifest was not modified."
      return 0
    fi
    local merge_source="${explicit_source:-$generated_output}"
    [[ -n "$merge_source" && -f "$merge_source" ]] || {
      echo "[custom-nodes] Cannot retain nodes: generated/source manifest is unavailable: ${merge_source:-<none>}" >&2
      return 1
    }
    local -a merge_args=(merge "$merge_source" --into "$target_manifest" --set "$write_set")
    ((update_existing)) && merge_args+=(--update-existing)
    _custom_nodes_manage "${merge_args[@]}" || return $?
    echo
    echo "Review and commit:"
    echo "  git -C $(dirname "$target_manifest") diff -- $(basename "$target_manifest")"
    echo "  git -C $(dirname "$target_manifest") add $(basename "$target_manifest")"
  fi
}
