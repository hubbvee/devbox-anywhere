# Coding-agent handoffs

Follow `docs/11-switch-coding-agents-mid-session.md` as repository authority.

## One-writer protocol

1. Identify the exact checkout, branch/HEAD, tmux pane, and current writer.
2. Stop autonomous background work before handing ownership over.
3. Preserve tracked and untracked work. Treat ignored files as potentially secret-bearing.
4. Create a provider-neutral handoff containing goals, exact Git state, changed paths, tests run, failures, and prohibited external effects.
5. Independently verify the handoff against Git and process state.
6. Exit only the outgoing provider process.
7. Start the replacement in the same verified checkout and prove it entered real activity before calling the handoff complete.

Provider chat history does not migrate. Portable state consists of files, Git objects, tmux/process state, services, test evidence, and a verified handoff note.

## Authority boundaries

A handoff does not authorize commit, push, release, deployment, credential use, or public network changes. Preserve the user's existing approvals exactly; do not widen them.

Broad modes such as `danger-full-access` expose everything reachable by the devbox account. Isolation must come from a dedicated checkout/worktree, one writer, narrow task contracts, diff inspection, and independent tests.

## tmux input

The repository helper is installed as `tmuxctl`, not `hermes`. `tmuxctl send`, `run`, and `broadcast` inject literal terminal input; they are not authentication or parsing boundaries. Broadcast requires explicit `--yes`.
