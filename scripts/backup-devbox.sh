#!/bin/bash
# Nightly backup of the devbox container's ~/project, ~/.ssh and ~/.local/secrets.
# Runs on the VPS HOST (via cron), independent of the container lifecycle, so it survives
# image rebuilds. Finds the container by the STABLE Coolify label so it keeps working
# after delete+recreate. Plain docker compose: swap the filter for  -f name=devbox
#
# Install on the host:
#   crontab -e   →   15 3 * * * $HOME/bin/backup-devbox.sh >> $HOME/devbox-backups/backup.log 2>&1
#
# Restore:
#   CID=$(docker ps -q -f label=coolify.resourceName=devbox | head -1)
#   docker exec -i $CID tar xzf - -C /home/coder < devbox-YYYYMMDD-HHMMSS.tar.gz
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/devbox-backups}"
KEEP="${KEEP:-14}"                    # how many nightly archives to retain
PATHS="project .ssh .local/secrets"   # dirs (relative to /home/coder) to include

mkdir -p "$BACKUP_DIR"

CID=$(docker ps -q -f label=coolify.resourceName=devbox | head -1)
if [ -z "$CID" ]; then
  echo "$(date -Is) ERROR: devbox container not running" >&2
  exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/devbox-$STAMP.tar.gz"

# Stream a tar of the target dirs out of the container to a host file.
docker exec "$CID" tar czf - -C /home/coder $PATHS > "$OUT"

# Retention: keep the newest $KEEP, delete the rest.
ls -1t "$BACKUP_DIR"/devbox-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "$(date -Is) OK: $OUT ($(du -h "$OUT" | cut -f1))"
