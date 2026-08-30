# Browsers and authenticating to services

Full user-facing guide: `docs/12-browser-and-auth.md`. This reference is the operational
summary Hermes uses when a user needs a browser or must authenticate a service on the
devbox.

## Decision order (cheapest and safest first)

1. **Headless testing** — every image ships a pinned Playwright + Chromium (baked, offline
   ready). Run `devbox-browser-check` in a session for a smoke test. No port, no display.
2. **Token-first auth** — most services need a credential, not a browser. Read the token
   from the user's secret manager (`op read 'op://...'`) into an env var. Never print,
   paste, log, or commit it.
3. **SSH-forwarded callback** — for OAuth CLIs that open a `localhost` redirect, have the
   user `ssh -L PORT:127.0.0.1:PORT ...` and complete the login in their own trusted
   browser. Forward the exact port the CLI announces.
4. **Opt-in GUI browser** — only when a login must happen on the server. Enabled with the
   installer flag `--with-browser`; noVNC binds `127.0.0.1:8081` only.

## Cloudflare specifics

- **API token:** `export CLOUDFLARE_API_TOKEN=$(op read 'op://<vault>/cloudflare-api/token')`;
  prefer this over `wrangler login`.
- **Access (protected origin):** use a **service token** (Client ID + Secret) with
  `CF-Access-Client-Id` / `CF-Access-Client-Secret` headers and a Service Auth policy —
  not an interactive login.
- **Named tunnel:** `cloudflared tunnel run --token $(op read 'op://<vault>/cf-tunnel/token')`
  rather than `cloudflared tunnel login`.

## The --with-browser service

- Off by default. Enable at install: `sudo ./scripts/install-devbox --yes --with-browser --approved-commit EXACT_SHA`.
- noVNC endpoint is loopback-only (`127.0.0.1:8081`). Reach it over the SSH tunnel or
  behind Cloudflare Access. Never expose 8081 publicly.
- Its VNC password is generated into the owner-only environment file, like the code-server
  password. Never print it; tell the user the local command to read it on the server.
- Browser profile persists under `/data/devbox/browser` (survives rebuilds).

## Boundaries

- The interactive browser is a convenience, **not a sandbox or a security boundary**.
- Prefer token-first for anything an API supports; reserve the GUI browser for genuine
  click-through logins.
- Enabling `--with-browser` is a privileged/network change: require explicit user approval
  before adding it, exactly like SSH exposure.
