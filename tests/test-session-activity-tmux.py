#!/usr/bin/env python3
"""Activity-classification contract: `devbox-session status` against a REAL tmux
server (the __tmux__ probe path that the fixture-driven test never exercises).

The operator smoke found `blocked` can NEVER fire on a real pane: the probe took the literal last
line of `tmux capture-pane -p`, which includes the blank rows below the cursor, so on any pane
that is not full the "last line" is empty and a waiting prompt (e.g. "... (y/n)") is never seen.
This drives an actual tmux server and asserts:
  - a pane waiting at a "(y/n)" prompt  -> blocked   (previously misread as idle)
  - a pane running a non-shell command  -> working
  - an idle shell pane                  -> idle
It also pins the window-existence proof. `tmux display-message -t "=S:W"` (also "=S:=W") silently
falls back to the session's CURRENT window and exits 0 when W does not exist, so a name-targeted
probe reported another window's activity for an agent that has no window at all:
  - registered agent with NO window, current window an idle shell -> unknown (was misread idle)
  - two windows carrying the agent's name (ambiguous)              -> unknown (was misread working)
  - another window whose name holds a raw newline forging "<id>\t<agent>" for the current
    (idle shell) window's id                                       -> unknown (was misread idle)

tmux is present in the devbox image and the operator smoke runs this. When tmux is absent (e.g.
a CI host without it) the test SKIPS cleanly rather than failing -- but it never fakes a pass.

Isolation: a dedicated TMUX_TMPDIR gives this test its own tmux server, so it never touches any
real session on the host; TMUX is unset so we are not operating inside an existing server. Both
this test's tmux calls and devbox-session's own `tmux` calls inherit TMUX_TMPDIR via the env.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-session"
WT_TOOL = REPO / "scripts/devbox-worktree"

TMUX = shutil.which("tmux")
if TMUX is None:
    print("session_activity_tmux=SKIP (tmux not installed)")
    sys.exit(0)

base = pathlib.Path(tempfile.mkdtemp(prefix="devbox-acttmux-"))
sock_dir = base / "tmux"          # isolated TMUX_TMPDIR -> our own server socket
sock_dir.mkdir()
project = "rt"
server_env = {k: v for k, v in os.environ.items() if k != "TMUX"}
server_env["TMUX_TMPDIR"] = str(sock_dir)


def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([TMUX, *args], env=server_env, capture_output=True, text=True, check=check)


def git(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def cleanup() -> None:
    subprocess.run([TMUX, "kill-server"], env=server_env, capture_output=True, text=True)
    shutil.rmtree(base, ignore_errors=True)


try:
    # --- a real git repo + six registered agents (no tmux at creation time) ---
    repo = base / "repo"; repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@e", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    (repo / "README.md").write_text("seed\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-q", "-m", "seed", cwd=repo)

    home = base / "sessions"; home.mkdir()
    wt_root = base / "worktrees"
    wt_env = os.environ | {
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_WORKTREE_ROOT": str(wt_root),
        "DEVBOX_WORKTREE_REPO": str(repo),
        "DEVBOX_WORKTREE_NO_TMUX": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }
    for agent in ("rt-block", "rt-work", "rt-idle", "rt-ghost", "rt-dup", "rt-forge"):
        r = subprocess.run(["bash", str(WT_TOOL), "add", project, agent], env=wt_env,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"wt add {agent}: {r.stderr}"

    # --- a REAL tmux server: session == project, one window per agent, isolated socket ---
    wt_block = wt_root / "rt-block"
    wt_work = wt_root / "rt-work"
    wt_idle = wt_root / "rt-idle"
    # rt-block: a shell waiting at a (y/n) prompt -> last non-blank line is the prompt.
    tmux("new-session", "-d", "-s", project, "-n", "rt-block", "-c", str(wt_block),
         "sh -c 'printf \"Overwrite file? (y/n) \"; read x'")
    # rt-work: a non-shell foreground command.
    tmux("new-window", "-t", f"={project}", "-n", "rt-work", "-c", str(wt_work), "sleep 300")
    # rt-idle: a plain interactive shell at its prompt.
    tmux("new-window", "-t", f"={project}", "-n", "rt-idle", "-c", str(wt_idle),
         "bash --norc --noprofile -i")
    # rt-dup: the agent's name labels TWO windows -> ambiguous.
    tmux("new-window", "-t", f"={project}", "-n", "rt-dup", "-c", str(wt_root / "rt-dup"), "sleep 300")
    tmux("new-window", "-t", f"={project}", "-n", "rt-dup", "-c", str(wt_root / "rt-dup"), "sleep 300")
    # main: a non-agent idle shell (the operator's own window) -- made the session's CURRENT
    # window below, which is exactly what a name-targeted display-message falls back to.
    tmux("new-window", "-t", f"={project}", "-n", "main", "-c", str(base), "bash --norc --noprofile -i")
    main_id = tmux("display-message", "-p", "-t", f"={project}:main", "#{window_id}").stdout.strip()
    assert main_id.startswith("@") and main_id[1:].isdigit(), f"setup: main window id: {main_id!r}"
    # rt-forge: no window of its own; a decoy window's name holds a raw newline so that
    # list-windows prints a forged "<main window id>\t<rt-forge>" row.
    tmux("new-window", "-t", f"={project}", "-n", f"decoy\n{main_id}\trt-forge", "sleep 300")
    # rt-ghost: registered, NO window at all.
    tmux("select-window", "-t", main_id)
    names = tmux("list-windows", "-t", f"={project}", "-F", "#{window_name}").stdout.splitlines()
    assert "rt-ghost" not in names and names.count("rt-dup") == 2, f"setup: windows {names!r}"
    time.sleep(1.5)  # let panes render so capture-pane + window_activity are populated

    # --- run status against the REAL tmux probe (no injected activity cmd); stale=0 so a
    #     currently-waiting prompt counts as blocked deterministically regardless of timing ---
    status_env = wt_env | {
        "DEVBOX_STATUS_BASE": "main",
        "DEVBOX_STATUS_STALE": "0",
        "TMUX_TMPDIR": str(sock_dir),
    }
    status_env.pop("TMUX", None)
    status_env.pop("DEVBOX_STATUS_ACTIVITY_CMD", None)
    r = subprocess.run(["bash", str(TOOL), "status", project, "--json"], env=status_env,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"status against real tmux must succeed: {r.stderr}"
    agents = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}

    assert agents["rt-block"]["activity"] == "blocked", \
        f"a pane waiting at a (y/n) prompt must read blocked: {agents['rt-block']}"
    assert agents["rt-work"]["activity"] == "working", \
        f"a non-shell foreground command must read working: {agents['rt-work']}"
    assert agents["rt-idle"]["activity"] == "idle", \
        f"an idle shell must read idle: {agents['rt-idle']}"
    assert agents["rt-ghost"]["activity"] == "unknown", \
        f"an agent with no tmux window must read unknown, not the current window's activity: {agents['rt-ghost']}"
    assert agents["rt-dup"]["activity"] == "unknown", \
        f"an agent whose name labels two windows is ambiguous and must read unknown: {agents['rt-dup']}"
    assert agents["rt-forge"]["activity"] == "unknown", \
        f"a newline-forged window row must not alias the agent to another window: {agents['rt-forge']}"

    print("session_activity_tmux=PASS")
finally:
    cleanup()
