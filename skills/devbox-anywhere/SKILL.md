---
name: devbox-anywhere
description: "Use when operating or recovering Devbox Anywhere."
version: 1.0.0
author: hubbvee
license: MIT
metadata:
  hermes:
    tags: [devbox, vps, docker, tmux, hermes, operations]
    related_skills: [hermes-agent, coding-project-orchestration]
---

# Devbox Anywhere

## Overview

Operate Devbox Anywhere through its versioned repository harness. Hermes explains and coordinates; repository scripts enforce source trust, privilege boundaries, secret handling, private network defaults, and runtime checks.

A skill is not a security boundary. Never replace a failing repository check with prompt reasoning or a hand-written command that bypasses the harness.

## When to use

Load this skill when the user asks to:

- install or upgrade Devbox Anywhere on a Linux VPS;
- verify or diagnose an installation;
- configure Hermes project topics and tmux sessions;
- hand a checkout between coding agents;
- back up, restore, or rebuild a devbox.

Do not use this for unrelated Docker hosts or generic VPS administration.

## Core workflow

1. **Resolve release truth.** Select a stable release that contains `./scripts/devbox-anywhere`, `./scripts/install-devbox`, this skill, and its references. Resolve and display its exact commit. Never substitute a branch tip.
2. **Inspect without mutation.** Run `./scripts/devbox-anywhere preflight --json`. Treat `ok: false` and malformed JSON as a stop, not an invitation to improvise.
3. **Build the plan.** Run `./scripts/devbox-anywhere plan --json --approved-commit EXACT_SHA`. Add `--expose-ssh` only after the user explicitly chooses public SSH and understands firewall preparation.
4. **Ask for explicit approval.** Show the exact commit, source location, persistent paths, listeners, approvals, and installer command. Approval is required before sudo, packages, firewall, public exposure, DNS/TLS, or container build/start.
5. **Install only pinned bytes.** Create the clean root-owned checkout at `/opt/devbox-anywhere` using the approved stable release. Run the repository installer exactly as planned. Do not install from an agent-writable checkout.
6. **Verify real boundaries.** After explicit sudo approval, run `sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json`. Root is required to read the owner-only installer state. Completion requires every reported check to pass.
7. **Diagnose truthfully.** On failure and with the same explicit sudo approval, run `sudo /opt/devbox-anywhere/scripts/devbox-anywhere diagnose --json`, present failed check IDs and safe local recovery commands, and stop. Do not claim success from command intent.

Completion: the selected stable tag resolves to the approved exact commit, the privileged command consumed the root-owned checkout, and `verify --json` returned `ok: true`.

## Hard boundaries

- Keep code-server and container SSH on loopback by default.
- Never print, request, paste, log, or commit generated passwords, private keys, Telegram tokens, provider credentials, or installer environment-file contents.
- Ask only for SSH public keys.
- Treat Telegram/Hermes terminal access as the gateway OS account's authority, not chat-level containment.
- Treat project topics and tmux names as routing policy, not authentication or sandboxing.
- Keep one writer per checkout during coding-agent handoffs.
- Preserve owner-only backups and use authenticated encryption off-host.
- Do not publish, deploy unrelated services, alter firewalls, or rotate credentials without separate authority.

## Progressive references

Load only the branch needed:

- Installation and upgrades: `references/install-and-upgrade.md`
- Runtime verification and diagnosis: `references/verify-and-diagnose.md`
- Telegram project topics: `references/telegram-project-topics.md`
- Coding-agent handoffs: `references/agent-handoffs.md`
- Backups, restore, and rebuild: `references/backups-and-recovery.md`
- Threat model and approval boundaries: `references/security-boundaries.md`

## Install this skill

Install from the same verified stable checkout used for the workflow. After showing the exact release commit and obtaining approval to modify Hermes state:

```bash
install -d -m 0700 "$HOME/.hermes/skills/devbox-anywhere"
cp -R ./skills/devbox-anywhere/. "$HOME/.hermes/skills/devbox-anywhere/"
```

Do not use the GitHub skill identifier for this security-sensitive workflow: Hermes currently resolves that identifier from the mutable default branch rather than a tag or commit. Start a new Hermes session after installation so the skill index is refreshed.

## Common pitfalls

1. **Skill prose replaces the harness.** Run the repository command and consume its JSON.
2. **Latest branch is treated as latest release.** Resolve a stable tag and exact commit.
3. **Preflight is treated as installation.** It is read-only readiness evidence.
4. **A green container start is treated as completion.** Require all verify checks.
5. **Public SSH is inferred from convenience.** It requires the explicit option and firewall approval.
6. **Diagnostics are pasted wholesale.** Keep sensitive logs local; report check IDs and redacted conclusions.

## Verification checklist

- [ ] Stable installer-bearing release and exact commit displayed
- [ ] `./scripts/devbox-anywhere preflight --json` parsed successfully
- [ ] `./scripts/devbox-anywhere plan --json` matched the approved network mode
- [ ] Human approved every listed privileged/public effect
- [ ] Root-owned `/opt/devbox-anywhere` consumed the exact commit
- [ ] `sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json` returned `ok: true`
- [ ] No secret value appeared in chat, logs, or committed files
