#!/usr/bin/env python3
"""Contract for scripts/devbox-session: resolve project -> session -> agent.

No live tmux is required; the resolver reads a registry directory ($DEVBOX_SESSION_HOME)
that the worktree helper maintains. Session name == project name by convention (one
project -> one tmux session). Agent ids must follow <project>-<suffix> so channels can
address them unambiguously. Everything fails closed.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-session"


def run(*args: str, home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"DEVBOX_SESSION_HOME": str(home)}
    return subprocess.run(["bash", str(TOOL), *args], env=env, capture_output=True, text=True)


def kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith(" "):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


assert TOOL.is_file(), "scripts/devbox-session must exist"

home = pathlib.Path(tempfile.mkdtemp(prefix="devbox-session-"))
# webapp project: two agents; empty project 'blank' with a session but no agents.
(home / "webapp.tsv").write_text(
    "webapp-api\t/data/devbox/project/.worktrees/webapp-api\tagent/webapp-api\n"
    "webapp-web\t/data/devbox/project/.worktrees/webapp-web\tagent/webapp-web\n"
)
(home / "blank.tsv").write_text("")

# resolve <project> -> session == project
r = run("resolve", "webapp", home=home)
assert r.returncode == 0, r.stderr
assert kv(r.stdout).get("session") == "webapp", r.stdout

# resolve a registered project with no agents still yields its session
r = run("resolve", "blank", home=home)
assert r.returncode == 0 and kv(r.stdout).get("session") == "blank", r.stdout

# resolve <project> <agent> -> session/window/worktree/branch
r = run("resolve", "webapp", "webapp-api", home=home)
assert r.returncode == 0, r.stderr
d = kv(r.stdout)
assert d.get("session") == "webapp", d
assert d.get("window") == "webapp-api", d
assert d.get("worktree") == "/data/devbox/project/.worktrees/webapp-api", d
assert d.get("branch") == "agent/webapp-api", d

# list shows both projects and webapp' two agents
r = run("list", home=home)
assert r.returncode == 0, r.stderr
assert "project=webapp" in r.stdout and "project=blank" in r.stdout
assert "webapp-api" in r.stdout and "webapp-web" in r.stdout

# --- fail closed cases ---
# unknown project
assert run("resolve", "ghost", home=home).returncode != 0, "unknown project must fail"
# unknown agent
assert run("resolve", "webapp", "webapp-nope", home=home).returncode != 0, "unknown agent must fail"
# agent id not matching the <project>-<suffix> convention. Put an off-convention agent
# IN the registry so this proves the convention guard rejects it BEFORE the lookup would
# otherwise succeed (defense against a hand-edited/corrupted registry).
(home / "webapp.tsv").write_text(
    "webapp-api\t/data/devbox/project/.worktrees/webapp-api\tagent/webapp-api\n"
    "webapp-web\t/data/devbox/project/.worktrees/webapp-web\tagent/webapp-web\n"
    "otherproj-api\t/data/devbox/project/.worktrees/otherproj-api\tagent/otherproj-api\n"
)
assert run("resolve", "webapp", "otherproj-api", home=home).returncode != 0, "off-convention agent must fail"
# a bare agent that lacks the project prefix
assert run("resolve", "webapp", "api", home=home).returncode != 0, "unprefixed agent must fail"
# restore the clean two-agent registry for any later checks
(home / "webapp.tsv").write_text(
    "webapp-api\t/data/devbox/project/.worktrees/webapp-api\tagent/webapp-api\n"
    "webapp-web\t/data/devbox/project/.worktrees/webapp-web\tagent/webapp-web\n"
)

# ambiguous/malformed registry must fail closed, not guess.
(home / "dupe.tsv").write_text(
    "dupe-api\t/data/devbox/project/.worktrees/dupe-api\tagent/dupe-api\n"
    "dupe-api\t/data/devbox/project/.worktrees/dupe-api2\tagent/dupe-api2\n"
)
assert run("resolve", "dupe", "dupe-api", home=home).returncode != 0, "duplicate agent must fail closed"

(home / "bad.tsv").write_text("bad-api\tonly-two-columns\n")
assert run("resolve", "bad", "bad-api", home=home).returncode != 0, "malformed row must fail closed"

# path traversal / unsafe project names must never escape the registry dir
assert run("resolve", "../etc/passwd", home=home).returncode != 0, "path traversal must fail"

print("session_registry=PASS")
