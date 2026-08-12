# Devbox Anywhere — desktop-side helpers (zsh; macOS + Linux).
# Append this file's contents to ~/.zshrc (or source it), then edit the two variables.
#
# Assumes an ssh alias `devbox` in ~/.ssh/config for the container sshd:
#   Host devbox
#     HostName YOUR_SERVER_IP
#     Port 2222
#     User coder
#     IdentityFile ~/.ssh/id_ed25519

DEVBOX_HOST="youruser@YOUR_SERVER_IP"      # VPS host login (for the docker-exec route)
DEVBOX_LABEL="coolify.resourceName=devbox" # container lookup; compose: use name=devbox

# devbox [session] / devbox ls / devbox kill <name>
# Attach to (or create) a named tmux session in the devbox from your desktop terminal.
# Goes through the HOST + docker exec, so it works even if the container sshd is down.
# NOTE: must be a FUNCTION, not an alias — alias quoting runs the $(docker ps ...)
# lookup on your Mac instead of the server ("No such container: tmux").
devbox() {
  local session
  if [ "$1" = "ls" ]; then
    ssh "$DEVBOX_HOST" "docker exec -u coder \$(docker ps -q -f label=$DEVBOX_LABEL | head -1) tmux ls"
    return
  fi
  if [ "$1" = "kill" ]; then
    if [ -z "$2" ]; then echo "usage: devbox kill <session>  (see: devbox ls)"; return 1; fi
    session="$2"
    [[ -n "$session" && "$session" != *[^A-Za-z0-9._-]* ]] || { echo "invalid session name: $session" >&2; return 2; }
    ssh "$DEVBOX_HOST" "docker exec -u coder \$(docker ps -q -f label=$DEVBOX_LABEL | head -1) tmux kill-session -t '=$session'" \
      && echo "killed session: $session"
    return
  fi
  session="${1:-main}"
  [[ -n "$session" && "$session" != *[^A-Za-z0-9._-]* ]] || { echo "invalid session name: $session" >&2; return 2; }
  ssh -t "$DEVBOX_HOST" "docker exec -it -u coder \$(docker ps -q -f label=$DEVBOX_LABEL | head -1) tmux new -A -s '$session'"
}

# --- file/screenshot bridge ---------------------------------------------------------
# Drag-dropping a file onto a REMOTE terminal only pastes your LOCAL path — the bytes
# never transfer, so an agent running on the devbox can't see the file. These ship the
# bytes to ~/project/_inbox/ on the devbox and put the REMOTE path in your clipboard.

# 2dev [files...]: send file(s) (default: your newest screenshot) to the devbox.
2dev() {
  local -a files
  if (( $# )); then files=("$@"); else
    local dir=$(defaults read com.apple.screencapture location 2>/dev/null)
    dir=${dir:-$HOME/Desktop}; dir=${dir/#\~/$HOME}
    local latest=$(command ls -t "$dir" 2>/dev/null | grep -iE '\.(png|jpe?g|gif|pdf|mov)$' | head -1)
    [[ -z $latest ]] && { echo "2dev: no screenshots found in $dir"; return 1; }
    files=("$dir/$latest")
  fi
  ssh devbox 'mkdir -p ~/project/_inbox' || return 1
  scp -q "${files[@]}" "devbox:project/_inbox/" || return 1
  local out="" f base
  for f in "${files[@]}"; do base="${f:t}"; out+="~/project/_inbox/${base// /\\ } "; done
  print -rn -- "${out% }" | pbcopy
  echo "→ devbox ~/project/_inbox/ (${#files[@]} file(s); remote path copied to clipboard)"
}

# devshot: interactive area-capture straight to the devbox (macOS; skips Desktop entirely)
devshot() {
  local f="/tmp/devshot-$(date +%Y%m%d-%H%M%S).png"
  screencapture -i "$f" && [[ -s "$f" ]] || { echo "devshot: capture cancelled"; return 1; }
  2dev "$f" && rm -f "$f"
}
