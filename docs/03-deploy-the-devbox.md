# 03 — Deploy the devbox

The devbox is one container: [code-server](https://github.com/coder/code-server)
(VS Code in the browser) + tmux + a key-only sshd, built from
[`stack/Dockerfile`](../stack/Dockerfile). The browser IDE is the *screen*; tmux is the
*brain* that keeps everything alive when you disconnect.

For the supported almost-one-shot plain-Docker path, including instructions an AI agent
can follow safely, start with [00 — Agent-guided installation](00-agent-guided-install.md).

## 1. Prepare persistent storage on the HOST first

**This is the single most important step in the whole guide.** Use fixed host paths
(bind mounts), not named volumes:

```bash
sudo mkdir -p /data/devbox/{project,dot-local,claude,codex,ssh}
sudo chown -R 1000:1000 /data/devbox     # 1000 = the container's `coder` user
```

Why: named volumes get a new identity every time an app is deleted and recreated — your
code, logins and tools silently start from zero after a rebuild. Bind mounts survive
redeploys, reboots, *and* full delete+recreate rebuilds; to rebuild you just re-attach
the same five paths.

| Host path | Container path | What lives there |
| --- | --- | --- |
| `/data/devbox/project` | `/home/coder/project` | all your code + `_inbox/` for file drops |
| `/data/devbox/dot-local` | `/home/coder/.local` | self-installed tools, npm globals, secrets, extensions |
| `/data/devbox/claude` | `/home/coder/.claude` | Claude Code OAuth + config |
| `/data/devbox/codex` | `/home/coder/.codex` | Codex OAuth + config |
| `/data/devbox/ssh` | `/home/coder/.ssh` | authorized_keys, sshd host key, your git key |

## 2. Create the app in Coolify

1. Fork this repository, then choose **+ New → Application → Public/Private Repository**.
   Select your fork, use the Dockerfile build pack, set `stack/` as the build context,
   and set `Dockerfile` as the Dockerfile location. Do not paste the Dockerfile alone:
   the build also requires `stack/config/*` and `stack/entrypoint.sh` from the same
   pinned repository revision.
2. Name it **`devbox`** — the name matters: scripts find the container via the stable
   label `coolify.resourceName=devbox`, which survives rebuilds (the app uuid does not).
3. **Domain:** `https://devbox.example.com`, **Ports Exposes:** `8080`.
   If the page 502s after deploy, check `docker logs` — some code-server versions
   ignore the CMD bind-addr and listen on `80`; if so set Ports Exposes to `80`.
4. **Env var:** `PASSWORD` = a long random string (25+ chars). This is the browser
   login for the IDE.
5. **Port mapping:** `127.0.0.1:2222:22` by default. Use `2222:22` only for deliberate
   direct access after restricting the host/provider firewall (see docs/05).
6. **Storages:** add the five bind mounts from the table above
   (type *persistent*, with the host path set — host path non-null = bind mount).
7. Deploy.

**Gotcha — crash-loop on first boot ("restarting"):** fresh persistent volumes mount
root-owned, and code-server runs as `coder`. The Dockerfile pre-creates and chowns the
mount points, and step 1 chowned the host dirs — if you skipped step 1, that's your fix.

## 3. First login

Open `https://devbox.example.com`, enter the `PASSWORD`. Every terminal you open
auto-attaches to the tmux session `main` (that's the seeded VS Code setting). Kill the
tab, come back tomorrow from another device — same shell, same running processes.

Install the two in-container helper scripts (they live on the persisted mount, so this
is a one-time step that survives rebuilds):

```bash
mkdir -p ~/.local/bin
# paste in scripts/devbox and scripts/devbox-relink from this repo, then:
chmod +x ~/.local/bin/devbox ~/.local/bin/devbox-relink
```

## 4. Lock it down harder (recommended): Cloudflare Access

A password prompt on the open internet is fine; a zero-trust wall in front of it is
better and free (up to 50 users). In Cloudflare Zero Trust: **Access → Applications →
Self-hosted**, domain `devbox.example.com`, policy *Include → Emails → your email*,
one-time-PIN identity provider. Requires the DNS record proxied (orange cloud) and
SSL Full (strict) from docs/02. Unauthenticated visitors now get Cloudflare's login
before code-server even sees the request.

## Running a second instance

The plain-Docker installer ([docs/00](00-agent-guided-install.md)) can run a second,
fully separate devbox next to your first — for example, one for a bot's agents with
dev-only credentials ([docs/14](14-let-a-bot-manage-your-devbox.md)). From the same
approved checkout:

```bash
cd /opt/devbox-anywhere
./scripts/devbox-anywhere plan --json --approved-commit "$APPROVED_COMMIT" \
  --instance bot --web-port 8180 --ssh-port 2322
sudo ./scripts/install-devbox --dry-run --yes --approved-commit "$APPROVED_COMMIT" \
  --instance bot --web-port 8180 --ssh-port 2322
sudo ./scripts/install-devbox --yes --approved-commit "$APPROVED_COMMIT" \
  --instance bot --web-port 8180 --ssh-port 2322
sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json --instance bot
```

`plan` needs the same `--instance`, `--web-port`, and `--ssh-port` as the installer;
`preflight`, `verify`, and `diagnose` need only `--instance NAME`. Add
`--with-browser --browser-port N` to both `plan` and the installer if the instance also
needs the opt-in GUI browser.

What changes for an instance named `NAME`:

| | Default install | `--instance NAME` |
| --- | --- | --- |
| Data root | `/data/devbox` | `/data/devbox-NAME` |
| Container | `devbox` | `devbox-NAME` |
| Compose project | Compose's default | `devbox-NAME` |
| Ports | `8080` / `2222` (`8081` browser) | the ports you pass, loopback-only by default |

- `NAME` is a letter followed by up to 14 lowercase letters or digits; a few reserved
  names are refused.
- Ports must be in 1024–65535, distinct, not `8080`, `2222`, or `8081`, and not already
  in use; the installer refuses anything else.
- Everything is separate: bind mounts, `authorized_keys`, CLI logins, helpers, sessions.
  Add keys to the instance's own `~/.ssh/authorized_keys`, and tunnel the instance's SSH
  port instead of `2222` ([docs/05](05-connect-from-any-device.md)). Once anything you do
  not fully trust runs in the instance, edit its files from inside it as `coder` (see
  [docs/14 step 3](14-let-a-bot-manage-your-devbox.md#3-add-the-gate-line)), not as host
  root through `/data/devbox-NAME/...`, where a planted symlink would be followed.
- **Without `--instance` nothing changes:** the default install, its paths, and its ports
  are exactly as before. Upgrade an instance by re-running the installer with the same
  flags.
- Backups: `scripts/backup-devbox.sh` takes no arguments (not even `--help`; running it
  starts a backup) and targets one container. Read the comments at the top of the script
  before pointing a copy of it at an instance, or take the stopped-instance `tar` backup
  shown below ([docs/09](09-backups-rebuilds-hardening.md)).

**Removing an instance.** Stop and remove its containers by Compose project name (run it
from a directory without a compose file, so only the project name is used):

```bash
cd / && sudo docker --context default compose -p devbox-NAME down
```

This leaves `/data/devbox-NAME` on disk. Delete it only **after** you have backed it up
and checked the backup, because it holds that instance's code, logins, and keys:

```bash
sudo sh -c 'umask 077; tar -C /data -czf /root/devbox-NAME-final.tar.gz devbox-NAME'
sudo tar -tzf /root/devbox-NAME-final.tar.gz >/dev/null && echo backup-readable
sudo rm -rf /data/devbox-NAME     # irreversible; double-check the name first
```

Never aim these at your default instance (`/data/devbox`, container `devbox`).

## Two ways to add tools later (and make them stick)

1. **Bake into the Dockerfile** — permanent, required for apt/system packages;
   applies on next rebuild.
2. **Self-service, no rebuild** — drop static binaries into `~/.local/bin`, or
   `npm i -g` / `pip install --user` (both are routed into persisted `~/.local`).
   apt packages can't self-persist; bake those.

Next: [04 — tmux sessions](04-tmux-sessions.md)
