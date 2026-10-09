#!/usr/bin/env python3
"""Host-independent guard for the activity probe's "blocked" detection (last NON-BLANK line).

The real-tmux test (test-session-activity-tmux.py) is the high-fidelity layer but skips where
tmux is absent (e.g. macOS, minimal CI), leaving the `status-blocked-last-blank-line` mutation
unguarded there. This test needs NO real tmux: it puts a fake `tmux` first on PATH whose
`capture-pane -p` prints a "(y/n)" prompt followed by blank padding rows (exactly the real-pane
shape that broke the literal-last-line probe), with `has-session`/`display-message` stubbed so
`devbox-session` classifies the pane. It therefore runs on every host and catches the mutation
everywhere, while staying faithful to the four tmux subcommands the probe actually calls:
  has-session -t =<s> ; display-message -p -t =<s>:<w> '#{pane_current_command}' and
  '#{window_activity}' ; capture-pane -p -t =<s>:<w>.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-session"

base = pathlib.Path(tempfile.mkdtemp(prefix="devbox-faketmux-"))

# A fake `tmux`: answers the four subcommands the probe uses. capture-pane prints a waiting
# prompt THEN blank padding rows, so the literal last line is blank (the defect) while the
# last non-blank line is the prompt (the fix). window_activity=1 (epoch) => huge age => stalled.
FAKE_TMUX = r"""#!/bin/sh
sub=$1; shift
case "$sub" in
  has-session) exit 0 ;;
  display-message)
    fmt=$4
    case "$fmt" in
      *pane_current_command*) printf 'python\n' ;;   # non-shell -> not idle
      *window_activity*) printf '1\n' ;;              # ancient -> stalled past any threshold
      *) printf '\n' ;;
    esac
    ;;
  capture-pane)
    printf 'Overwrite existing file? (y/n) \n'        # the waiting prompt (last NON-blank line)
    printf '\n'                                        # blank padding rows below the cursor,
    printf '\n'                                        # exactly what a non-full real pane shows
    printf '\n'
    ;;
  *) exit 0 ;;
esac
"""


def cleanup() -> None:
    shutil.rmtree(base, ignore_errors=True)


try:
    bindir = base / "bin"
    bindir.mkdir()
    fake = bindir / "tmux"
    fake.write_text(FAKE_TMUX)
    fake.chmod(0o755)

    # A real git repo + one registered worktree (git facts must not crash); base pinned so the
    # loop never needs to resolve main/master. The registry window name == agent.
    repo = base / "repo"; repo.mkdir()

    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)

    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@e", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    (repo / "README.md").write_text("seed\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-q", "-m", "seed", cwd=repo)

    wt = base / "wt-blk"
    git("worktree", "add", "-q", "-b", "agent/blk", str(wt), cwd=repo)

    home = base / "sessions"; home.mkdir()
    reg = home / "waiting.tsv"
    reg.write_text(f"waiting-blk\t{wt}\tagent/blk\n")

    # PATH with the fake tmux FIRST so devbox-session's `command -v tmux` and every `tmux` call
    # resolve to the shim regardless of whether a real tmux exists on this host.
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_STATUS_BASE": "main",
        "DEVBOX_STATUS_STALE": "0",
    }
    env.pop("DEVBOX_STATUS_ACTIVITY_CMD", None)  # force the real __tmux__ path, not an injected probe
    env.pop("TMUX", None)

    r = subprocess.run(["bash", str(TOOL), "status", "waiting", "--json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"status must succeed with the fake tmux: {r.stderr}"
    agents = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
    blk = agents["waiting-blk"]
    # The probe must read the last NON-BLANK line (the prompt) -> blocked. The mutation that
    # takes the literal last line sees a blank padding row and misclassifies as working.
    assert blk["activity"] == "blocked", \
        f"a pane whose last non-blank line is a (y/n) prompt must read blocked: {blk}"

    print("session_activity_faketmux=PASS")
finally:
    cleanup()
