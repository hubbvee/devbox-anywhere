# Backups and recovery

Follow `docs/09-backups-rebuilds-hardening.md` and `scripts/backup-devbox.sh` as repository authority.

## Backup

- Treat `/data/devbox` and Hermes state as secret-bearing.
- Require owner-only local backup directories and archives.
- Reject symlink destinations and unsafe ownership or modes.
- Stop a running Hermes gateway before capture when consistency requires it.
- Verify the archive before atomic publication.
- Recover the gateway and confirm recovery before declaring backup success.
- Never publish an archive after capture, verification, recovery, or interruption failure.
- Encrypt sensitive off-host backups with authenticated encryption.

Do not print archive contents or secret-bearing paths into chat. Retention must be explicit and validated.

## Restore and rebuild

1. Verify the backup archive and encryption/authentication before replacing state.
2. Resolve a stable Devbox Anywhere release and exact commit.
3. Recreate the root-owned source checkout and persistent directory ancestry.
4. Restore data with restrictive ownership and modes.
5. Run the pinned installer to rebuild the container declaration.
6. After explicit sudo approval, run `sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json`.
7. Verify Hermes gateway, topic routing, project directories, tmux sessions, credentials, and provider logins separately.

A passing container check does not prove restored Hermes routing or third-party credentials. Report each recovery layer independently.
