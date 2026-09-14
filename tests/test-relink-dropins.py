#!/usr/bin/env python3
"""Contract for scripts/devbox-relink drop-in composition (Part A / D1 fix).

devbox-relink recreates home-dir symlinks after a container rebuild. Operators need to add
their OWN relinks in an upgrade-safe way: the installer overwrites the shipped helper on every
upgrade, so hand-editing it (as docs/10 used to instruct) loses customization (defect D1).

The fix: after the shipped in-file relinks, devbox-relink reads ~/.local/share/devbox-relink.d/*.conf
(one `target link` pair per line, `#` comments and blank lines ignored). This test pins that
contract:
  - shipped in-file relinks AND drop-in relinks are both applied;
  - drop-ins load in LC_ALL=C sorted filename order (deterministic, last-writer-wins on a link);
  - a .conf line whose target source does not exist is reported and SKIPPED -- never a dangling
    link, never fatal (this is what makes docs/10's dangling-link hazard impossible);
  - idempotent: a second run is a no-op with identical stable output;
  - fail-closed: an unreadable drop-in dir warns and continues with the in-file relinks, so the
    new feature can never make hands-off worse than it is today.

The helper runs with HOME pointed at a fixture. It targets ~/.local/... which lives under HOME,
so a fixture HOME fully isolates it. No container or tmux needed.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-relink"

assert TOOL.is_file(), "scripts/devbox-relink must exist"


def run(home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(home), "LC_ALL": "C"}
    return subprocess.run(["bash", str(TOOL)], env=env, capture_output=True, text=True)


def seed_shipped_sources(home: pathlib.Path) -> None:
    """Create the real dirs the shipped in-file relinks point at, so those links resolve."""
    share = home / ".local/share"
    share.mkdir(parents=True, exist_ok=True)
    (share / "terminfo").mkdir(exist_ok=True)
    (share / "gh-config").mkdir(exist_ok=True)
    (share / "gitconfig").mkdir(exist_ok=True)
    (home / ".local/secrets").mkdir(parents=True, exist_ok=True)


def make_home() -> pathlib.Path:
    home = pathlib.Path(tempfile.mkdtemp(prefix="devbox-relink-"))
    seed_shipped_sources(home)
    return home


def is_link_to(link: pathlib.Path, target: pathlib.Path) -> bool:
    return link.is_symlink() and os.readlink(link) == str(target)


# --- 1. Shipped in-file relinks still applied (regression guard) --------------------------------
home = make_home()
r = run(home)
assert r.returncode == 0, f"shipped relink run failed: {r.stderr}"
assert is_link_to(home / ".gitconfig", home / ".local/share/gitconfig"), "shipped gitconfig relink missing"
assert is_link_to(home / ".config/gh", home / ".local/share/gh-config"), "shipped gh relink missing"
assert is_link_to(home / ".secrets", home / ".local/secrets"), "shipped secrets relink missing"

# --- 2. Drop-in relinks are applied alongside the shipped ones ----------------------------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
# real sources the drop-ins point at
(home / ".local/share/mytool-config").mkdir()
(home / ".local/share/hermes-home").mkdir()
(dropin_dir / "10-mytool.conf").write_text(
    "# operator tool config\n"
    f"{home}/.local/share/mytool-config {home}/.config/mytool\n"
)
(dropin_dir / "20-hermes.conf").write_text(
    f"{home}/.local/share/hermes-home {home}/.hermes\n"
)
r = run(home)
assert r.returncode == 0, f"dropin run failed: {r.stderr}"
# shipped still applied
assert is_link_to(home / ".gitconfig", home / ".local/share/gitconfig"), "shipped relink lost when drop-ins present"
# drop-ins applied
assert is_link_to(home / ".config/mytool", home / ".local/share/mytool-config"), "drop-in mytool relink missing"
assert is_link_to(home / ".hermes", home / ".local/share/hermes-home"), "drop-in hermes relink missing"

# --- 3. Deterministic LC_ALL=C sorted load order (last writer wins on the same link) ------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
(home / ".local/share/src-a").mkdir()
(home / ".local/share/src-b").mkdir()
# both target the SAME link; sorted order means 20-*.conf is applied last and wins
(dropin_dir / "20-second.conf").write_text(f"{home}/.local/share/src-b {home}/.contested\n")
(dropin_dir / "10-first.conf").write_text(f"{home}/.local/share/src-a {home}/.contested\n")
r = run(home)
assert r.returncode == 0, f"ordered run failed: {r.stderr}"
assert is_link_to(home / ".contested", home / ".local/share/src-b"), "drop-ins must load in LC_ALL=C sorted order (last wins)"

# --- 4. Missing-source drop-in is reported and skipped: never dangling, never fatal -------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
(dropin_dir / "30-missing.conf").write_text(f"{home}/.local/share/does-not-exist {home}/.ghost\n")
r = run(home)
assert r.returncode == 0, f"missing-source drop-in must not be fatal: {r.stderr}"
assert not (home / ".ghost").exists() and not (home / ".ghost").is_symlink(), \
    "missing-source drop-in must be SKIPPED, never create a dangling link"
combined = r.stdout + r.stderr
assert "does-not-exist" in combined or "skip" in combined.lower(), \
    "a skipped missing-source drop-in must be reported"

# --- 5. Idempotence: a second run is a no-op with identical stable output -----------------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
(home / ".local/share/mytool-config").mkdir()
(dropin_dir / "10-mytool.conf").write_text(f"{home}/.local/share/mytool-config {home}/.config/mytool\n")
first = run(home)
second = run(home)
assert first.returncode == 0 and second.returncode == 0, "idempotent runs must succeed"
assert is_link_to(home / ".config/mytool", home / ".local/share/mytool-config"), "link missing after second run"
assert first.stdout == second.stdout, "second run output must be identical (idempotent)"

# --- 6. Fail-closed: unreadable drop-in dir warns and still applies shipped relinks -------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
(dropin_dir / "10-x.conf").write_text(f"{home}/.local/share/gitconfig {home}/.xlink\n")
os.chmod(dropin_dir, 0o000)
try:
    r = run(home)
finally:
    os.chmod(dropin_dir, 0o755)  # restore so TemporaryDirectory cleanup can proceed
assert r.returncode == 0, "an unreadable drop-in dir must not break relink (fail-closed to shipped behavior)"
assert is_link_to(home / ".gitconfig", home / ".local/share/gitconfig"), \
    "shipped relinks must still apply when the drop-in dir is unreadable"
combined = r.stdout + r.stderr
assert "warn" in combined.lower() or "devbox-relink.d" in combined, \
    "an unreadable drop-in dir must be reported (warn and continue)"

print("relink_dropins=PASS")
