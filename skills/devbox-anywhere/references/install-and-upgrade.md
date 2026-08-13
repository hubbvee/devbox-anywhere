# Installation and upgrades

## Fresh installation

1. Query published stable releases and choose one containing the harness, installer, skill, and guide.
2. Clone that tag into an unprivileged review directory and resolve `APPROVED_COMMIT` with Git.
3. Run:

```bash
./scripts/devbox-anywhere preflight --json
./scripts/devbox-anywhere plan --json --approved-commit "$APPROVED_COMMIT"
```

4. Show the parsed plan. Obtain explicit approval for its sudo and container effects.
5. Create `/opt/devbox-anywhere` as a clean root-owned detached checkout of the exact commit, following `docs/00-agent-guided-install.md`.
6. Run the exact `install_command` from the plan only after approval.
7. After explicit sudo approval, run `sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json`.

Do not interpolate `APPROVED_COMMIT` inside an unreviewed privileged command. Resolve it first, display the exact 40-character value, obtain approval, and pass that literal approved value.

## Upgrade

An upgrade is another pinned installation, not an in-place branch pull:

1. Back up the existing devbox and verify the archive before changing source or containers.
2. Resolve the new stable tag and exact commit independently from the installed checkout.
3. Review release notes and the harness plan, including network-mode changes.
4. Obtain approval for replacing `/opt/devbox-anywhere` and rebuilding/restarting containers.
5. Create a fresh root-owned detached checkout at the new commit; do not run `git pull` in a privileged mutable tree.
6. Run the installer. It preserves the existing generated browser password and persistent `/data/devbox` mounts on a normal rerun.
7. Require the sudo verification command to pass before reporting the upgrade complete.

If verification fails, preserve state, run `diagnose --json`, and avoid rolling forward with additional speculative changes.

## Human-only steps

The user controls:

- server access and sudo approval;
- public-network exposure and firewall rules;
- DNS/TLS provider changes;
- their SSH public key;
- reading the generated browser password locally.

Never ask them to send the password or a private key through chat.
