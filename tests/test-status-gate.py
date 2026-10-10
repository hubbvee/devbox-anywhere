#!/usr/bin/env python3
"""Contract for scripts/devbox-status-gate: read-only SSH forced command for a bot's key.

The gate is installed as `restrict,command="<gate>"` in authorized_keys; sshd puts the
client's request in SSH_ORIGINAL_COMMAND. Only `version`, `list`, `status <project>` and
`status <project> --json` are allowed; each allowed form execs the devbox-session BESIDE the
gate with an exact argv, a fixed PATH and a scrubbed environment. Everything else is denied
(exit 126, fixed stderr, request never echoed, helper never run, nothing interpreted). Every
request is audit-logged 0600 with a sanitized request; the log rotates past 256 KiB; an allow
whose log line cannot be written is denied (fail closed). The gate is copied into a temp dir
next to a STUB devbox-session that records its argv/env/stdin.

Not covered here: the "owned by you or root" half of the trust checks (helper, devbox-turn,
helper dir, log dir, log file) needs a file owned by ANOTHER non-root user, which an
unprivileged test cannot create. Only the symlink/mode/type halves are exercised.
"""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE = REPO / "scripts/devbox-status-gate"
SESSION_TOOL = REPO / "scripts/devbox-session"
TURN_TOOL = REPO / "scripts/devbox-turn"
DENIED = b"devbox-status-gate: denied\n"
SAFE_PATH = "/usr/bin:/bin"
CLIENT = "203.0.113.7 51234 22"

assert GATE.is_file(), "scripts/devbox-status-gate must exist"
assert os.stat(GATE).st_mode & 0o111 == 0o111, "gate_executable_bit"

STUB = """#!/bin/sh
rec="${0%/*}/record"
{
  printf 'argc=%s\\n' "$#"
  for a in "$@"; do printf 'arg=%s\\n' "$a"; done
  printf 'stdin=%s\\n' "$(/bin/cat)"
  printf 'env-begin\\n'
  /usr/bin/env
  printf 'env-end\\n'
} > "$rec"
exit 0
"""

tmp = pathlib.Path(tempfile.mkdtemp(prefix="devbox-status-gate-")).resolve()
atexit.register(shutil.rmtree, tmp, ignore_errors=True)  # also when an assertion fails
os.chmod(tmp, 0o700)
bindir = tmp / "bin"
home = tmp / "home"
work = tmp / "work"  # the gate's cwd: a shell injection would drop its canary here
for d in (bindir, home, work):
    d.mkdir()
    os.chmod(d, 0o700)
gate = bindir / "devbox-status-gate"
shutil.copyfile(GATE, gate)
os.chmod(gate, 0o755)
stub = bindir / "devbox-session"
stub.write_text(STUB)
os.chmod(stub, 0o755)
record = bindir / "record"
log = home / ".local/state/devbox/gate/status-gate.log"
empty_bash_env = tmp / "bash-env"
empty_bash_env.write_text("")

# Env an attacker (or a confused caller) might try to smuggle in. None may reach the helper.
POISON = {
    "DEVBOX_STATUS_ACTIVITY_CMD": str(tmp / "evil-probe"),
    "DEVBOX_SESSION_HOME": str(tmp / "evil-registry"),
    "DEVBOX_STATUS_BASE": "--output=evil",
    "DEVBOX_STATUS_STALE": "0",
    "DEVBOX_TURN_STATE": str(tmp / "evil-turn"),
    "DEVBOX_TURN_HOLDER": "evil",
    "DEVBOX_TURN_TTL": "0",
    "GIT_DIR": str(tmp / "evil-git"),
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "touch canary",
    "BASH_ENV": str(empty_bash_env),
    "ENV": str(empty_bash_env),
    "LD_LIBRARY_PATH": str(tmp / "evil-lib"),
    "TMUX": "evil",
    "TMUX_TMPDIR": str(tmp / "evil-tmux"),
    "MY_SECRET_TOKEN": "TEST_ONLY_NOT_A_SECRET",
}
ALLOWED_CHILD_KEYS = {"HOME", "PATH", "LC_ALL", "PWD", "OLDPWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING"}


def gate_env(request: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ) | POISON | {"HOME": str(home), "SSH_CLIENT": CLIENT}
    env.pop("XDG_STATE_HOME", None)
    env.pop("SSH_ORIGINAL_COMMAND", None)
    if request is not None:
        env["SSH_ORIGINAL_COMMAND"] = request
    env |= extra or {}
    return env


def run_gate(request: str | None, *, path: pathlib.Path | None = None, extra: dict[str, str] | None = None,
             args: tuple[str, ...] = (), stdin: bytes = b"STDIN_FROM_CLIENT") -> subprocess.CompletedProcess[bytes]:
    env = gate_env(request, extra)
    return subprocess.run([str(path or gate), *args], env=env, cwd=work, input=stdin, capture_output=True, timeout=60)


def utf8_locale() -> str | None:
    """A locale in which bash counts characters, not bytes (None if this host has none)."""
    for loc in ("C.UTF-8", "en_US.UTF-8"):
        r = subprocess.run(["bash", "-c", 'x=$(printf "\\303\\251"); printf %s "${#x}"'],
                           env=dict(os.environ, LC_ALL=loc), capture_output=True, text=True)
        if r.stdout == "1":
            return loc
    return None


def read_record(where: pathlib.Path = record) -> dict[str, object] | None:
    if not where.exists():
        return None
    lines = where.read_text().splitlines()
    argc = int(lines[0].split("=", 1)[1])
    argv = [line[len("arg="):] for line in lines[1:1 + argc]]
    stdin_line = lines[1 + argc]
    begin, end = lines.index("env-begin"), lines.index("env-end")
    env = dict(line.split("=", 1) for line in lines[begin + 1:end] if "=" in line)
    return {"argv": argv, "stdin": stdin_line[len("stdin="):], "env": env}


def clear_record() -> None:
    if record.exists():
        record.unlink()


def log_lines(path: pathlib.Path = log) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t") for line in path.read_bytes().decode("latin-1").split("\n") if line]


def sanitized(request: str) -> str:
    raw = request.encode("utf-8")[:200]
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "?" for b in raw)


def expect_denied(request: str | None, label: str, **kw) -> subprocess.CompletedProcess[bytes]:
    clear_record()
    r = run_gate(request, **kw)
    assert r.returncode == 126, f"gate_hostile_not_denied:{label}:rc={r.returncode}:{r.stdout!r}:{r.stderr!r}"
    assert r.stdout == b"" and r.stderr == DENIED, f"gate_deny_no_echo:{label}:{r.stdout!r}:{r.stderr!r}"
    assert read_record() is None, f"gate_hostile_not_denied:{label}:helper ran"
    return r


def last_reason() -> str:
    return log_lines()[-1][4]


# --- 1. Allowed forms exec the helper with the exact argv, fixed PATH, scrubbed env. -------
ALLOWED = [
    ("list", ["list"]),
    ("status myapp", ["status", "myapp"]),
    ("status myapp --json", ["status", "myapp", "--json"]),
    ("status my.app_2-x", ["status", "my.app_2-x"]),
    ("status a", ["status", "a"]),
    ("status " + "a" * 64, ["status", "a" * 64]),
    ("status " + "b" * 64 + " --json", ["status", "b" * 64, "--json"]),
]
for request, argv in ALLOWED:
    clear_record()
    r = run_gate(request)
    rec = read_record()
    assert r.returncode == 0 and rec is not None, f"gate_allowed_exec:{request}:rc={r.returncode}:{r.stderr!r}"
    assert rec["argv"] == argv, f"gate_allowed_exact_argv:{request}:{rec['argv']}"
    assert rec["stdin"] == "", f"gate_stdin_closed:{request}:{rec['stdin']!r}"
    env = rec["env"]
    assert isinstance(env, dict)
    assert env.get("PATH") == SAFE_PATH, f"gate_fixed_path:{env.get('PATH')!r}"
    leaked = sorted(set(POISON) & set(env))
    assert not leaked and set(env) <= ALLOWED_CHILD_KEYS, f"gate_env_scrubbed:{leaked}:{sorted(env)}"
    assert env.get("HOME") == str(home) and env.get("LC_ALL") == "C", f"gate_env_scrubbed:{env}"

# version: the gate's own line, no helper.
clear_record()
r = run_gate("version")
assert r.returncode == 0 and r.stdout == b"devbox-status-gate 1.8.0\n" and r.stderr == b"", f"gate_version:{r!r}"
assert read_record() is None, "gate_version_runs_no_helper"

# The helper's exit status passes straight through (exec, not a wrapper).
stub.write_text(STUB.replace("exit 0", "exit 7"))
r = run_gate("list")
assert r.returncode == 7, f"gate_exec_status_passthrough:{r.returncode}"
stub.write_text(STUB)

# The gate works in BYTES whatever the caller's locale: a multibyte request is denied and
# logged as at most 200 '?' (one per byte), never as 200 characters. Logged elsewhere so the
# line accounting of section 4 is untouched.
UTF8 = utf8_locale()
if UTF8:
    xdg_loc = tmp / "xdg-locale"
    wide = "status " + "\u00e9" * 150
    clear_record()
    r = run_gate(wide, extra={"LC_ALL": UTF8, "LANG": UTF8, "XDG_STATE_HOME": str(xdg_loc)})
    assert r.returncode == 126 and read_record() is None, f"gate_byte_locale:not-denied:{r!r}"
    shown = log_lines(xdg_loc / "devbox/gate/status-gate.log")[-1][2]
    assert len(shown) == 200, f"gate_byte_locale:{len(shown)}"
    assert shown == sanitized(wide), f"gate_log_sanitized:wide:{shown!r}"
else:
    print("status_gate_utf8_locale=SKIP (no UTF-8 locale for bash on this host)")

# --- 2. Interactive / empty / argument-only invocations are denied. ------------------------
expect_denied(None, "unset")
assert last_reason() == "empty", "gate_deny_reason:unset"
expect_denied("", "empty")
expect_denied(None, "args-ignored", args=("status", "myapp"))
expect_denied(None, "args-ignored-list", args=("list",))

# --- 3. Hostile / malformed requests: denied, never interpreted, never reach the helper. --
HOSTILE = [
    "list ", " list", "list\n", "list\t", "list\r", "LIST", "List", "list\x01", "list\x1b[31m", "list\x7f",
    "list;touch canary", "list && touch canary", "list | touch canary", "list`touch canary`",
    "list$(touch canary)", "list\ntouch canary", "status $(touch canary)", "status x;touch canary",
    "status x|touch canary", "status x&touch canary", "status x>canary", "status x<canary",
    "status x>>canary", "status 'x'", 'status "x"', "status *", "status x?", "status [x]",
    "status {x,y}", "status ~", "status x\\y", "status ../x", "status x/y", "status /etc",
    "status -x", "status --json", "status -", "status .hidden", "status .", "status ..",
    "status", "status ", "status  x", "status x  --json", "status x --json ", "status x --JSON",
    "status x --json --json", "status x y", "status x\t--json", "status x\n--json", "status " + "a" * 65,
    "status café", "status x\u200b", "status \u0430dmin", "resolve x", "resolve x x-a", "bash", "sh",
    "sh -c 'touch canary'", "bash -c touch canary", "scp -t .", "scp -f x", "internal-sftp", "sftp",
    "git-upload-pack 'x'", "rsync --server . x", "version --help", "version ", "help", "--help", "-h",
    "x" * 5000, "status x" + " " * 100, "exec touch canary", "env", "true", "${IFS}", "status x${IFS}y",
]
assert len(HOSTILE) >= 25, "need at least 25 hostile requests"
for request in HOSTILE:
    expect_denied(request, repr(request[:40]))
assert not (work / "canary").exists(), "gate_injection_interpreted:canary in cwd"
assert not list(tmp.rglob("canary")), "gate_injection_interpreted:canary somewhere"
assert not (tmp / "evil-git").exists() and not (tmp / "evil-turn").exists(), "gate_injection_interpreted:poison path touched"

# --- 4. Audit log: one sanitized single line per request, 0600 in a 0700 dir. -------------
lines = log_lines()
expected_requests = [req for req, _ in ALLOWED] + ["version", "list", "", "", "", ""] + HOSTILE
expected_decisions = ["allow"] * (len(ALLOWED) + 2) + ["deny"] * (4 + len(HOSTILE))
assert len(lines) == len(expected_requests), f"gate_log_sanitized:count={len(lines)}!={len(expected_requests)}"
for fields, request, expected_decision in zip(lines, expected_requests, expected_decisions):
    assert len(fields) == 5, f"gate_log_sanitized:fields:{fields}"
    when, decision, shown, client, reason = fields
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", when), f"gate_log_time:{when}"
    assert shown == sanitized(request), f"gate_log_sanitized:{shown!r}!={sanitized(request)!r}"
    assert len(shown) <= 200 and all(0x20 <= ord(c) <= 0x7E for c in shown), f"gate_log_sanitized:{shown!r}"
    assert client == "203.0.113.7", f"gate_log_client:{client}"
    assert decision == expected_decision, f"gate_log_decision:{request!r}:{decision}"
    assert re.fullmatch(r"[a-z-]+", reason), f"gate_log_reason:{reason!r}"
assert "TEST_ONLY_NOT_A_SECRET" not in log.read_text(), "gate_log_leaks_env"
assert stat.S_IMODE(log.stat().st_mode) == 0o600, f"gate_log_mode:{oct(log.stat().st_mode)}"
assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700, f"gate_log_dir_mode:{oct(log.parent.stat().st_mode)}"

# Deny reasons pin WHICH gate stopped a request (each layer is checked on its own).
REASONS = [
    ("list;touch canary", "charset"), ("status x/y", "charset"), ("status café", "charset"),
    ("list\n", "charset"), ("x" * 5000, "length"), ("status x" + " " * 100, "length"),
    ("LIST", "form"), (" list", "form"), ("resolve x", "form"), ("status -x", "project"),
    ("status .hidden", "project"), ("status x y", "project"), ("status " + "a" * 65, "project"),
]
for request, reason in REASONS:
    expect_denied(request, repr(request[:40]))
    assert last_reason() == reason, f"gate_deny_reason:{request[:20]!r}:{last_reason()}!={reason}"

# Hostile SSH_CLIENT is sanitized too (first field, hex/.: only, no line breaks).
expect_denied("bad;", "client", extra={"SSH_CLIENT": "1.2.3.4\nZZ\tqq;$(x) 1 2"})
assert len(log_lines()[-1]) == 5, f"gate_log_client_sanitized:fields:{log_lines()[-1]}"
assert log_lines()[-1][3] == "1.2.3.4" + "?" * 11, f"gate_log_client_sanitized:{log_lines()[-1]}"
expect_denied("bad;", "no-client", extra={"SSH_CLIENT": ""})
assert log_lines()[-1][3] == "-", f"gate_log_client_absent:{log_lines()[-1]}"

# devbox/ is shared with the session registry and is often group-writable (umask 002): fine,
# because the log lives in the gate's own gate/ dir below it.
os.chmod(log.parent.parent, 0o775)
clear_record()
assert run_gate("list").returncode == 0 and read_record() is not None, "gate_log_shared_parent_ok"
os.chmod(log.parent.parent, 0o700)
# gate/ itself must be yours alone: group- or world-writable fails closed, nothing written.
for mode, label in ((0o770, "group-writable-log-dir"), (0o777, "world-writable-log-dir")):
    os.chmod(log.parent, mode)
    before = log.read_bytes()
    clear_record()
    r = run_gate("list")
    os.chmod(log.parent, 0o700)
    assert r.returncode == 126 and r.stderr == DENIED and read_record() is None, f"gate_allow_fail_closed:{label}"
    assert log.read_bytes() == before, f"gate_allow_fail_closed:{label}:written"

# A log the gate cannot create (gate/ read-only, no log yet) fails closed, and the failed append's
# shell error -- which names the gate's absolute path -- never reaches the client's stderr.
if os.geteuid() != 0:  # root ignores the mode
    saved = tmp / "saved-status-gate.log"
    log.rename(saved)
    os.chmod(log.parent, 0o500)
    clear_record()
    r = run_gate("list")
    os.chmod(log.parent, 0o700)
    created = log.exists()
    saved.rename(log)
    assert r.returncode == 126 and r.stderr == DENIED and read_record() is None and not created, \
        f"gate_allow_fail_closed:read-only-log-dir:{r.returncode}:{r.stderr!r}"

# A symlinked gate/ dir is never followed, even to a dir you own that is also named gate.
elsewhere = tmp / "elsewhere/gate"
elsewhere.mkdir(parents=True)
os.chmod(elsewhere, 0o700)
real_gate_dir = log.parent.with_name("gate.real")
log.parent.rename(real_gate_dir)
log.parent.symlink_to(elsewhere)
clear_record()
r = run_gate("list")
written = list(elsewhere.iterdir())
log.parent.unlink()
real_gate_dir.rename(log.parent)
assert r.returncode == 126 and read_record() is None and not written, f"gate_log_dir_symlink_refused:{written}"

# A pre-existing looser log is tightened back to 0600.
os.chmod(log, 0o644)
run_gate("list")
assert stat.S_IMODE(log.stat().st_mode) == 0o600, "gate_log_mode_tightened"

# Rotation: past 256 KiB the log moves to .1 (one generation) and a fresh log starts.
log.write_bytes(b"x" * 262144)
run_gate("list")
assert not log.with_name("status-gate.log.1").exists() and log.stat().st_size > 262144, "gate_log_rotated:early"
big = log.read_bytes()
run_gate("list")
rotated = log.with_name("status-gate.log.1")
assert rotated.exists() and rotated.read_bytes() == big, "gate_log_rotated"
assert len(log_lines()) == 1 and log_lines()[0][1] == "allow", "gate_log_rotated:fresh"
assert stat.S_IMODE(rotated.stat().st_mode) == 0o600, "gate_log_rotated:mode"

# Rotation never moves the log INTO a directory sitting at .1 (directly or through a symlink).
lock = log.with_name("status-gate.lock")
target_dir = tmp / "rot-target"
target_dir.mkdir()
os.chmod(target_dir, 0o700)
for label in ("symlink-to-dir", "dir"):
    rotated.unlink()
    if label == "dir":
        rotated.mkdir()
    else:
        rotated.symlink_to(target_dir)
    log.write_bytes(b"x" * (262144 + 1))
    clear_record()
    r = run_gate("list")
    moved_in = list(target_dir.iterdir()) + (list(rotated.iterdir()) if label == "dir" else [])
    assert r.returncode == 126 and read_record() is None and not moved_in, f"gate_log_rotate_target_refused:{label}:{moved_in}"
    assert log.stat().st_size == 262144 + 1 and not lock.exists(), f"gate_log_rotate_target_refused:{label}:state"
    if label == "dir":
        rotated.rmdir()
    else:
        rotated.unlink()
    rotated.write_text("")

# Concurrent requests during a rotation: every allow succeeds (a log rotated away between one
# gate's checks is a fresh log, not a failure), nothing leaks to the client's stderr, exactly one
# gate rotates, and .1 keeps the whole old generation. 24 gates x 10 trials: with 6 x 5 the
# vanished-log race (a valid status read denied as log-failed) slipped through most runs.
CONCURRENT = 24
for trial in range(10):
    big = b"x" * (262144 + 100)
    log.write_bytes(big)
    rotated.unlink()
    procs = [subprocess.Popen([str(gate)], env=gate_env("list"), cwd=work, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(CONCURRENT)]
    outcomes = [(proc.wait(timeout=60), proc.stderr.read()) for proc in procs]
    for proc in procs:
        proc.stderr.close()
    codes = [code for code, _ in outcomes]
    assert codes == [0] * CONCURRENT, f"gate_log_rotation_concurrent:rc:{codes}"
    assert all(err == b"" for _, err in outcomes), f"gate_log_rotation_concurrent:stderr:{[e for _, e in outcomes if e][:2]}"
    old = rotated.read_bytes()
    assert old.startswith(big) and not lock.exists(), f"gate_log_rotation_concurrent:generation:{len(old)}"
    tail = old[len(big):].decode() + log.read_text()
    assert tail.count("\tallow\tlist\t") == CONCURRENT, f"gate_log_rotation_concurrent:lines:{tail!r}"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600, "gate_log_rotation_concurrent:mode"
rotated.unlink()

# XDG_STATE_HOME is honored when it is a safe absolute path.
xdg = tmp / "xdg"
clear_record()
r = run_gate("list", extra={"XDG_STATE_HOME": str(xdg)})
assert r.returncode == 0 and (xdg / "devbox/gate/status-gate.log").exists(), "gate_log_xdg"

# Fail closed for allows: if the log line cannot be written, the request is denied.
blocked = tmp / "blocked"
blocked.mkdir()
(blocked / "devbox").write_text("not a dir")
for label, extra in (
    ("log-dir-is-file", {"XDG_STATE_HOME": str(blocked)}),
    ("relative-xdg", {"XDG_STATE_HOME": "relative/state"}),
    ("weird-xdg", {"XDG_STATE_HOME": str(tmp) + "/a b"}),
    ("dot-segment-xdg", {"XDG_STATE_HOME": str(tmp) + "/xdg-dots/../xdg-norm"}),
):
    clear_record()
    r = run_gate("list", extra=extra)
    assert r.returncode == 126 and r.stderr == DENIED and read_record() is None, f"gate_allow_fail_closed:{label}:{r!r}"
assert not (tmp / "xdg-norm").exists(), "gate_allow_fail_closed:dot-segment-xdg:created"

# A symlinked log is never written through (allow fails closed, deny stays denied).
victim = tmp / "victim"
victim.write_text("ORIGINAL\n")
log.unlink()
log.symlink_to(victim)
clear_record()
r = run_gate("list")
assert r.returncode == 126 and read_record() is None, "gate_allow_fail_closed:symlinked-log"
expect_denied("bad;", "symlinked-log-deny")
assert victim.read_text() == "ORIGINAL\n", "gate_log_symlink_followed"
log.unlink()

# --- 5. Helper resolution: beside the gate's real path, never via PATH, fail closed. -------
# Missing helper -> denied; a decoy earlier on the caller's PATH is never used.
decoy_dir = tmp / "decoy"
decoy_dir.mkdir()
os.chmod(decoy_dir, 0o700)
(decoy_dir / "devbox-session").write_text(STUB)
os.chmod(decoy_dir / "devbox-session", 0o755)
stub.unlink()
expect_denied("list", "missing-helper", extra={"PATH": f"{decoy_dir}:{os.environ.get('PATH', SAFE_PATH)}"})
assert last_reason() == "helper", "gate_deny_reason:missing-helper"
assert not (decoy_dir / "record").exists(), "gate_never_via_path"

# Symlinked helper -> denied, its target never runs.
(bindir / "devbox-session").symlink_to(decoy_dir / "devbox-session")
clear_record()
r = run_gate("list")
assert r.returncode == 126 and r.stderr == DENIED, f"gate_symlink_helper_denied:{r!r}"
assert not (decoy_dir / "record").exists() and read_record() is None, "gate_symlink_helper_denied:ran"
assert last_reason() == "helper", "gate_symlink_helper_denied:reason"
(bindir / "devbox-session").unlink()

stub.write_text(STUB)
for mode, label in ((0o775, "group-writable"), (0o757, "world-writable"), (0o644, "not-executable")):
    os.chmod(stub, mode)
    expect_denied("list", f"helper-{label}")
os.chmod(stub, 0o755)

# The gate fixes its OWN PATH before any check: a decoy `find` early on the caller's PATH
# (which would vouch for anything) cannot get a group-writable helper accepted.
decoy_bin = tmp / "decoy-bin"
decoy_bin.mkdir()
os.chmod(decoy_bin, 0o700)
(decoy_bin / "find").write_text("#!/bin/sh\nexit 0\n")
os.chmod(decoy_bin / "find", 0o755)
os.chmod(stub, 0o775)
clear_record()
r = run_gate("list", extra={"PATH": f"{decoy_bin}:{os.environ.get('PATH', SAFE_PATH)}"})
os.chmod(stub, 0o755)
assert r.returncode == 126 and r.stderr == DENIED and read_record() is None, f"gate_own_path_fixed:{r!r}"

# HOME must be a safe absolute directory before the helper runs (the log may live elsewhere).
(work / "relhome").mkdir()
(tmp / "h me").mkdir()
for label, bad_home in (("relative", "relhome"), ("space", str(tmp / "h me")), ("missing", str(tmp / "no-such-home"))):
    clear_record()
    r = run_gate("list", extra={"HOME": bad_home, "XDG_STATE_HOME": str(tmp / "xdg-home")})
    assert r.returncode == 126 and r.stderr == DENIED and read_record() is None, f"gate_home_checked:{label}:{r!r}"
    assert log_lines(tmp / "xdg-home/devbox/gate/status-gate.log")[-1][4] == "home", f"gate_home_checked:{label}:reason"

# A shared (group/world-writable) helper directory -> denied.
for mode, label in ((0o777, "world"), (0o770, "group")):
    os.chmod(bindir, mode)
    clear_record()
    r = run_gate("list")
    os.chmod(bindir, 0o700)
    assert r.returncode == 126 and read_record() is None, f"gate_shared_dir_denied:{label}"

# devbox-turn beside the helper (devbox-session runs it) must be a trusted file too.
turn = bindir / "devbox-turn"
turn.symlink_to(decoy_dir / "devbox-session")
expect_denied("list", "symlinked-turn")
turn.unlink()
turn.write_text("#!/bin/sh\nexit 0\n")
os.chmod(turn, 0o775)
expect_denied("list", "group-writable-turn")
os.chmod(turn, 0o755)
clear_record()
assert run_gate("list").returncode == 0 and read_record() is not None, "gate_allowed_exec:with-turn"

# The gate reached through a symlink resolves to its REAL dir; a helper beside the link is ignored.
links = tmp / "links"
links.mkdir()
os.chmod(links, 0o700)
(links / "devbox-status-gate").symlink_to(gate)
(links / "devbox-session").write_text(STUB)
os.chmod(links / "devbox-session", 0o755)
clear_record()
r = run_gate("status myapp", path=links / "devbox-status-gate")
assert r.returncode == 0 and read_record() is not None, f"gate_resolves_real_path:{r!r}"
assert not (links / "record").exists(), "gate_resolves_real_path:used helper beside the link"

# --- 6. Integration with the REAL devbox-session: env overrides cannot redirect it. --------
real = tmp / "real"
real.mkdir()
os.chmod(real, 0o700)
for src in (GATE, SESSION_TOOL, TURN_TOOL):
    shutil.copyfile(src, real / src.name)
    os.chmod(real / src.name, 0o755)
reg = home / ".local/state/devbox/sessions"
reg.mkdir(parents=True)
(reg / "myapp.tsv").write_text(f"myapp-a\t{tmp}/no-such-worktree\tagent/myapp-a\n")
evil_reg = tmp / "evil-registry"
evil_reg.mkdir()
(evil_reg / "evilproj.tsv").write_text(f"evilproj-a\t{tmp}\tagent/evilproj-a\n")
r = run_gate("list", path=real / "devbox-status-gate")
assert r.returncode == 0 and b"project=myapp" in r.stdout and b"evilproj" not in r.stdout, f"gate_real_list:{r!r}"
r = run_gate("status myapp --json", path=real / "devbox-status-gate")
assert r.returncode == 0, f"gate_real_status:{r!r}"
doc = json.loads(r.stdout)
assert doc["project"] == "myapp" and doc["agents"][0]["missing"] is True, f"gate_real_status:{doc}"
r = run_gate("status evilproj", path=real / "devbox-status-gate")
assert r.returncode == 1 and b"unknown project: evilproj" in r.stderr, f"gate_real_status_unknown:{r!r}"

# --- 7. Static: no eval / nested shell / sourcing; the request is read in exactly one place.
code = [line for line in GATE.read_text().splitlines() if not line.lstrip().startswith("#")]
body = "\n".join(code)
assert not re.search(r"\beval\b", body), "gate_source_no_eval"
assert not re.search(r"\b(ba|z|da)?sh\s+-c\b", body), "gate_source_no_eval:sh -c"
assert not re.search(r"(^|\s)(source|\.)\s", body, re.M), "gate_source_no_eval:sourcing"
assert body.count("SSH_ORIGINAL_COMMAND") == 1, "gate_source_single_read"

print(f"status_gate=PASS allowed={len(ALLOWED)} hostile={len(HOSTILE)}")
