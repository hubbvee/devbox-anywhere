# Verification and diagnosis

## Machine-readable contract

All harness reports use `schema_version: 2`, a command name, an `ok` boolean, and stable check IDs. Reject malformed JSON or an unknown schema version.

### Check status enum

Each entry in `checks` has an `id`, a `summary`, and a `status` that is one of three values:

- `pass` — the check succeeded.
- `fail` — the check failed. Any `fail` clears `ok` (sets it to `false`) and the command exits non-zero.
- `warn` — an advisory finding that does **not** clear `ok`. The install is still considered healthy; the warning names something worth attention (for example an unresolved relink target or a declared daemon that is not running).

`ok` aggregates as *no check is `fail`* (`all(status != "fail")`), so a report can be `ok: true` while carrying `warn` entries. A consumer must treat `status` as this three-value enum: do **not** assume `pass|fail`, and do **not** recompute `ok` as `all(status == "pass")` — either mistake reads a healthy install (one with warnings) as broken. This is why the schema version was raised from 1 to 2: reports gained the `warn` value.

The set of checks that emit `warn` may grow, and some may later be **promoted to `fail`** in a future schema version once field data justifies it. Gate on `ok` and on specific check IDs you understand; do not hard-code the full check set.

### Preflight

```bash
./scripts/devbox-anywhere preflight --json
```

This is read-only. It checks Linux, Git, Docker, Compose v2, daemon reachability, and OpenSSL. It does not install missing prerequisites.

### Verify

```bash
sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json
```

`ok: true` (no `fail`) requires:

- safe installer state file present;
- container running;
- actual Docker port bindings exactly matching the root-owned installer state;
- exactly five writable Docker bind mounts matching the fixed `/data/devbox` paths;
- `devbox` helper executable;
- `devbox-relink` helper executable;
- code-server responding inside the container;
- SSH responding inside the container.

Verify also emits warn-only checks that do not affect `ok`:

- `relink.targets` — every symlink `devbox-relink` manages (its shipped in-file relinks plus every `~/.local/share/devbox-relink.d/*.conf` pair) exists, is a symlink, and resolves. An unresolved target is reported as `warn` naming the path. This closes the old gap where a dangling `~/.hermes` still returned `ok: true`.
- `daemon.<name>` — each daemon declared in `~/.local/share/devbox-daemons.d/*.conf` is running (default backend: a detached tmux session). Declared-but-not-running is `warn`. If the directory is absent, no `daemon.*` checks are emitted (skipped, not failed).

The report includes only non-secret bind settings, check IDs, summaries naming paths or daemon names, and the bind addresses. It never returns the generated password or any environment value.

### Diagnose

```bash
sudo /opt/devbox-anywhere/scripts/devbox-anywhere diagnose --json
```

Root is required because installer state is deliberately owner-only. Obtain explicit sudo approval before either command. `failed_checks` lists only `fail` entries (warnings are not failures) to explain the boundary that failed. `recovery_commands` are suggestions for local inspection, not automatic authorization. Some commands, such as container logs, can expose operational or secret material. Run them locally, redact output, and report only the necessary conclusion.

## Failure handling

- Exit `0`: report is valid and `ok` is true (may include `warn` entries).
- Exit `1`: report is valid but one or more checks are `fail`.
- Exit `2`: invocation or input is invalid.
- Non-JSON output with `--json`: harness failure; stop.

Do not convert a `fail` readiness check into a `warn`: the `warn` status is for genuinely new advisory checks, never a downgrade of an existing hard failure. Do not claim a service is healthy because Docker Compose accepted the model or started a container.
