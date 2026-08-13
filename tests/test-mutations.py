#!/usr/bin/env python3
"""Prove critical tests turn red for named invariant failures."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "tests/run.sh").read_text()
assert "python3 tests/test-runner-inventory.py\n" in RUNNER, "runner_inventory_guard_missing"


def named_red(output: str, expected: str) -> bool:
    forbidden = ("SyntaxError:", "NameError:", "ImportError:", "ModuleNotFoundError:", "TimeoutExpired")
    if any(item in output for item in forbidden):
        return False
    terminal = [line for line in output.splitlines() if line.startswith("AssertionError:")]
    return len(terminal) == 1 and expected in terminal[0]


assert named_red("Traceback\nAssertionError: runtime_http_probe\n", "runtime_http_probe"), "named_red_positive_control"
assert not named_red("Traceback\nNameError: runtime_http_probe\n", "runtime_http_probe"), "named_red_reject_name_error"
assert not named_red("AssertionError: other\nAssertionError: runtime_http_probe\n", "runtime_http_probe"), "named_red_reject_multiple"

BASELINES = (
    ("compose", ["python3", "tests/test-compose-model.py"]),
    ("installer", ["python3", "tests/test-install-devbox-lifecycle.py"]),
    ("harness", ["python3", "tests/test-agent-harness.py"]),
    ("operations", ["python3", "tests/test-agent-harness-operations.py"]),
    ("inventory", ["python3", "tests/test-runner-inventory.py"]),
)
for name, command in BASELINES:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"mutation_baseline_failed:{name}:{result.stdout}{result.stderr}"


def mutated(
    name: str,
    relative: str,
    old: str,
    new: str,
    test: list[str],
    expected_red: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"devbox-mutation-{name}-") as tmp:
        copy = pathlib.Path(tmp) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
        target = copy / relative
        source = target.read_text()
        count = source.count(old)
        assert count == 1, f"mutation_activation:{name}:count={count}"
        target.write_text(source.replace(old, new, 1))
        result = subprocess.run(test, cwd=copy, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        assert result.returncode != 0, f"mutation_falsely_passed:{name}"
        assert named_red(output, expected_red), (
            f"mutation_wrong_red:{name}:expected={expected_red!r}:"
            f"exit={result.returncode}:output={output[-2000:]!r}"
        )


CASES = [
    ("compose-extra-port", "stack/docker-compose.yml", "    volumes:\n", '      - "0.0.0.0:9999:8080"\n    volumes:\n', ["python3", "tests/test-compose-model.py"], "ports must contain exactly"),
    ("compose-password-override", "stack/docker-compose.yml", "    ports:\n", '      - "PASSWORD=unsafe-override"\n    ports:\n', ["python3", "tests/test-compose-model.py"], "environment must contain exactly"),
    ("compose-extra-mount", "stack/docker-compose.yml", "    volumes:\n", "    volumes:\n      - /tmp:/tmp\n", ["python3", "tests/test-compose-model.py"], "volume wiring/count drifted"),
    ("compose-host-network", "stack/docker-compose.yml", "    environment:\n", "    network_mode: host\n    environment:\n", ["python3", "tests/test-compose-model.py"], "devbox service keys drifted"),
    ("compose-extra-service", "stack/docker-compose.yml", "services:\n", "services:\n  attacker:\n    image: alpine\n", ["python3", "tests/test-compose-model.py"], "service set drifted"),
    ("installer-omit-devbox", "scripts/install-devbox", "for helper in devbox devbox-relink; do", "for helper in devbox-relink; do", ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_call_count"),
    ("installer-omit-relink", "scripts/install-devbox", "for helper in devbox devbox-relink; do", "for helper in devbox; do", ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_call_count"),
    ("installer-helper-order", "scripts/install-devbox", "for helper in devbox devbox-relink; do", "for helper in devbox-relink devbox; do", ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_order:first_install"),
    ("harness-wget-argv", "scripts/devbox-anywhere", '"/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"', '"/usr/bin/true"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-ssh-argv", "scripts/devbox-anywhere", '"/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"', '"/usr/bin/true"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-http-forced-true", "scripts/devbox-anywhere", "http_ok = docker_ok([", "http_ok = True or docker_ok([", ["python3", "tests/test-agent-harness-operations.py"], "runtime_http_probe"),
    ("harness-ssh-forced-true", "scripts/devbox-anywhere", "ssh_ok = docker_ok([", "ssh_ok = True or docker_ok([", ["python3", "tests/test-agent-harness-operations.py"], "runtime_ssh_probe"),
    ("harness-wrong-port", "scripts/devbox-anywhere", '"HostPort": "8080"', '"HostPort": "9999"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-wrong-mount", "scripts/devbox-anywhere", '("/data/devbox/project", "/home/coder/project")', '("/data/devbox/project-WRONG", "/home/coder/project")', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("installer-context", "scripts/install-devbox", 'docker_cmd=("${compose_env[@]}" "$DOCKER" --context default)', 'docker_cmd=("${compose_env[@]}" "$DOCKER")', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("installer-config", "scripts/install-devbox", 'compose_env=(env -i PATH="$SAFE_PATH" HOME=/root DOCKER_CONFIG="$DOCKER_CONFIG")', 'compose_env=(env -i PATH="$SAFE_PATH" HOME=/root)', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_config"),
    ("installer-recovery-context", "scripts/install-devbox", "docker --context default logs devbox", "docker logs devbox", ["python3", "tests/test-install-devbox-lifecycle.py"], "recovery_docker_context"),
    ("installer-status-context", "scripts/install-devbox", "docker --context default compose --env-file", "docker compose --env-file", ["python3", "tests/test-install-devbox-lifecycle.py"], "status_docker_context"),
    ("harness-context", "scripts/devbox-anywhere", 'return run([docker, "--context", "default", *arguments], clean=True)', "return run([docker, *arguments], clean=True)", ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-config", "scripts/devbox-anywhere", '"DOCKER_CONFIG": DOCKER_CONFIG,', '"IGNORED_DOCKER_CONFIG": DOCKER_CONFIG,', ["python3", "tests/test-agent-harness-operations.py"], "runtime_docker_config"),
    ("json-option-reflection", "scripts/devbox-anywhere", 'safe_message = "unknown option"', "safe_message = message", ["python3", "tests/test-agent-harness.py"], "json_unknown_option_redaction"),
    ("json-command-reflection", "scripts/devbox-anywhere", 'command = next((item for item in sys.argv[1:] if item in known), "unknown")', 'command = next((item for item in sys.argv[1:] if not item.startswith("-")), "unknown")', ["python3", "tests/test-agent-harness.py"], "json_command_redaction"),
    ("runner-omit-operations", "tests/run.sh", "python3 tests/test-agent-harness-operations.py\n", "", ["python3", "tests/test-runner-inventory.py"], "runner_inventory_mismatch"),
    ("runner-omit-inventory", "tests/run.sh", "python3 tests/test-runner-inventory.py\n", "", ["python3", "tests/test-mutations.py"], "runner_inventory_guard_missing"),
]

for case in CASES:
    mutated(*case)

print(f"mutation_tests=PASS cases={len(CASES)} named_reds={len(CASES)}")
