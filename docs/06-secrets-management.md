# 06 — Secrets across every device: 1Password or Bitwarden CLI

The problem: your devbox (and each of its tmux sessions, and each agent in them) needs
API keys, but you never want secrets committed, pasted into chat scrollback, or living
only on one laptop. The pattern: **a vault is the source of truth; the devbox gets
read-only machine access; repos commit only references.**

## Layer 1 — `~/.secrets/main.env` (works with any manager)

The image auto-loads `~/.secrets/main.env` (persisted, `0600`) into **every** shell —
login, interactive, tmux, ssh. Cross-project values go here once and exist everywhere.
Start from [`templates/main.env.example`](../templates/main.env.example).

> **The one rule that will save you an afternoon:** only put LITERAL values in an
> auto-exported file — and only for variables no CLI reads implicitly. We once put a
> `GITHUB_TOKEN=op://...` vault *reference* in it: `gh` prefers `GITHUB_TOKEN` over its
> own stored login, treated the literal string `op://...` as the token, and every clone
> failed with "token invalid" until we found it. Vault references belong in per-project
> `.env.op` files (Layer 3), not in the global env.

## Layer 2 — 1Password CLI (what we run)

**Why the service-account pattern:** the devbox gets a token that can *read one vault*
and nothing else. No master password on the server, revocable in one click, works
headlessly in every shell and cron job.

1. **Install `op` on the devbox** (self-service into persisted `~/.local/bin` — no
   rebuild needed; check [1Password's site](https://developer.1password.com/docs/cli/get-started/)
   for the current version number):

   ```bash
   V=2.30.0
   curl -sSfLo /tmp/op.zip "https://cache.agilebits.com/dist/1P/op2/pkg/v${V}/op_linux_amd64_v${V}.zip"
   unzip -o /tmp/op.zip -d /tmp/opx && install /tmp/opx/op ~/.local/bin/op && rm -rf /tmp/op.zip /tmp/opx
   op --version
   ```

2. **Create a shared vault** (e.g. `Dev`) in your 1Password account; put each secret in
   it as an item with labeled fields (kebab-case names pay off in references).
3. **Create a service account** (1Password web → Developer → Service Accounts) with
   **read-only** access to that vault only. Copy the `ops_...` token once.
4. **Drop the token in `main.env`:**

   ```bash
   echo 'OP_SERVICE_ACCOUNT_TOKEN=ops_...' >> ~/.secrets/main.env
   ```

   New shells can now `op read`, `op run`, `op inject` with zero prompts:

   ```bash
   op vault list                                   # sanity check
   export STRIPE_KEY=$(op read "op://Dev/myproject-env/stripe-secret-key")
   ```

### Layer 3 — per-project `.env.op` (commit references, never secrets)

Each repo commits a `.env.op` containing only `op://vault/item/field` references
([template](../templates/project.env.op.example)). Any devbox clone rebuilds its real
env file in one command:

```bash
op inject -i .env.op -o .env.local     # .env.local stays gitignored
```

Gotchas we hit so you don't:

- In scripts, target the vault by **UUID**, not name — names can be ambiguous and `op`
  once wrote an item to the wrong vault for us.
- `op item edit item "field[concealed]=$VAR"` with an **empty** `$VAR` silently writes
  an empty field. Guard with `[ -n "$VAR" ]` first.
- Keep vault **writes** on your own trusted machine; the devbox token stays read-only.
- In non-interactive ssh commands, use `bash -l` so `main.env` (and the token) loads.

## Layer 2 alternative — Bitwarden CLI (free / self-hostable)

Same architecture, different vault. Works with bitwarden.com or your own
[Vaultwarden](https://github.com/dani-garcia/vaultwarden) (which Coolify installs in
one click — pleasingly circular).

```bash
npm i -g @bitwarden/cli        # lands in persisted ~/.local, survives rebuilds
bw config server https://vault.example.com   # only if self-hosting
bw login --apikey              # uses BW_CLIENTID / BW_CLIENTSECRET from main.env
```

The key difference from `op`: **`bw` needs an unlock per session** — `bw unlock`
returns a session token you must export. Practical helper in `~/.bashrc`:

```bash
bwu() {  # unlock once per shell: bwu, then bw get ... just works
  export BW_SESSION=$(bw unlock --raw) && echo "bw unlocked"
}
bws() {  # bws <item> [custom-field]  → prints password or a named custom field
  if [ -n "${2:-}" ]; then
    bw get item "$1" | jq -er --arg field "$2" \
      '.fields[] | select(.name == $field) | .value'
  else
    bw get password "$1"
  fi
}
```

And the `.env.op` equivalent — a committed `.env.bw` mapping + a tiny script that fills
it via `bw get`. If you want zero-prompt automation like a service account, look at
[Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/) (`bws`
CLI), which has machine tokens (its free tier is limited; Vaultwarden does not
implement it as of writing).

**Choosing:** already pay for 1Password → use it, service accounts are the cleanest
machine-auth in the space. Want free/self-hosted → Vaultwarden + `bw` with the unlock
helper. Either way, Layers 1 and 3 are identical.

Next: [07 — Getting files in](07-getting-files-in.md)
