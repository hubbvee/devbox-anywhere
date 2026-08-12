# 05 — Connect from any device (browser, desktop, Termius on your phone)

Five ways into the same box, all landing in the same tmux sessions. Use them all.

## A. Browser (any device, zero setup)

`https://devbox.example.com` → password (→ Cloudflare Access if you enabled it).
Every terminal tab auto-attaches to `main`. Works on a phone browser in a pinch, but
for real phone work use Termius (section D).

## B. Desktop terminal via the host (docker exec route)

Add the `devbox()` function from [`clients/devbox.zsh`](../clients/devbox.zsh) to your
`~/.zshrc` and set `DEVBOX_HOST`. It SSHes to the VPS host and `docker exec`s into the
container's tmux:

```bash
devbox            # attach main
devbox api        # attach/create api
devbox ls
```

This route works even if the container's own sshd is down — useful as the fallback.
(It must be a shell *function*, not an alias: with an alias the `$(docker ps ...)`
container lookup runs on your machine instead of the server.)

## C. Direct SSH into the container (port 2222)

The image runs its own key-only sshd, published as host port `2222`. Add your key and
an alias:

```bash
# on the SERVER (host): append your device's pubkey to the persisted authorized_keys
cat laptop-devbox.pub | sudo tee -a /data/devbox/ssh/authorized_keys
```

```sshconfig
# ~/.ssh/config on your device
Host devbox
  HostName YOUR_SERVER_IP
  Port 2222
  User coder
  IdentityFile ~/.ssh/laptop-devbox
```

Now `ssh devbox` lands as `coder` with the full toolchain, `scp`/`rsync`/SFTP work, and
IDE-style remotes (VS Code Remote-SSH, the Claude Code desktop app's SSH host feature)
can target `devbox` directly. The sshd host key is persisted, so rebuilds don't trigger
"host key changed" warnings.

**Adding a device = append one pubkey line. Revoking a device = delete that line.**

## D. Phone: Termius, done right (this is the good part)

Install [Termius](https://termius.com) (iOS/Android), generate a key **in the app**
(Keychain → generate ed25519), and export/send yourself the public key. Then create
**two hosts** pointing at the same server:

### Host 1 — "devbox picker" (one tap → choose a session)

On the **VPS host**, install [`scripts/devbox-attach`](../scripts/devbox-attach) at
`~/bin/devbox-attach` (`chmod +x`), then add the phone's key to the **host** user's
`~/.ssh/authorized_keys` with a **forced command** (all one line):

```text
command="/home/youruser/bin/devbox-attach",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA...yourphonekey phone-devbox
```

Termius host: `YOUR_SERVER_IP`, port `22`, user `youruser`, that key.

One tap on your phone now shows a numbered menu of live sessions — tap a number, type a
new name to create one, or hit Enter for `main`. The forced command means this key can
*only* run the picker: no port forwarding, no arbitrary shell on the host, and session
names are sanitized (`[A-Za-z0-9._-]+`) against injection. Lost phone = delete the line.

### Host 2 — "devbox shell" (full container shell)

Append the same phone pubkey to `/data/devbox/ssh/authorized_keys` (the *container*
sshd), and add a second Termius host: `YOUR_SERVER_IP`, port `2222`, user `coder`.
This gives a normal shell for file management and one-off commands; from there
`devbox <name>` works like everywhere else.

Phone workflow in practice: kick off an AI agent from your desk in session `api`, leave,
then from the couch one-tap into `api` and watch/approve it live. tmux mouse mode means
you scroll with your finger.

## E. Fixes for weird terminals (you'll hit these)

**Exotic TERM (Ghostty, kitty):** tmux dies instantly with
`missing or unsuitable terminal: xterm-ghostty` because the container lacks the
terminfo entry. One-time fix from the affected machine — no root, survives rebuilds:

```bash
infocmp -x xterm-ghostty | ssh devbox 'mkdir -p ~/.local/share/terminfo && tic -x -o ~/.local/share/terminfo -'
```

(`devbox-relink` maintains the `~/.terminfo` symlink pointing at it.)

**Locale warnings** (`setlocale: cannot change locale`): your terminal forwards its
locale (e.g. `en_CA.UTF-8`) over SSH; if the container hasn't generated it, every shell
warns. Add your locale to the `locale.gen` line in the Dockerfile and rebuild.

Next: [06 — Secrets with 1Password or Bitwarden](06-secrets-management.md)
