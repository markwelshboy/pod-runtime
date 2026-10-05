#!/usr/bin/env bash

# Git-repository override for init_repo.
#
# helpers_core.sh still owns the legacy HF implementation. This module is
# sourced after helpers_core.sh and overrides only the git path so git clones
# can honor GIT_DEPTH and optionally use a media-sparse partial checkout.

if ! declare -F init_repo >/dev/null 2>&1; then
  echo "[helpers_git_repo] init_repo from helpers_core.sh is not loaded" >&2
  return 1 2>/dev/null || exit 1
fi

if ! declare -F _init_repo_legacy >/dev/null 2>&1; then
  # Preserve the core implementation for --hf calls. declare -f emits a normal
  # function definition; rename only its declaration line before evaluating it.
  eval "$(declare -f init_repo | sed '1s/^init_repo[[:space:]]*()/_init_repo_legacy ()/')"
fi

init_repo() {
  local mode="git"
  local exclude_media="false"

  while (($#)); do
    case "${1:-}" in
      --hf)            mode="hf"; shift ;;
      --git)           mode="git"; shift ;;
      --exclude-media) exclude_media="true"; shift ;;
      --)              shift; break ;;
      *)               break ;;
    esac
  done

  if [[ "$mode" == "hf" ]]; then
    if [[ "$exclude_media" == "true" ]]; then
      _sync_err "init_repo: --exclude-media is only valid with --git"
      return 1
    fi
    _init_repo_legacy --hf "$@"
    return $?
  fi

  if [[ $# -lt 2 ]]; then
    _sync_err "init_repo: missing arguments. Usage: init_repo [--hf|--git] [--exclude-media] <repo-id-or-url> <local-dir> [patterns...]"
    return 1
  fi

  local repo_id="$1"
  local local_dir="$2"
  shift 2

  # Trailing patterns retain the legacy git-mode meaning: LFS tracking specs.
  local -a specs=("$@")
  if [[ ${#specs[@]} -eq 1 && "${specs[0]}" == *" "* ]]; then
    read -r -a specs <<<"${specs[0]}"
  fi

  local remote_url
  if [[ "$repo_id" == http*://* || "$repo_id" == git@*:* ]]; then
    remote_url="$repo_id"
  else
    remote_url="https://github.com/${repo_id}.git"
  fi

  mkdir -p "$(dirname "$local_dir")" 2>/dev/null || true

  echo ""
  echo "------------------------------------------------------------------------------------------------------"
  if [[ "$exclude_media" == "true" ]]; then
    _sync_info "init_repo (mode=git, exclude-media=true) for repo: $repo_id at local dir: $local_dir"
  else
    _sync_info "init_repo (mode=git) for repo: $repo_id at local dir: $local_dir"
  fi
  echo ""

  local -a clone_args=()
  if [[ -n "${GIT_DEPTH:-}" ]]; then
    clone_args+=(--depth "$GIT_DEPTH")
  fi

  if [[ "$exclude_media" == "true" ]]; then
    # Prevent HEAD blobs from being downloaded before sparse rules are active.
    # GitHub supports blobless partial clone, and --no-checkout ensures the
    # sparse definition is installed before the first working-tree checkout.
    clone_args+=(--filter=blob:none --no-checkout)
  fi

  if [[ ! -d "$local_dir/.git" ]]; then
    local clone_detail=""
    [[ -n "${GIT_DEPTH:-}" ]] && clone_detail+=" depth=${GIT_DEPTH}"
    [[ "$exclude_media" == "true" ]] && clone_detail+=" media-sparse"
    _sync_info "Cloning git repo: $remote_url → $local_dir${clone_detail:+ (${clone_detail# })}"

    GIT_TERMINAL_PROMPT=0 git clone "${clone_args[@]}" "$remote_url" "$local_dir" || {
      _sync_err "init_repo: failed to clone $remote_url"
      return 1
    }
  else
    _sync_info "init_repo: '$local_dir' already a git repo, skipping clone."
  fi

  if [[ "$exclude_media" == "true" ]]; then
    # Non-cone sparse patterns use gitignore-style matching. Bracket expressions
    # make extension matching case-insensitive without changing core.ignoreCase.
    local -a sparse_patterns=(
      '/*'
      '!*.[pP][nN][gG]'
      '!*.[jJ][pP][gG]'
      '!*.[jJ][pP][eE][gG]'
      '!*.[wW][eE][bB][pP]'
      '!*.[gG][iI][fF]'
      '!*.[mM][pP]4'
      '!*.[mM][oO][vV]'
      '!*.[wW][eE][bB][mM]'
    )

    _sync_info "Configuring sparse checkout to exclude common image/video media..."
    git -C "$local_dir" sparse-checkout set --no-cone "${sparse_patterns[@]}" || {
      _sync_err "init_repo: failed to configure media-sparse checkout for $local_dir"
      return 1
    }

    # Fresh --no-checkout clones need their first checkout here; on existing
    # repos this also normalizes the working tree to the sparse definition.
    GIT_TERMINAL_PROMPT=0 git -C "$local_dir" checkout || {
      _sync_err "init_repo: failed to populate sparse checkout for $local_dir"
      return 1
    }
  fi

  # Preserve the legacy git-mode LFS tracking semantics.
  if ((${#specs[@]} > 0)); then
    (
      cd "$local_dir" || exit 1

      if ! command -v git-lfs >/dev/null 2>&1; then
        _sync_warn "git-lfs not found; cannot add LFS tracking for ${specs[*]}"
        exit 0
      fi

      git lfs install --local >/dev/null 2>&1 || true

      local spec
      for spec in "${specs[@]}"; do
        [[ -n "$spec" ]] || continue
        _sync_info "Adding LFS tracking: $spec"
        git lfs track "$spec" || _sync_warn "Failed to track '$spec' with git-lfs"
      done

      if [[ -f .gitattributes ]]; then
        if ! git diff --cached --quiet -- .gitattributes 2>/dev/null; then
          git add .gitattributes
          git commit -m "Add LFS tracking: ${specs[*]}" || true
        fi
      fi
    )
  fi

  if [[ "$exclude_media" == "true" ]]; then
    _sync_ok "init_repo: ready at $local_dir (mode=git, exclude-media=true)"
  else
    _sync_ok "init_repo: ready at $local_dir (mode=git)"
  fi
}
