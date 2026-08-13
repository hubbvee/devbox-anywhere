# Security boundaries

## Enforced by repository code

The installer enforces:

- an exact approved 40-character commit;
- a detached, clean, root-owned and non-writable source tree at `/opt/devbox-anywhere`;
- byte comparison against the approved Git archive;
- sanitized Git, Docker, and Compose environments;
- fixed storage under `/data/devbox` with controlled ancestry;
- owner-only installer state and atomic secret writes;
- loopback web and SSH defaults;
- explicit public SSH exposure;
- container, helper, HTTP, and SSH readiness.

If one of these checks fails, stop. A prompt cannot waive it.

## Enforced by human approval

Require explicit approval before:

- sudo or privileged filesystem changes;
- installing packages;
- replacing the root-owned checkout;
- building or starting containers;
- changing firewalls, DNS, TLS, or ingress;
- exposing SSH publicly;
- deploying, publishing, committing, pushing, or releasing;
- reading or rotating credentials.

Approval for one effect does not imply approval for another.

## Residual risks

No harness can guarantee absolute security. Risks remain from compromised Telegram accounts or bot tokens, SSH keys, provider credentials, prompt injection, Docker/root authority, dependency compromise, broad host mounts, and deployment mistakes.

Use the wording: "No known blockers within the reviewed and tested scope." Do not say the system is fully secure.

## Secret-output rule

Harness JSON is designed to omit secret values. Even so, treat environment files, Docker logs, shell histories, provider output, Hermes state, and backup archives as secret-bearing. Never print or transmit them wholesale. Redact locally and report only the failed boundary and necessary recovery action.
