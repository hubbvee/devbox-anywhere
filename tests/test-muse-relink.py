#!/usr/bin/env python3
"""Contract for the shipped Muse Code relink template (v1.8 Part A).

Muse Code (Meta's terminal coding agent, binary `muse`) installs to ~/.local/bin/muse -- already
on Devbox Anywhere's persistent mount, so the binary survives rebuilds for free. Its user config
and login live under ~/.config/muse/, which is NOT on the persistent mount and would be wiped on
every container rebuild -- so a fresh box would demand `muse login` again after each rebuild.

Devbox already solves this exact class of problem with the v1.6 devbox-relink drop-in mechanism:
move the real dir onto the persistent mount, then relink it back on boot. This test pins a
SHIPPED, ready-to-copy template so operators don't have to hand-author the .conf (and can't get
the persistent path wrong):

  - the template exists at templates/devbox-relink.d/20-muse.conf.example;
  - every non-comment line is a well-formed `target link` pair (exactly two fields, no spaces in
    paths) -- so it drops straight into ~/.local/share/devbox-relink.d/ and the loader accepts it;
  - the target lives under the persistent mount ($HOME/.local/share/...) and the link is
    $HOME/.config/muse -- i.e. it actually moves muse's config off the ephemeral path;
  - fed through the REAL devbox-relink loader it produces the correct symlink;
  - FIRST-BOOT SAFE: before the operator has migrated the dir (persistent source absent), the
    loader skips it -- no dangling ~/.config/muse link, never fatal -- matching the v1.6 contract.

Config persistence is orthogonal to the auth/sandbox blockers (B1 device-OAuth TTY, B2 bubblewrap
nesting), which are smoke-gated; this template is safe to ship regardless of how those resolve.

Runs with HOME pointed at a fixture; targets ~/... under HOME, so a fixture HOME fully isolates
it. No container or tmux needed.
"""
from __future__ import annotations

import atexit
import os
import pathlib
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TOOL = REPO / "scripts/devbox-relink"
TEMPLATE = REPO / "templates/devbox-relink.d/20-muse.conf.example"

assert TOOL.is_file(), "scripts/devbox-relink must exist"

_HOMES: list[pathlib.Path] = []


def fresh_home() -> pathlib.Path:
    home = pathlib.Path(tempfile.mkdtemp(prefix="muse-relink-"))
    _HOMES.append(home)
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".local/share").mkdir(parents=True, exist_ok=True)
    return home


@atexit.register
def _cleanup() -> None:
    for h in _HOMES:
        shutil.rmtree(h, ignore_errors=True)


def run(home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(home), "LC_ALL": "C"}
    return subprocess.run(["bash", str(TOOL)], env=env, capture_output=True, text=True)


def is_link_to(link: pathlib.Path, target: pathlib.Path) -> bool:
    return link.is_symlink() and os.path.realpath(link) == os.path.realpath(target)


def template_pairs(home: pathlib.Path) -> list[tuple[str, str]]:
    """Parse the shipped template, expanding $HOME -> fixture home. Fails the format contract loudly."""
    pairs: list[tuple[str, str]] = []
    for raw in TEMPLATE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        assert len(fields) == 2, f"malformed template line (want `target link`, got {len(fields)} fields): {raw!r}"
        target, link = (f.replace("$HOME", str(home)) for f in fields)
        pairs.append((target, link))
    return pairs


# --- the template must exist and be well-formed ---
assert TEMPLATE.is_file(), f"shipped muse relink template must exist at {TEMPLATE.relative_to(REPO)}"
_h0 = fresh_home()
pairs = template_pairs(_h0)
assert pairs, "template must declare at least one relink pair (a comments-only example is useless)"

# --- it must actually move muse config OFF the ephemeral path ONTO the persistent mount ---
persistent_prefix = f"{_h0}/.local/share/"
muse_link = f"{_h0}/.config/muse"
assert any(
    link == muse_link and target.startswith(persistent_prefix)
    for target, link in pairs
), "muse_target_not_persistent"

def deploy(template_home: pathlib.Path, dropin_dir: pathlib.Path) -> None:
    """Materialize the template the way docs instruct: expand $HOME to absolute paths, since the
    devbox-relink loader reads literal paths and does not itself expand $HOME."""
    dropin_dir.mkdir(parents=True, exist_ok=True)
    expanded = TEMPLATE.read_text().replace("$HOME", str(template_home))
    (dropin_dir / "20-muse.conf").write_text(expanded)


# --- fed through the REAL loader with the persistent source present -> correct symlink ---
home = fresh_home()
dropin_dir = home / ".local/share/devbox-relink.d"
deploy(home, dropin_dir)
# operator has done the one-time migration: the persistent source dirs exist
for target, _link in template_pairs(home):
    pathlib.Path(target).mkdir(parents=True, exist_ok=True)
r = run(home)
assert r.returncode == 0, f"devbox-relink failed with shipped muse template: {r.stderr}"
for target, link in template_pairs(home):
    assert is_link_to(pathlib.Path(link), pathlib.Path(target)), f"muse relink missing: {link} -> {target}\n{r.stdout}\n{r.stderr}"

# --- FIRST-BOOT SAFE: persistent source absent -> skipped, no dangling link, not fatal ---
home = fresh_home()
dropin_dir = home / ".local/share/devbox-relink.d"
deploy(home, dropin_dir)
# deliberately do NOT create the persistent source dirs (operator hasn't migrated yet)
r = run(home)
assert r.returncode == 0, f"devbox-relink must not fail when muse source is absent: {r.stderr}"
for _target, link in template_pairs(home):
    p = pathlib.Path(link)
    assert not (p.is_symlink() and not p.exists()), f"first-boot dangling link created: {link}"

print("muse_relink_template=PASS")
