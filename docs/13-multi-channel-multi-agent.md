# Multi-channel sessions with multiple agents

This devbox lets several channels — a terminal over SSH, a Telegram topic, a Slack channel —
drive the **same** project work, and lets **several agents** work one project in parallel
without stepping on each other. The box, not any single chat, is the source of truth.

## Model

```
project   -> one tmux session            the shared "room"; every channel resolves to it
agent     -> one window + one worktree    its own checkout + branch = real parallel isolation
channel   -> project:window | session     a thin control surface onto the pane
turn-lock -> per worktree                 one writer per checkout (advisory coordination)
```

- **Session name == project name.** One project is one durable tmux session on the devbox.
  Attaching from any channel (`tmux attach`, a Telegram topic, a Slack channel) reaches the
  same live session — the shell, running processes, branch, and files are identical
  everywhere the instant you switch.
- **Each agent is a tmux window backed by its own git worktree and branch.** Two agents on
  the same project work in separate checkouts (`agent/<agent>` branches), so they never
  collide. One agent = one window = zero extra overhead vs. a plain session.
- **The agent lives in the pane; channels drive it.** A channel sends keystrokes and reads
  output; it does not spawn its own agent. Switch channels and you are talking to the same
  agent process with its full context. If the agent process exited, recover it with the
  CLI's own resume (`claude --resume`, `codex resume`) against the persistent
  `~/.claude` / `~/.codex` mounts — not by starting a fresh one.

## Channels are configured in Hermes, not here

Which channels exist (Telegram, Slack, …), how they authenticate, and who is allowed to use
them are **Hermes configuration**, not part of this repository. Devbox Anywhere provides only
the box-side session layer (`devbox-session`, `devbox-turn`, `devbox-worktree`) and this
guide. To add a channel, configure it in Hermes and point it at a project's tmux target via
the repository helper `tmuxctl` (see `docs/04-tmux-sessions.md` and
`docs/10-telegram-project-topics.md`).

## Tools

The installer copies these helpers into the container's `~/.local/bin` (on the persistent
`dot-local` mount, so they survive rebuilds), and the harness `verify` confirms each is
executable. Run them from any shell in the devbox.

- `devbox-session list` — show projects, their sessions, and registered agents.
- `devbox-session resolve <project>` — print the session name.
- `devbox-session resolve <project> <agent>` — print `session` / `window` / `worktree` /
  `branch` for one agent. Fails closed on unknown, off-convention, duplicate, or malformed
  input.
- `devbox-worktree add <project> <agent>` — create the agent's git worktree + `agent/<agent>`
  branch + tmux window and register it. Atomic: a failure rolls the worktree/branch back so
  you never get a half-registered agent.
- `devbox-worktree list` — show all agents with their worktree and branch.
- `devbox-worktree remove <project> <agent> [--force]` — tear down window + worktree +
  branch. Refuses to drop a worktree with uncommitted changes unless `--force`.
- `devbox-turn take|release|status <worktree>` — claim / release / inspect the one-writer
  turn for a checkout.
- `devbox-daemon start|status|stop <name>` / `start-all` / `status-all` — supervise
  long-running helpers (e.g. a Hermes gateway) declared in
  `~/.local/share/devbox-daemons.d/*.conf`. Start is start-if-not-running; `status` is the
  liveness source of truth. `devbox-relink` runs `devbox-daemon start-all` on every container
  boot, so declared daemons come back after a rebuild with no manual step. The default backend
  is a detached tmux session, which works on this image where systemd is present but not PID 1
  (so `hermes gateway install` does not). See `docs/10-telegram-project-topics.md` for the full
  gateway example.

The installer also places `devbox-status-gate` beside them: a read-only forced command for a
bot's SSH key that answers only `version`, `list`, and `status <project> [--json]`, and is
inert until an `authorized_keys` line uses it. See `docs/14-let-a-bot-manage-your-devbox.md`.

## Naming convention

Agent ids **must** be `<project>-<suffix>` (e.g. `webapp-api`, `webapp-web`) so any channel
can address an agent unambiguously as `project:agent`. The helpers reject off-convention or
colliding names.

## Worktrees and the turn-lock

- Worktrees live under `~/project/.worktrees/<agent>` — on the persistent project mount, so
  they survive container rebuilds like all other devbox state.
- The turn-lock is keyed on the **worktree path**, because the real collision surface is two
  writers in one checkout, not the shared session. Use it when an agent and a human (or two
  agents) can both write the same worktree:

  ```sh
  devbox-turn take   ~/project/.worktrees/webapp-api   # claim before editing
  devbox-turn status ~/project/.worktrees/webapp-api   # see the current holder
  devbox-turn release ~/project/.worktrees/webapp-api  # hand it back
  ```

  Acquisition is atomic (only one taker wins a race). A lock left idle past
  `DEVBOX_TURN_TTL` (default one hour) is reclaimable as a stale-lock safety net. Prefer
  explicit `release` over waiting for the TTL.

## Example: two agents on one project

```sh
devbox-worktree add webapp webapp-api    # window webapp-api, branch agent/webapp-api
devbox-worktree add webapp webapp-web    # window webapp-web, branch agent/webapp-web
devbox-session list                        # confirm both agents
# run an agent CLI in each window; drive either one from terminal, Telegram, or Slack.
devbox-worktree remove webapp webapp-api # clean removal once merged (refuses dirty WIP)
```

## Agent status board

`devbox-session status <project>` gives an at-a-glance readout of every agent on a project —
which are working, and which are safe to clean up. (The idea is inspired by herdr's
"agents at a glance"; this is a native reimplementation on tmux + git, not a dependency, and
a full cockpit TUI is out of scope — run herdr on top if you want one.)

```
$ devbox-session status webapp
project=webapp session=webapp base=main  (activity is a heuristic)
webapp-api       dirty         +3/-0  turn:alice      working
webapp-web       clean         +1/-0  turn:free       idle
webapp-fresh     new           +0/-0  turn:free       idle
webapp-cli       merged+dirty  +0/-0  turn:free       working
webapp-old       merged        +0/-0  turn:free       idle       (reapable)
```

Two kinds of signal, deliberately distinguished:

- **Exact git/turn facts** — `clean|dirty`, `+ahead/-behind` vs the base branch, `merged`
  (the branch is an ancestor of base **and has moved past its fork point**), `new` (the
  branch still sits exactly where it was forked — no commits of its own yet), and the
  `devbox-turn` holder. These are computed from git and the lock; trust them. The state
  column shows every fact that applies, so dirt is never hidden: a fresh branch with
  uncommitted changes reads `new+dirty` and a merged one reads `merged+dirty`. `(reapable)`
  = `merged && clean && turn free && activity != working`, and **never** while a window
  bearing the agent's name may exist but cannot be proven (see activity below). A `new`
  branch is **never** `merged` or `reapable`, so a just-created (possibly live) agent is
  never flagged for cleanup. A worktree missing from disk is never `reapable` either.

  How `new` is detected: for a worktree created by this version, `devbox-worktree` records
  the fork point (the base tip at creation) as a 4th registry column, and `new` means
  `HEAD == fork`. For a **legacy 3-column registry** written before the upgrade, the fork
  column is absent, so status falls back to the branch reflog: a branch whose only reflog
  entry is its creation (`branch: Created from …`) has no commits of its own and is `new`.
  If the reflog is unreadable (disabled, or pruned away), newness can't be determined — the
  agent is then **never** reported `reapable`, erring toward keeping it rather than reaping a
  branch we can't judge. New worktrees get the fork column automatically; no migration of an
  existing registry is required.
- **Activity is a HEURISTIC** — `working|blocked|idle`, inferred from the tmux pane
  (`working` = a non-shell foreground command; `idle` = a shell prompt; `blocked` = a known
  waiting-for-input prompt that has stalled past `DEVBOX_STATUS_STALE`, default 60s). When the
  pane can't be read it is `unknown` — never guessed. The board first proves the agent's
  window exists — exactly one window in the project's session whose name is exactly the
  agent id — and reads only that window, so it never borrows the state of the session's main
  shell. Two kinds of `unknown` follow, and they differ for cleanup:
  - **Provably nothing there** — no tmux session for the project, or no window with the
    agent's name. Activity is `unknown`, but nothing can be running there, so the agent can
    still be `(reapable)` when it is merged, clean, and the turn is free.
  - **A window that may exist but cannot be proven** — the agent's name appears on more than
    one window, tmux's listing is inconsistent (for example, a raw newline inside a window
    name or a pane command forges extra rows), or the window vanishes mid-read. Activity is
    `unknown` and the agent is **never** `(reapable)`.

  `--json` marks activity with `"activity_confidence":"heuristic"`. Do not gate
  irreversible actions on activity alone.
  **Known limit:** `working` means *any* non-shell foreground process, so an agent CLI
  (claude/codex) sitting idle at its own prompt still reads `working` — its process is always
  in the foreground. For the board's main use case that is usually what you want (`working`
  ≈ "an agent CLI is open in this window"), but it is not a claim that the agent is actively
  producing output. Treat `working` as "occupied", not "busy".

`--json` emits a schema-versioned document (`schema_version: 1`) with one object per agent;
values are JSON-escaped and no secrets appear. The base branch is `DEVBOX_STATUS_BASE`, else
the repo's `main` then `master`. Unknown project fails closed; a worktree that has vanished
from disk is reported `"missing": true`, never a crash.

**Reap workflow:** an agent shown `(reapable)` is merged, clean, unheld, and not actively
running — tear it down with `devbox-worktree remove <project> <agent>` (still refuses a dirty
tree without `--force`). An agent whose window reads `working` is never `(reapable)`. The
board only sees the tmux server its own environment points at, though: if tmux is not
installed, if the agents run on a server it does not reach (a `-L` socket, or a
`TMUX_TMPDIR` the caller does not share — the read-only status gate of
[docs/14](14-let-a-bot-manage-your-devbox.md) never shares it), or if an agent runs outside
its named window, activity is `unknown` and a live agent can read `(reapable)`. In those
setups, look before you reap.

## Dependency policy

A new worktree is a **fresh checkout with no installed dependencies** — `node_modules/`, a
Python virtualenv, build caches, etc. do not exist yet. An agent dropped into a brand-new
worktree will hit missing-dependency errors until they are installed.

**Install dependencies per worktree.** Each agent's worktree is an independent working tree;
run the project's install step inside it before (or as part of) starting work:

```sh
cd ~/project/.worktrees/webapp-api && npm ci        # or: uv sync, pip install -e ., etc.
```

Automate it with the post-add hook — `DEVBOX_WORKTREE_POSTADD` runs in the new worktree
right after the agent is created:

```sh
DEVBOX_WORKTREE_POSTADD='npm ci' devbox-worktree add webapp webapp-api
```

If the hook fails, `add` exits non-zero but keeps the worktree, branch, and registration, so
you can fix the environment and re-run the install without recreating the agent.

**Do not share `node_modules/` (or a venv) between worktrees** — e.g. via a symlink to a
common directory. It reintroduces exactly the cross-checkout coupling worktrees exist to
avoid: native modules built for one branch's dependency tree corrupt another, concurrent
installs race, and lockfile drift becomes invisible. Each worktree owns its own dependency
directory. If disk or install time is a concern, prefer a package manager with a global
content-addressed store (e.g. `pnpm`, or `uv`'s cache) that stays safe across worktrees,
rather than sharing the install directory itself.

## What this is not

- **Not a live TUI mirror.** Line-oriented command/response maps cleanly to chat via
  pane snapshots and new-line streaming. Full-screen TUIs (vim, htop, a full-screen agent
  UI) do **not** render in Telegram or Slack — attach a real terminal for those.
- **Not a security or sandbox boundary.** The turn-lock is advisory coordination, not
  enforcement. And every channel you wire in carries the devbox account's full terminal
  authority — this is **not a sandbox**. Restrict who can reach each channel in Hermes
  configuration, and stream output with the same redaction discipline you use in chat.
