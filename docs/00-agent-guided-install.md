# 00 — Agent-guided installation

If you are using Claude, Codex, Hermes, or another terminal-capable agent, give it the
repository URL and say:

> **Availability:** this workflow is not publicly installable until a stable release tag
> containing `scripts/install-devbox` is published. Until then, agents must stop after
> discovery rather than substitute an unreviewed branch tip.
>
> Install Devbox Anywhere on my Linux server using the repository's `AGENTS.md` and
> `docs/00-agent-guided-install.md`. Show me the dry-run plan first, keep ports private by
> default, ask before privileged or public-network changes, execute the supported
> installer, verify the result, and guide me through only the human-only steps.

The agent can perform almost the entire plain-Docker installation. You remain responsible
for approving privileged changes, supplying server access, choosing public exposure, and
adding your own public SSH key. The agent must never ask you to paste a private key or
secret into chat.

## What the installer does

`scripts/install-devbox` is a local, inspectable Bash script. It:

1. shows a resolved installation plan and requires confirmation;
2. checks Linux, Docker Engine, Docker Compose v2, OpenSSL, and daemon access;
3. creates rebuild-resistant host directories with restrictive permissions;
4. generates a random code-server password without printing it;
5. stores deployment settings in an owner-only file;
6. builds and starts the pinned Compose stack;
7. installs the persisted `devbox` and `devbox-relink` helpers; and
8. verifies the running container before reporting success.

It is resumable: running it again preserves the generated browser password and persistent
data while rebuilding the declared stack. It does not install Docker, configure DNS/TLS,
alter the firewall, upload keys, or silently expose services.

## Safe agent workflow

### 1. Connect and inspect

The agent should connect using the access method you authorized and inspect the stable
release you selected. After you approve its exact commit, it creates a clean root-owned
checkout; privileged Docker must never consume an agent-owned mutable working tree.

```bash
git clone https://github.com/hubbvee/devbox-anywhere.git /tmp/devbox-anywhere-review
cd /tmp/devbox-anywhere-review
git fetch --tags
git checkout vX.Y.Z
APPROVED_COMMIT=$(git rev-parse HEAD)
./scripts/install-devbox --help
./scripts/install-devbox --dry-run --yes --approved-commit "$APPROVED_COMMIT"
```

The agent must resolve the available release tags, show the user the selected exact tag
and commit, and verify that it contains this installer. It must not silently select an
unreviewed branch tip merely because it is newer.

After approval, create the installation checkout without copying the mutable review tree:

```bash
sudo rm -rf /opt/devbox-anywhere
sudo git clone --no-checkout https://github.com/hubbvee/devbox-anywhere.git /opt/devbox-anywhere
sudo git -C /opt/devbox-anywhere checkout --detach "$APPROVED_COMMIT"
sudo chmod -R go-w /opt/devbox-anywhere
```

### 2. Approve the plan

Defaults are deliberately private:

- code-server: `127.0.0.1:8080`;
- SSH: `127.0.0.1:2222`;
- persistent data: `/data/devbox`.

Use the exact SSH tunnel printed by the installer initially. A VPN alone does not expose a
service bound to server loopback. If you deliberately need direct SSH, configure a
restrictive host/provider firewall first and then use `--expose-ssh`. Do not expose port
8080 directly; put authenticated HTTPS through Coolify, Caddy, Traefik, nginx, or a
zero-trust access proxy in front of it.

### 3. Install and verify

After you approve the dry-run and any required `sudo` use:

```bash
cd /opt/devbox-anywhere
sudo ./scripts/install-devbox --yes --approved-commit "$APPROVED_COMMIT"
```

Examples of deliberate overrides:

```bash
sudo ./scripts/install-devbox --yes --expose-ssh --approved-commit "$APPROVED_COMMIT"
```

The agent should retain the command output but redact any accidental credential material.
It must verify the final status command printed by the installer instead of assuming a
successful build means a healthy service.

### 4. Human-only completion

The installer prints local commands to:

- read the generated browser password on the server;
- append your **public** SSH key; and
- inspect Compose status.

With the private default, keep the host SSH tunnel open and connect the container client
to `127.0.0.1:2222`. A direct `SERVER_ADDRESS:2222` connection is printed only when the
installation was explicitly run with `--expose-ssh`.

Keep the generated environment file and `/data/devbox` private. Continue with
[03 — Deploy the devbox](03-deploy-the-devbox.md) for HTTPS/Coolify details and
[05 — Connect from any device](05-connect-from-any-device.md) for client setup.

## Why not `curl | sudo bash`?

A blind remote one-liner can change after review, hides what receives root privileges,
and encourages agents to skip approval boundaries. Cloning a pinned release, inspecting
the local script, running its dry-run, and then approving the exact local command is only
slightly longer and substantially safer.
