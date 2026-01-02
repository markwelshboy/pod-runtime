#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# ensure_tmux_conf.sh
# - Writes /etc/tmux.conf (system-wide) with safe mouse wheel scrolling
# - Reloads config into any running tmux server(s)
# - Designed for ephemeral GPU pods where tmux may be auto-launched by scripts
# ------------------------------------------------------------

TMUX_CONF_PATH="${TMUX_CONF_PATH:-/etc/tmux.conf}"
BACKUP_SUFFIX="${BACKUP_SUFFIX:-.bak.$(date +%Y%m%d_%H%M%S)}"
FORCE_WRITE="${FORCE_WRITE:-0}"  # set to 1 to overwrite even if identical
VERBOSE="${VERBOSE:-1}"

log() { [[ "$VERBOSE" == "1" ]] && echo "[tmuxconf] $*"; }

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "[tmuxconf] ERROR: must run as root to write ${TMUX_CONF_PATH}" >&2
    exit 1
  fi
}

# Content: tuned for tmux 3.2a+ and "no junk while scrolling"
tmux_conf_content() {
  cat <<'TMUX'
##### =========================================================
#####  /etc/tmux.conf — Ephemeral GPU pods / log watching / sane mouse
#####  Goal: wheel scroll = tmux history (copy-mode), no ^[[ junk
##### =========================================================

##### --- Terminal / colors ---
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",*:RGB"

##### --- Performance / feel ---
set -g escape-time 0
set -sg repeat-time 300
set -g history-limit 200000

##### --- Clipboard integration (keep simple) ---
# Don't let tmux attempt clipboard integration; terminals handle local clipboard.
set -g set-clipboard off

##### --- Copy-mode UX ---
setw -g mode-keys vi
set -g mouse on

# Enter copy-mode quickly
bind [ copy-mode

# Vim-ish selection inside copy-mode
bind -T copy-mode-vi v       send -X begin-selection
bind -T copy-mode-vi V       send -X select-line
bind -T copy-mode-vi y       send -X copy-selection-and-cancel
bind -T copy-mode-vi Escape  send -X cancel
bind -T copy-mode-vi Enter   send -X copy-selection-and-cancel

##### ---------------------------------------------------------
#####  CRITICAL SECTION: Wheel scroll must NOT send mouse escapes
#####  Fixes “^[[ …” junk appearing in shells/logs while scrolling.
##### ---------------------------------------------------------

# Remove any existing wheel bindings to avoid conflicts
unbind -n WheelUpPane
unbind -n WheelDownPane

# Wheel up: if already in copy-mode -> scroll up
#           else -> enter copy-mode and scroll up
bind -n WheelUpPane if -F "#{pane_in_mode}" \
  "send -X scroll-up" \
  "copy-mode -e; send -X scroll-up"

# Wheel down: scroll down in copy-mode; otherwise it will just "do nothing" (safe).
bind -n WheelDownPane if -F "#{pane_in_mode}" \
  "send -X scroll-down" \
  "send -X scroll-down"

# Mouse drag selection in copy-mode: release copies & exits copy-mode
bind -T copy-mode-vi MouseDragEnd1Pane send -X copy-selection-and-cancel

##### --- Status line (minimal useful hint) ---
set -g status on
set -g status-interval 2
set -g status-left-length 40
set -g status-right-length 80
set -g status-left "#[fg=colour39]#S#[default] "
set -g status-right "#[fg=colour244]#{?pane_in_mode,COPY,}#[default] %Y-%m-%d %H:%M"

##### --- Quality-of-life (optional) ---
set -g renumber-windows on
TMUX
}

write_conf_if_needed() {
  local tmp; tmp="$(mktemp)"
  tmux_conf_content >"$tmp"

  if [[ -f "$TMUX_CONF_PATH" && "$FORCE_WRITE" != "1" ]]; then
    if cmp -s "$tmp" "$TMUX_CONF_PATH"; then
      log "Config already up to date: $TMUX_CONF_PATH"
      rm -f "$tmp"
      return 0
    fi
    log "Existing config differs; backing up -> ${TMUX_CONF_PATH}${BACKUP_SUFFIX}"
    cp -a "$TMUX_CONF_PATH" "${TMUX_CONF_PATH}${BACKUP_SUFFIX}"
  fi

  log "Writing tmux config -> $TMUX_CONF_PATH"
  install -m 0644 "$tmp" "$TMUX_CONF_PATH"
  rm -f "$tmp"
}

reload_running_servers() {
  # If tmux isn't installed or isn't runnable, nothing to reload.
  if ! command -v tmux >/dev/null 2>&1; then
    log "tmux not found; skipping reload"
    return 0
  fi

  # If no server running, we're done (new tmux instances will pick up /etc/tmux.conf).
  if ! tmux ls >/dev/null 2>&1; then
    log "No running tmux server detected; nothing to reload"
    return 0
  fi

  # Reload the config into the running server.
  # This affects existing sessions immediately (mouse bindings, etc.).
  log "Reloading config into running tmux server: source-file $TMUX_CONF_PATH"
  tmux source-file "$TMUX_CONF_PATH" || true

  # Helpful post-checks (non-fatal)
  local mouse_state wheel_bind
  mouse_state="$(tmux show -gv mouse 2>/dev/null || true)"
  wheel_bind="$(tmux list-keys -T root 2>/dev/null | grep -E 'WheelUpPane|WheelDownPane' || true)"
  log "tmux mouse => ${mouse_state:-unknown}"
  if [[ -n "$wheel_bind" ]]; then
    log "wheel bindings loaded:"
    echo "$wheel_bind" | sed 's/^/[tmuxconf]   /'
  else
    log "wheel bindings not visible (unexpected, but continuing)"
  fi
}

main() {
  require_root
  write_conf_if_needed
  reload_running_servers
  log "Done."
}

main "$@"
