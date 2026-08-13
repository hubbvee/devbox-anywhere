#!/usr/bin/env python3
"""Prove critical tests turn red for known unsafe mutations."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def mutated(relative: str, old: str, new: str, test: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="devbox-mutation-") as tmp:
        copy = pathlib.Path(tmp) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        target = copy / relative
        source = target.read_text()
        assert old in source, (relative, old)
        target.write_text(source.replace(old, new, 1))
        result = subprocess.run(test, cwd=copy, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0, f"mutation falsely passed: {relative}: {new}"


for addition in (
    '      - "0.0.0.0:9999:8080"\n',
    '      - "PASSWORD=unsafe-override"\n',
):
    section = "    volumes:\n" if "9999" in addition else "    ports:\n"
    mutated("stack/docker-compose.yml", section, addition + section, ["python3", "tests/test-compose-model.py"])
mutated(
    "stack/docker-compose.yml",
    "    volumes:\n",
    "    volumes:\n      - /tmp:/tmp\n",
    ["python3", "tests/test-compose-model.py"],
)
mutated(
    "stack/docker-compose.yml",
    "    environment:\n",
    "    network_mode: host\n    environment:\n",
    ["python3", "tests/test-compose-model.py"],
)
mutated(
    "stack/docker-compose.yml",
    "services:\n",
    "services:\n  attacker:\n    image: alpine\n",
    ["python3", "tests/test-compose-model.py"],
)
for omitted, remaining in (("devbox", "devbox-relink"), ("devbox-relink", "devbox")):
    mutated(
        "scripts/install-devbox",
        "for helper in devbox devbox-relink; do",
        f"for helper in {remaining}; do",
        ["python3", "tests/test-install-devbox-lifecycle.py"],
    )

print("mutation_tests=PASS")