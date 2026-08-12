#!/bin/bash
# Nightly backup of project data, SSH, secrets, and the Hermes Agent home.
# Runs on the VPS HOST (via cron), independent of the container lifecycle, so it survives
# image rebuilds. Finds the container by the STABLE Coolify label so it keeps working
# after delete+recreate. Plain docker compose: swap the filter for  -f name=devbox
#
# Install on the host:
#   install -d -m 0700 "$HOME/devbox-backups"
#   crontab -e   →   15 3 * * * umask 077; $HOME/bin/backup-devbox.sh >> $HOME/devbox-backups/backup.log 2>&1
#
# Restore:
#   CID=$(docker ps -q -f label=coolify.resourceName=devbox | head -1)
#   docker exec -i "$CID" tar xzf - -C /home/coder < devbox-YYYYMMDD-HHMMSS.tar.gz
set -euo pipefail

# Backups contain SSH keys, API tokens, and private session history. Create directories
# and archives owner-only regardless of the host account's inherited cron umask.
umask 077

BACKUP_DIR="${BACKUP_DIR:-$HOME/devbox-backups}"
KEEP="${KEEP:-14}"                    # how many nightly archives to retain

case "$KEEP" in
  ''|*[!0-9]*) echo "KEEP must be a positive integer" >&2; exit 2 ;;
esac
if [ "$KEEP" -lt 1 ]; then
  echo "KEEP must be at least 1" >&2
  exit 2
fi

# Check before mkdir/chmod: chmod follows a symlink and must not touch its target.
if [ -L "$BACKUP_DIR" ]; then
  echo "$(date -Is) ERROR: backup directory must not be a symlink: $BACKUP_DIR" >&2
  exit 1
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

CID=$(docker ps -q -f label=coolify.resourceName=devbox | head -1)
if [ -z "$CID" ]; then
  echo "$(date -Is) ERROR: devbox container not running" >&2
  exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/devbox-$STAMP.tar.gz"
TMP=$(mktemp "$BACKUP_DIR/.devbox-$STAMP.XXXXXX.tmp")
GATEWAY_WAS_RUNNING=0
gateway_is_running() {
  docker exec "$CID" sh -c \
    "ps -u \$(id -u) -o command= | grep -Eq '([g]ateway/run\.py|[h]ermes_cli\.main gateway run)'"
}
restart_gateway() {
  attempts=0
  while [ "$attempts" -lt 3 ]; do
    if docker exec "$CID" hermes gateway start >/dev/null 2>&1 && gateway_is_running; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 2
  done
  return 1
}
cleanup() {
  rm -f -- "$TMP"
  if [ "$GATEWAY_WAS_RUNNING" -eq 1 ]; then
    # Make a bounded best effort to restore service on every failure path. Keep the
    # nonzero backup exit status if recovery still fails so cron monitoring can alert.
    if restart_gateway; then
      GATEWAY_WAS_RUNNING=0
    else
      echo "$(date -Is) ERROR: Hermes gateway restart failed after backup; manual recovery required" >&2
    fi
  fi
}
on_signal() {
  signal=$1
  trap - HUP INT TERM
  # EXIT owns cleanup. Re-raise the signal so callers and cron see the conventional
  # signal-derived status, and never resume the backup after service restoration.
  kill -s "$signal" "$$"
}
trap cleanup EXIT
trap 'on_signal HUP' HUP
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

# Build the include list from paths that exist. Hermes is optional until docs/10. Its
# SQLite/session state must not be copied while the gateway is writing it.
set -- project .ssh .local/secrets
if docker exec "$CID" test -d /home/coder/.local/share/hermes-home; then
  if gateway_is_running; then
    GATEWAY_WAS_RUNNING=1
    docker exec "$CID" hermes gateway stop >/dev/null
  fi
  set -- "$@" .local/share/hermes-home
fi

# Stream to an owner-only temporary file, verify it as a readable tar archive, then
# publish atomically. A failed docker/tar run must never leave a plausible final archive.
docker exec "$CID" tar czf - -C /home/coder "$@" > "$TMP"
tar tzf "$TMP" >/dev/null
if [ "$GATEWAY_WAS_RUNNING" -eq 1 ]; then
  restart_gateway
  GATEWAY_WAS_RUNNING=0
fi
# Do not publish the archive until the gateway has been restored successfully.
mv -- "$TMP" "$OUT"
trap - EXIT HUP INT TERM

# Retention: keep the newest $KEEP, delete the rest.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'devbox-*.tar.gz' -print0 |
  xargs -0 -r ls -1t -- |
  tail -n +$((KEEP + 1)) |
  while IFS= read -r old; do rm -f -- "$old"; done

echo "$(date -Is) OK: $OUT ($(du -h "$OUT" | cut -f1))"
