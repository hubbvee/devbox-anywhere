#!/usr/bin/env python3
"""Contract for `devbox-session status <project> [--json]` (v1.7 Part A: git convergence).

Exact facts per agent: dirty, ahead/behind vs base, merged (branch is ancestor of base),
turn holder, and reapable = merged && !dirty && turn free. Fixture-driven with a real git
repo + worktrees; no live tmux (activity is Part B). Fails closed on unknown project; a
registered worktree gone from disk is reported `missing`, never a crash.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-session"
WT_TOOL = REPO / "scripts/devbox-worktree"
TURN_TOOL = REPO / "scripts/devbox-turn"


def git(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def wt_env(home: pathlib.Path, wt_root: pathlib.Path, repo: pathlib.Path) -> dict[str, str]:
    return os.environ | {
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_WORKTREE_ROOT": str(wt_root),
        "DEVBOX_WORKTREE_REPO": str(repo),
        "DEVBOX_WORKTREE_NO_TMUX": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }


def wt(*args: str, home, wt_root, repo) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(WT_TOOL), *args], env=wt_env(home, wt_root, repo), capture_output=True, text=True)


def status(*args: str, home, wt_root, repo, turn_state=None, activity_cmd=None, stale=None) -> subprocess.CompletedProcess[str]:
    env = wt_env(home, wt_root, repo) | {"DEVBOX_STATUS_BASE": "main"}
    if turn_state is not None:
        env["DEVBOX_TURN_STATE"] = str(turn_state)
    if activity_cmd is not None:
        env["DEVBOX_STATUS_ACTIVITY_CMD"] = str(activity_cmd)
    if stale is not None:
        env["DEVBOX_STATUS_STALE"] = str(stale)
    return subprocess.run(["bash", str(TOOL), "status", *args], env=env, capture_output=True, text=True)


def write_stub(path: pathlib.Path, body: str) -> pathlib.Path:
    # An activity probe: invoked as `$CMD <session> <window>`, prints one line
    # "<cmd>\t<age_seconds>\t<last_line>" (empty/nonzero => unknown).
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


assert TOOL.is_file()

base = pathlib.Path(tempfile.mkdtemp(prefix="devbox-status-"))
repo = base / "repo"; repo.mkdir()
git("init", "-q", "-b", "main", cwd=repo)
git("config", "user.email", "t@e", cwd=repo)
git("config", "user.name", "t", cwd=repo)
(repo / "README.md").write_text("seed\n")
git("add", "README.md", cwd=repo)
git("commit", "-q", "-m", "seed", cwd=repo)

home = base / "sessions"; home.mkdir()
wt_root = base / "worktrees"
turn_state = base / "turn"

# three agents
for a in ("webapp-api", "webapp-web", "webapp-cli"):
    r = wt("add", "webapp", a, home=home, wt_root=wt_root, repo=repo)
    assert r.returncode == 0, r.stderr

# webapp-api: dirty + 1 commit ahead of main
api = wt_root / "webapp-api"
(api / "feature.txt").write_text("wip\n")
git("add", "feature.txt", cwd=api)
git("commit", "-q", "-m", "api work", cwd=api)
(api / "dirty.txt").write_text("uncommitted\n")  # leaves the tree dirty

# webapp-web: clean, 1 commit ahead
web = wt_root / "webapp-web"
(web / "w.txt").write_text("done\n")
git("add", "w.txt", cwd=web)
git("commit", "-q", "-m", "web work", cwd=web)

# webapp-cli: its branch merged into main (so it is an ancestor of main), clean
cli = wt_root / "webapp-cli"
(cli / "c.txt").write_text("cli\n")
git("add", "c.txt", cwd=cli)
git("commit", "-q", "-m", "cli work", cwd=cli)
git("merge", "--no-ff", "-m", "merge cli", "agent/webapp-cli", cwd=repo)  # main now contains cli

# hold the turn on webapp-api as alice
subprocess.run(["bash", str(TURN_TOOL), "take", str(api)],
               env=os.environ | {"DEVBOX_TURN_STATE": str(turn_state), "DEVBOX_TURN_HOLDER": "alice"},
               capture_output=True, text=True, check=True)

# --- JSON status ---
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert r.returncode == 0, "status --json must succeed: " + r.stderr
doc = json.loads(r.stdout)
assert doc["schema_version"] == 1, doc
assert doc["project"] == "webapp" and doc["base"] == "main", doc
agents = {a["agent"]: a for a in doc["agents"]}
assert set(agents) == {"webapp-api", "webapp-web", "webapp-cli"}, agents

api_a = agents["webapp-api"]
assert api_a["dirty"] is True, "status_dirty_true"
assert api_a["ahead"] == 1 and api_a["behind"] == 2, api_a  # 2 behind: main gained cli work + merge
assert api_a["merged"] is False, api_a
assert api_a["turn"] == "alice", api_a
assert api_a["reapable"] is False, "status_reapable_false_when_dirty"

web_a = agents["webapp-web"]
assert web_a["dirty"] is False and web_a["ahead"] == 1, web_a
assert web_a["turn"] == "free", web_a
assert web_a["reapable"] is False, web_a  # ahead + not merged

cli_a = agents["webapp-cli"]
assert cli_a["merged"] is True and cli_a["dirty"] is False, "status_merged_true"
assert cli_a["turn"] == "free", cli_a
assert cli_a["reapable"] is True, "status_reapable_true_when_merged_clean_free"

# --- human table ---
h = status("webapp", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert h.returncode == 0, h.stderr
assert "webapp-api" in h.stdout and "webapp-cli" in h.stdout, h.stdout
assert "reapable" in h.stdout.lower(), "table should flag the reapable agent"

# --- Part B: activity heuristic (injectable probe) ---
# working = a non-shell foreground command; idle = a shell prompt; blocked = a known
# waiting-prompt tail that has stalled; unknown = probe unavailable/errors (never faked).
stub = write_stub(base / "act_ok.sh", (
    'case "$2" in\n'
    '  webapp-api) printf "node\\t3\\t\\n" ;;\n'          # non-shell, recent -> working
    '  webapp-web) printf "bash\\t500\\t$ \\n" ;;\n'       # shell prompt -> idle
    '  webapp-cli) printf "bash\\t500\\t$ \\n" ;;\n'       # shell prompt -> idle
    '  *) exit 1 ;;\n'
    'esac\n'
))
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub)
assert r.returncode == 0, r.stderr
doc = json.loads(r.stdout)
ag = {a["agent"]: a for a in doc["agents"]}
assert ag["webapp-api"]["activity"] == "working", "act_working"
assert ag["webapp-web"]["activity"] == "idle", "act_idle"
assert ag["webapp-cli"]["activity"] == "idle", ag["webapp-cli"]
# Activity must be explicitly labeled a heuristic, never presented as exact fact.
assert doc.get("activity_confidence") == "heuristic", "act_confidence_label"

# blocked: a waiting prompt that has stalled (age >= stale threshold).
stub_b = write_stub(base / "act_blocked.sh", (
    'case "$2" in\n'
    '  webapp-api) printf "bash\\t120\\tDo you want to proceed? (y/n) \\n" ;;\n'
    '  *) printf "bash\\t500\\t$ \\n" ;;\n'
    'esac\n'
))
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub_b, stale=30)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-api"]["activity"] == "blocked", "act_blocked"

# probe errors -> unknown, NEVER fabricated as working.
stub_err = write_stub(base / "act_err.sh", "exit 1\n")
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub_err)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-api"]["activity"] == "unknown", "act_unknown_on_error"

# probe prints nothing -> unknown.
stub_empty = write_stub(base / "act_empty.sh", "exit 0\n")
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub_empty)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-api"]["activity"] == "unknown", "act_unknown_on_empty"

# probe returns a line with an EMPTY command field (leading tab) -> unknown, not fabricated working.
stub_nocmd = write_stub(base / "act_nocmd.sh", 'printf "\\t5\\t$ \\n"\n')
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub_nocmd)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-api"]["activity"] == "unknown", "act_unknown_on_empty_cmd"

# no probe configured at all -> must not crash, activity is a valid label (unknown when no tmux).
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert r.returncode == 0, r.stderr
for a in json.loads(r.stdout)["agents"]:
    assert a["activity"] in {"working", "idle", "blocked", "unknown"}, a

# --- fail closed: unknown project ---
assert status("ghost", "--json", home=home, wt_root=wt_root, repo=repo).returncode != 0

# --- missing worktree reported, not crashed ---
import shutil
shutil.rmtree(web)
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert r.returncode == 0, "a vanished worktree must not crash status: " + r.stderr
agents2 = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert agents2["webapp-web"].get("missing") is True, agents2["webapp-web"]

# --- no secret leakage in JSON ---
assert "DEVBOX_TURN" not in r.stdout and "PASSWORD" not in r.stdout

print("session_status=PASS")
