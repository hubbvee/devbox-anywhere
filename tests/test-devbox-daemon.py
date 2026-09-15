#!/usr/bin/env python3
"""Contract for scripts/devbox-daemon: declarative, rebuild-safe supervision of long-running
helpers (e.g. a Hermes gateway) on a container where systemd is present but not PID 1 (dumb-init),
so `hermes gateway install` never runs and a hand-started tmux session dies on rebuild.

Daemons are declared in ~/.local/share/devbox-daemons.d/*.conf with fields:
  name          required, the daemon id
  command       required, the shell command to launch
  tmux_session  optional, the tmux session name for the DEFAULT (tmux) backend; defaults to name
  backend       optional, defaults to "tmux"; a non-tmux value is expressible so verify does not
                have to parse tmux details

`devbox-daemon status <name>` is the SINGLE SOURCE OF TRUTH for liveness. Part B's verify probe
delegates to it (falling back to a raw tmux check only when devbox-daemon is absent), so this test
is written against the status subcommand from the start — not a hardcoded tmux assumption.

The default backend uses a detached tmux session (works under dumb-init, no systemd). This test
puts a FAKE tmux on PATH so behavior is observable without a real server: the fake records
new-session / has-session / kill-session calls and simulates a session registry via a state file.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-daemon"

assert TOOL.is_file(), "scripts/devbox-daemon must exist"


def make_env() -> tuple[pathlib.Path, dict[str, str], pathlib.Path]:
    """A fixture HOME with a fake tmux on PATH. Returns (home, env, tmux_state)."""
    home = pathlib.Path(tempfile.mkdtemp(prefix="devbox-daemon-"))
    (home / ".local/share/devbox-daemons.d").mkdir(parents=True)
    fake_bin = home / "bin"
    fake_bin.mkdir()
    tmux_state = home / "tmux-sessions"  # newline-delimited list of "live" sessions
    tmux_state.write_text("")
    calls_log = home / "tmux-calls"
    calls_log.write_text("")
    # Fake tmux: has-session exits 0/1 by membership; new-session appends and runs the command so a
    # broken command surfaces a non-zero rc; kill-session removes. Enough surface for the contract.
    tmux = fake_bin / "tmux"
    tmux.write_text(
        "#!/usr/bin/env bash\n"
        f'state="{tmux_state}"\n'
        f'log="{calls_log}"\n'
        'printf "%s\\n" "$*" >> "$log"\n'
        'cmd=$1; shift\n'
        'case "$cmd" in\n'
        '  has-session)\n'
        '    # args: -t <name>\n'
        '    name=$2\n'
        '    grep -qxF "$name" "$state" 2>/dev/null && exit 0 || exit 1 ;;\n'
        '  new-session)\n'
        '    # args: -d -s <name> <command...>\n'
        '    name=""; args=("$@")\n'
        '    for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-s" ] && name="${args[$((i+1))]}"; done\n'
        '    run=""; for ((i=0;i<${#args[@]};i++)); do if [ "${args[$i]}" = "-s" ]; then run="${args[@]:$((i+2))}"; break; fi; done\n'
        '    grep -qxF "$name" "$state" 2>/dev/null || printf "%s\\n" "$name" >> "$state"\n'
        '    # execute the launch command so a broken command fails the start\n'
        '    bash -c "$run" ;;\n'
        '  kill-session)\n'
        '    name=$2\n'
        '    grep -vxF "$name" "$state" > "$state.tmp" 2>/dev/null || true; mv "$state.tmp" "$state" ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    tmux.chmod(0o755)
    env = os.environ | {"HOME": str(home), "PATH": f"{fake_bin}:{os.environ.get('PATH','')}", "LC_ALL": "C"}
    return home, env, tmux_state


def declare(home: pathlib.Path, name: str, command: str, *, tmux_session: str | None = None, backend: str | None = None) -> None:
    lines = [f"name {name}", f"command {command}"]
    if tmux_session is not None:
        lines.append(f"tmux_session {tmux_session}")
    if backend is not None:
        lines.append(f"backend {backend}")
    (home / ".local/share/devbox-daemons.d" / f"{name}.conf").write_text("\n".join(lines) + "\n")


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(TOOL), *args], env=env, capture_output=True, text=True)


# --- 1. status is the liveness source of truth: stopped before start, running after -------------
home, env, _ = make_env()
declare(home, "gateway", "sleep 300")
r = run(env, "status", "gateway")
assert r.returncode != 0, "status of a stopped daemon must exit non-zero"
assert "stopped" in (r.stdout + r.stderr).lower(), f"status must report stopped: {r.stdout!r}{r.stderr!r}"

r = run(env, "start", "gateway")
assert r.returncode == 0, f"start must succeed: {r.stderr}"
r = run(env, "status", "gateway")
assert r.returncode == 0, "status of a running daemon must exit 0"
assert "running" in r.stdout.lower(), f"status must report running: {r.stdout!r}"

# --- 2. start is start-if-not-running: a second start is a no-op, not a second session ----------
_, _, tmux_state = home, env, home / "tmux-sessions"
before = (home / "tmux-calls").read_text().count("new-session")
r = run(env, "start", "gateway")
assert r.returncode == 0, "second start must succeed (idempotent)"
after = (home / "tmux-calls").read_text().count("new-session")
assert after == before, "a second start must NOT create a second session (start-if-not-running)"
assert tmux_state.read_text().count("gateway") == 1, "exactly one session after repeated starts"

# --- 3. unknown daemon: fail closed, non-zero, no side effects ----------------------------------
home2, env2, tmux_state2 = make_env()
r = run(env2, "start", "ghost")
assert r.returncode != 0, "starting an undeclared daemon must fail closed"
assert tmux_state2.read_text().strip() == "", "an unknown daemon must create no session (no side effect)"
r = run(env2, "status", "ghost")
assert r.returncode != 0, "status of an undeclared daemon must fail closed"

# --- 4. a failing daemon command exits non-zero FROM THE CLI ------------------------------------
home3, env3, _ = make_env()
declare(home3, "broken", "exit 7")
r = run(env3, "start", "broken")
assert r.returncode != 0, "a daemon whose command fails must make `start` exit non-zero from the CLI"

# --- 5. start-all NEVER aborts the caller (the relink-hook path), even with a broken daemon -----
# devbox-relink runs under `set -e` and calls `devbox-daemon start-all || true` last; but start-all
# itself must not abort partway and must still attempt the healthy daemon.
home4, env4, tmux_state4 = make_env()
declare(home4, "broken", "exit 7")
declare(home4, "healthy", "sleep 300")
r = run(env4, "start-all")
# start-all reports trouble via exit code (the CLI is honest) AND must have ATTEMPTED all daemons.
# The honest non-zero is what makes the CLI usable outside the relink hook; inside the hook it is
# neutralized with `|| true`, so testing it here keeps it from decaying to always-0.
assert r.returncode != 0, "start-all with a broken daemon must exit non-zero (honest CLI)"
assert "healthy" in tmux_state4.read_text(), "start-all must start the healthy daemon even if another is broken"
r2 = run(env4, "status", "healthy")
assert r2.returncode == 0, "the healthy daemon must be running after start-all"

# --- 6. no daemons.d dir at all: start-all is a clean no-op (fresh install) ---------------------
home5 = pathlib.Path(tempfile.mkdtemp(prefix="devbox-daemon-empty-"))
fake_bin5 = home5 / "bin"; fake_bin5.mkdir()
(fake_bin5 / "tmux").write_text("#!/usr/bin/env bash\nexit 0\n"); (fake_bin5 / "tmux").chmod(0o755)
env5 = os.environ | {"HOME": str(home5), "PATH": f"{fake_bin5}:{os.environ.get('PATH','')}", "LC_ALL": "C"}
r = run(env5, "start-all")
assert r.returncode == 0, "start-all with no daemons.d must be a clean no-op"

# --- 7. backend field: a non-tmux backend is expressible; tmux_session is a default-backend detail
# status delegates to the declared backend. For an unknown/unsupported backend, status must not
# silently claim running via a raw tmux check (that would resurrect the very coupling we removed).
home6, env6, tmux_state6 = make_env()
declare(home6, "external", "true", backend="external")
# Simulate the external backend being "up" by pre-seeding the tmux registry with the SAME name,
# which a naive tmux-only status would wrongly report as running.
tmux_state6.write_text("external\n")
r = run(env6, "status", "external")
# A naive tmux-only status would find the pre-seeded session and report running, exit 0. That must
# be impossible: for a non-tmux backend, reporting running via a raw tmux has-session is the exact
# coupling C2 removes. Fail-closed or not-running are both acceptable; running is not.
assert not (r.returncode == 0 and "running" in r.stdout.lower()), \
    "status must judge a non-tmux backend by that backend, never report running via a raw tmux has-session"

# --- 8. tmux_session override is honored by the default backend --------------------------------
home7, env7, tmux_state7 = make_env()
declare(home7, "gw", "sleep 300", tmux_session="hermes-gw")
r = run(env7, "start", "gw")
assert r.returncode == 0, f"start with tmux_session override must succeed: {r.stderr}"
assert "hermes-gw" in tmux_state7.read_text(), "the default backend must use the declared tmux_session name"
r = run(env7, "status", "gw")
assert r.returncode == 0 and "running" in r.stdout.lower(), "status must resolve via the declared tmux_session"

print("devbox_daemon=PASS")
