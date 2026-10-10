#!/usr/bin/env python3
"""Host-independent guard for the activity probe's tmux path (no real tmux needed).

The real-tmux test (test-session-activity-tmux.py) is the high-fidelity layer but skips where
tmux is absent (e.g. macOS, minimal CI), leaving the probe's mutations unguarded there. This
test puts a fake `tmux` first on PATH that models the subcommands the probe may call, including
the real quirks it must not trust, so it runs on every host:
  - has-session -t =<s>                 exit 0 for a known session, else 1
  - list-windows -t =<s> -F <fmt>       one row per window, names/commands printed RAW (a newline
                                        in one splits it over several lines, as real tmux does);
                                        #{session_windows} is the true window count
  - list-panes -t @<id> -F <fmt>        one row per pane of that window (#{window_panes} is the
                                        true pane count; commands printed RAW); the window's
                                        list-windows #{pane_current_command} is its ACTIVE pane's
  - capture-pane -p -t <target>         exact resolution; a missing window errors (like real tmux)
  - display-message -p -t <target> fmt  the real QUIRK: a missing window silently falls back to
                                        the session's current window and exits 0
Cases (three sessions, one status call each); "held" agents are merged+clean+free, so only the
probe's verdict decides whether they read reapable:
  waiting (no raw newlines anywhere):
  - blk:      last NON-blank line is a "(y/n)" prompt above blank padding rows -> blocked
  - idle:     a shell -> idle;  work: a non-shell command -> working
  - ghost:    registered, NO window, current window an idle shell, and a window whose name merely
              EXTENDS the agent's ("<agent>-2", busy) -> unknown; provably absent, so reapable
  - dup:      two windows carry the agent's name -> unknown and NEVER reapable (may be live)
  - gone:     window listed but capture-pane fails (vanished mid-probe) -> unknown, not reapable
  - vanish:   window in the name listing but gone from the facts listing -> unknown, not reapable
  - nocmd:    window with an empty pane command -> unknown, not reapable
  - twofacts: the facts listing carries the window's id twice -> unknown, not reapable
  forged: a decoy window's name holds raw newlines forging "<count>\t<id>\t<agent>" for the
          current window -> the whole listing is rejected: the ghost reads unknown and a real,
          live agent window in that session reads unknown and is NOT reapable
  twin:   another window's pane command holds raw newlines forging a second facts row for the
          agent's window id -> unknown, not reapable
  split:  the agent's window is split; its ACTIVE pane is an idle shell and the agent CLI runs in
          the other pane -> working, not reapable (the active-pane reads alone said idle)
  splitforge: a pane command with raw newlines makes the pane listing inconsistent -> unknown,
          not reapable
  nosess: no tmux session for the project at all -> unknown; provably absent, so reapable
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

def render(fmt, w, count, pane_cmd=None):
    vals = {"window_id": w["id"], "window_name": w["name"], "window_index": str(w["index"]),
            "window_activity": str(w["activity"]),
            "pane_current_command": w["cmd"] if pane_cmd is None else pane_cmd,
            "session_windows": str(count), "window_panes": str(len(w.get("panes", [w["cmd"]])))}
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
    fmt = opts.get("-F", "")
    facts = "pane_current_command" in fmt
    # names_only: the window vanished between the name listing and the facts listing.
    # facts_dup:  a facts listing that repeats the window's id (a second, different row).
    rows = []
    for w in s["windows"]:
        if facts and w.get("names_only"):
            continue
        rows.append(w)
        if facts and w.get("facts_dup"):
            rows.append(dict(w, cmd=w["facts_dup"]))
    for w in rows:
        sys.stdout.write(render(fmt, w, len(rows)) + "\n")
    sys.exit(0)
if sub == "list-panes":
    w = strict(t) if t.startswith("@") else None
    if w is None:
        sys.stderr.write("can't find window\n"); sys.exit(1)
    fmt = opts.get("-F", "")
    for cmd in w.get("panes", [w["cmd"]]):
        sys.stdout.write(render(fmt, w, 0, cmd) + "\n")
    sys.exit(0)
if sub == "capture-pane":
    w = strict(t)
    if w is None or w.get("capture_fails"):
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
    sys.stdout.write((render(fmt, w, 0) if w else re.sub(r"#\{[a-z_]+\}", "", fmt)) + "\n")
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

    # window_activity=1 (epoch) => huge age => stalled past any threshold. @0/@20/@30 are each
    # session's CURRENT window: an idle shell, exactly what a name-target fallback would read.
    def win(wid, index, name, cmd, capture, **extra):
        return {"id": wid, "index": index, "name": name, "cmd": cmd, "activity": 1,
                "capture": capture, **extra}

    sessions = {
        "waiting": {"current": "@0", "windows": [
            win("@0", 1, "main", "bash", SHELL_CAPTURE),
            win("@1", 2, "waiting-blk", "python", PROMPT_CAPTURE),
            win("@2", 3, "waiting-dup", "python", BUSY_CAPTURE),
            win("@3", 4, "waiting-dup", "python", BUSY_CAPTURE),
            # a name that only EXTENDS the ghost's: a prefix/glob match would alias it (busy)
            win("@4", 5, "waiting-ghost-2", "python", BUSY_CAPTURE),
            win("@5", 6, "waiting-idle", "bash", SHELL_CAPTURE),
            win("@6", 7, "waiting-work", "python", BUSY_CAPTURE),
            win("@7", 8, "waiting-gone", "bash", SHELL_CAPTURE, capture_fails=True),
            win("@8", 9, "waiting-vanish", "bash", SHELL_CAPTURE, names_only=True),
            # the window listing has no command for its active pane (the pane listing alone would
            # read a shell): the window-level check must hold it on its own
            win("@9", 10, "waiting-nocmd", "", SHELL_CAPTURE, panes=["bash"]),
            win("@10", 11, "waiting-twofacts", "bash", SHELL_CAPTURE, facts_dup="python"),
            # split: the ACTIVE pane (what list-windows and capture-pane read) is an idle shell;
            # the agent CLI runs in the other pane.
            win("@11", 12, "waiting-split", "bash", SHELL_CAPTURE, panes=["bash", "python"]),
            win("@12", 13, "waiting-splitforge", "bash", SHELL_CAPTURE, panes=["bash", "x\nbash"]),
        ]},
        # a name with raw newlines: list-windows prints "<n>\t@21\tdecoy" and then a forged
        # "<n>\t@20\tforged-forge" row (count prefix included, so only the line count betrays it)
        "forged": {"current": "@20", "windows": [
            win("@20", 1, "main", "bash", SHELL_CAPTURE),
            win("@21", 2, "decoy\n3\t@20\tforged-forge", "sleep", BUSY_CAPTURE),
            win("@22", 3, "forged-live", "bash", SHELL_CAPTURE),
        ]},
        # a pane command with raw newlines forging a second facts row for @30 (busy command)
        "twin": {"current": "@30", "windows": [
            win("@30", 1, "twin-agent", "bash", SHELL_CAPTURE),
            win("@31", 2, "other", "x\n2\t@30\t1\tpython", BUSY_CAPTURE),
        ]},
    }
    spec = base / "spec.json"
    spec.write_text(json.dumps({"sessions": sessions}))
    calls_log = base / "calls.log"

    # A real git repo + one worktree per registered agent (git facts must not crash); base pinned
    # so the loop never needs to resolve main/master. The registry window name == agent. Rows
    # carry the fork SHA; agents in MERGED get a commit merged into main (merged, clean, turn
    # free), so their reapable flag is decided by the activity probe alone.
    repo = base / "repo"; repo.mkdir()

    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)

    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@e", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    (repo / "README.md").write_text("seed\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-q", "-m", "seed", cwd=repo)
    fork = git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    projects = {
        "waiting": ("waiting-blk", "waiting-ghost", "waiting-dup", "waiting-idle", "waiting-work",
                    "waiting-gone", "waiting-vanish", "waiting-nocmd", "waiting-twofacts",
                    "waiting-split", "waiting-splitforge"),
        "forged": ("forged-forge", "forged-live"),
        "twin": ("twin-agent",),
        "nosess": ("nosess-agent",),  # no tmux session at all
    }
    MERGED = {"waiting-ghost", "waiting-dup", "waiting-gone", "waiting-vanish", "waiting-nocmd",
              "waiting-twofacts", "waiting-split", "waiting-splitforge", "forged-live", "twin-agent",
              "nosess-agent"}
    home = base / "sessions"; home.mkdir()
    for project, names in projects.items():
        rows = []
        for agent in names:
            wt = base / f"wt-{agent}"
            git("worktree", "add", "-q", "-b", f"agent/{agent}", str(wt), fork, cwd=repo)
            if agent in MERGED:
                (wt / f"{agent}.txt").write_text("done\n")
                git("add", f"{agent}.txt", cwd=wt)
                git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", agent, cwd=wt)
                git("merge", "-q", "--no-ff", "-m", f"merge {agent}", f"agent/{agent}", cwd=repo)
            rows.append(f"{agent}\t{wt}\tagent/{agent}\t{fork}\n")
        (home / f"{project}.tsv").write_text("".join(rows))

    # PATH with the fake tmux FIRST so devbox-session's `command -v tmux` and every `tmux` call
    # resolve to the shim regardless of whether a real tmux exists on this host.
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "DEVBOX_SESSION_HOME": str(home),
        "DEVBOX_STATUS_BASE": "main",
        "DEVBOX_STATUS_STALE": "0",
        "DEVBOX_TURN_STATE": str(base / "turn"),
        "FAKE_TMUX_SPEC": str(spec),
        "FAKE_TMUX_LOG": str(calls_log),
    }
    env.pop("DEVBOX_STATUS_ACTIVITY_CMD", None)  # force the real __tmux__ path, not an injected probe
    env.pop("TMUX", None)

    def status(project):
        r = subprocess.run(["bash", str(TOOL), "status", project, "--json"],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, f"status must succeed with the fake tmux: {r.stderr}"
        got = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
        for agent in MERGED & set(got):
            assert got[agent]["merged"] is True and got[agent]["dirty"] is False \
                and got[agent]["turn"] == "free", f"setup: {agent} must be merged, clean, free: {got[agent]}"
        return got

    agents = status("waiting")
    # The probe must read the last NON-BLANK line (the prompt) -> blocked. The mutation that
    # takes the literal last line sees a blank padding row and misclassifies as working.
    blk = agents["waiting-blk"]
    assert blk["activity"] == "blocked", \
        f"a pane whose last non-blank line is a (y/n) prompt must read blocked: {blk}"
    assert agents["waiting-idle"]["activity"] == "idle", \
        f"an idle shell must read idle: {agents['waiting-idle']}"
    assert agents["waiting-work"]["activity"] == "working", \
        f"a non-shell foreground command must read working: {agents['waiting-work']}"
    # No window at all: a name-targeted probe falls back to the current (idle shell) window, and
    # a prefix/glob name match would alias the busy "waiting-ghost-2" window.
    ghost = agents["waiting-ghost"]
    assert ghost["activity"] == "unknown", \
        f"an agent with no tmux window must read unknown, not the current window's activity: {ghost}"
    assert ghost["reapable"] is True, \
        f"a provably absent window (merged, clean, free) stays reapable: {ghost}"
    dup = agents["waiting-dup"]
    assert dup["activity"] == "unknown", \
        f"an agent whose name labels two windows is ambiguous and must read unknown: {dup}"
    assert dup["reapable"] is False, \
        f"a live but ambiguous window must never be reapable: {dup}"
    gone = agents["waiting-gone"]
    assert gone["activity"] == "unknown" and gone["reapable"] is False, \
        f"a window that vanished before capture must read unknown and not reapable: {gone}"
    vanish = agents["waiting-vanish"]
    assert vanish["activity"] == "unknown" and vanish["reapable"] is False, \
        f"a window gone from the facts listing must read unknown and not reapable: {vanish}"
    nocmd = agents["waiting-nocmd"]
    assert nocmd["activity"] == "unknown" and nocmd["reapable"] is False, \
        f"a window with no readable command must read unknown and never be reapable: {nocmd}"
    split = agents["waiting-split"]
    assert split["activity"] == "working" and split["reapable"] is False, \
        f"a split window running the agent in a pane that is not active must read working: {split}"
    splitforge = agents["waiting-splitforge"]
    assert splitforge["activity"] == "unknown" and splitforge["reapable"] is False, \
        f"an inconsistent pane listing must read unknown and not reapable: {splitforge}"
    twofacts = agents["waiting-twofacts"]
    assert twofacts["activity"] == "unknown" and twofacts["reapable"] is False, \
        f"an inconsistent facts listing (id twice) must read unknown and not reapable: {twofacts}"

    agents = status("forged")
    forge = agents["forged-forge"]
    assert forge["activity"] == "unknown", \
        f"a newline-forged window row must not alias the agent to another window: {forge}"
    live = agents["forged-live"]
    assert live["activity"] == "unknown" and live["reapable"] is False, \
        f"a listing broken by a newline-forged row must read unknown and not reapable: {live}"

    agents = status("twin")
    twin = agents["twin-agent"]
    assert twin["activity"] == "unknown" and twin["reapable"] is False, \
        f"a newline-forged facts row for the same window id must read unknown: {twin}"

    agents = status("nosess")
    nosess = agents["nosess-agent"]
    assert nosess["activity"] == "unknown" and nosess["reapable"] is True, \
        f"no tmux session for the project reads unknown and, provably absent, stays reapable: {nosess}"

    # Never address a window by NAME: that is the target form tmux resolves with a fallback.
    calls = [json.loads(line) for line in calls_log.read_text().splitlines()]
    assert calls, "the fake tmux must have been called"
    for argv in calls:
        if "-t" in argv:
            target = argv[argv.index("-t") + 1]
            assert target in ("=waiting", "=forged", "=twin", "=nosess") or (target.startswith("@") and target[1:].isdigit()), \
                f"probe must target the session or a window id, never a window name: {argv}"
        assert argv[0] != "display-message", f"probe must not trust display-message: {argv}"

    print("session_activity_faketmux=PASS")
finally:
    cleanup()
