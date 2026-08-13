# 07 — Getting files INTO the devbox

The trap everyone hits: you drag a screenshot onto a terminal running a remote session
and the terminal pastes your **local** path (`/Users/you/Desktop/shot.png`). The bytes
never left your machine — an agent running on the devbox can't see them. Everything
here ships the bytes and hands you the **remote** path.

## The `_inbox` convention

All inbound files land in one place: `~/project/_inbox/` (created by the entrypoint).
One folder to check, one folder to clean out.

**If you run AI agents on the devbox**, tell them about it once, in the devbox's
persisted agent instructions (`~/.claude/CLAUDE.md` or `~/AGENTS.md`):

```markdown
Files sent from my other devices land in ~/project/_inbox/. When I mention an
uploaded/dropped file, look there first.
```

Before we added that line, agents kept searching the whole filesystem for "the file I
just sent you."

## Level 0 — plain scp/rsync (works from anything with the 2222 key)

These commands use the `devbox` SSH alias configured in docs/05. With the installer's
private default, that alias points to `127.0.0.1:2222` while the host SSH tunnel is open;
it points directly to the server only in explicit `--expose-ssh` mode.

```bash
scp report.pdf devbox:project/_inbox/
rsync -av --exclude node_modules ./myproject/ devbox:project/myproject/
```

macOS tar gotcha for archives: prefix with `COPYFILE_DISABLE=1 tar czf ...` or your
archive arrives full of `._*` AppleDouble junk.

## Level 1 — `2dev` and `devshot` (macOS shell functions)

From [`clients/devbox.zsh`](../clients/devbox.zsh):

- **`2dev`** — no args: ships your *newest screenshot*; with args: ships those files.
  Remote path lands in your clipboard, ready to paste to an agent.
- **`devshot`** — interactive area screenshot (`screencapture -i`) straight to the
  devbox, skipping your Desktop entirely. Screenshot → paste path → agent sees it,
  in ~3 seconds.

## Level 2 — DevboxDrop (drag-and-drop folder, macOS)

A Dock folder that ships anything dropped into it:

1. `mkdir -p ~/DevboxDrop ~/bin`, copy in [`clients/devbox-drop.sh`](../clients/devbox-drop.sh)
   (`chmod +x`), edit `YOUR_MAC_USERNAME` in
   [`clients/com.devbox.drop.plist`](../clients/com.devbox.drop.plist), then:

   ```bash
   cp com.devbox.drop.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.devbox.drop.plist
   ```

2. Pin `~/DevboxDrop` to the Dock. Drag anything onto it → it appears in
   `~/project/_inbox/`, the remote path is in your clipboard, and you get a
   notification. Originals archive to `~/DevboxDrop/.sent/`.

It handles directories (`scp -r`) and half-copied files (size-settle check). **The
silent-failure gotcha is baked in:** launchd agents don't inherit `SSH_AUTH_SOCK`, so a
passphrase-protected key fails without any error — the script's first line rediscovers
the agent socket. If drops don't arrive, that line is where to look.

## From a phone

- **Termius** has a built-in SFTP tab — connect through the private tunnel, or directly to
  the `devbox` port 2222 host only in explicit `--expose-ssh` mode,
  upload into `project/_inbox/`.
- Or the browser IDE: code-server accepts drag/upload into the file explorer directly.

Next: [08 — The Hermes pattern](08-hermes-agent.md)
