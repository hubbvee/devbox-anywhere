# 03 — Deploy the devbox

The devbox is one container: [code-server](https://github.com/coder/code-server)
(VS Code in the browser) + tmux + a key-only sshd, built from
[`stack/Dockerfile`](../stack/Dockerfile). The browser IDE is the *screen*; tmux is the
*brain* that keeps everything alive when you disconnect.

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

1. **+ New → Application → Dockerfile** (paste the contents of `stack/Dockerfile`;
   Coolify's Dockerfile build pack also needs the `stack/config/*` files and
   `entrypoint.sh` — easiest is to point Coolify at your fork of this repo with
   `stack/` as the build context).
2. Name it **`devbox`** — the name matters: scripts find the container via the stable
   label `coolify.resourceName=devbox`, which survives rebuilds (the app uuid does not).
3. **Domain:** `https://devbox.example.com`, **Ports Exposes:** `8080`.
   If the page 502s after deploy, check `docker logs` — some code-server versions
   ignore the CMD bind-addr and listen on `80`; if so set Ports Exposes to `80`.
4. **Env var:** `PASSWORD` = a long random string (25+ chars). This is the browser
   login for the IDE.
5. **Port mapping:** `2222:22` (the container's direct sshd — docs/05).
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

## Two ways to add tools later (and make them stick)

1. **Bake into the Dockerfile** — permanent, required for apt/system packages;
   applies on next rebuild.
2. **Self-service, no rebuild** — drop static binaries into `~/.local/bin`, or
   `npm i -g` / `pip install --user` (both are routed into persisted `~/.local`).
   apt packages can't self-persist; bake those.

Next: [04 — tmux sessions](04-tmux-sessions.md)
