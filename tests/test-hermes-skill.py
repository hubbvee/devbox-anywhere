#!/usr/bin/env python3
"""Static acceptance contract for the distributable Hermes umbrella skill."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "devbox-anywhere"
MAIN = SKILL / "SKILL.md"
REFERENCES = {
    "references/install-and-upgrade.md",
    "references/verify-and-diagnose.md",
    "references/telegram-project-topics.md",
    "references/agent-handoffs.md",
    "references/backups-and-recovery.md",
    "references/security-boundaries.md",
}

assert MAIN.is_file(), "umbrella skill is missing"
text = MAIN.read_text()
assert text.startswith("---\n")
frontmatter = text.split("---\n", 2)[1]
assert re.search(r"(?m)^name: devbox-anywhere$", frontmatter)
description = re.search(r'(?m)^description: ["\']?(.+?)["\']?$', frontmatter)
assert description and description.group(1) == "Use when operating or recovering Devbox Anywhere."
assert len(description.group(1)) <= 57
assert len(text) <= 100_000
for relative in REFERENCES:
    assert (SKILL / relative).is_file(), f"missing {relative}"
    assert relative in text, f"umbrella omits {relative}"

for command in (
    "./scripts/devbox-anywhere preflight --json",
    "./scripts/devbox-anywhere plan --json",
    "sudo /opt/devbox-anywhere/scripts/devbox-anywhere verify --json",
    "sudo /opt/devbox-anywhere/scripts/devbox-anywhere diagnose --json",
):
    assert command in text, f"skill omits {command}"

for invariant in (
    "stable release",
    "exact commit",
    "/opt/devbox-anywhere",
    "explicit approval",
    "loopback",
    "never print",
):
    assert invariant.lower() in text.lower(), f"skill omits invariant: {invariant}"

combined = text + "\n" + "\n".join((SKILL / path).read_text() for path in sorted(REFERENCES))
for forbidden in ("curl | sudo bash", "group_allowed_chats", "sudo ./scripts/install-devbox --yes --approved-commit $("):
    assert forbidden not in combined, f"unsafe skill guidance: {forbidden}"
assert 'cp -R ./skills/devbox-anywhere/. "$HOME/.hermes/skills/devbox-anywhere/"' in text
assert "mutable default branch" in text

print("hermes_skill=PASS")
