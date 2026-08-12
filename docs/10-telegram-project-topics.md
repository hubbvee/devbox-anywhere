# 10 — Manage each project from a Telegram topic

This chapter turns a Telegram **private forum group** into a mobile control plane for
your devbox:

- one Telegram group for the whole devbox;
- one forum topic per project;
- one isolated Hermes Agent conversation per topic;
- one tmux session (and one mutable checkout owner) per project.

For example, a message in the `api` topic can inspect and steer the `api` tmux session
without mixing its history with the `blog` topic.

> This chapter uses [Nous Research Hermes Agent](https://hermes-agent.nousresearch.com/docs/),
> not only the lightweight `scripts/hermes` tmux wrapper introduced in docs/08. If you
> installed that wrapper as `~/.local/bin/hermes`, rename it to `tmuxctl` first so it
> does not shadow the real `hermes` CLI:
>
> ```bash
> mv ~/.local/bin/hermes ~/.local/bin/tmuxctl
> ```

## Architecture

```text
Telegram private forum group
├── General topic ───── portfolio-wide questions
├── api topic ───────── isolated Hermes session ──► tmux session api ──► ~/project/api
├── blog topic ──────── isolated Hermes session ──► tmux session blog ─► ~/project/blog
└── shop topic ──────── isolated Hermes session ──► tmux session shop ─► ~/project/shop

Hermes gateway (one process on the devbox)
└── Telegram Bot API (outbound long polling; no inbound firewall port required)
```

A Telegram topic is a **conversation boundary**, not automatic tmux authorization or a
security sandbox. Messages, pasted logs, repository files, pane output, and observed
messages from other group members are untrusted input and can contain prompt injection.
Only an authorized sender may request terminal actions; project rules and independent
checks must still enforce one writer per checkout, read-before-write, and no deployment
or publication without an explicit human decision.

## 1. Install Hermes Agent on the devbox

Download from the official HTTPS endpoint, inspect the script, then run it. Piping a
mutable network response directly into a shell gives the server/CDN immediate code
execution on the devbox.

```bash
install_script=$(mktemp)
curl -fL --proto '=https' --tlsv1.2 \
  https://hermes-agent.nousresearch.com/install.sh -o "$install_script"
less "$install_script"
bash "$install_script"
rm -f "$install_script"
hermes doctor
hermes model
```

The devbox image persists `~/.local`, but Hermes normally stores configuration,
sessions, skills, and secrets in `~/.hermes`. Persist it through the existing
`~/.local` bind mount. Stop Hermes/gateway processes first, then move the state on the
same filesystem; never migrate a live state database while it may be writing:

```bash
(
hermes gateway stop  # run from an external shell, not from inside the gateway process
mkdir -p ~/.local/share
if [ -e ~/.local/share/hermes-home ]; then
  printf '%s\n' 'Refusing to merge two Hermes homes automatically.' >&2
  printf '%s\n' 'Back up both paths and reconcile them explicitly.' >&2
  exit 1
elif [ -d ~/.hermes ] && [ ! -L ~/.hermes ]; then
  mv ~/.hermes ~/.local/share/hermes-home
elif [ -L ~/.hermes ]; then
  printf '%s\n' '~/.hermes is already a symlink; verify its target first.' >&2
  exit 1
else
  install -d -m 0700 ~/.local/share/hermes-home
fi
ln -s ~/.local/share/hermes-home ~/.hermes
)
```

Add this line to the local copy of `~/.local/bin/devbox-relink` so a rebuilt container
restores the link automatically. This line is intentionally opt-in: adding it before
`hermes-home` exists would make `~/.hermes` a dangling link and can break the installer.

```bash
relink "$HOME/.local/share/hermes-home" "$HOME/.hermes"
```

Run it once and verify the paths:

```bash
devbox-relink
readlink ~/.hermes
hermes config path
hermes config env-path
```

`~/.hermes/.env` contains credentials and must never be committed. Keep normal settings
in `~/.hermes/config.yaml`; use `hermes config set ...` or the setup wizard rather than
hand-editing configuration where a CLI option exists.

## 2. Create the Telegram bot

In Telegram:

1. Open the official [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and choose a display name and a unique username ending in `bot`.
3. Save the token in your password manager. Anyone with it can impersonate and control
   the bot. Enable Telegram two-step verification on the owner account as well.
4. Optionally use `/setdescription`, `/setabouttext`, `/setuserpic`, and `/setcommands`.
5. Use `/setprivacy_policy` if the bot will be shared beyond a private test group.

Do **not** paste the token into a repository, issue, screenshot, or Telegram group.
If it leaks, use BotFather's `/revoke` immediately and configure the replacement token.

Find your numeric Telegram user ID by messaging `@userinfobot` (the numeric ID is not
your `@username`).

## 3. Configure Hermes and start the gateway

Run the supported wizard on the devbox:

```bash
hermes gateway setup
```

Select Telegram and enter:

- the BotFather token;
- your numeric Telegram user ID in the allowed-users list.

Then run `hermes tools`, select the Telegram platform, and enable `terminal` only if this
bot is intended to control tmux. **Terminal is effectively account-level access:** it can
read or modify files, control processes, use network clients, access credentials, and
cross project boundaries as the gateway's OS user. Disabling the separate `file` tool does
not contain terminal access. Tool toggles and `approvals.mode: smart` reduce accidental
operations but are not a security sandbox against prompt injection or a compromised model.

For stronger isolation, run this gateway under a dedicated restricted OS account or
container/VM with only approved project worktrees and the minimum tmux/control socket,
credentials, commands, and network access exposed. Do not mount SSH/provider/production
credentials that Telegram-driven work does not require. Keep secret redaction and command
approvals on:

```bash
hermes config set security.redact_secrets true
hermes config set approvals.mode smart
```

Start a new session or use `/reset` after tool/security changes. Secret redaction reduces
accidental disclosure in model/tool output, but it is not a substitute for authorization
or for keeping secrets out of prompts.

The wizard stores credentials in `~/.hermes/.env`. Verify that the persisted home is not
accessible to other local accounts:

```bash
chmod 700 ~/.local/share/hermes-home
chmod 600 ~/.hermes/.env
```

To keep the gateway running after you disconnect, install and start its service. Keep the
devbox and host firewalls closed to unsolicited gateway ports; Telegram long polling does
not require an inbound public listener:

```bash
hermes gateway install
hermes gateway start
hermes gateway status
```

If service installation is unavailable in your container, run the gateway in its own
tmux session instead:

```bash
tmux new-session -d -s telegram-gateway 'hermes gateway run'
```

Send the bot a DM and confirm it replies. Useful diagnostics:

```bash
hermes logs gateway -f
hermes send --list telegram
```

## 4. Create the private forum group

1. Create a **private Telegram group** and enable **Topics** in the group settings.
2. Add the bot.
3. Keep the bot's BotFather **Group Privacy enabled** for the least privilege. With the
   `require_mention` setup below, invoke it through commands, direct mentions, or replies.
4. Only if your workflow requires the bot to observe ordinary unmentioned messages,
   choose one broader delivery option:
   - turn privacy mode off in BotFather via `/mybots` → your bot → **Bot Settings** →
     **Group Privacy** → **Turn off**, then remove and re-add the bot; or
   - make the bot an administrator with only the minimum permissions it needs.
   Do not grant member management, message deletion, topic management, invite-link, or
   other administrative rights merely to receive messages.
5. Create one topic per project, using the same stable name as its tmux session:
   `api`, `blog`, `shop`, and so on. Keep `General` for cross-project coordination.

For a private topic URL such as:

```text
https://t.me/c/1234567890/55
```

- group chat ID: `-1001234567890`;
- topic/thread ID: `55`;
- explicit Hermes target: `telegram:-1001234567890:55`.

The final URL number is the thread ID. The internal group number gains the `-100`
prefix when used as a Bot API chat ID.

## 5. Restrict access to the group

Use the setup wizard or `hermes config set` to configure Telegram access. The desired
shape is equivalent to:

```yaml
gateway:
  platforms:
    telegram:
      extra:
        allow_from:
          - "YOUR_NUMERIC_USER_ID"
        allowed_chats:
          - "-1001234567890"
        require_mention: true
```

Important:

- `allow_from` lets the listed users invoke the bot in DMs and groups.
- `allowed_chats` restricts the chats where Hermes may respond; it does not grant every
  member access, so sender authorization still comes from `allow_from`.
- For a shared group where only selected people may invoke Hermes, configure the
  sender-scoped `group_allow_from` list as well.
- `group_allowed_chats` is different: it authorizes **every member** of each listed
  group/forum. Use it only when group membership is intentionally the access boundary,
  or when observed unmentioned group context requires a shared group session.
- `require_mention: true` keeps the bot quiet until it is mentioned or replied to.
- Never use `"*"` for a private personal control plane.
- If several people share the bot, configure Hermes slash-command admin controls as
  well; DM admin status does not automatically grant group admin status.

Restart after configuration changes:

```bash
hermes gateway restart
hermes gateway status
```

See the live [Telegram integration documentation](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)
for the current config keys, group access controls, and troubleshooting details.

## 6. Bind topics to projects

Telegram forum topics already give Hermes a separate session per `thread_id`. Add a
project-specific channel prompt so each topic has an explicit repository and tmux
boundary. A concise prompt for the `api` topic is:

```text
This topic manages project api.
Repository: /home/coder/project/api
Tmux session: api

Before acting, verify the repository path, Git branch/status, tmux pane CWD, and resident
writer PID. Keep exactly one mutable writer per checkout. Read the pane before sending
keys. A visible staged prompt is queued, not active; require generation/tool or child-
process evidence before reporting ACTIVE. Preserve Git history; do not amend, rebase,
reset, squash, or force-push. Pause and request explicit human authority before committing,
pushing, opening a PR, merging, deploying, publishing, or sending destructive commands.
Keep all api status and cron delivery in this topic.
```

Channel prompts can be assigned to topic IDs. Topic-level prompts override a group-level
prompt. Use `hermes config set` or `hermes config edit`; the resulting configuration is
equivalent to:

```yaml
telegram:
  channel_prompts:
    "55": |
      This topic manages project api.
      Repository: /home/coder/project/api
      Tmux session: api
      Verify Git/tmux ownership before acting. One writer per checkout.
      Never deploy or publish without explicit human authority.
    "56": |
      This topic manages project blog.
      Repository: /home/coder/project/blog
      Tmux session: blog
      Verify Git/tmux ownership before acting. One writer per checkout.
      Never deploy or publish without explicit human authority.
```

If you have reusable project skills, optionally bind them under
`gateway.platforms.telegram.extra.group_topics`:

```yaml
gateway:
  platforms:
    telegram:
      extra:
        group_topics:
          - chat_id: -1001234567890
            topics:
              - name: api
                thread_id: 55
                skill: software-development
              - name: blog
                thread_id: 56
```

A topic without a skill is still session-isolated.

## 7. Give Hermes safe tmux controls

Install the repo's wrapper under the non-conflicting name `tmuxctl`. Treat `send`, `run`,
and especially `broadcast` as direct terminal-input capabilities—not as command parsing or
authorization boundaries. The current helper accepts any existing tmux session name; topic
prompts are policy, not enforcement. An authorized operator must verify the exact target
with `peek` and avoid relaying message text or pane/repository instructions directly into
`tmuxctl send`:

```bash
install -m 0755 scripts/hermes ~/.local/bin/tmuxctl
```

From a project topic, Hermes can now use:

```bash
tmuxctl ls

tmuxctl peek api 80

tmuxctl send api "Please report current branch, status, tests, and blocker only."
```

Use `peek` before `send`. Avoid `broadcast` from an automated agent. The helper's `wait`
command only proves that text matched the pane; it does not prove semantic completion.
After any worker report, independently check Git, tmux/process ownership, and tests.

Recommended status vocabulary:

- **ACTIVE** — relevant generation/tool activity or child process is observed;
- **QUEUED** — text is staged but not submitted;
- **IDLE** — writer is at a prompt with no relevant child work;
- **BLOCKED** — an explicit decision, credential, approval, or failure prevents progress;
- **COMPLETED** — the requested checkpoint and independent verification both passed.

## 8. Prove each route before relying on it

Send a direct test to every topic:

```bash
hermes send --to 'telegram:-1001234567890:55' \
  'Routing test: this message belongs only in the api topic.'
```

A successful CLI exit is useful, but verify the message actually arrived in the correct
topic. Then mention the bot in that topic and ask:

```text
Identify this topic's repository and tmux session, then run read-only checks only:
Git branch/status, tmux session existence, pane CWD, and resident process ownership.
Do not send keys or modify files.
```

Repeat for each project. A project is onboarded only when its repository, tmux session,
and topic route all agree.

## 9. Route project updates and cron results correctly

For a one-off update, always include the complete chat and thread target:

```bash
hermes send --to 'telegram:-1001234567890:55' 'api: tests passed on the current HEAD'
```

For scheduled jobs, set delivery to the same full target:

```text
telegram:-1001234567890:55
```

Do not use only `telegram:-1001234567890`; that sends to the group/root rather than the
project topic. Retarget only jobs belonging to that project and preserve whether each
job is active or paused. Job execution success is not proof of message delivery, so test
arrival in the real topic.

Keep updates low-noise by default: report meaningful Git/process/test transitions. If
you promise a fixed heartbeat, send it even when nothing changed and label the state
accurately.

## 10. Operating rules

- **One topic ↔ one project ↔ one tmux session ↔ one mutable checkout owner.**
- Separate worktrees are required for concurrent writers in one repository.
- Treat project topic names as labels; verify paths and Git identity before action.
- Never treat a worker's prose as proof. Inspect the diff and run the relevant checks.
- Keep project messages in their own topics; aggregate only fresh evidence in General.
- Store credentials only in `~/.hermes/.env` or your secret manager.
- Pause and request explicit human authority before commit, push, PR publication, merge,
  deployment, or other external side effects.
- Back up the persisted Hermes home, but protect it as sensitive because it contains
  tokens, session history, and configuration.

## Troubleshooting

### The real `hermes` command opens the tmux wrapper instead

```bash
command -v hermes
mv ~/.local/bin/hermes ~/.local/bin/tmuxctl
hash -r
command -v hermes
```

### Bot works in DMs but ignores the group

- make it an admin with only the minimum required permission, or disable BotFather
  privacy mode and remove/re-add it only when unmentioned-message observation is needed;
- verify your numeric user ID and the negative group ID are allowlisted;
- if `require_mention` is enabled, mention the bot or reply to one of its messages;
- inspect `hermes logs gateway -f`.

### Replies appear in the wrong topic

- verify the final number in the `t.me/c/.../<thread>` URL;
- use `telegram:<chat_id>:<thread_id>` for direct and scheduled delivery;
- do not rely on a root/home-channel target to infer topic affinity.

### A topic starts managing the wrong checkout

Stop mutable work. Re-check the channel prompt, repository remote, tmux pane CWD, writer
PID, and current Git status. Do not launch a second agent into the occupied checkout.

### Gateway disappears after a container rebuild

Verify `~/.hermes` still links to `~/.local/share/hermes-home`, run
`devbox-relink`, and restart the gateway service or `telegram-gateway` tmux session.

Next: [11 — Switch coding agents mid-session](11-switch-coding-agents-mid-session.md),
or return to [README](../README.md).
