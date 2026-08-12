# Devbox Anywhere — code-server + tmux + direct sshd, built for rebuild-proof persistence.
#
# Everything installed here as root lands in /usr and is "baked" (survives rebuilds by
# definition). Everything the USER installs later should go to ~/.local, which is a host
# bind mount (see docs/03) — that's how self-installed tools survive rebuilds too.

# Pin the multi-architecture code-server 4.132.0 image index so this release does not
# silently change when an upstream `latest` tag moves.
FROM codercom/code-server@sha256:b88ed46a6ace76a0294a17a24f39aa88032ed0a3692c3d8ab5433b47ab57ccbf

USER root

# Base tools + dev-terminal staples. tmux is the whole point; the rest save you
# apt-installing on every fresh shell.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tmux git curl wget htop ca-certificates openssh-client openssh-server build-essential \
      jq ripgrep fzf bat tree unzip \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && rm -rf /var/lib/apt/lists/*

# Locales your clients actually forward over SSH. macOS Terminal sends its region's
# locale (e.g. en_CA.UTF-8, de_DE.UTF-8); if the container doesn't have it, every new
# tmux shell warns "setlocale: cannot change locale". Add your region's line here
# (run `echo $LANG` on your machine to see what it forwards).
RUN sed -i -e 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' \
           /etc/locale.gen && locale-gen

# GitHub CLI (official apt repo)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y gh \
 && rm -rf /var/lib/apt/lists/*

# Node.js LTS + AI coding CLIs. Release-defining versions and the NodeSource bootstrap
# script are pinned; update these values deliberately in a reviewed release.
# User-level `npm i -g` later goes to ~/.local instead (entrypoint sets the npm prefix).
ARG NODEJS_VERSION=22.23.2-1nodesource1
ARG CLAUDE_CODE_VERSION=2.1.228
ARG CODEX_VERSION=0.147.0
RUN curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource-setup.sh \
 && echo "575583bbac2fccc0b5edd0dbc03e222d9f9dc8d724da996d22754d6411104fd1  /tmp/nodesource-setup.sh" | sha256sum -c - \
 && bash /tmp/nodesource-setup.sh \
 && rm -f /tmp/nodesource-setup.sh \
 && apt-get install -y --no-install-recommends "nodejs=${NODEJS_VERSION}" \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

# Git identity baked at system level → persists via image, no volume needed.
# CHANGE THESE to your own name/email before building.
RUN git config --system user.name  "Your Name" \
 && git config --system user.email "you@example.com" \
 && git config --system init.defaultBranch main

# Stage defaults; the entrypoint seeds them into persisted volumes on first boot only,
# so your later edits are never overwritten.
COPY config/settings.json /etc/devbox-defaults/settings.json
COPY config/tmux.conf     /etc/devbox-defaults/tmux.conf
COPY entrypoint.sh        /usr/local/bin/devbox-entrypoint.sh
RUN chmod +x /usr/local/bin/devbox-entrypoint.sh

# Devbox sshd: key-only direct SSH into the container (host port 2222 → 22).
# Host key + authorized_keys live in the persisted ~/.ssh (entrypoint manages them).
# SSH sessions don't inherit container ENV, so PATH is wired via PAM (/etc/environment,
# for non-interactive commands) and profile.d (interactive login shells).
COPY config/devbox-sshd.conf /etc/ssh/sshd_config.d/devbox.conf
# internal-sftp instead of the standalone sftp-server binary: some SFTP clients (e.g. the
# Claude Code desktop app's file upload) fail against Debian's standalone sftp-server,
# but work with the in-process implementation. (Sed the MAIN config: a second Subsystem
# line in the drop-in would be a fatal duplicate.)
RUN sed -i 's|^Subsystem[[:space:]].*|Subsystem sftp internal-sftp|' /etc/ssh/sshd_config \
 && echo 'PATH="/home/coder/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' > /etc/environment \
 && echo 'export PATH="/home/coder/.local/bin:$PATH"' > /etc/profile.d/devbox-path.sh

# Shared dev credentials: ~/.secrets/main.env (persisted via ~/.local/secrets; the
# entrypoint makes the symlink) is auto-loaded into login shells (profile.d) and
# interactive shells (bash.bashrc). Per-project .env files still override at app level.
# IMPORTANT: keep only LITERAL values in main.env — see docs/06.
RUN printf '%s\n' '# Load shared devbox credentials (see ~/.secrets/main.env).' '[ -f "$HOME/.local/secrets/main.env" ] && { set -a; . "$HOME/.local/secrets/main.env"; set +a; }' > /etc/profile.d/devbox-env.sh \
 && cat /etc/profile.d/devbox-env.sh >> /etc/bash.bashrc

# Persisted user-bin on PATH for every process/shell in the container.
ENV PATH="/home/coder/.local/bin:${PATH}"

# Pre-create volume mount points owned by coder. CRITICAL: fresh named/persistent volumes
# mount root-owned; code-server runs as `coder` and will crash-loop without this.
# .ssh must be 0700.
RUN mkdir -p /home/coder/.local/bin /home/coder/project \
             /home/coder/.claude /home/coder/.codex /home/coder/.ssh \
 && chown -R coder:coder /home/coder/.local /home/coder/project \
             /home/coder/.claude /home/coder/.codex /home/coder/.ssh \
 && chmod 700 /home/coder/.ssh

USER coder

ENTRYPOINT ["/usr/local/bin/devbox-entrypoint.sh"]
CMD ["--bind-addr", "0.0.0.0:8080", "/home/coder/project"]
