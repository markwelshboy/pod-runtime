# ── Git QoL Pack (aliases + prompt + completion) ──
# Portable across Debian/Ubuntu/WSL/Crostini/macOS (best-effort)

# ----- Other Helpers -----
_confirm() { read -r -p "${1:-Are you sure?} [y/N] " ans; [[ "$ans" == [yY] ]]; }

# ----- Aliases -----
alias g='git'
alias gs='git status -sb'
alias ga='git add'; alias gaa='git add -A'
alias gb='git branch -vv'
alias gco='git checkout'; alias gcb='git checkout -b'
alias gc='git commit -v'; alias gca='git commit -v -a'; alias gcm='git commit -am'
alias gd='git diff'; alias gdc='git diff --cached'
alias gl='git log --oneline --decorate --graph --all'
alias gll='git log --stat -p --decorate'
alias gshow='git show --stat'
alias gpr='git pull --rebase --autostash'
alias gp='git push'; alias gpf='git push --force-with-lease'
alias gcl='git clone'; alias gmv='git mv'; alias grm='git rm'
alias gtag='git tag -n'
alias gfetch='git fetch -p'
alias gsr='git submodule update --init --recursive'
alias gprune='git fetch -p'

# ----- Functions -----
gclean() { _confirm "Remove ALL untracked files/dirs (git clean -fdx)?" && git clean -fdx; }
gbclean() {
  local main_branch
  main_branch="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo main)"
  git branch --merged | grep -vE "^\*|${main_branch}|main|master" | xargs -r git branch -d
}
gbdelr() { [[ -n "${1:-}" ]] && git push origin --delete "$1"; }

gsummary() {
  echo -e "${BOLD}${FG_W}Branch:${RESET} $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
  echo; git status -sb; echo; git log --oneline -5
}

gfile() { git log -p -1 -- "$@"; }
gfind() { git grep -n --full-name "$@"; }
gundo() { git reset --soft HEAD~1; }
gamendmsg() { git commit --amend -m "${*:-fixups}"; }
gfix() { git add -A && git commit --amend --no-edit; }
gwip() { git add -A && git commit -m "WIP: $(date +%F-%T)"; }
grb() { git for-each-ref --count="${1:-10}" --sort=-committerdate refs/heads --format='%(refname:short)'; }
glg() { git log --oneline --graph --decorate --all | grep -E "${1:-.}"; }
gout() { git rev-parse --abbrev-ref @{u} &>/dev/null || { echo "No upstream set."; return 1; }; git log --oneline --decorate --graph @{u}..HEAD; }
gfp() { local cur; cur="$(git rev-parse --abbrev-ref HEAD)"; git push --force-with-lease origin "$cur"; }

gbrowse() {
  local url
  url="$(git config --get remote.origin.url | sed -E 's#^git@([^:]+):#https://\1/#; s#\.git$##')"
  [[ -z "$url" ]] && { echo "No origin remote."; return 1; }
  if command -v xdg-open >/dev/null; then xdg-open "$url"
  elif command -v open >/dev/null; then open "$url"
  else echo "$url"
  fi
}

# Git check: see local + remote differences and file changes
gck() {
  echo "🔍 Checking repo status..."
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ Not a git repository."; return 1; }

  # Fetch latest info from remote
  git fetch origin >/dev/null 2>&1 || { echo "⚠️  Couldn't fetch from remote."; return 1; }

  local LOCAL=$(git rev-parse @ 2>/dev/null)
  local REMOTE=$(git rev-parse @{u} 2>/dev/null || echo "")
  local BASE=$(git merge-base @ @{u} 2>/dev/null || echo "")
  local changed=0

  # --- 1. Local uncommitted changes ---
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "🧩 You have local uncommitted changes:"
    git status -s
    echo
    changed=1
  fi

  # --- 2. Check for remote updates ---
  if [ -z "$REMOTE" ]; then
    echo "⚠️  No upstream branch set. Use: git push -u origin main"
    return 1
  fi

  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "✅ Up to date with remote."
  elif [ "$LOCAL" = "$BASE" ]; then
    echo "⬇️  Remote has new commits you don't have. Files changed since your last pull:"
    git diff --stat $LOCAL..$REMOTE
    changed=1
  elif [ "$REMOTE" = "$BASE" ]; then
    echo "⬆️  You have local commits not pushed yet:"
    git log --oneline @{u}..@
    changed=1
  else
    echo "⚠️  Local and remote have diverged (both changed). You’ll need to pull/rebase carefully."
    changed=1
  fi

  # --- 3. Summary ---
  echo
  if [ "$changed" -eq 0 ]; then
    echo "✨ Everything clean and up to date!"
  else
    echo "📋 Summary: some changes detected — review above before pulling."
  fi
}

# Simple confirm helper (reuse if you already have one)
_confirm() {
  read -r -p "${1:-Are you sure?} [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]]
}

# gup: update (pull --rebase) with safety checks
# Usage:
#   gup          # pulls/rebases if needed
#   gup more     # pulls + then shows short “what changed” summary
gup() {
  local show_more=0
  [[ "$1" == "more" ]] && show_more=1

  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ Not a git repo."; return 1; }

  # Refresh knowledge of remote
  git fetch origin >/dev/null 2>&1 || { echo "⚠️ Unable to fetch remote."; return 1; }

  # Snapshot state
  local LOCAL REMOTE BASE
  LOCAL=$(git rev-parse @ 2>/dev/null) || return 1
  REMOTE=$(git rev-parse @{u} 2>/dev/null || echo "")
  BASE=$(git merge-base @ @{u} 2>/dev/null || echo "")

  if [[ -z "$REMOTE" ]]; then
    echo "⚠️  No upstream set. First time push:"
    echo "    git push -u origin $(git rev-parse --abbrev-ref HEAD)"
    return 1
  fi

  # Detect local un/staged edits (these will be autostashed, but warn anyway)
  local has_local_edits=0
  if ! git diff --quiet || ! git diff --cached --quiet; then
    has_local_edits=1
    echo "🧩 Local uncommitted changes detected:"
    git status -s
    echo
  fi

  # Decide situation
  if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo "✅ Already up to date."
    return 0
  elif [[ "$LOCAL" == "$BASE" ]]; then
    echo "⬇️  Remote has new commits (fast-forward)."
    # Safe; optional confirm only if local edits present
    if (( has_local_edits )); then
      _confirm "Proceed with pull (your uncommitted changes will be autostashed)?" || { echo "Canceled."; return 1; }
    fi
  elif [[ "$REMOTE" == "$BASE" ]]; then
    echo "⬆️  You are ahead (local commits not pushed). No pull needed."
    return 0
  else
    echo "⚠️  Diverged: both you and remote have commits."
    echo "    A rebase will rewrite your local commits on top of remote."
    git log --oneline --decorate --graph --boundary @{u}..@ 2>/dev/null | sed 's/^/  local: /'
    git log --oneline --decorate --graph --boundary @..@{u} 2>/dev/null | sed 's/^/  remote: /'
    echo
    _confirm "Rebase your local commits onto the updated upstream now?" || { echo "Canceled."; return 1; }
  fi

  # Do the pull (rebase + autostash)
  local BEFORE AFTER
  BEFORE=$(git rev-parse HEAD)
  echo "⬇️  Pulling (rebase + autostash)…"
  if ! git pull --rebase --autostash; then
    echo "❌ Pull/rebase failed. Resolve conflicts, then:  git rebase --continue"
    echo "   Or abort with:                               git rebase --abort"
    return 1
  fi
  AFTER=$(git rev-parse HEAD)

  # Optional “more” report
  if (( show_more )); then
    if [[ "$BEFORE" != "$AFTER" ]]; then
      echo
      echo "📦 Updated to: $(git rev-parse --short HEAD)"
      echo "📝 Commits pulled:"
      git log --oneline --decorate "${BEFORE}..${AFTER}"
      echo
      echo "📊 File changes (diffstat):"
      git diff --stat --color "${BEFORE}..${AFTER}"
    else
      echo "ℹ️  No changes applied by pull."
    fi
  fi
}

gitscan() {
  local base="${1:-$HOME/git}"
  shift || true

  local do_fetch=1
  local max_depth=1

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-fetch) do_fetch=0 ;;
      --fetch)    do_fetch=1 ;;
      --depth)    shift; max_depth="${1:-1}" ;;
      -h|--help)
        cat <<'EOF'
Usage:
  gitscan [BASE_DIR] [--fetch|--no-fetch] [--depth N]
EOF
        return 0
        ;;
    esac
    shift
  done

  # ── colors ─────────────────────────────────────────────
  local R G Y B DIM RESET
  R=$(tput setaf 1); G=$(tput setaf 2); Y=$(tput setaf 3)
  B=$(tput setaf 6); DIM=$(tput dim); RESET=$(tput sgr0)

  # ── discover repos ─────────────────────────────────────
  mapfile -t repos < <(
    find "$base" -maxdepth "$max_depth" -mindepth 1 -type d -name .git 2>/dev/null \
      | sed 's|/\.git$||' \
      | sort
  )

  [[ ${#repos[@]} -eq 0 ]] && { echo "No repos found in $base"; return 1; }

  # ── first pass: calc column widths ─────────────────────
  local name max_name=4
  for r in "${repos[@]}"; do
    name="$(basename "$r")"
    (( ${#name} > max_name )) && max_name=${#name}
  done

  local fmt="%-${max_name}s  %-9s  %-5s  %-11s  %s\n"

  # ── header ─────────────────────────────────────────────
  printf "$fmt" "REPO" "BRANCH" "DIRTY" "A/B" "STATUS"
  printf "$fmt" "$(printf '%*s' "$max_name" | tr ' ' '-')" \
                "---------" "-----" "-----------" "------"

  # ── second pass: status ────────────────────────────────
  for r in "${repos[@]}"; do
    git -C "$r" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
    (( do_fetch )) && git -C "$r" fetch --prune --quiet >/dev/null 2>&1 || true

    name="$(basename "$r")"
    branch="$(git -C "$r" symbolic-ref --quiet --short HEAD 2>/dev/null || echo DETACHED)"

    [[ -n "$(git -C "$r" status --porcelain)" ]] && dirty="YES" || dirty="no"

    upstream="$(git -C "$r" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
    ahead=0 behind=0
    if [[ -n "$upstream" ]]; then
      read -r ahead behind < <(
        git -C "$r" rev-list --left-right --count HEAD..."$upstream" 2>/dev/null
      )
      ab="${ahead}/${behind}"
    else
      ab="n/a"
    fi

    # ── status logic ─────────────────────────────────────
    local icon color status
    if [[ -z "$upstream" ]]; then
      icon="◼"; color="$R"; status="NO UPSTREAM"
    elif (( behind > 0 )); then
      icon="↓"; color="$R"; status="NEEDS PULL"
    elif (( ahead > 0 )); then
      icon="↑"; color="$Y"; status="AHEAD"
    elif [[ "$dirty" == "YES" ]]; then
      icon="✎"; color="$Y"; status="DIRTY"
    else
      icon="✔"; color="$G"; status="OK"
    fi

    printf "$fmt" \
      "$name" \
      "$branch" \
      "$dirty" \
      "$ab" \
      "${color}${icon} ${status}${RESET}"
  done
}
