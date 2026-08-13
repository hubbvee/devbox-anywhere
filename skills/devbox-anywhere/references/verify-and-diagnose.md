# Verification and diagnosis

## Machine-readable contract

All harness reports use `schema_version: 1`, a command name, an `ok` boolean, and stable check IDs. Reject malformed JSON or an unknown schema version.

### Preflight

```bash
./scripts/devbox-anywhere preflight --json
```

This is read-only. It checks Linux, Git, Docker, Compose v2, daemon reachability, and OpenSSL. It does not install missing prerequisites.

### Verify

```bash
sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json
```

Success requires:

- safe installer state file present;
- container running;
- actual Docker port bindings exactly matching the root-owned installer state;
- exactly five writable Docker bind mounts matching the fixed `/data/devbox` paths;
- `devbox` helper executable;
- `devbox-relink` helper executable;
- code-server responding inside the container;
- SSH responding inside the container.

The report includes only non-secret bind settings. It never returns the generated password.

### Diagnose

```bash
sudo /opt/devbox-anywhere/scripts/devbox-anywhere diagnose --json
```

Root is required because installer state is deliberately owner-only. Obtain explicit sudo approval before either command. Use `failed_checks` to explain the boundary that failed. `recovery_commands` are suggestions for local inspection, not automatic authorization. Some commands, such as container logs, can expose operational or secret material. Run them locally, redact output, and report only the necessary conclusion.

## Failure handling

- Exit `0`: report is valid and `ok` is true.
- Exit `1`: report is valid but one or more checks failed.
- Exit `2`: invocation or input is invalid.
- Non-JSON output with `--json`: harness failure; stop.

Do not convert a failed readiness check into a warning. Do not claim a service is healthy because Docker Compose accepted the model or started a container.
