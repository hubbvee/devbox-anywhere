#!/usr/bin/env python3
"""Contract: the shipped sshd config must exempt loopback from OpenSSH PerSourcePenalties.

verify (scripts/devbox-anywhere) and the installer readiness probe (scripts/install-devbox)
both check SSH with an unauthenticated `ssh-keyscan ... 127.0.0.1` from inside the container.
OpenSSH 10's default PerSourcePenalties charges every unauthenticated connection a `noauth`
penalty; after a run of quick keyscans sshd refuses 127.0.0.1 and `service.ssh` -> fail ->
ok:false (a hard check). Any agent/operator that re-runs verify in a loop (retry-until-green)
locks itself out with a false ok:false that heals by itself minutes later.

The fix exempts loopback: `PerSourcePenaltyExemptList 127.0.0.1,::1`. Loopback sources inside
the container are local processes only; external clients arrive via the bridge, so brute-force
protection is unchanged.

The penalty is sshd runtime behavior, so the only fully honest RED is a container-level hammer
(the operator smoke runs verify 25x as that gate). This suite test pins the static invariant:
the shipped config exempts EVERY loopback address the probes actually connect from, so the
exemption cannot silently drift away from the probe.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SSHD_CONF = ROOT / "stack/config/devbox-sshd.conf"
VERIFY = ROOT / "scripts/devbox-anywhere"
INSTALLER = ROOT / "scripts/install-devbox"

assert SSHD_CONF.is_file(), "stack/config/devbox-sshd.conf must exist"

conf = SSHD_CONF.read_text()

# --- 1. the exempt directive exists and parses -------------------------------------------------
# Match an active (non-commented) PerSourcePenaltyExemptList line and capture its value.
exempt = None
for line in conf.splitlines():
    s = line.strip()
    if s.startswith("#") or not s:
        continue
    m = re.match(r"(?i)^PerSourcePenaltyExemptList\s+(.+?)\s*$", s)
    if m:
        exempt = m.group(1)
        break
assert exempt is not None, \
    "sshd config must set PerSourcePenaltyExemptList to exempt loopback from penalties"

# Split on whitespace and/or commas, per sshd_config list syntax.
exempt_entries = {e for e in re.split(r"[\s,]+", exempt) if e}

# --- 2. every loopback address the probes connect from is exempt -------------------------------
# Derive the probe targets from the real scripts so this test cannot drift from the probe.
PROBE_HOSTS = set()
for script in (VERIFY, INSTALLER):
    for m in re.finditer(r"ssh-keyscan[^\n]*?(-p\s*\d+\s+)?(\d{1,3}(?:\.\d{1,3}){3}|::1|localhost)", script.read_text()):
        PROBE_HOSTS.add(m.group(2))
assert "127.0.0.1" in PROBE_HOSTS, \
    f"expected the keyscan probes to target 127.0.0.1 (derived set: {PROBE_HOSTS})"

for host in PROBE_HOSTS:
    assert host in exempt_entries, \
        f"probe host {host!r} must be in PerSourcePenaltyExemptList {sorted(exempt_entries)}"

# --- 3. IPv6 loopback is also exempt (defensive: localhost may resolve to ::1) ------------------
assert "::1" in exempt_entries, \
    f"IPv6 loopback ::1 must be exempt too: {sorted(exempt_entries)}"

print("ssh_penalty_exempt=PASS")
