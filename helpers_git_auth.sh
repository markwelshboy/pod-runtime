#!/usr/bin/env bash
# Deploy-key repository wiring layered over helpers_shell.sh.
#
# Environment variables are discovered by git_auth_bootstrap as:
#   GIT_DEPLOY_KEY_<REPO_NAME_WITH_UNDERSCORES>
# while repository names and SSH aliases use lower-case hyphens.

: "${GIT_POD_RUNTIME_REPO_NAME:=pod-runtime}"
: "${GIT_POD_RUNTIME_REPO_ID:=${GIT_USERNAME:-markwelshboy}/${GIT_POD_RUNTIME_REPO_NAME}}"
: "${GIT_POD_RUNTIME_REPO_LOCAL:=${POD_RUNTIME_DIR:-/workspace/pod-runtime}}"
export GIT_POD_RUNTIME_REPO_NAME GIT_POD_RUNTIME_REPO_ID GIT_POD_RUNTIME_REPO_LOCAL

# Compatibility with the existing start.sh call. The deploy-key helper now
# accepts the repository name directly, so no upper-case/underscore conversion
# is required in .env.
: "${GIT_MYWORKFLOWS_REPO_KEY:=${GIT_MYWORKFLOWS_REPO_NAME:-comfyui-templates}}"
export GIT_MYWORKFLOWS_REPO_KEY

_git_deploy_normalize_name() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-'
}

_git_deploy_env_suffix() {
  printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'
}

# git_repo_use_deploy_key <repo_dir> <repo_name_or_env_suffix> [owner/repo] [--push-only]
#
# Default behavior preserves the legacy helper: fetch and push both use the
# deploy-key SSH alias. With --push-only, the fetch URL is left untouched and
# only the push URL is changed. That mode is used for pod-runtime so bootstrap
# can continue pulling it over public HTTPS before ~/.ssh has been recreated.
git_repo_use_deploy_key() {
  local repo_dir="${1:-}"
  local env_name="${2:-}"
  local owner_repo="${3:-}"
  shift $(( $# >= 3 ? 3 : $# )) || true

  local push_only=0
  while (($#)); do
    case "$1" in
      --push-only) push_only=1 ;;
      --help|-h)
        echo "usage: git_repo_use_deploy_key <repo_dir> <repo_name_or_env_suffix> [owner/repo] [--push-only]"
        return 0
        ;;
      *)
        echo "git_repo_use_deploy_key: unknown option: $1" >&2
        return 2
        ;;
    esac
    shift
  done

  if [[ -z "$repo_dir" || -z "$env_name" ]]; then
    echo "usage: git_repo_use_deploy_key <repo_dir> <repo_name_or_env_suffix> [owner/repo] [--push-only]" >&2
    return 2
  fi

  if [[ ! -d "$repo_dir/.git" ]]; then
    echo "❌ Not a git repo: $repo_dir" >&2
    return 2
  fi

  local name env_suffix key_file host_alias
  name="$(_git_deploy_normalize_name "$env_name")"
  env_suffix="$(_git_deploy_env_suffix "$env_name")"
  key_file="$HOME/.ssh/github_${name}"
  host_alias="github-${name}"

  if [[ ! -f "$key_file" ]]; then
    echo "❌ Deploy key not found: $key_file" >&2
    echo "   Did you set GIT_DEPLOY_KEY_${env_suffix} and run git_auth_bootstrap?" >&2
    return 2
  fi

  if [[ -z "$owner_repo" ]]; then
    local origin
    origin="$(git -C "$repo_dir" remote get-url origin 2>/dev/null || true)"
    origin="${origin%.git}"
    case "$origin" in
      https://github.com/*) owner_repo="${origin#https://github.com/}" ;;
      git@*:*/*) owner_repo="${origin#*:}" ;;
    esac
  fi

  if [[ -z "$owner_repo" ]]; then
    echo "❌ Could not infer owner/repo for origin in $repo_dir" >&2
    echo "   Provide it explicitly: git_repo_use_deploy_key $repo_dir $env_name owner/repo" >&2
    return 2
  fi

  owner_repo="${owner_repo%.git}"
  local desired="git@${host_alias}:${owner_repo}.git"

  if ((push_only)); then
    local current_push
    current_push="$(git -C "$repo_dir" remote get-url --push origin 2>/dev/null || true)"
    if [[ "$current_push" != "$desired" ]]; then
      echo "🔧 Setting push URL for $(basename "$repo_dir") -> $desired"
      git -C "$repo_dir" remote set-url --push origin "$desired" || return $?
      echo "✅ Push URL set for $(basename "$repo_dir")"
    else
      echo "✅ Push URL already set for $(basename "$repo_dir")"
    fi
  else
    local current
    current="$(git -C "$repo_dir" remote get-url origin 2>/dev/null || true)"
    if [[ "$current" != "$desired" ]]; then
      echo "🔧 Setting origin for $(basename "$repo_dir") -> $desired"
      git -C "$repo_dir" remote set-url origin "$desired" || return $?
      git -C "$repo_dir" remote set-url --push origin "$desired" || return $?
      echo "✅ Origin set for $(basename "$repo_dir")"
    else
      echo "✅ Origin already set for $(basename "$repo_dir")"
    fi
  fi

  # Best-effort auth check. GitHub returns a non-zero SSH status even when
  # authentication succeeded, so inspect the response text instead.
  {
    local ssh_out
    ssh_out="$(ssh \
      -o BatchMode=yes \
      -o ConnectTimeout=5 \
      -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile=/tmp/github_known_hosts \
      -o GlobalKnownHostsFile=/dev/null \
      -T "git@${host_alias}" 2>&1 || true)"

    if grep -q "successfully authenticated" <<<"$ssh_out"; then
      echo "✅ SSH auth check passed for host alias: $host_alias"
    else
      echo "⚠️ SSH auth check inconclusive for $host_alias" >&2
      echo "   Last line: $(tail -n 1 <<<"$ssh_out")" >&2
    fi
  } || true

  return 0
}

_git_auth_configure_pod_runtime() {
  [[ -n "${GIT_DEPLOY_KEY_POD_RUNTIME:-}" ]] || return 0
  [[ -d "${GIT_POD_RUNTIME_REPO_LOCAL}/.git" ]] || {
    echo "ℹ️  pod-runtime repo not found; deploy-key remote not configured: ${GIT_POD_RUNTIME_REPO_LOCAL}"
    return 0
  }

  # Keep fetch public so early bootstrap pulls work before ~/.ssh is rebuilt.
  local public_fetch="https://github.com/${GIT_POD_RUNTIME_REPO_ID}.git"
  local current_fetch
  current_fetch="$(git -C "$GIT_POD_RUNTIME_REPO_LOCAL" remote get-url origin 2>/dev/null || true)"
  if [[ "$current_fetch" != "$public_fetch" ]]; then
    echo "🔧 Setting pod-runtime fetch URL -> $public_fetch"
    git -C "$GIT_POD_RUNTIME_REPO_LOCAL" remote set-url origin "$public_fetch" || return $?
  fi

  git_repo_use_deploy_key \
    "$GIT_POD_RUNTIME_REPO_LOCAL" \
    "$GIT_POD_RUNTIME_REPO_NAME" \
    "$GIT_POD_RUNTIME_REPO_ID" \
    --push-only
}

# Extend the existing bootstrap rather than requiring another start.sh call.
if declare -F git_auth_bootstrap >/dev/null 2>&1 \
   && ! declare -F _git_auth_bootstrap_without_repo_wiring >/dev/null 2>&1; then
  eval "$(declare -f git_auth_bootstrap | sed '1s/^git_auth_bootstrap /_git_auth_bootstrap_without_repo_wiring /')"
fi

git_auth_bootstrap() {
  local rc=0
  if declare -F _git_auth_bootstrap_without_repo_wiring >/dev/null 2>&1; then
    _git_auth_bootstrap_without_repo_wiring "$@" || rc=$?
  else
    echo "⚠️ Base git_auth_bootstrap helper is unavailable" >&2
    rc=1
  fi

  _git_auth_configure_pod_runtime || true
  return "$rc"
}
