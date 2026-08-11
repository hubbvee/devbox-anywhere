#!/usr/bin/env bash
set -e

# --- Seed VS Code user settings on first boot (don't overwrite your changes) ---
SETTINGS_DIR="$HOME/.local/share/code-server/User"
mkdir -p "$SETTINGS_DIR"
if [ ! -f "$SETTINGS_DIR/settings.json" ]; then
  cp /etc/devbox-defaults/settings.json "$SETTINGS_DIR/settings.json"
fi

# --- Seed tmux config (re-seeded from image on a fresh container; fine since static) ---
if [ ! -f "$HOME/.tmux.conf" ]; then
  cp /etc/devbox-defaults/tmux.conf "$HOME/.tmux.conf"
fi

# --- Workspace + persisted user-bin dir + inbox for file drops (see docs/07) ---
mkdir -p "$HOME/project/_inbox" "$HOME/.local/bin"

# --- Route user-level `npm i -g` into the persisted ~/.local (survives rebuilds) ---
if [ ! -f "$HOME/.npmrc" ] || ! grep -q '^prefix=' "$HOME/.npmrc" 2>/dev/null; then
  echo "prefix=$HOME/.local" >> "$HOME/.npmrc"
fi

# --- SSH dir perms (a fresh persistent volume can mount back as 0755) ---
if [ -d "$HOME/.ssh" ]; then chmod 700 "$HOME/.ssh" || true; fi

# --- Shared dev credentials: ~/.secrets -> persisted ~/.local/secrets ---
mkdir -p "$HOME/.local/secrets" && chmod 700 "$HOME/.local/secrets"
ln -sfn "$HOME/.local/secrets" "$HOME/.secrets"

# --- Restore persisted-data symlinks (terminfo, gh login, gitconfig, ...). The script
# lives in persisted ~/.local/bin so it survives rebuilds; safe no-op when absent,
# e.g. on the first-ever boot. This is what makes rebuilds fully hands-off. ---
if [ -x "$HOME/.local/bin/devbox-relink" ]; then
  "$HOME/.local/bin/devbox-relink" || echo "WARN: devbox-relink failed"
fi

# --- sshd: direct SSH into the devbox (desktop apps, ssh -p 2222) ---
# Host key lives in the persisted ~/.ssh so the server identity survives rebuilds
# (no "host key changed!" warnings after a rebuild).
HOSTKEY_DIR="$HOME/.ssh/host_keys"
mkdir -p "$HOSTKEY_DIR"
if [ ! -f "$HOSTKEY_DIR/ssh_host_ed25519_key" ]; then
  ssh-keygen -t ed25519 -N "" -f "$HOSTKEY_DIR/ssh_host_ed25519_key" -C "devbox-sshd-host-key"
fi
chmod 600 "$HOSTKEY_DIR/ssh_host_ed25519_key"
touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys"
sudo mkdir -p /run/sshd
sudo /usr/sbin/sshd || echo "WARN: sshd failed to start; devbox direct SSH unavailable"

# Hand off to the stock code-server entrypoint (dumb-init + code-server "$@").
exec /usr/bin/entrypoint.sh "$@"
