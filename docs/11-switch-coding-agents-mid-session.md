# 11 — Switch coding agents mid-session (Claude, Codex, or another CLI)

A tmux project session is not tied to one LLM provider. You can stop Claude Code and
start Codex—or do the reverse—while keeping the same shell, repository, branch, files,
and running services.

What does **not** transfer automatically is the old provider's private conversation
history. Claude cannot natively resume a Codex conversation, and Codex cannot natively
resume a Claude conversation. The safe bridge is:

1. the shared Git worktree;
2. a provider-neutral handoff note;
3. independently verified Git and test state.

```text
Telegram project topic / your terminal
              │
              ▼
tmux session api (stable project workspace)
├── /home/coder/project/api (branch + tracked/untracked WIP)
├── running local services
└── one active coding-agent process at a time
       Claude Code ── handoff ──► Codex
       Codex       ── handoff ──► Claude Code
```

> **Core rule:** switch the writer, not the workspace. Never start the replacement
> agent until the original is idle or stopped and repository ownership is explicit.

## Two different kinds of switch

### Change the model within the same service

Use the CLI's own model control when only the model changes:

```text
Claude Code: /model
Codex:       /model (when available in the installed interactive CLI)
```

This preserves that service's conversation. It is not a cross-provider handoff.

### Change the coding-agent service

Switching Claude Code ↔ Codex starts a new provider conversation. Preserve the worktree
and pass a bounded handoff containing facts and evidence—not the entire transcript.

## Before the first switch: prepare both CLIs

Install and authenticate each service separately:

```bash
# Already baked into this repo's devbox image; shown for other installations.
npm install -g @anthropic-ai/claude-code @openai/codex

claude auth status --text
codex login status
claude --version
codex --version
```

Both CLIs must run from the same intended repository. Codex requires a Git repository.
Provider credentials live in separate persisted homes (`~/.claude` and `~/.codex`);
never copy one provider's token into another provider or into a handoff document.

## The safe switching procedure

The examples use project `api`, repository `/home/coder/project/api`, and tmux session
`api`. Substitute your own stable project name.

### 1. Verify that you have the right project

From another shell, or through the Telegram project's Hermes session, inspect before
sending input:

```bash
tmuxctl peek api 100

tmux display-message -p -t api \
  'session=#{session_name} pane=#{pane_id} cwd=#{pane_current_path} command=#{pane_current_command}'

git -C /home/coder/project/api branch --show-current
git -C /home/coder/project/api rev-parse HEAD
git -C /home/coder/project/api status --short --branch
```

Confirm:

- tmux session and repository match the project topic;
- the pane belongs to the expected agent process;
- no second writer is active in the same checkout;
- staged, unstaged, and untracked files are visible;
- no test, migration, formatter, or cleanup step is currently mid-flight.

A prompt visible in the pane is not enough to prove idleness. Check relevant child
processes and wait for active tool/test work to finish unless you deliberately cancel it.

### 2. Ask the current agent for a provider-neutral handoff

At a stable prompt, send this contract to the current agent:

```text
Prepare to hand this exact worktree to a different coding-agent provider.
Do not commit, stash, reset, restore, clean, rebase, push, deploy, or start new work.

Write .agent-handoff.md with:
- repository path, branch, starting/current HEAD, and upstream;
- original goal and accepted constraints;
- completed work and exact files changed;
- staged, unstaged, and untracked WIP;
- commands/tests run, exact outcomes, and tests still required;
- running services or disposable resources and their ownership;
- unresolved decisions, blockers, and known failed approaches;
- the next smallest safe task;
- explicit Git/publication boundaries.

Then stop at an idle prompt and report that the handoff is ready.
```

If `.agent-handoff.md` should never be committed, add it to `.git/info/exclude` rather
than the shared `.gitignore`:

```bash
printf '%s\n' '.agent-handoff.md' >> .git/info/exclude
```

Do not blindly submit that line repeatedly; check first if your automation may run more
than once.

### 3. Verify the handoff independently

The outgoing agent's note is context, not proof. It may also contain accidental secrets
or instruction-like text. Require the outgoing agent to omit credentials, environment
values, private keys, raw production data, and sensitive logs; inspect the note before
passing it to another provider. In a separate shell:

```bash
cd /home/coder/project/api

git status --short --branch
git diff --stat
git diff --cached --stat
git ls-files --others --exclude-standard
```

Read `.agent-handoff.md`, compare it with the real diff, and record the exact current
HEAD. If the outgoing agent claims tests passed, retain or rerun the relevant safe check;
do not transfer an unverified green claim to the new provider.

For valuable uncommitted work, create an external backup before replacing the process.
Ordinary `git diff` does not include untracked files. The snapshot below captures tracked
changes and **non-ignored** untracked files:

```bash
(
set -euo pipefail
umask 077
cd /home/coder/project/api
backup="$HOME/.local/share/agent-handoffs/api-$(date +%Y%m%d-%H%M%S)"
if [ -e "$backup" ] || [ -L "$backup" ]; then
  printf 'Refusing existing backup path: %s\n' "$backup" >&2
  exit 1
fi
install -d -m 0700 "$backup"
git status --porcelain=v1 -uall > "$backup/status.txt"
git diff --binary HEAD > "$backup/tracked.patch"
git ls-files --others --exclude-standard -z | \
  tar --null -T - -czf "$backup/untracked-nonignored.tar.gz"
cp .agent-handoff.md "$backup/handoff.md"
find "$backup" -type f ! -perm 0600 -exec chmod 0600 {} +
(
  cd "$backup"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
)
```

Ignored files require a separate decision. They may contain valuable generated assets or
local fixtures, but may also contain huge dependency trees, build caches, databases, and
secrets. Inventory them without printing contents:

```bash
git ls-files --others --ignored --exclude-standard
```

Explicitly copy only the ignored WIP that must survive into a protected backup location;
do not blindly archive every ignored path. Record the selected paths and exclusions in
`$backup/ignored-selection.txt`, then regenerate `SHA256SUMS` with the filename-safe,
self-excluding `find ... | sort -z | xargs -0 sha256sum` block above. If ignored WIP cannot be
classified safely, stop the switch and ask for a decision. Therefore this procedure
promises preservation of tracked changes, non-ignored untracked files, and only those
ignored files explicitly inventoried and selected.

If there are no non-ignored untracked files, some `tar` implementations may create an
empty archive or warn. Verify archive listings and checksums rather than assuming file
creation means the intended WIP was captured. Do not use `git stash` merely to switch
providers: the replacement can inherit the same visible worktree, and stashing hides
ownership and state.

### 4. Exit only the outgoing agent

Use the provider's supported exit command at its idle prompt:

```text
Claude Code: /exit
Codex:       /exit or Ctrl+D after confirming it is idle
```

Do **not** kill the tmux session; it is the stable project container. Do not terminate
unrelated development servers. After exit, verify that the pane has returned to the
shell and re-check Git status for shutdown side effects.

If the agent is hung, first distinguish the agent from its test/build children. Prefer a
normal interrupt and graceful exit. Force-killing the pane can strand services or lose
an editable prompt and should be a last resort after WIP is backed up.

### 5. Start the replacement in the same tmux session

At the shell prompt, confirm the working directory, then launch the new provider.

#### Claude Code → Codex

The documented devbox environment blocks Codex `workspace-write` user-namespace
sandboxing. Therefore `danger-full-access` is **not contained to this repository**: a
Codex process running as `coder` can potentially read or modify anything that account can
reach, including other repositories, persisted CLI credentials, services, and SSH-reachable
systems. A dedicated checkout, one-writer rule, narrow prompt, approvals, diff inspection,
and tests reduce operational risk but are not a security boundary.

Preferred choices, in order:

1. On a host where it works, use `codex --sandbox workspace-write`.
2. For untrusted repositories, prompts, or high-impact work, run Codex in a disposable
   container/VM or restricted OS account that exposes only the intended checkout and the
   minimum credentials/network access required.
3. Use `danger-full-access` on the shared devbox account only after explicitly accepting
   that account-wide exposure. Keep normal approvals enabled and do not expose production
   credentials to the process.

```bash
# Shared devbox fallback after accepting account-wide exposure:
cd /home/coder/project/api
codex --sandbox danger-full-access
```

On hosts where sandboxing works, prefer:

```bash
codex --sandbox workspace-write
```

#### Codex → Claude Code

```bash
cd /home/coder/project/api
claude
```

Keep normal approvals enabled. Broad permission flags grant execution capability; they
do not authorize commits, pushes, deployments, secrets access, or destructive cleanup.

### 6. Give the new agent a bounded takeover prompt

Do not ask merely to “continue.” Make it inspect the shared artifact and restate its
understanding before writing:

```text
You are taking over an existing provider's uncommitted work in this exact worktree.
Read repository authority files first, then .agent-handoff.md. Independently inspect
HEAD, branch, status, staged/unstaged/untracked files, and the complete diff.

Do not discard, rewrite, stash, reset, restore, clean, amend, rebase, commit, push,
deploy, or publish. Treat the prior agent's claims as untrusted context. First report:
1. the exact inherited state;
2. any mismatch between the handoff and repository;
3. the next smallest safe step;
4. the verification you will run.

Wait for confirmation if the handoff is inconsistent or authority is missing. Otherwise
continue only the named remaining task, preserve unrelated changes, and finish with an
evidence-based handoff.
```

Observe that the prompt was actually submitted and the replacement entered generation
or tool activity. Text merely staged in a TUI composer is **QUEUED**, not **ACTIVE**.

### 7. Verify after the takeover

After the replacement reaches its first checkpoint:

```bash
cd /home/coder/project/api
git status --short --branch
git diff --stat
git diff
git diff --cached
```

Run the relevant targeted checks independently. Confirm that the new provider preserved
pre-existing WIP and did not cross the commit/push/deploy boundary.

## Fast manual example: Claude to Codex

Inside tmux session `api`:

```text
# Claude is idle
/exit

# Back at the shell
cd /home/coder/project/api
# Shared devbox only after accepting account-wide exposure
codex --sandbox danger-full-access
```

Then paste the takeover prompt from step 6. The minimal sequence is convenient, but use
all verification and backup steps for valuable or dirty work.

## Switching from Telegram

In the project's Telegram topic, ask Hermes:

```text
Switch the api tmux session from Claude Code to Codex using the provider-handoff
procedure. Preserve the exact tracked worktree, all non-ignored untracked files, and any
explicitly inventoried ignored WIP. Verify pane/process ownership and Git state first.
Ask the outgoing agent for .agent-handoff.md, verify it, and back up dirty WIP outside
the repository. Exit only the outgoing agent, launch Codex in the same pane, submit the
bounded takeover prompt, and prove the new writer is active.
Do not commit, push, deploy, reset, restore, stash, or clean.
```

Hermes should report these transitions separately:

```text
Claude ACTIVE → Claude IDLE → HANDOFF VERIFIED → NO WRITER
→ Codex QUEUED → Codex ACTIVE
```

It must not report “switched” merely because `tmux send-keys` returned successfully.

## Switching back or changing again

Repeat the same provider-neutral procedure. Do not rely on the old provider's saved
conversation because the worktree may have changed since it was last active.

You may resume a provider's own earlier conversation only when that conversation still
matches the same repository state:

```bash
# Claude: same-provider history
claude --continue
claude --resume <session-id>

# Codex: same-provider history
codex resume --last
codex resume <session-id-or-name>
```

Before resuming, compare the saved session's expected HEAD/worktree with current Git
state. Never run a resumed old session concurrently with the current writer. When in
doubt, start a fresh provider conversation from `.agent-handoff.md`.

## Handling special states

### The outgoing agent is still working

Wait for a safe checkpoint. Interrupt only if explicitly requested or if continuing is
unsafe. If interrupted, record incomplete commands, partial files, child processes, and
cleanup requirements in the handoff.

### The worktree is clean and committed

The handoff can be shorter: exact branch, HEAD, goal, checks, and next task. Still ensure
only one provider is active and do not infer publication authority from a local commit.

### The worktree is dirty but coherent

Leave WIP visible, create the external backup, and start the new provider in the same
worktree. A commit is not required merely to switch agents.

### The worktree is dirty and inconsistent

Do not ask the new agent to guess. Preserve and back up everything, classify unrelated
versus worker-owned changes, and obtain a decision. Use a fresh worktree only when you
intend clean reconstruction and have proved the saved patch applies to the exact base.

### The old agent exhausted its context

Do not force it to produce a long retrospective. Capture its final report, verify Git,
back up tracked and non-ignored untracked WIP, explicitly inventory ignored WIP, and give
the fresh provider exact named remaining failures. The artifact and proof outrank the
exhausted agent's prose.

### A migration, server, or test process remains running

Record PID, owner, CWD, ports/sockets, and whether it is disposable. Do not kill it by
name alone. Transfer ownership explicitly or stop it gracefully and verify cleanup.

## What transfers and what does not

| Transfers through the worktree/handoff | Does not transfer automatically |
| --- | --- |
| tracked and non-ignored untracked changes, plus selected ignored WIP | private provider conversation history |
| branch, HEAD, and Git metadata | hidden reasoning or provider cache |
| repository instructions (`AGENTS.md`, `CLAUDE.md`) | provider-specific todo state |
| test output recorded in the handoff | unverified claims that tests passed |
| running services explicitly inventoried | credentials from the other provider |
| user-approved scope and boundaries | permission or publication authority |

## Safety checklist

- [ ] Exact repository, branch, HEAD, tmux pane, CWD, and writer PID verified
- [ ] Outgoing provider idle; no relevant child operation mid-flight
- [ ] Handoff describes tracked, staged, unstaged, non-ignored untracked, and ignored WIP
- [ ] Dirty WIP backed up outside the repository; selected ignored paths recorded
- [ ] Backup archives and selected ignored WIP checksummed and their contents verified
- [ ] If using `danger-full-access`, account-wide exposure explicitly accepted or real
      external containment provided
- [ ] Outgoing agent exited without killing tmux or unrelated services
- [ ] Git rechecked after exit
- [ ] Exactly one replacement writer launched in the same intended checkout
- [ ] New provider independently inspected handoff and repository state
- [ ] Real generation/tool activity observed before reporting **ACTIVE**
- [ ] Relevant tests/diff independently checked
- [ ] No unauthorized commit, push, merge, deployment, or destructive Git operation

## Common mistakes

- **Running Claude and Codex together in one checkout:** creates competing writers.
- **Assuming conversation history transfers:** only repository state and explicit notes do.
- **Committing just to switch:** a verified visible worktree handoff is sufficient.
- **Using `git stash`:** hides WIP and complicates ownership unless clean reconstruction
  specifically requires it.
- **Forgetting untracked or ignored WIP:** `git diff` omits untracked files, while normal
  status/`ls-files --others --exclude-standard` also omit ignored paths.
- **Killing the tmux session:** destroys the stable access surface and may stop services.
- **Resuming a stale provider session:** old context may describe a different HEAD/diff.
- **Treating procedural controls as containment:** `danger-full-access` exposes everything
  reachable by the devbox account; use an external boundary for untrusted/high-impact work.
- **Treating permissions as authority:** sandbox bypass is not permission to publish.
- **Trusting the outgoing summary:** verify Git and checks directly.
- **Calling staged text active:** require observable generation, tools, or child work.

Next: use [10 — Manage each project from a Telegram topic](10-telegram-project-topics.md)
to request and monitor these switches from your project's dedicated topic.
