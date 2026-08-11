# 04 — One session per project (running multiple instances)

tmux is what turns "VS Code on a server" into a devbox: sessions keep running when no
device is attached, and any number of devices can attach to the same session at once.

## The vocabulary: `devbox [session]`

Every entry point (desktop function, in-container script, phone picker) speaks the same
three commands, so your muscle memory is identical everywhere:

```bash
devbox              # attach/create session "main"
devbox api          # attach/create session "api"     ← one session per project
devbox ls           # list sessions
devbox kill api     # kill one
```

Inside the container that's [`scripts/devbox`](../scripts/devbox) (installed to
`~/.local/bin` in docs/03). On your desktop it's the `devbox()` function from
[`clients/devbox.zsh`](../clients/devbox.zsh). On your phone it's the session picker
(docs/05). All of them end in `tmux new -A -s <name>` — *attach if it exists, create if
it doesn't*.

The in-container script has one extra trick: if you're already inside tmux it
*switches* sessions instead of nesting tmux-inside-tmux.

## Running multiple agents / long jobs in parallel

Because sessions are independent shells that never die on disconnect:

```bash
devbox blog        # → run `claude` here working on your blog
devbox api         # → run `codex` here refactoring the API
devbox builds      # → a long test suite or build
```

Three AI agents (or builds, or servers) running simultaneously; from any device you
attach to whichever one you want to check on. This is also the substrate the Hermes
orchestrator drives in docs/08.

Practical conventions that keep this sane:

- **Name sessions after projects**, not devices. `main` is your scratch/default.
- One agent per session. An agent's session is its workspace — logs scroll there,
  approvals happen there.
- `devbox ls` before creating; dead sessions accumulate otherwise.
- The seeded [`tmux.conf`](../stack/config/tmux.conf) enables mouse mode (scroll/select
  panes by touch on a phone), 50k lines of scrollback, and never auto-destroys an
  unattached session.

## Minimal tmux survival kit

Everything below uses the default prefix `Ctrl-b`:

| Keys | Does |
|---|---|
| `Ctrl-b d` | detach (session keeps running) |
| `Ctrl-b c` / `Ctrl-b n` | new window / next window |
| `Ctrl-b %` / `Ctrl-b "` | split vertical / horizontal |
| `Ctrl-b s` | interactive session switcher |
| `Ctrl-b [` | scroll mode (or just use the mouse) |

Next: [05 — Connect from any device](05-connect-from-any-device.md)
