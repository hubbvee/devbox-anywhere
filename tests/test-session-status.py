#!/usr/bin/env python3
"""Contract for `devbox-session status <project> [--json]` (exact git-convergence facts).

Exact facts per agent: dirty, ahead/behind vs base, merged (branch is ancestor of base),
turn holder, and reapable = merged && !dirty && turn free. Fixture-driven with a real git
repo + worktrees; no live tmux (activity classification is covered separately): every status
call gets a private, empty TMUX_TMPDIR and no TMUX, so a tmux server on the host can never
change a result. Fails closed on unknown project; a registered worktree gone from disk is
reported `missing`, one git cannot read is reported `error`, never a crash. Also pinned: status
never takes git's optional index lock, a turn it cannot read exactly never reads free, and every
field is safe to print (JSON-escaped control bytes, printable-ASCII table).
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


NO_TMUX_DIR = pathlib.Path(tempfile.mkdtemp(prefix="devbox-status-notmux-"))


def hermetic(env: dict[str, str]) -> dict[str, str]:
    # A private, empty tmux socket dir: the host's own tmux server is never queried.
    env = dict(env) | {"TMUX_TMPDIR": str(NO_TMUX_DIR)}
    for key in ("TMUX", "DEVBOX_STATUS_ACTIVITY_CMD", "GIT_OPTIONAL_LOCKS", "DEVBOX_TURN_HOLDER"):
        env.pop(key, None)
    return env


def status(*args: str, home, wt_root, repo, turn_state=None, activity_cmd=None, stale=None) -> subprocess.CompletedProcess[str]:
    env = hermetic(wt_env(home, wt_root, repo) | {"DEVBOX_STATUS_BASE": "main"})
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

# --- activity heuristic (injectable probe) ---
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

# --- read-only: status never takes git's optional index lock or rewrites the index ---
# A plain `git status` refreshes stat data and rewrites the worktree's index under index.lock,
# so polling status (e.g. a bot through the status gate) would make an agent's own git
# add/commit/rebase fail at random with "index.lock: File exists".
web_index = pathlib.Path(git("rev-parse", "--absolute-git-dir", cwd=web)) / "index"
future = web_index.stat().st_mtime + 100
os.utime(web / "w.txt", (future, future))  # stat data now differs from the index entry
index_before = web_index.read_bytes()
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert r.returncode == 0, r.stderr
assert web_index.read_bytes() == index_before, "status_index_untouched"
assert not web_index.with_name("index.lock").exists(), "status_index_untouched:lock"

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

# ============================================================================
# Status-board corrections found by operator smoke. The activity probe's blocked path
# (a waiting prompt never fires on a non-full real pane) lives in the real tmux probe and
# is covered by test-session-activity-tmux.py.
# ============================================================================

# --- A fresh agent (no commits of its own) is NEW, not merged/reapable ---
# A brand-new worktree sits exactly at the commit it forked from, so its branch is
# trivially an ancestor of base. Before the fix that read as merged -> reapable, so the
# documented "reapable -> devbox-worktree remove" workflow would delete a LIVE agent's
# worktree, and a never-started agent was indistinguishable from a genuinely merged one.
fr = wt("add", "webapp", "webapp-fresh", home=home, wt_root=wt_root, repo=repo)
assert fr.returncode == 0, fr.stderr
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
fresh = ag["webapp-fresh"]
assert fresh.get("new") is True, "fresh_agent_is_new"
assert fresh["merged"] is False, "fresh_agent_not_merged"
assert fresh["reapable"] is False, "fresh_agent_not_reapable"
# a committed+merged agent is NOT new (it has its own history)
assert ag["webapp-cli"].get("new") is False, "merged_agent_not_new"

# --- An actively-working merged agent is not reapable (activity excluded) ---
# reapable must exclude activity=working so the reaper never targets a live agent.
stub_cli_working = write_stub(base / "act_cli_work.sh", (
    'case "$2" in\n'
    '  webapp-cli) printf "node\\t3\\t\\n" ;;\n'   # non-shell, recent -> working
    '  *) printf "bash\\t500\\t$ \\n" ;;\n'
    'esac\n'
))
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state, activity_cmd=stub_cli_working)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-cli"]["activity"] == "working", ag["webapp-cli"]
assert ag["webapp-cli"]["reapable"] is False, "reapable_excludes_working"

# --- The table shows dirty even when merged (merged+dirty), never hidden ---
# gs used to be overwritten by `merged`, so a merged-but-dirty worktree printed just `merged`.
(cli / "late.txt").write_text("uncommitted\n")  # the merged agent is now also dirty
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-cli"]["merged"] is True and ag["webapp-cli"]["dirty"] is True, ag["webapp-cli"]
h = status("webapp", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert "merged+dirty" in h.stdout, "table must show merged+dirty, not hide dirty under merged: " + h.stdout

# --- A fresh agent with an uncommitted file is new+dirty, never just `new` ---
# `new` precedence must not swallow dirt, same rule as merged+dirty: dirty is never hidden.
(wt_root / "webapp-fresh" / "scratch.txt").write_text("uncommitted\n")
r = status("webapp", "--json", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
ag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
assert ag["webapp-fresh"]["new"] is True and ag["webapp-fresh"]["dirty"] is True, ag["webapp-fresh"]
assert ag["webapp-fresh"]["reapable"] is False, "new_dirty_not_reapable"
h = status("webapp", home=home, wt_root=wt_root, repo=repo, turn_state=turn_state)
assert "new+dirty" in h.stdout, "table must show new+dirty, not hide dirty under new: " + h.stdout

# --- Legacy 3-column registry rows (created before the fork-SHA column existed) ---
# Every existing user's registry is 3-column; status must still tell a fresh agent from a
# merged one via the branch reflog, so the reap workflow can never delete a never-started agent.
lbase = pathlib.Path(tempfile.mkdtemp(prefix="devbox-status-legacy-"))
lrepo = lbase / "repo"; lrepo.mkdir()
git("init", "-q", "-b", "main", cwd=lrepo)
git("config", "user.email", "t@e", cwd=lrepo)
git("config", "user.name", "t", cwd=lrepo)
(lrepo / "README.md").write_text("seed\n")
git("add", "README.md", cwd=lrepo)
git("commit", "-q", "-m", "seed", cwd=lrepo)
lhome = lbase / "sessions"; lhome.mkdir()
lwt_root = lbase / "worktrees"
lturn = lbase / "turn"
# create two agents the normal way, then STRIP the 4th column to emulate a pre-upgrade registry
for a in ("legacy-fresh", "legacy-done"):
    rr = wt("add", "legacy", a, home=lhome, wt_root=lwt_root, repo=lrepo)
    assert rr.returncode == 0, rr.stderr
done = lwt_root / "legacy-done"
(done / "d.txt").write_text("done\n")
git("add", "d.txt", cwd=done)
git("commit", "-q", "-m", "legacy work", cwd=done)
git("merge", "--no-ff", "-m", "merge legacy-done", "agent/legacy-done", cwd=lrepo)
reg = lhome / "legacy.tsv"
stripped = "\n".join("\t".join(line.split("\t")[:3]) for line in reg.read_text().splitlines() if line) + "\n"
reg.write_text(stripped)
assert all(len(l.split("\t")) == 3 for l in reg.read_text().splitlines() if l), "registry must be 3-column"
r = status("legacy", "--json", home=lhome, wt_root=lwt_root, repo=lrepo, turn_state=lturn)
assert r.returncode == 0, r.stderr
lag = {a["agent"]: a for a in json.loads(r.stdout)["agents"]}
# fresh legacy agent (only its creation reflog entry): new, never merged, never reapable
assert lag["legacy-fresh"]["new"] is True, "legacy_fresh_is_new"
assert lag["legacy-fresh"]["merged"] is False, "legacy_fresh_not_merged"
assert lag["legacy-fresh"]["reapable"] is False, "legacy_fresh_not_reapable"
# genuinely merged legacy agent (has its own commit): not new, merged, reapable
assert lag["legacy-done"]["new"] is False, "legacy_done_not_new"
assert lag["legacy-done"]["merged"] is True and lag["legacy-done"]["reapable"] is True, "legacy_done_reapable"
shutil.rmtree(lbase, ignore_errors=True)

# ============================================================================
# Edge cases: everything below is written by agents (registry rows, turn locks), so status must
# fail closed on what it cannot read exactly and print only what is safe to print.
# ============================================================================
ebase = pathlib.Path(tempfile.mkdtemp(prefix="devbox-status-edge-"))
erepo = ebase / "repo"; erepo.mkdir()
git("init", "-q", "-b", "main", cwd=erepo)
git("config", "user.email", "t@e", cwd=erepo)
git("config", "user.name", "t", cwd=erepo)
(erepo / "README.md").write_text("seed\n")
git("add", "README.md", cwd=erepo)
git("commit", "-q", "-m", "seed", cwd=erepo)
ehome = ebase / "sessions"; ehome.mkdir()
ewt_root = ebase / "worktrees"
eturn = ebase / "turn"
EDGE = ("edge-ok", "edge-free", "edge-byfree", "edge-ts", "edge-ctl")
for a in EDGE:  # all merged + clean: only the turn decides whether they read reapable
    rr = wt("add", "edge", a, home=ehome, wt_root=ewt_root, repo=erepo)
    assert rr.returncode == 0, rr.stderr
    awt = ewt_root / a
    (awt / f"{a}.txt").write_text("done\n")
    git("add", f"{a}.txt", cwd=awt)
    git("commit", "-q", "-m", a, cwd=awt)
    git("merge", "-q", "--no-ff", "-m", f"merge {a}", f"agent/{a}", cwd=erepo)


def take(agent: str, holder: str) -> None:
    subprocess.run(["bash", str(TURN_TOOL), "take", str(ewt_root / agent)],
                   env=os.environ | {"DEVBOX_TURN_STATE": str(eturn), "DEVBOX_TURN_HOLDER": holder},
                   capture_output=True, text=True, check=True)


take("edge-free", "free")             # a holder literally named "free" still holds the turn
take("edge-byfree", "x by free")      # a holder whose name ends in " by free"
take("edge-ts", "bob")                # held, then its timestamp is corrupted below
take("edge-ctl", "bob\r\x1b[2Kok")    # control bytes in the holder name
key = subprocess.run(["bash", "-c", 'printf %s "$1" | { sha256sum 2>/dev/null || shasum -a 256; } | cut -d" " -f1',
                      "_", str(ewt_root / "edge-ts")], capture_output=True, text=True, check=True).stdout.strip()
(eturn / key / "ts").write_text("x y")

# A registered directory git cannot read, and a row whose fields hold control and non-UTF-8 bytes.
notgit = ebase / "notgit"; notgit.mkdir()
ctl_agent = b"edge-x\x1b]0;pwned\x07\r"
ctl_row = ctl_agent + b"\t/nonexistent/\x1b[2K\xff\tb\x7f\n"
with (ehome / "edge.tsv").open("ab") as reg_file:
    reg_file.write(f"edge-broken\t{notgit}\tagent/edge-broken\n".encode() + ctl_row)


def edge_status(*args: str, base_env: bool = True, tool: pathlib.Path = TOOL) -> subprocess.CompletedProcess[bytes]:
    env = hermetic(wt_env(ehome, ewt_root, erepo) | {"DEVBOX_TURN_STATE": str(eturn)})
    if base_env:
        env["DEVBOX_STATUS_BASE"] = "main"
    else:
        env.pop("DEVBOX_STATUS_BASE", None)
    return subprocess.run(["bash", str(tool), "status", "edge", *args], env=env, capture_output=True)


def parsed(r: subprocess.CompletedProcess[bytes]) -> dict[str, dict]:
    assert r.returncode == 0, f"status_edge_rc:{r.returncode}:{r.stderr!r}"
    try:
        doc = json.loads(r.stdout.decode("utf-8"))
    except ValueError as error:  # UnicodeDecodeError is a ValueError too
        raise AssertionError(f"status_json_control_escaped:{error}:{r.stdout[-300:]!r}") from None
    return {a["agent"]: a for a in doc["agents"]}


for base_env in (True, False):
    eag = parsed(edge_status("--json", base_env=base_env))
    assert eag["edge-ok"]["turn"] == "free" and eag["edge-ok"]["reapable"] is True, f"setup:{eag['edge-ok']}"
    # A turn that cannot be read exactly is never "free", so never reapable.
    assert eag["edge-free"]["turn"] == "unknown" and eag["edge-free"]["reapable"] is False, \
        f"turn_holder_named_free_not_reapable:{eag['edge-free']}"
    assert eag["edge-byfree"]["turn"] == "unknown" and eag["edge-byfree"]["reapable"] is False, \
        f"turn_holder_by_free_not_reapable:{eag['edge-byfree']}"
    assert eag["edge-ts"]["turn"] == "bob" and eag["edge-ts"]["reapable"] is False, \
        f"turn_corrupt_ts_still_held:{eag['edge-ts']}"
    assert eag["edge-ctl"]["turn"] == "unknown" and eag["edge-ctl"]["reapable"] is False, \
        f"turn_holder_unsafe_reads_unknown:{eag['edge-ctl']}"
    # One unreadable worktree is that agent's error, not a crash hiding every other agent.
    broken = eag["edge-broken"]
    assert broken["error"] is True and broken["missing"] is False and broken["reapable"] is False, \
        f"status_broken_worktree_error:{broken}"
    assert eag["edge-ok"]["error"] is False, eag["edge-ok"]
    # Control bytes are \u-escaped (the value round-trips), invalid UTF-8 bytes too.
    ctl = eag[ctl_agent.decode("latin-1")]
    assert ctl["worktree"] == "/nonexistent/\x1b[2K\u00ff" and ctl["branch"] == "b\x7f", f"status_json_control_escaped:{ctl}"
assert set(eag) == set(EDGE) | {"edge-broken", ctl_agent.decode("latin-1")}, sorted(eag)

# The table and `list` print only printable ASCII (no ESC/CR/BEL reaches a terminal or a bot).
table = edge_status()
assert table.returncode == 0, table.stderr
listed = subprocess.run(["bash", str(TOOL), "list"], env=hermetic(wt_env(ehome, ewt_root, erepo)), capture_output=True)
assert listed.returncode == 0, listed.stderr
for label, out in (("table", table.stdout), ("list", listed.stdout)):
    bad = sorted({b for b in out if (b < 0x20 and b != 0x0A) or b >= 0x7F})
    assert not bad, f"status_table_printable:{label}:{bad}"
rows = {line.split()[0]: line for line in table.stdout.decode().splitlines()[1:]}
assert rows["edge-broken"].split()[1] == "ERROR", "status_broken_worktree_error:table"
assert "(reapable)" in rows["edge-ok"] and "(reapable)" not in rows["edge-free"], f"setup:{rows}"
assert rows["edge-x?]0;pwned??"].split()[1] == "MISSING", f"status_table_printable:row:{rows}"

# devbox-turn failing (absent state, a crash, anything) reads "unknown", never "free".
fake_bin = ebase / "bin"; fake_bin.mkdir()
shutil.copyfile(TOOL, fake_bin / "devbox-session")
(fake_bin / "devbox-turn").write_text("#!/bin/sh\nprintf 'free: %s\\n' \"$2\"\nexit 1\n")
(fake_bin / "devbox-turn").chmod(0o755)
eag = parsed(edge_status("--json", tool=fake_bin / "devbox-session"))
assert eag["edge-ok"]["turn"] == "unknown" and eag["edge-ok"]["reapable"] is False, f"turn_error_reads_unknown:{eag['edge-ok']}"
shutil.rmtree(ebase, ignore_errors=True)
shutil.rmtree(NO_TMUX_DIR, ignore_errors=True)

print("session_status=PASS")
