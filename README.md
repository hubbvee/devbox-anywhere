# Devbox Anywhere

**Your dev environment on a cheap VPS — reachable from every device you own, including
your phone. Code, long-running builds, and AI coding agents that keep working after you
close the laptop.**

This isn't a theoretical tutorial: it's the exact setup we run daily, extracted into a
repo. Browser IDE + tmux on a VPS, one named session per project, one-tap attach from
an iPhone via Termius, secrets from 1Password/Bitwarden, drag-and-drop file transfer,
and an orchestrator pattern ("Hermes") where one agent supervises every session.

```text
                        ┌────────────────────────── YOUR VPS (OVH / Hetzner / any) ─┐
  Desktop browser ──────►  HTTPS (Coolify/Traefik + optional Cloudflare Access)     │
  Desktop terminal ─────►  ssh host → docker exec ─┐                                │
  Laptop / VS Code ─────►  ssh :2222 (container) ──┤   ┌──────────────────────────┐ │
  iPhone (Termius) ─────►  ssh :22 forced-command ─┼──►│  devbox container        │ │
       one-tap picker      "devbox-attach" menu    │   │  code-server (browser IDE)│ │
  Any device w/ key ────►  ssh :2222 full shell ───┘   │  sshd :22 (key-only)     │ │
                        │                              │  tmux ── main            │ │
                        │   /data/devbox/* bind ──────►│       ├─ api    (agent)  │ │
                        │   mounts (survive rebuilds)  │       ├─ blog   (agent)  │ │
                        │                              │       └─ hermes (orchestrator)
                        └──────────────────────────────┴──────────────────────────┴─┘
```

## What you get

- **Code lives on the server, not your laptop.** Close the lid mid-build; reattach from
  your phone; nothing died.
- **One session per project** — run several AI agents / builds / servers in parallel and
  hop between them from any device with the same 3 commands (`devbox`, `devbox ls`,
  `devbox kill`).
- **Phone access done right** — Termius + a forced-command SSH key = one tap opens a
  numbered menu of your live sessions. Lost phone = delete one line to revoke.
- **Rebuild-proof persistence** — host bind mounts + a relink script mean image
  rebuilds keep your code, tools, and every CLI login (GitHub, Claude, etc.).
- **Secrets that follow you** — 1Password service account (or Bitwarden) read by the
  box; repos commit only `op://` references, never keys.
- **Files in, from anywhere** — a Dock drop-folder, a screenshot command, SFTP from the
  phone; everything lands in `~/project/_inbox/`.
- **Hermes** — a tiny tmux wrapper that lets one agent list, read, and type into every
  other session. Orchestration with zero infrastructure.

## Quick start

1. **[Get a VPS](docs/01-get-a-vps.md)** — Ubuntu LTS, ~$5+/mo, 10 min of hardening.
2. **[Install Coolify](docs/02-install-coolify.md)** — one command; gives you HTTPS +
   deploy UI. (Plain-Docker alternative included.)
3. **[Deploy the devbox](docs/03-deploy-the-devbox.md)** — the container from
   [`stack/`](stack/): code-server + tmux + sshd, with bulletproof bind-mount
   persistence.
4. **[Learn the session vocabulary](docs/04-tmux-sessions.md)** — one session per
   project, multiple agents in parallel.
5. **[Connect every device](docs/05-connect-from-any-device.md)** — browser, terminal,
   VS Code/Claude desktop over SSH, and the Termius one-tap phone setup.
6. **[Wire up secrets](docs/06-secrets-management.md)** — 1Password or Bitwarden CLI.
7. **[Send files in](docs/07-getting-files-in.md)** — DevboxDrop, `2dev`, `devshot`.
8. **[Run the Hermes pattern](docs/08-hermes-agent.md)** — one agent to drive them all.
9. **[Backups & rebuilds](docs/09-backups-rebuilds-hardening.md)** — nightly cron,
   hands-off rebuilds, hardening checklist.
10. **[Manage projects from Telegram topics](docs/10-telegram-project-topics.md)** —
    one private forum group, one isolated topic and tmux session per project.
11. **[Switch coding agents mid-session](docs/11-switch-coding-agents-mid-session.md)** —
    safely hand a live worktree between Claude Code, Codex, or another CLI.

## Repo layout

| Path | What |
| --- | --- |
| `docs/01–11` | The guide, in build order |
| `stack/` | Dockerfile, entrypoint, tmux/sshd/VS Code configs, compose alternative |
| `scripts/` | Server-side: `devbox`, `devbox-attach` (phone picker), `devbox-relink`, `hermes`, backup cron |
| `clients/` | Your Mac: `devbox()` + `2dev` + `devshot` zsh functions, DevboxDrop watcher |
| `templates/` | `main.env` and per-project `.env.op` examples |

## Get a server

We run this on **[OVH](https://www.ovhcloud.com)**; **[Hetzner](https://www.hetzner.com)**
is equally good (often cheaper). Sizing table in [docs/01](docs/01-get-a-vps.md).

> **Disclosure:** some provider links in this repo may be or become affiliate links —
> signing up through them supports this guide at no extra cost to you. The setup works
> identically wherever you rent your server.

## FAQ

**Why not just VS Code Remote-SSH / Codespaces / a cloud IDE?**
Those give you an editor; this gives you a *place*. Sessions that outlive every client,
reachable from a phone, hosting your own deployed apps on the same box, no per-seat
pricing, and your agents keep working while you're gone.

**Does it need Coolify?** No — [`stack/docker-compose.yml`](stack/docker-compose.yml)
runs it with plain Docker + any reverse proxy. Coolify just makes HTTPS and redeploys
one-click, and you'll want it for everything else you self-host.

**Android instead of iPhone?** Termius works the same; any SSH client with key auth
does (the picker is server-side).

**Windows/Linux desktop instead of Mac?** Everything server-side is OS-agnostic. The
`clients/` helpers are macOS/zsh; ports to PowerShell/systemd-user timers are
straightforward PRs — contributions welcome.

## License

[MIT](LICENSE). Built from a real production setup; sanitized, but the gotchas are all
real. Issues and PRs welcome.
