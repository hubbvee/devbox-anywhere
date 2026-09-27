# Multi-channel sessions with multiple agents

Follow `docs/13-multi-channel-multi-agent.md` as repository authority.

## Model

- Project == one tmux session (session name == project name); every channel resolves to the
  same live session, so shell/processes/branch/files are identical across terminal, Telegram,
  and Slack.
- Each agent == one tmux window backed by its own git worktree + `agent/<agent>` branch, so
  multiple agents work one project in parallel without breaking one-writer-per-checkout.
- The agent lives in the pane; channels drive it (send keystrokes, read output). Recover a
  dead agent with the CLI's own `--resume` against the persistent `~/.claude` / `~/.codex`
  mounts, not a fresh process.

## Channels live in Hermes config

Channel existence, authentication, and access control are Hermes configuration, not this
repository. Point a configured channel at a project's tmux target via `tmuxctl`. This repo
provides only the box-side layer.

## Tools

- `devbox-session list | resolve <project> [agent]` — resolve project -> session -> agent
  (`session`/`window`/`worktree`/`branch`). Fails closed on unknown/off-convention/duplicate/
  malformed input.
- `devbox-session status <project> [--json]` — agent board: exact git facts (dirty,
  ahead/behind vs base, merged, turn holder, `reapable`) plus a LABELED activity heuristic
  (`working|blocked|idle|unknown`; `--json` sets `activity_confidence:"heuristic"`). Base via
  `DEVBOX_STATUS_BASE` else repo main/master. Unknown project fails closed; a vanished
  worktree is `missing`, never a crash. Trust git/turn facts; don't gate on activity alone.
- `devbox-worktree add|list|remove <project> <agent> [--force]` — create/list/tear down an
  agent's worktree + branch + window. `add` rolls back on failure; `remove` refuses a dirty
  worktree without `--force`.
- `devbox-turn take|release|status <worktree>` — per-worktree one-writer turn.

## Conventions and boundaries

- Agent ids must be `<project>-<suffix>`; worktrees under
  `~/project/.worktrees/<agent>` (persistent).
- A fresh worktree has no installed dependencies: install them per worktree (or via
  `DEVBOX_WORKTREE_POSTADD`, run in the new worktree after `add`), and never share
  `node_modules`/venv across worktrees. See docs/13 "Dependency policy".
- The turn-lock is keyed on the worktree path and is advisory coordination, not a security
  boundary; acquisition is atomic and idle locks past `DEVBOX_TURN_TTL` are reclaimable.
- Chat surfaces show snapshots/streams, not a live TUI mirror.
- Every wired channel carries the devbox account's full terminal authority. This is not a
  sandbox; restrict channel access in Hermes and keep output redaction discipline.
