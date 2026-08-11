# 09 — Backups, rebuilds, hardening

## Nightly backups (host cron)

[`scripts/backup-devbox.sh`](../scripts/backup-devbox.sh) runs on the **host** (so it
survives anything that happens to the container), tars `~/project`, `~/.ssh` and
`~/.local/secrets` out of the container, keeps 14 nightly archives:

```bash
# on the VPS host
mkdir -p ~/bin && cp backup-devbox.sh ~/bin/ && chmod +x ~/bin/backup-devbox.sh
crontab -e
# 15 3 * * * $HOME/bin/backup-devbox.sh >> $HOME/devbox-backups/backup.log 2>&1
```

Restore is one line (in the script header). For real disaster recovery, also sync
`~/devbox-backups/` off the server (rclone to any object storage, or restic).

## Rebuilds are hands-off — here's the machinery

You will rebuild the image (new baked tools, base-image updates). The design makes
that boring:

1. **Bind mounts** (docs/03) — code, tools, logins live at `/data/devbox/*` on the
   host; a rebuilt container just re-mounts them.
2. **`devbox-relink`** ([script](../scripts/devbox-relink)) — the few dotfiles that
   CLIs insist on keeping *outside* `~/.local` (e.g. `~/.config/gh`, `~/.gitconfig`)
   live in `~/.local/share/*` with symlinks pointing at them. The entrypoint re-runs
   relink at every boot, so a fresh container has every login restored before you
   even connect. **When you add a CLI that stores config in `~/.config/<tool>`:** move
   the dir into `~/.local/share/`, add one `relink` line, done forever.
3. **Persisted sshd host key** — no "host key changed!" warnings after rebuilds.
4. **Stable container label** — host scripts find the container by
   `coolify.resourceName=devbox` (tracks the app *name*), never by uuid (changes on
   delete+recreate).

Only true loss on rebuild: running tmux sessions (they live in the container). Finish
or checkpoint agent work before rebuilding.

**Know your two install modes** (from docs/03): baked (Dockerfile, permanent) vs
self-service (`~/.local`, instant). When a self-serviced tool proves out, bake it so
fresh rebuilds have it from boot.

## Hardening checklist

- [ ] VPS host: key-only SSH, no root login, ufw, fail2ban (docs/01)
- [ ] code-server `PASSWORD` is long + random, stored in your password manager
- [ ] Cloudflare Access (or equivalent zero-trust/VPN) in front of the web IDE (docs/03)
- [ ] Cloudflare SSL mode **Full (strict)** — never Flexible (docs/02)
- [ ] One SSH key **per device**, so revocation is per-device (docs/01)
- [ ] Phone/tablet keys are **forced-command** on the host — menu only, no shell (docs/05)
- [ ] Container sshd: key-only, `AllowUsers coder`, no root (baked in `stack/config`)
- [ ] Vault access from the box is **read-only** (service account; docs/06)
- [ ] `main.env` is `0600`, holds literals only, and is in the nightly backup
- [ ] Backups tested: actually restore one archive once
- [ ] Know your revoke moves: delete a line in host `authorized_keys` (phone/picker),
      delete a line in `/data/devbox/ssh/authorized_keys` (container), rotate the
      service-account token (vault)
