# Devbox Anywhere agent installation contract

When a user asks you to install Devbox Anywhere, use the supported guided workflow in
[`docs/00-agent-guided-install.md`](docs/00-agent-guided-install.md). Do not invent a new
installer and do not pipe a remote script into a shell.

## Required behavior

1. Confirm the target is a Linux server and that the user controls it.
2. Inspect the checked-out revision and show `scripts/install-devbox --dry-run --yes`
   before making changes.
3. Explain that the default ports are loopback-only. Ask separately before exposing SSH;
   never expose code-server's HTTP port directly to the public internet.
4. Ask for approval before `sudo`, package installation, firewall changes, DNS/TLS work,
   or starting/replacing containers.
5. Select an installer-bearing stable release, show its exact commit, and obtain approval.
   Create a clean root-owned checkout under `/opt/devbox-anywhere` at that commit. Never
   install from an agent-owned working tree or from a branch tip.
6. Run `sudo ./scripts/install-devbox --yes --approved-commit EXACT_SHA` only from that
   root-owned checkout. The installer must reject a different SHA, dirty tree, non-root
   source owner, or group/other-writable source.
7. Never request, print, paste, log, or commit the generated password, private SSH keys,
   Telegram tokens, provider credentials, or the contents of the generated environment
   file.
8. Verify the container and helpers, then give the user the exact local command for
   reading the generated password and adding their **public** SSH key.
9. Stop and report the real error if a prerequisite or verification fails. Do not claim
   installation succeeded from command intent or partial output.

Coolify remains a guided UI path. The automated installer targets the repository's plain
Docker Compose deployment so it can be run consistently by Claude, Codex, Hermes, or any
other terminal-capable agent.
