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

## Naming convention

Agent ids **must** be `<project>-<suffix>` (e.g. `radioos-api`, `radioos-web`) so any channel
can address an agent unambiguously as `project:agent`. The helpers reject off-convention or
colliding names.

## Worktrees and the turn-lock

- Worktrees live under `/data/devbox/project/.worktrees/<agent>` — inside the persistent,
  root-controlled data root, so they survive rebuilds like all other devbox state.
- The turn-lock is keyed on the **worktree path**, because the real collision surface is two
  writers in one checkout, not the shared session. Use it when an agent and a human (or two
  agents) can both write the same worktree:

  ```sh
  devbox-turn take   /data/devbox/project/.worktrees/radioos-api   # claim before editing
  devbox-turn status /data/devbox/project/.worktrees/radioos-api   # see the current holder
  devbox-turn release /data/devbox/project/.worktrees/radioos-api  # hand it back
  ```

  Acquisition is atomic (only one taker wins a race). A lock left idle past
  `DEVBOX_TURN_TTL` (default one hour) is reclaimable as a stale-lock safety net. Prefer
  explicit `release` over waiting for the TTL.

## Example: two agents on one project

```sh
devbox-worktree add radioos radioos-api    # window radioos-api, branch agent/radioos-api
devbox-worktree add radioos radioos-web    # window radioos-web, branch agent/radioos-web
devbox-session list                        # confirm both agents
# run an agent CLI in each window; drive either one from terminal, Telegram, or Slack.
devbox-worktree remove radioos radioos-api # clean removal once merged (refuses dirty WIP)
```

## What this is not

- **Not a live TUI mirror.** Line-oriented command/response maps cleanly to chat via
  pane snapshots and new-line streaming. Full-screen TUIs (vim, htop, a full-screen agent
  UI) do **not** render in Telegram or Slack — attach a real terminal for those.
- **Not a security or sandbox boundary.** The turn-lock is advisory coordination, not
  enforcement. And every channel you wire in carries the devbox account's full terminal
  authority — this is **not a sandbox**. Restrict who can reach each channel in Hermes
  configuration, and stream output with the same redaction discipline you use in chat.
