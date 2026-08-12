# Devbox Anywhere — code-server + tmux + direct sshd, built for rebuild-proof persistence.
#
# Everything installed here as root lands in /usr and is "baked" (survives rebuilds by
# definition). Everything the USER installs later should go to ~/.local, which is a host
# bind mount (see docs/03) — that's how self-installed tools survive rebuilds too.

# Pin the multi-architecture code-server 4.132.0 image index so this release does not
# silently change when an upstream `latest` tag moves.
FROM codercom/code-server@sha256:b88ed46a6ace76a0294a17a24f39aa88032ed0a3692c3d8ab5433b47ab57ccbf

USER root

# Freeze Debian package indexes at a dated snapshot. Combined with the base-image digest,
# this keeps apt resolution stable instead of following mutable Debian mirrors.
ARG DEBIAN_SNAPSHOT=20260810T000000Z
RUN for sources in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
      [ -f "$sources" ] || continue; \
      sed -i \
        -e "s|http://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
        -e "s|https://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
        -e "s|http://security.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
        -e "s|https://security.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
        -e "s|http://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
        -e "s|https://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
        "$sources"; \
    done \
 && ! grep -R -E 'https?://(deb\.debian\.org/debian(-security)?|security\.debian\.org/debian-security)' \
      /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null
RUN printf 'Acquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/99snapshot

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

# GitHub CLI, pinned and checksum-verified for both supported image architectures.
ARG GH_VERSION=2.97.0
RUN arch="$(dpkg --print-architecture)" \
 && case "$arch" in \
      amd64) gh_sha256="a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112" ;; \
      arm64) gh_sha256="73ea440ecad9c9e284429997ee6f93577bc6f7bc6fba357ef62c53ad8fb641a5" ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz" \
      -o /tmp/gh.tar.gz \
 && echo "$gh_sha256  /tmp/gh.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/gh.tar.gz -C /tmp \
 && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh \
 && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${arch}"

# Node.js LTS + AI coding CLIs. Release-defining package checksums and npm integrities
# are pinned; both CLIs currently publish without npm dependencies.
# Update these values deliberately in a reviewed release.
# User-level `npm i -g` later goes to ~/.local instead (entrypoint sets the npm prefix).
ARG NODEJS_VERSION=22.23.2-1nodesource1
ARG CLAUDE_CODE_VERSION=2.1.228
ARG CODEX_VERSION=0.147.0
ARG CLAUDE_CODE_INTEGRITY=sha512-S3Iy+c6ZuFjswQOekbVgXA+RxAuU8H2ae2nxFynqmvR5r3Gm9oyFV19XgiuatYRFKKjxP0K3i5vvvelPDgx12g==
ARG CODEX_INTEGRITY=sha512-EQLEXecAG2ptxI7UpBMo2TR/ga5596/c/OsYF/0LoUDh5JANZ7IoGqlzBEWbuEVQ76JePIbtTW/ihCkp1a7Z3w==
ARG CLAUDE_CODE_LINUX_X64_INTEGRITY=sha512-LMrLUYW5FY3r8wsQk/U5HWacHmxlEWKxaOgNzmDn1f5FhgKsSAPpioqf2JE5AusRRKXyWvhYM1crOE/CKIqoNQ==
ARG CLAUDE_CODE_LINUX_ARM64_INTEGRITY=sha512-rWSzUqON6kyIXUVz9KDU+9R6FdO11IVCO94D7kkWWyRPzFqzaAB80RmfgP//QgTIVFApEUzEUH2tfAGsUhD6ug==
ARG CODEX_LINUX_X64_INTEGRITY=sha512-0W9MBxPpWW0cSkNqrTDN2jR7rzzT7oNMhQY5446lT2Lw5cz5yhDTck4Va9rjkQEm+HlFzP/dmEMSZbXfJsINmw==
ARG CODEX_LINUX_ARM64_INTEGRITY=sha512-SLC1JXw2TYfr/c3HhrJubyyLelq7vTOLWVmiThFA+z0+WgzCPmaseJ/kzDD3Gge/TO7fCnnj7UcPmC0d2c8XAg==
RUN arch="$(dpkg --print-architecture)" \
 && case "$arch" in \
      amd64) node_sha256="eed0c5f0ab411f28783f81f051fcf7928ae8bf833e2df11f48f3fa78270025cb" ;; \
      arm64) node_sha256="0018ee0bf997fce587042a2382941dcfac9f404fb994a5c3267fe7d12d8d837b" ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "https://deb.nodesource.com/node_22.x/pool/main/n/nodejs/nodejs_${NODEJS_VERSION}_${arch}.deb" \
      -o /tmp/nodejs.deb \
 && echo "$node_sha256  /tmp/nodejs.deb" | sha256sum -c - \
 && apt-get update \
 && apt-get install -y --no-install-recommends /tmp/nodejs.deb \
 && rm -f /tmp/nodejs.deb \
 && test "$(npm view "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" dist.integrity)" = "$CLAUDE_CODE_INTEGRITY" \
 && test "$(npm view "@openai/codex@${CODEX_VERSION}" dist.integrity)" = "$CODEX_INTEGRITY" \
 && case "$arch" in \
      amd64) \
        test "$(npm view "@anthropic-ai/claude-code-linux-x64@${CLAUDE_CODE_VERSION}" dist.integrity)" = "$CLAUDE_CODE_LINUX_X64_INTEGRITY" \
        && test "$(npm view "@openai/codex@${CODEX_VERSION}-linux-x64" dist.integrity)" = "$CODEX_LINUX_X64_INTEGRITY" ;; \
      arm64) \
        test "$(npm view "@anthropic-ai/claude-code-linux-arm64@${CLAUDE_CODE_VERSION}" dist.integrity)" = "$CLAUDE_CODE_LINUX_ARM64_INTEGRITY" \
        && test "$(npm view "@openai/codex@${CODEX_VERSION}-linux-arm64" dist.integrity)" = "$CODEX_LINUX_ARM64_INTEGRITY" ;; \
    esac \
 && npm install -g --ignore-scripts=false --omit=dev \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@openai/codex@${CODEX_VERSION}" \
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
