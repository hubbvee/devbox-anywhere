#!/usr/bin/env python3
"""Contract for verify's relink.targets probe (RELINK_TARGETS_PROBE in scripts/devbox-anywhere).

The v1.6.0 operator smoke proved relink.targets warned on EVERY box, forever, for two reasons:

  DEFECT 1 -- the probe's `grep -E '^[[:space:]]*relink '` over the on-box scripts/devbox-relink
  also matched the drop-in loader's own indented internal call `relink "$target" "$link"`, so it
  emitted a bogus `"$link" -> "$target"` pair (literal, unexpanded $) on every install.

  DEFECT 2 -- fresh installs link the shipped write-through defaults (terminfo, gh-config,
  gitconfig) to sources that do not exist yet (no `gh auth login` / git config on a new box).
  relink creates those symlinks anyway (by design: the tool writes THROUGH the link into the
  persisted ~/.local/share store on first use). The probe flagged all three as DANGLING on a
  perfectly healthy fresh box.

Together these made the check pure noise and unable to detect the one case it exists for: an
operator drop-in link whose source was removed (a dangling ~/.hermes).

This test runs the REAL probe text under /bin/sh against the REAL shipped scripts/devbox-relink
in a temp HOME -- the layer the Part B test (which feeds canned probe output) never exercised.

Contract:
  (1a) a fresh HOME with only .local/secrets present (the installer's state) is clean: no DANGLING.
  (1b) no emitted pair contains a literal '$' -- the probe must never parse the loader's own call.
  (1c) a drop-in whose source existed when relink ran and was then removed is DANGLING (warn),
       naming the offending link path -- the real dangling-drop-in case the check is built for.
"""
from __future__ import annotations

import atexit
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
RELINK = REPO / "scripts/devbox-relink"
HARNESS = REPO / "scripts/devbox-anywhere"

assert RELINK.is_file(), "scripts/devbox-relink must exist"
assert HARNESS.is_file(), "scripts/devbox-anywhere must exist"

# Pin the REAL probe string from the harness (same extraction test-verify-invariants.py uses),
# so this test exercises the shipped probe, not a copy.
_HARNESS_TEXT = HARNESS.read_text()
_m = re.search(
    r'RELINK_TARGETS_PROBE = (r?"""(?:.*?)"""|r?\'\'\'(?:.*?)\'\'\')',
    _HARNESS_TEXT,
    re.DOTALL,
)
assert _m, "harness must define RELINK_TARGETS_PROBE"
RELINK_TARGETS_PROBE = eval(_m.group(1))

_HOMES: list[pathlib.Path] = []


@atexit.register
def _cleanup() -> None:
    for h in _HOMES:
        shutil.rmtree(h, ignore_errors=True)


def make_home() -> pathlib.Path:
    """A temp HOME with the shipped devbox-relink installed where the probe looks for it."""
    home = pathlib.Path(tempfile.mkdtemp(prefix="relink-probe-"))
    _HOMES.append(home)
    (home / ".local/bin").mkdir(parents=True)
    installed = home / ".local/bin/devbox-relink"
    shutil.copy(RELINK, installed)
    installed.chmod(0o755)
    # The installer creates ~/.local/secrets; the other shipped sources do not exist on a fresh box.
    (home / ".local/secrets").mkdir(parents=True)
    return home


def run_relink(home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(home), "LC_ALL": "C"}
    return subprocess.run(["bash", str(home / ".local/bin/devbox-relink")], env=env, capture_output=True, text=True)


def run_probe(home: pathlib.Path) -> list[str]:
    """Return the DANGLING pairs (text after 'DANGLING ') the real probe emits for this HOME."""
    env = os.environ | {"HOME": str(home), "LC_ALL": "C"}
    r = subprocess.run(["/bin/sh", "-c", RELINK_TARGETS_PROBE], env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"probe must exit 0 (warn-only lives in the caller): {r.stderr}"
    return [ln[len("DANGLING "):] for ln in r.stdout.splitlines() if ln.startswith("DANGLING ")]


# --- 1b first: the probe must never parse the loader's own `relink "$target" "$link"` call -------
# (checked across every scenario below, but asserted explicitly here on a plain fresh box)
home = make_home()
run_relink(home)
pairs = run_probe(home)
assert not any("$" in p for p in pairs), \
    f"probe must not parse the loader call: no pair may contain a literal '$': {pairs}"

# --- 1a: a healthy fresh box (only .local/secrets) is clean: no dangling targets -----------------
home = make_home()
run_relink(home)  # creates write-through placeholder links for terminfo/gh/gitconfig (sources absent)
pairs = run_probe(home)
assert pairs == [], \
    f"fresh box must report no dangling targets (shipped write-through defaults are healthy): {pairs}"

# --- 1c: a drop-in whose source existed and was removed is DANGLING, naming the link -------------
home = make_home()
dropin_dir = home / ".local/share/devbox-relink.d"
dropin_dir.mkdir(parents=True)
(home / ".local/share/hermes-home").mkdir(parents=True)  # source exists NOW
(dropin_dir / "10-hermes.conf").write_text(f"{home}/.local/share/hermes-home {home}/.hermes\n")
run_relink(home)  # loader sees the source, creates ~/.hermes -> ~/.local/share/hermes-home
assert (home / ".hermes").is_symlink(), "precondition: drop-in link must be created when source exists"
shutil.rmtree(home / ".local/share/hermes-home")  # source removed AFTER relink -> now dangling
pairs = run_probe(home)
assert any(str(home / ".hermes") in p for p in pairs), \
    f"a removed drop-in source must dangle (the ~/.hermes case): {pairs}"
# and the fresh shipped defaults must NOT have crept back in as noise
assert not any(".terminfo" in p or ".config/gh" in p or ".gitconfig" in p for p in pairs), \
    f"shipped write-through defaults must not be flagged alongside a real dangling drop-in: {pairs}"

print("relink_targets_probe=PASS")
