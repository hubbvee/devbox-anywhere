# 01 — Get a VPS

Everything in this guide runs on one ordinary Linux server. No Kubernetes, no managed
platform, no per-seat SaaS — a single VPS you rent for a few dollars a month.

## Where to rent one

Any provider works. We run this exact setup on OVH; Hetzner is the other one we
recommend to people starting fresh:

- **[OVH / OVHcloud](https://www.ovhcloud.com)** — VPS or dedicated, solid EU/NA presence,
  the box this guide was built on.
- **[Hetzner](https://www.hetzner.com)** — famously good price/performance
  (CX/CPX cloud instances), EU + US locations.

> **Disclosure:** some provider links in this guide may be or become affiliate links —
> if you sign up through them we may earn a small commission at no extra cost to you.
> It's how we fund maintaining this guide. Feel free to go to the providers directly
> instead; nothing in the setup depends on how you sign up.

## Sizing

| Usage | Spec | Roughly |
|---|---|---|
| Solo devbox, a few tmux sessions | 2 vCPU / 4 GB RAM / 40 GB SSD | ~$5–8/mo |
| Devbox + a few deployed side projects | 4 vCPU / 8 GB RAM / 80 GB+ | ~$10–20/mo |
| Devbox + Coolify hosting "everything you build" | 8 vCPU / 16–32 GB | ~$30+/mo |

Coolify itself wants ~2 GB free. AI coding agents (Claude Code, Codex) are mostly
network-bound, not CPU-bound — RAM for your builds is what matters.

**OS: Ubuntu LTS (22.04 or 24.04), x86_64.** Everything below assumes it.

## First 10 minutes on a fresh server

SSH in as root once, then immediately:

```bash
# 1. Create your everyday user with sudo
adduser youruser
usermod -aG sudo youruser

# 2. Put your public key on it (from YOUR machine)
ssh-copy-id youruser@YOUR_SERVER_IP

# 3. Key-only SSH: edit /etc/ssh/sshd_config
#    PasswordAuthentication no
#    PermitRootLogin no
systemctl restart ssh

# 4. Basic firewall — leave 80/443 for the web UI + HTTPS, 22 for SSH,
#    2222 for the devbox container's direct sshd (docs/05), 8000 for Coolify setup.
ufw allow 22,80,443,2222,8000/tcp
ufw enable

# 5. Updates
apt update && apt upgrade -y
```

Optional but sensible: `apt install fail2ban` (default config is fine), and unattended
security upgrades (`dpkg-reconfigure -plow unattended-upgrades`).

Generate a **dedicated key per device** you'll connect from (Mac, laptop, phone). One
key per device means you can revoke a lost phone without re-keying everything:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/laptop-devbox -C "laptop-devbox"
```

Next: [02 — Install Coolify](02-install-coolify.md)
