# 02 — Install Coolify (or go plain Docker)

[Coolify](https://coolify.io) is a self-hosted, open-source deploy platform (think
"your own Heroku/Vercel" on your VPS). We use it because the devbox then lives next to
everything else you deploy, and Coolify gives you for free:

- **Traefik reverse proxy + automatic Let's Encrypt HTTPS** for any domain you point at it
- A UI for env vars, volumes, port mappings, redeploys, logs
- One-click deploys for the *other* things you'll inevitably self-host later

## Install

On the server, as your sudo user:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```

Then open `http://YOUR_SERVER_IP:8000`, create the admin account (use a long password —
this UI controls your whole server), and add the server itself when prompted
(`localhost` deployment target).

## DNS

Point a subdomain at your server before deploying the devbox, e.g.:

```
devbox.example.com    A    YOUR_SERVER_IP
```

### If you use Cloudflare in front (orange cloud)

Set **SSL/TLS mode to "Full (strict)"** for the zone. Cloudflare's "Automatic SSL/TLS"
can silently pick *Flexible*, which sends plain HTTP to your origin while Traefik
redirects to HTTPS → an infinite 307 redirect loop that looks like a broken app. Full
(strict) works because Traefik serves a valid Let's Encrypt cert at the origin.
Proxied (orange) DNS is required if you later want Cloudflare Access (docs/03).

## Don't want Coolify?

The whole stack also runs with plain Docker — see [`stack/docker-compose.yml`](../stack/docker-compose.yml).
You'll need to bring your own HTTPS reverse proxy (Caddy is the least-effort option:
two lines of Caddyfile gets you auto-TLS). Everything else in this guide still applies;
where we reference the Coolify container label
(`coolify.resourceName=devbox`), substitute `-f name=devbox`.

Next: [03 — Deploy the devbox](03-deploy-the-devbox.md)
