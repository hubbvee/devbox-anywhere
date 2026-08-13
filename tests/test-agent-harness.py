#!/usr/bin/env python3
"""Acceptance contract for the agent-facing Devbox Anywhere harness."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_HARNESS = ROOT / "scripts" / "devbox-anywhere"
HARNESS = SOURCE_HARNESS


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HARNESS), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


assert HARNESS.is_file(), "agent harness is missing"
assert os.access(HARNESS, os.X_OK), "agent harness is not executable"

help_result = run("--help")
assert help_result.returncode == 0, help_result.stderr
for command in ("preflight", "plan", "verify", "diagnose"):
    assert command in help_result.stdout, f"help omits {command}"

with tempfile.TemporaryDirectory() as td:
    temp_root = pathlib.Path(td)
    fake_bin = temp_root / "bin"
    fake_bin.mkdir()
    for command, body in {
        "python3": "exit 0",
        "uname": "printf 'Linux\\n'",
        "git": """
case "$*" in
  *'rev-parse HEAD'*) printf 'c2c1caeebfc55047233cbdeae11670e07cbede75\\n' ;;
  *'status --porcelain'*) : ;;
  *) exit 0 ;;
esac
""",
        "docker": """
case "$*" in
  *'--context default compose version'*) printf 'Docker Compose version v2.30.0\\n' ;;
  *'--context default info'*) exit 0 ;;
  *) exit 0 ;;
esac
""",
        "openssl": "exit 0",
    }.items():
        path = fake_bin / command
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    harness_copy = temp_root / "devbox-anywhere"
    harness_copy.write_text(SOURCE_HARNESS.read_text().replace(
        'SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
        f'SAFE_PATH = "{fake_bin}:/usr/bin:/bin"',
    ))
    harness_copy.chmod(0o755)
    HARNESS = harness_copy
    env = os.environ.copy()
    result = run("preflight", "--json", env=env)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["command"] == "preflight"
    assert report["ok"] is True
    assert report["network"]["web_bind"] == "127.0.0.1"
    assert report["network"]["ssh_bind"] == "127.0.0.1"
    checks = {item["id"]: item for item in report["checks"]}
    for check_id in (
        "os.linux",
        "python3.available",
        "git.available",
        "docker.available",
        "compose.v2",
        "docker.daemon",
        "openssl.available",
    ):
        assert checks[check_id]["status"] == "pass", check_id
    serialized = json.dumps(report)
    assert "DEVBOX_PASSWORD=" not in serialized
    assert "OP_SERVICE_ACCOUNT_TOKEN" not in serialized
    HARNESS = SOURCE_HARNESS

bad = run("preflight", "--json", "--expose-ssh")
assert bad.returncode == 2
bad_report = json.loads(bad.stdout)
assert bad_report["ok"] is False
assert "unknown option" in bad_report["error"]["message"], "json_unknown_option_redaction"

secret_argument = "TOPSECRET_MUST_NOT_APPEAR"
secret_bad = run("preflight", "--json", f"--unknown={secret_argument}")
assert secret_bad.returncode == 2
secret_report = json.loads(secret_bad.stdout)
assert secret_report["command"] == "preflight"
assert secret_report["error"]["message"] == "unknown option", "json_unknown_option_redaction"
assert secret_argument not in secret_bad.stdout + secret_bad.stderr

secret_command = run(f"invalid-{secret_argument}", "--json")
assert secret_command.returncode == 2
secret_command_report = json.loads(secret_command.stdout)
assert secret_command_report["command"] == "unknown", "json_command_redaction"
assert secret_command_report["error"]["message"] == "invalid command"
assert secret_argument not in secret_command.stdout + secret_command.stderr

print("agent_harness_acceptance=PASS")
