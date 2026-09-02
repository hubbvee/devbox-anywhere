#!/usr/bin/env python3
"""Contract for scripts/devbox-turn: per-worktree advisory one-writer lock.

The lock is keyed on the WORKTREE PATH (not the session): the collision risk is two
writers in one checkout. Explicit take/release (OQ1); an idle lock past its TTL is
reclaimable as a stale-lock safety net. This is advisory coordination, NOT a security or
sandbox boundary.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-turn"


def run(*args: str, state: pathlib.Path, holder: str | None = None, ttl: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"DEVBOX_TURN_STATE": str(state)}
    if holder is not None:
        env["DEVBOX_TURN_HOLDER"] = holder
    if ttl is not None:
        env["DEVBOX_TURN_TTL"] = ttl
    return subprocess.run(["bash", str(TOOL), *args], env=env, capture_output=True, text=True)


assert TOOL.is_file(), "scripts/devbox-turn must exist"

state = pathlib.Path(tempfile.mkdtemp(prefix="devbox-turn-"))
# Worktrees must be real directories; `take` refuses a path that does not exist.
wt_root = pathlib.Path(tempfile.mkdtemp(prefix="devbox-turn-wt-"))
WT = str(wt_root / "webapp-api"); pathlib.Path(WT).mkdir()
WT2 = str(wt_root / "webapp-web"); pathlib.Path(WT2).mkdir()

# take on a nonexistent worktree must fail closed (not lock a typo'd path).
missing = str(wt_root / "does-not-exist")
r = run("take", missing, state=state, holder="alice")
assert r.returncode != 0, "take on a nonexistent worktree must fail"

# status on a free worktree reports free, exit 0.
r = run("status", WT, state=state)
assert r.returncode == 0 and "free" in r.stdout.lower(), r.stdout

# alice takes the turn.
r = run("take", WT, state=state, holder="alice")
assert r.returncode == 0, r.stderr

# status now shows held by alice.
r = run("status", WT, state=state)
assert r.returncode == 0 and "alice" in r.stdout, r.stdout

# bob cannot take a held worktree; must fail and name the holder, must NOT steal it.
r = run("take", WT, state=state, holder="bob")
assert r.returncode != 0, "second take must fail closed"
assert "alice" in (r.stdout + r.stderr), "must name the current holder"
r = run("status", WT, state=state)
assert "alice" in r.stdout, "holder must be unchanged after a refused take"

# a DIFFERENT worktree is independent — bob can hold it at the same time.
r = run("take", WT2, state=state, holder="bob")
assert r.returncode == 0, "distinct worktrees lock independently"

# release only by the holder: bob cannot release alice's lock.
r = run("release", WT, state=state, holder="bob")
assert r.returncode != 0, "non-holder release must fail"
assert "alice" in run("status", WT, state=state).stdout, "lock must survive a foreign release"

# alice releases her own lock; worktree is free again.
r = run("release", WT, state=state, holder="alice")
assert r.returncode == 0, r.stderr
assert "free" in run("status", WT, state=state).stdout.lower()

# re-take after release works.
assert run("take", WT, state=state, holder="carol").returncode == 0

# stale lock: with a tiny TTL, an idle lock is reclaimable by a new holder.
stale = pathlib.Path(tempfile.mkdtemp(prefix="devbox-turn-stale-"))
assert run("take", WT, state=stale, holder="alice", ttl="1").returncode == 0
time.sleep(2)
r = run("take", WT, state=stale, holder="bob", ttl="1")
assert r.returncode == 0, "expired lock must be reclaimable"
assert "bob" in run("status", WT, state=stale, ttl="1").stdout, "reclaimer becomes holder"

# path-unsafe / empty worktree arg fails closed.
assert run("take", "", state=state, holder="x").returncode != 0
assert run("status", state=state).returncode != 0

# The tool documents itself as advisory, not a security boundary.
text = TOOL.read_text().lower()
assert "not a" in text and ("security" in text or "sandbox" in text), "must disclaim being a boundary"

print("turn_lock=PASS")
