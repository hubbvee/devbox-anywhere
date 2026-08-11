# 08 — Hermes: one agent that controls every session

By docs/04 you have multiple tmux sessions, each possibly running its own AI agent or
long job. **Hermes** is the messenger on top: one orchestrator agent (or just you, with
one command) that can *list* every session, *read* what's on any screen, and *type*
into any of them. No daemons, no APIs — it's all plain tmux:

```
tmux list-sessions      → what's running?
tmux capture-pane       → what's on that screen?
tmux send-keys          → type into that screen
```

[`scripts/hermes`](../scripts/hermes) wraps those three into a tool that's equally
usable by humans and agents:

```bash
hermes ls                                  # all sessions + attached/activity
hermes peek api 60                         # last 60 lines of the api session
hermes send api "git status"               # type into api + Enter
hermes run tests "npm test"                # create tests session if needed, then run
hermes wait tests "passed|failed"          # block until the output matches
hermes broadcast "git fetch"               # every session (confirms on a TTY)
```

Install inside the container (`~/.local/bin`, persists) — or run it from your laptop
against the box with `export HERMES_SSH=devbox` (any host with the 2222 SSH alias).

## Making an AI agent the operator

Start a dedicated session and an agent in it:

```bash
devbox hermes
claude    # or codex, or any CLI agent
```

Then tell the agent about its hands, persistently, in `~/.claude/CLAUDE.md` (or
`~/AGENTS.md`):

```markdown
## Orchestrating other sessions
This box runs one tmux session per project. You have the `hermes` CLI:
- `hermes ls` / `hermes peek <s> [n]` / `hermes send <s> "<cmd>"` / `hermes run <s> "<cmd>"`
- Other sessions may be running their own interactive AI agents. `hermes send` types
  into their prompt — you can delegate to them and `hermes peek` for their answer.
- Never `broadcast` destructive commands. Prefer peek-before-send.
```

What this unlocks:

- **Morning standup:** "peek every session and summarize what happened overnight" —
  one prompt, and Hermes reads each pane's scrollback.
- **Delegation:** Hermes `run`s a fresh session per subtask (`hermes run migrate
  "claude -p 'run and fix the db migration'"`), then `wait`s on completion patterns.
  tmux is the process manager; every subtask's full history stays visible in its pane.
- **Agent-to-agent:** an interactive agent's prompt is just stdin. `hermes send blog
  "summarize your last change"` literally types into that agent; `hermes peek blog`
  reads its reply. Crude, transparent, and debuggable from any phone.
- **You, watching:** everything Hermes does is visible — attach to any session from any
  device and you see exactly what was typed. That transparency is the reason to build
  on tmux instead of a message bus.

## Keep it safe

- `send-keys` types with **your** permissions into **live** shells: treat `broadcast`
  like `sudo` (the script asks for confirmation on a TTY for a reason).
- Give the orchestrator the same rule you'd give a junior: read (`peek`) before you
  write (`send`), and no destructive one-liners into sessions you didn't create.
- Agents inside sessions still have their own approval prompts for dangerous actions —
  Hermes doesn't bypass those, it just types.
- If a remote machine should *only* orchestrate, give it a dedicated SSH key and lock
  it down like the phone key in docs/05 (forced command, no forwarding).

Next: [09 — Backups, rebuilds, hardening](09-backups-rebuilds-hardening.md)
