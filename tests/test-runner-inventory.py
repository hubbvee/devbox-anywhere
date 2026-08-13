#!/usr/bin/env python3
"""Prevent canonical security gates from being silently omitted."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
lines = [line.strip() for line in (root / "tests/run.sh").read_text().splitlines()]
expected = [
    "tests/test-install-devbox.sh",
    "python3 tests/test-compose-model.py",
    "python3 tests/test-install-devbox-lifecycle.py",
    "python3 tests/test-source-trust.py",
    "python3 tests/test-mutations.py",
    "python3 tests/test-agent-harness.py",
    "python3 tests/test-agent-harness-operations.py",
    "python3 tests/test-hermes-skill.py",
    "python3 tests/test-runner-inventory.py",
]
actual = [line for line in lines if line.startswith(("tests/", "python3 tests/"))]
assert actual == expected, ("runner_inventory_mismatch", actual, expected)
print("runner_inventory=PASS")
