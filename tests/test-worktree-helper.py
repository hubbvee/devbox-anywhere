#!/usr/bin/env python3
"""Contract for scripts/devbox-worktree: add/list/remove an agent's worktree+window.

Each agent gets its own git worktree + branch (real parallel isolation) plus a tmux window
(session == project). tmux ops are gated: with DEVBOX_WORKTREE_NO_TMUX=1 the helper does the
git + registry work only, so this test needs no live tmux. add is atomic-ish: a failure
must not leave a half-registered agent. remove refuses to drop a dirty worktree unless --force.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-worktree"
SESSION_TOOL = REPO / "scripts/devbox-session"


def git(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def run(*args: str, repo: pathlib.Path, home: pathlib.Path, wt_root: pathlib.Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_WORKTREE_ROOT": str(wt_root),
        "DEVBOX_WORKTREE_REPO": str(repo),
        "DEVBOX_WORKTREE_NO_TMUX": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }
    return subprocess.run(["bash", str(TOOL), *args], env=env, capture_output=True, text=True)


assert TOOL.is_file(), "scripts/devbox-worktree must exist"

base = pathlib.Path(tempfile.mkdtemp(prefix="devbox-wt-"))
repo = base / "repo"
repo.mkdir()
git("init", "-q", cwd=repo)
git("config", "user.email", "t@e", cwd=repo)
git("config", "user.name", "t", cwd=repo)
(repo / "README.md").write_text("seed\n")
git("add", "README.md", cwd=repo)
git("commit", "-q", "-m", "seed", cwd=repo)

home = base / "sessions"; home.mkdir()
wt_root = base / "worktrees"

# add radioos-api -> creates worktree, branch agent/radioos-api, registry row.
r = run("add", "radioos", "radioos-api", repo=repo, home=home, wt_root=wt_root)
assert r.returncode == 0, r.stderr
wt = wt_root / "radioos-api"
assert (wt / ".git").exists(), "worktree checkout must exist"
branches = git("branch", "--list", "agent/radioos-api", cwd=repo)
assert "agent/radioos-api" in branches, branches
reg = (home / "radioos.tsv").read_text()
assert "radioos-api\t" in reg and str(wt) in reg and "agent/radioos-api" in reg, reg

# the session resolver now resolves it end to end.
res = subprocess.run(
    ["bash", str(SESSION_TOOL), "resolve", "radioos", "radioos-api"],
    env=os.environ | {"DEVBOX_SESSION_HOME": str(home)}, capture_output=True, text=True)
assert res.returncode == 0 and str(wt) in res.stdout, res.stdout + res.stderr

# add a second agent -> independent worktree/branch.
r = run("add", "radioos", "radioos-web", repo=repo, home=home, wt_root=wt_root)
assert r.returncode == 0, r.stderr
assert (wt_root / "radioos-web" / ".git").exists()

# list shows both.
r = run("list", repo=repo, home=home, wt_root=wt_root)
assert "radioos-api" in r.stdout and "radioos-web" in r.stdout, r.stdout

# --- fail closed cases ---
# off-convention agent name rejected, no worktree, no registry row.
r = run("add", "radioos", "otherproj-x", repo=repo, home=home, wt_root=wt_root)
assert r.returncode != 0, "off-convention agent must be rejected"
assert not (wt_root / "otherproj-x").exists(), "rejected add must not create a worktree"
assert "otherproj-x" not in (home / "radioos.tsv").read_text()

# duplicate add rejected, existing worktree untouched.
r = run("add", "radioos", "radioos-api", repo=repo, home=home, wt_root=wt_root)
assert r.returncode != 0, "duplicate agent add must fail"

# remove refuses a dirty worktree without --force.
(wt / "dirty.txt").write_text("uncommitted\n")
r = run("remove", "radioos", "radioos-api", repo=repo, home=home, wt_root=wt_root)
assert r.returncode != 0, "dirty worktree must not be removed without --force"
assert wt.exists(), "worktree must survive a refused remove"
assert "radioos-api\t" in (home / "radioos.tsv").read_text(), "registry row must survive refused remove"

# remove --force tears it down: worktree gone, registry row gone.
r = run("remove", "radioos", "radioos-api", "--force", repo=repo, home=home, wt_root=wt_root)
assert r.returncode == 0, r.stderr
assert not wt.exists(), "forced remove must delete the worktree"
assert "radioos-api\t" not in (home / "radioos.tsv").read_text(), "registry row must be gone"
# the other agent is untouched.
assert "radioos-web\t" in (home / "radioos.tsv").read_text()

# clean remove of the still-clean second agent succeeds without --force.
r = run("remove", "radioos", "radioos-web", repo=repo, home=home, wt_root=wt_root)
assert r.returncode == 0, r.stderr
assert not (wt_root / "radioos-web").exists()

print("worktree_helper=PASS")
