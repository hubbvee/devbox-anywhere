# 12 — Browsers & authenticating to services (Cloudflare, GitHub, cloud SSO)

Your devbox runs headless on a VPS, so "just open a browser and log in" needs a plan.
This guide covers three layers, cheapest and safest first. Reach for a real GUI browser
only when the first two can't do the job.

```text
Need a browser?
 ├─ Testing / scraping / screenshots ......... headless browser (always installed)
 ├─ Auth to an API / service (Cloudflare, GH) . token-first, no browser needed
 ├─ OAuth CLI that opens localhost ........... SSH-forwarded callback → your laptop browser
 └─ Must click through a login on the server . opt-in GUI browser (--with-browser)
```

## 1. Headless browser (testing) — always available

Every devbox image ships a pinned Playwright + Chromium with its OS dependencies baked
in, so tests and scraping work offline with no first-run download. Smoke-test it:

```bash
devbox-browser-check      # launches headless Chromium, prints the version, exits non-zero on failure
```

Use it from any tmux session for end-to-end tests, screenshots, link checks, or scripted
scraping. It needs no display and exposes no network port.

## 2. Token-first authentication (preferred) — no browser at all

Most services don't need a *browser*; they need a credential a browser would have
fetched. Skip the browser and use an API token stored in your secret manager
(1Password/Bitwarden — see [docs/06](06-secrets-management.md)). Never paste a token into
chat or commit it; keep only `op://` references in the repo.

### Cloudflare

Cloudflare automation almost never needs an interactive login.

- **API token:** create a scoped token at *My Profile → API Tokens* (or an *Account* API
  token) and export it where the tool expects it:

  ```bash
  export CLOUDFLARE_API_TOKEN="$(op read 'op://<vault>/cloudflare-api/token')"
  npx wrangler whoami          # verifies without any browser
  ```

  Prefer this over `wrangler login`, which starts an OAuth browser flow.

- **`cloudflared` service token (Zero Trust / Access):** to reach a service behind
  Cloudflare Access non-interactively, use a **service token** (Client ID + Client
  Secret), not an interactive login:

  ```bash
  export CF_ACCESS_CLIENT_ID="$(op read 'op://<vault>/cf-access/client-id')"
  export CF_ACCESS_CLIENT_SECRET="$(op read 'op://<vault>/cf-access/client-secret')"
  curl -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
       -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
       https://protected.example.com/health
  ```

  In the Access application policy, add a **Service Auth** rule that accepts that service
  token. This is the right way to let the devbox (or an agent on it) call a protected
  origin without a human clicking a login screen.

- **`cloudflared tunnel` credentials:** to run a named tunnel, authenticate once with a
  **tunnel token** from the dashboard rather than `cloudflared tunnel login` (which needs
  a browser):

  ```bash
  cloudflared tunnel run --token "$(op read 'op://<vault>/cf-tunnel/token')" my-tunnel
  ```

### GitHub, Vercel, and similar

Use a personal access token / project token from your secret manager as the credential.
For example, `GH_TOKEN=$(op read 'op://<vault>/<github-item>/token') gh auth status`. Details in
[docs/06](06-secrets-management.md).

## 3. SSH-forwarded callback — for OAuth CLIs that insist on a browser

Some CLIs (e.g. `gh auth login`, some cloud SSO logins) start a temporary
`http://localhost:PORT/callback` listener and expect a browser to complete the redirect.
You don't need a browser *on the server* — forward that port to your own trusted machine:

```bash
# On your laptop: forward the CLI's callback port to the devbox, then attach.
ssh -L 53682:127.0.0.1:53682 HOST_USER@SERVER_ADDRESS

# In the devbox session, run the login. It prints a URL; open that URL in YOUR laptop
# browser. The redirect to localhost:53682 travels back through the tunnel to the CLI.
gh auth login   # choose HTTPS; complete the code/redirect in your own browser
```

Pick the exact port the CLI announces (it varies per tool/run) and forward that one. Your
real, trusted browser does the clicking; the authenticated session lands on the server.

## 4. Opt-in GUI browser on the server — `--with-browser`

When a flow genuinely requires a browser *on the server side* (a stubborn SSO screen, a
one-time cookie you must obtain in-context), enable the optional interactive browser
service. It is **off by default** and, when enabled, is a full Chromium reachable through
noVNC in your own browser — bound to **loopback only**.

```bash
# Enable it at install time (adds the Compose "browser" profile):
sudo ./scripts/install-devbox --yes --with-browser --approved-commit EXACT_SHA
```

- The noVNC endpoint binds **`127.0.0.1:8081`** only — never `0.0.0.0`.
- Reach it exactly like code-server: over your existing SSH tunnel, or behind an
  authenticated proxy / Cloudflare Access. **Do not expose port 8081 to the public
  internet.**

  ```bash
  ssh -L 8081:127.0.0.1:8081 HOST_USER@SERVER_ADDRESS
  # then open http://127.0.0.1:8081 in your laptop browser
  ```

- A random noVNC password is generated into the owner-only environment file, exactly like
  the code-server password; it is never printed to your screen or chat. Read it locally on
  the server the same way you read the code-server password. The KasmVNC web login uses
  username **`abc`** with that generated password.
- The browser profile (cookies, sessions) persists under `/data/devbox/browser`, so a
  login you complete survives container rebuilds.

> **Not a sandbox.** The interactive browser is a convenience for auth flows, not a
> security boundary. Keep it loopback-only, use it for the login you need, and prefer the
> token-first path (section 2) whenever the service supports it.

## Choosing quickly

| Situation | Use |
| --- | --- |
| Run tests, take screenshots, scrape | Headless browser (section 1) |
| Call Cloudflare/GitHub/Vercel APIs | Token-first (section 2) |
| Reach an origin behind Cloudflare Access | `cloudflared` **service token** (section 2) |
| CLI opens a `localhost` OAuth callback | SSH-forwarded callback (section 3) |
| Must click a login on the server itself | `--with-browser` GUI browser (section 4) |
