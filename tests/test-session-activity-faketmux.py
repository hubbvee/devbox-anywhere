#!/usr/bin/env python3
"""Host-independent guard for the activity probe's tmux path (no real tmux needed).

The real-tmux test (test-session-activity-tmux.py) is the high-fidelity layer but skips where
tmux is absent (e.g. macOS, minimal CI), leaving the probe's mutations unguarded there. This
test puts a fake `tmux` first on PATH that models the subcommands the probe may call, including
the real quirks it must not trust, so it runs on every host:
  - has-session -t =<s>                 exit 0 for a known session, else 1
  - list-windows -t =<s> -F <fmt>       one row per window; a missing session errors
  - capture-pane -p -t <target>         exact resolution; a missing window errors (like real tmux)
  - display-message -p -t <target> fmt  the real QUIRK: a missing window silently falls back to
                                        the session's current window and exits 0
Cases (one session, one status call):
  - blocked: last NON-blank line is a "(y/n)" prompt above blank padding rows -> blocked
  - ghost:   registered agent with NO window, current window is an idle shell -> unknown
             (the name-targeted probe read the fallback window: "idle")
  - dup:     two windows carry the agent's name -> unknown (ambiguous)
  - forge:   another window's name holds a raw newline that forges "<id>\\t<agent>" for the
             current window's id -> unknown
  - twin:    the agent's window is unique, but another window's command holds a raw newline that
             forges a second facts row for the same id -> unknown
It also asserts the probe never addresses a window by NAME (the fallback-prone target form).
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

# A fake `tmux` driven by a JSON spec ($FAKE_TMUX_SPEC); every call's argv is appended to
# $FAKE_TMUX_LOG (one JSON array per line). Unknown subcommands fail loudly (exit 2).
FAKE_TMUX = r'''#!/usr/bin/env python3
import json, os, re, sys

spec = json.load(open(os.environ["FAKE_TMUX_SPEC"]))
with open(os.environ["FAKE_TMUX_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
sessions = spec["sessions"]
args = sys.argv[1:]
sub = args.pop(0) if args else ""
opts, pos = {}, []
while args:
    a = args.pop(0)
    if a in ("-t", "-F"):
        opts[a] = args.pop(0) if args else ""
    elif a.startswith("-"):
        opts[a] = True
    else:
        pos.append(a)

def render(fmt, w):
    vals = {"window_id": w["id"], "window_name": w["name"], "window_index": str(w["index"]),
            "window_activity": str(w["activity"]), "pane_current_command": w["cmd"]}
    return re.sub(r"#\{([a-z_]+)\}", lambda m: vals.get(m.group(1), ""), fmt)

def session_of(target):
    if not target.startswith("="):
        return None
    return sessions.get(target[1:].split(":", 1)[0])

def strict(target):
    # exact resolution, as capture-pane/list-windows do: no fallback
    for s in sessions.values():
        for w in s["windows"]:
            if target == w["id"]:
                return w
    s = session_of(target)
    if s is None or ":" not in target:
        return None
    win = target.split(":", 1)[1].lstrip("=")
    for w in s["windows"]:
        if win in (w["name"], str(w["index"])):
            return w
    return None

t = opts.get("-t", "")
if sub == "has-session":
    sys.exit(0 if session_of(t) is not None and ":" not in t else 1)
if sub == "list-windows":
    s = session_of(t)
    if s is None:
        sys.stderr.write("can't find session\n"); sys.exit(1)
    for w in s["windows"]:
        sys.stdout.write(render(opts.get("-F", ""), w) + "\n")
    sys.exit(0)
if sub == "capture-pane":
    w = strict(t)
    if w is None:
        sys.stderr.write("can't find window\n"); sys.exit(1)
    sys.stdout.write(w["capture"])
    sys.exit(0)
if sub == "display-message":
    w = strict(t)
    if w is None:
        s = session_of(t)
        if s is None and not t.startswith("@"):
            sys.stderr.write("can't find session\n"); sys.exit(1)
        if s is not None:
            # the real quirk: fall back to the session's CURRENT window, exit 0
            w = next(x for x in s["windows"] if x["id"] == s["current"])
    fmt = pos[0] if pos else ""
    sys.stdout.write((render(fmt, w) if w else re.sub(r"#\{[a-z_]+\}", "", fmt)) + "\n")
    sys.exit(0)
sys.stderr.write("fake tmux: unexpected subcommand %r\n" % sub)
sys.exit(2)
'''

PROMPT_CAPTURE = "Overwrite existing file? (y/n) \n\n\n\n"   # prompt, then blank padding rows
SHELL_CAPTURE = "$ \n\n\n"
BUSY_CAPTURE = "compiling...\n\n"


def cleanup() -> None:
    shutil.rmtree(base, ignore_errors=True)


try:
    bindir = base / "bin"
    bindir.mkdir()
    fake = bindir / "tmux"
    fake.write_text(FAKE_TMUX)
    fake.chmod(0o755)

    # One session "waiting". window_activity=1 (epoch) => huge age => stalled past any threshold.
    # @0 is the CURRENT window: an idle shell, exactly what a name-target fallback would read.
    windows = [
        {"id": "@0", "index": 1, "name": "main", "cmd": "bash", "activity": 1, "capture": SHELL_CAPTURE},
        {"id": "@1", "index": 2, "name": "waiting-blk", "cmd": "python", "activity": 1, "capture": PROMPT_CAPTURE},
        {"id": "@2", "index": 3, "name": "waiting-dup", "cmd": "python", "activity": 1, "capture": BUSY_CAPTURE},
        {"id": "@3", "index": 4, "name": "waiting-dup", "cmd": "python", "activity": 1, "capture": BUSY_CAPTURE},
        # name with a raw newline: list-windows prints "@4\tdecoy" then a forged "@0\twaiting-forge"
        {"id": "@4", "index": 5, "name": "decoy\n@0\twaiting-forge", "cmd": "sleep", "activity": 1, "capture": BUSY_CAPTURE},
        {"id": "@5", "index": 6, "name": "waiting-twin", "cmd": "bash", "activity": 1, "capture": SHELL_CAPTURE},
        # command with a raw newline: forges a second facts row for @5 claiming a busy command
        {"id": "@6", "index": 7, "name": "other", "cmd": "x\n@5\t1\tpython", "activity": 1, "capture": BUSY_CAPTURE},
    ]
    spec = base / "spec.json"
    spec.write_text(json.dumps({"sessions": {"waiting": {"current": "@0", "windows": windows}}}))
    calls_log = base / "calls.log"

    # A real git repo + one worktree per registered agent (git facts must not crash); base pinned
    # so the loop never needs to resolve main/master. The registry window name == agent.
    repo = base / "repo"; repo.mkdir()

    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)

    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@e", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    (repo / "README.md").write_text("seed\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-q", "-m", "seed", cwd=repo)

    agents_in = ("waiting-blk", "waiting-ghost", "waiting-dup", "waiting-forge", "waiting-twin")
    rows = []
    for agent in agents_in:
        wt = base / f"wt-{agent}"
        git("worktree", "add", "-q", "-b", f"agent/{agent}", str(wt), cwd=repo)
        rows.append(f"{agent}\t{wt}\tagent/{agent}\n")
    home = base / "sessions"; home.mkdir()
    (home / "waiting.tsv").write_text("".join(rows))

    # PATH with the fake tmux FIRST so devbox-session's `command -v tmux` and every `tmux` call
    # resolve to the shim regardless of whether a real tmux exists on this host.
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_STATUS_BASE": "main",
        "DEVBOX_STATUS_STALE": "0",
        "FAKE_TMUX_SPEC": str(spec),
        "FAKE_TMUX_LOG": str(calls_log),
    }
    env.pop("DEVBOX_STATUS_ACTIVITY_CMD", None)  # force the real __tmux__ path, not an injected probe
    env.pop("TMUX", None)

    r = subprocess.run(["bash", str(TOOL), "status", "waiting", "--json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"status must succeed with the fake tmux: {r.stderr}"
    agents = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}

    # The probe must read the last NON-BLANK line (the prompt) -> blocked. The mutation that
    # takes the literal last line sees a blank padding row and misclassifies as working.
    blk = agents["waiting-blk"]
    assert blk["activity"] == "blocked", \
        f"a pane whose last non-blank line is a (y/n) prompt must read blocked: {blk}"
    # No window at all: a name-targeted probe falls back to the current (idle shell) window.
    ghost = agents["waiting-ghost"]
    assert ghost["activity"] == "unknown", \
        f"an agent with no tmux window must read unknown, not the current window's activity: {ghost}"
    dup = agents["waiting-dup"]
    assert dup["activity"] == "unknown", \
        f"an agent whose name labels two windows is ambiguous and must read unknown: {dup}"
    forge = agents["waiting-forge"]
    assert forge["activity"] == "unknown", \
        f"a newline-forged window row must not alias the agent to another window: {forge}"
    twin = agents["waiting-twin"]
    assert twin["activity"] == "unknown", \
        f"a newline-forged facts row for the same window id must read unknown: {twin}"

    # Never address a window by NAME: that is the target form tmux resolves with a fallback.
    calls = [json.loads(line) for line in calls_log.read_text().splitlines()]
    assert calls, "the fake tmux must have been called"
    for argv in calls:
        if "-t" in argv:
            target = argv[argv.index("-t") + 1]
            assert target == "=waiting" or (target.startswith("@") and target[1:].isdigit()), \
                f"probe must target the session or a window id, never a window name: {argv}"
        assert argv[0] != "display-message", f"probe must not trust display-message: {argv}"

    print("session_activity_faketmux=PASS")
finally:
    cleanup()
