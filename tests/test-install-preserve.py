#!/usr/bin/env python3
"""A3 behavior contract: the installer's helper-preservation blob (fixes D1).

install-devbox overwrites the five helpers on every upgrade. Before A3 it did so with no backup
and no merge, silently destroying operator customization -- and docs/10 used to instruct editing
~/.local/bin/devbox-relink by hand, which the next upgrade deleted. A3 preserves operator state.

The installer runs the preservation logic as a constant-argv `/bin/sh -c "$preserve_install_blob"
_ "$helper"` per helper (constant argv so the lifecycle test's first-install==rerun invariant
holds). This test extracts that exact blob from the installer source and exercises its behavior
directly under /bin/sh against a fixture HOME -- no Docker needed, since the blob is pure POSIX sh
operating on $HOME/.local/bin and $HOME/.local/share.

Contract:
  - a DIFFERING on-box helper is backed up to <helper>.pre-upgrade.<utc>.bak before overwrite,
    with a machine-readable `PRESERVED <dst> <bak>` notice; the new version is then installed;
  - an IDENTICAL on-box helper is left untouched: no backup file, no PRESERVED notice;
  - devbox-relink in-file custom `relink` lines (operator lines not in the shipped file) are
    reported (`CUSTOM_RELINK_LINES` + one `CUSTOM_RELINK_LINE` each) and preserved in the backup,
    never auto-migrated into the drop-in dir;
  - a failed backup must never fall through to the overwrite (set -e).

devbox-relink.d/ creation at 0700 is asserted by the lifecycle test's exact-argv mkdir call; here
we focus on the blob's file-level behavior.
"""
from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (REPO / "scripts/install-devbox").read_text()

m = re.search(r"preserve_install_blob='(.*?)'\n", SOURCE, re.DOTALL)
assert m, "installer must define preserve_install_blob (A3)"
BLOB = m.group(1)


def run_blob(home: pathlib.Path, helper: str, src_text: str) -> subprocess.CompletedProcess[str]:
    """Run the exact installer blob under /bin/sh: `sh -c "$BLOB" _ <helper>`, with /tmp/<helper>
    seeded to src_text and HOME pointed at the fixture."""
    (pathlib.Path("/tmp") / helper).write_text(src_text)
    env = os.environ | {"HOME": str(home), "LC_ALL": "C"}
    return subprocess.run(["/bin/sh", "-c", BLOB, "_", helper, str(home / ".local/bin")], env=env, capture_output=True, text=True)


def fresh_home() -> pathlib.Path:
    home = pathlib.Path(tempfile.mkdtemp(prefix="install-preserve-"))
    (home / ".local/bin").mkdir(parents=True)
    return home


def backups(home: pathlib.Path, helper: str) -> list[pathlib.Path]:
    return sorted((home / ".local/bin").glob(f"{helper}.pre-upgrade.*.bak"))


# --- 1. Differing helper is backed up before overwrite, with a PRESERVED notice -----------------
home = fresh_home()
dst = home / ".local/bin/devbox-session"
dst.write_text("#!/usr/bin/env bash\n# OPERATOR-CUSTOMIZED old version\n")
dst.chmod(0o755)
new_src = "#!/usr/bin/env bash\n# shipped new version\n"
r = run_blob(home, "devbox-session", new_src)
assert r.returncode == 0, f"blob failed: {r.stderr}"
baks = backups(home, "devbox-session")
assert len(baks) == 1, f"expected exactly one backup, got {baks}"
assert "OPERATOR-CUSTOMIZED old version" in baks[0].read_text(), "backup must hold the operator's old file"
assert dst.read_text() == new_src, "new version must be installed after backup"
assert re.search(r"^PRESERVED \S+/devbox-session \S+/devbox-session\.pre-upgrade\.\S+\.bak$", r.stdout, re.MULTILINE), \
    f"machine-readable PRESERVED notice missing: {r.stdout!r}"
# backup filename timestamp shape: .pre-upgrade.<UTC compact>.bak
assert re.search(r"devbox-session\.pre-upgrade\.\d{8}T\d{6}Z\.bak$", str(baks[0])), f"bad backup name: {baks[0]}"

# --- 2. Identical helper: no backup, no notice, left untouched ----------------------------------
home = fresh_home()
dst = home / ".local/bin/devbox-turn"
same = "#!/usr/bin/env bash\n# identical\n"
dst.write_text(same)
dst.chmod(0o755)
r = run_blob(home, "devbox-turn", same)
assert r.returncode == 0, f"blob failed: {r.stderr}"
assert backups(home, "devbox-turn") == [], "an identical helper must NOT be backed up"
assert "PRESERVED" not in r.stdout, "no PRESERVED notice when unchanged"
assert dst.read_text() == same, "unchanged helper stays put"

# --- 3. First install (no prior file): install, no backup, no notice ----------------------------
home = fresh_home()
r = run_blob(home, "devbox", "#!/usr/bin/env bash\n# fresh\n")
assert r.returncode == 0, f"blob failed: {r.stderr}"
assert backups(home, "devbox") == [], "no backup on first install"
assert "PRESERVED" not in r.stdout, "no notice on first install"
assert (home / ".local/bin/devbox").read_text() == "#!/usr/bin/env bash\n# fresh\n"

# --- 4. devbox-relink in-file custom lines are reported, preserved, and NOT auto-migrated -------
home = fresh_home()
dst = home / ".local/bin/devbox-relink"
shipped_relink = (REPO / "scripts/devbox-relink").read_text()
# operator hand-edited their on-box copy with an extra relink line (the D1 scenario)
custom_line = 'relink "$HOME/.local/share/mytool-config" "$HOME/.config/mytool"'
operator_copy = shipped_relink + custom_line + "\n"
dst.write_text(operator_copy)
dst.chmod(0o755)
r = run_blob(home, "devbox-relink", shipped_relink)  # upgrade installs the shipped version
assert r.returncode == 0, f"blob failed: {r.stderr}"
baks = backups(home, "devbox-relink")
assert len(baks) == 1, f"expected one backup, got {baks}"
assert custom_line in baks[0].read_text(), "operator custom relink line must be preserved in the backup"
assert "CUSTOM_RELINK_LINES" in r.stdout, "custom in-file relink lines must be reported"
assert any(custom_line in line for line in r.stdout.splitlines() if line.startswith("CUSTOM_RELINK_LINE")), \
    f"the specific custom relink line must be reported: {r.stdout!r}"
assert "not auto-migrated" in r.stdout, "report must state the lines are not auto-migrated"
# NOT auto-migrated: the drop-in dir must not have been written by the installer blob
dropin = home / ".local/share/devbox-relink.d"
assert not dropin.exists() or not any(dropin.iterdir()), "custom lines must NOT be auto-written into the drop-in dir"
# the installed file is exactly the shipped version (custom line only in the backup)
assert dst.read_text() == shipped_relink, "installed devbox-relink must be the shipped version"

# --- 5. set -e: a failed backup must not fall through to the overwrite --------------------------
# Make the backup step fail by making ~/.local/bin unwritable after seeding a differing file, so
# `cp` to the .bak fails; the install must NOT happen (old file remains, no partial overwrite).
if os.geteuid() != 0:
    home = fresh_home()
    dst = home / ".local/bin/devbox-worktree"
    old = "#!/usr/bin/env bash\n# OLD must survive a failed backup\n"
    dst.write_text(old)
    dst.chmod(0o755)
    os.chmod(home / ".local/bin", 0o500)  # read+exec only: cp of new .bak into this dir fails
    try:
        r = run_blob(home, "devbox-worktree", "#!/usr/bin/env bash\n# new\n")
    finally:
        os.chmod(home / ".local/bin", 0o755)
    assert r.returncode != 0, "a failed backup must make the blob exit non-zero (set -e)"
    assert dst.read_text() == old, "old helper must survive when backup fails (no fall-through overwrite)"
else:
    print("install_preserve: skipping set -e backup-failure case as root (dir mode does not restrict root)")

print("install_preserve=PASS")
