#!/usr/bin/env python3
"""Part B contract: `verify --json` must verify the hands-off invariant, not just assert it.

Two new checks, both WARN-ONLY in this release (a warn must NOT clear ok, because AGENTS.md
step 8 gates installs on ok: true and we will not start blocking installs that passed yesterday):

  - relink.targets : every symlink devbox-relink would manage exists, is a symlink, and resolves.
                     A dangling/missing target -> status "warn" naming the offending path, ok stays.
  - daemon.<name>  : each daemon declared in ~/.local/share/devbox-daemons.d/*.conf is running.
                     Declared-but-down -> "warn". No daemons.d -> the check is SKIPPED (absent),
                     never failed.

No secret may appear in the JSON. Report stays schema-valid; ok aggregates as all(status != fail).

Driven like test-agent-harness-operations.py: copy the harness, point SAFE_PATH at a fake bin
with a fake docker whose probe outputs are fixtured per scenario.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_HARNESS = ROOT / "scripts/devbox-anywhere"

# The two probes are constant-argv container calls (like A3's install blob). The harness exposes
# them as module constants so this test pins the *real* probe strings rather than duplicating them.
HARNESS_TEXT = SOURCE_HARNESS.read_text()
import re as _re
_rt = _re.search(r'RELINK_TARGETS_PROBE = (r?""".*?"""|r?\'\'\'.*?\'\'\'|r?".*?"|r?\'.*?\')', HARNESS_TEXT, _re.DOTALL)
_dd = _re.search(r'DAEMON_DECLARED_PROBE = (r?""".*?"""|r?\'\'\'.*?\'\'\'|r?".*?"|r?\'.*?\')', HARNESS_TEXT, _re.DOTALL)
assert _rt, "harness must define RELINK_TARGETS_PROBE (Part B)"
assert _dd, "harness must define DAEMON_DECLARED_PROBE (Part B)"
RELINK_TARGETS_PROBE = eval(_rt.group(1))
DAEMON_DECLARED_PROBE = eval(_dd.group(1))


def build_harness(root: pathlib.Path, relink_probe_out: str, daemon_probe_out: str) -> pathlib.Path:
    """Copy the harness with SAFE_PATH pointed at a fake docker that returns healthy results for the
    existing checks and the given canned stdout for the two Part B probes."""
    os.umask(0o022)
    fake_bin = root / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    # The fake docker recognizes the existing healthy argv (as in the operations test) plus the two
    # Part B probe calls, matched by a sentinel substring in the /bin/sh -c script, returning the
    # per-scenario canned stdout.
    docker.write_text(
        "#!/usr/bin/python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        f"relink_out = {relink_probe_out!r}\n"
        f"daemon_out = {daemon_probe_out!r}\n"
        "if len(args) >= 11 and args[8] == '/bin/sh' and args[9] == '-c':\n"
        "    script = args[10]\n"
        "    if 'relink.targets probe' in script:\n"
        "        sys.stdout.write(relink_out); sys.exit(0)\n"
        "    if 'daemon.declared probe' in script:\n"
        "        sys.stdout.write(daemon_out); sys.exit(0)\n"
        "if args == ['--context','default','inspect','-f','{{.State.Running}}','devbox']:\n"
        "    print('true'); sys.exit(0)\n"
        "if args == ['--context','default','inspect','--format','{{json .NetworkSettings.Ports}}','devbox']:\n"
        "    import json\n"
        "    print(json.dumps({'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':'8080'}],'22/tcp':[{'HostIp':'127.0.0.1','HostPort':'2222'}]})); sys.exit(0)\n"
        "if args == ['--context','default','inspect','--format','{{json .Mounts}}','devbox']:\n"
        "    import json\n"
        "    print(json.dumps([\n"
        "        {'Type':'bind','Source':'/data/devbox/project','Destination':'/home/coder/project','RW':True},\n"
        "        {'Type':'bind','Source':'/data/devbox/dot-local','Destination':'/home/coder/.local','RW':True},\n"
        "        {'Type':'bind','Source':'/data/devbox/claude','Destination':'/home/coder/.claude','RW':True},\n"
        "        {'Type':'bind','Source':'/data/devbox/codex','Destination':'/home/coder/.codex','RW':True},\n"
        "        {'Type':'bind','Source':'/data/devbox/ssh','Destination':'/home/coder/.ssh','RW':True},\n"
        "    ])); sys.exit(0)\n"
        "if len(args) >= 2 and args[0] == '--context' and args[2] == 'exec':\n"
        "    sys.exit(0)\n"
        "sys.exit(64)\n"
    )
    docker.chmod(0o755)
    harness_copy = root / "devbox-anywhere"
    text = SOURCE_HARNESS.read_text()
    text = text.replace(
        'SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
        f'SAFE_PATH = "{fake_bin}:/usr/bin:/bin"',
    )
    text = text.replace('SOURCE_ROOT = pathlib.Path("/opt/devbox-anywhere")', f'SOURCE_ROOT = pathlib.Path("{ROOT}")')
    text = text.replace('STATE_DIR = pathlib.Path("/data/devbox/install")', f'STATE_DIR = pathlib.Path("{root / "install"}")')
    text = text.replace(
        'STATE_ANCESTRY = (pathlib.Path("/data"), pathlib.Path("/data/devbox"), STATE_DIR)',
        'STATE_ANCESTRY = (STATE_DIR,)',
    )
    text = text.replace("EXPECTED_STATE_OWNER = 0", f"EXPECTED_STATE_OWNER = {os.getuid()}")
    harness_copy.write_text(text)
    harness_copy.chmod(0o755)
    install = root / "install"
    install.mkdir()
    env_file = install / "compose.env"
    env_file.write_text(
        "DEVBOX_PASSWORD=TEST_SECRET_MUST_NOT_APPEAR\n"
        "DEVBOX_DATA_ROOT=/data/devbox\n"
        "DEVBOX_WEB_BIND=127.0.0.1\n"
        "DEVBOX_SSH_BIND=127.0.0.1\n"
    )
    env_file.chmod(0o600)
    return harness_copy


def run_verify(harness: pathlib.Path) -> dict:
    result = subprocess.run(["python3", str(harness), "verify", "--json"], capture_output=True, text=True)
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in result.stdout + result.stderr, "no secret may appear in verify --json"
    return json.loads(result.stdout)


def by_id(report: dict) -> dict:
    return {item["id"]: item for item in report["checks"]}


# --- schema: every check has id/status/summary and status is one of the three known values -------
with tempfile.TemporaryDirectory(prefix="verify-inv-schema-") as tmp:
    report = run_verify(build_harness(pathlib.Path(tmp), "", ""))
    for item in report["checks"]:
        assert set(item) >= {"id", "status", "summary"}, f"check missing keys: {item}"
        assert item["status"] in {"pass", "warn", "fail"}, f"unknown status: {item}"

# --- 1. healthy: relink.targets present and passing; no daemons.d -> no daemon checks; ok True ----
with tempfile.TemporaryDirectory(prefix="verify-inv-healthy-") as tmp:
    report = run_verify(build_harness(pathlib.Path(tmp), "", ""))
    checks = by_id(report)
    assert "relink.targets" in checks, "relink.targets check must exist"
    assert checks["relink.targets"]["status"] == "pass", f"healthy relink.targets must pass: {checks['relink.targets']}"
    assert not any(cid.startswith("daemon.") for cid in checks), "absent daemons.d must skip daemon checks, not emit them"
    assert report["ok"] is True, "healthy verify must be ok"

# --- 2. dangling link: relink.targets WARN naming the path, ok STILL True (warn does not clear ok) -
with tempfile.TemporaryDirectory(prefix="verify-inv-dangling-") as tmp:
    dangle = "DANGLING /home/coder/.hermes -> /home/coder/.local/share/hermes-home\n"
    report = run_verify(build_harness(pathlib.Path(tmp), dangle, ""))
    checks = by_id(report)
    assert checks["relink.targets"]["status"] == "warn", \
        f"a dangling relink target must be WARN, not fail and not pass: {checks['relink.targets']}"
    assert "/home/coder/.hermes" in checks["relink.targets"]["summary"], \
        "relink.targets warn must name the offending path"
    assert report["ok"] is True, "a warn-only relink.targets must NOT clear ok (AGENTS.md step 8 gate)"

# --- 3. declared daemon running -> daemon.<name> pass; ok True -----------------------------------
with tempfile.TemporaryDirectory(prefix="verify-inv-daemon-up-") as tmp:
    report = run_verify(build_harness(pathlib.Path(tmp), "", "gateway\trunning\n"))
    checks = by_id(report)
    assert "daemon.gateway" in checks, "a declared daemon must produce daemon.<name>"
    assert checks["daemon.gateway"]["status"] == "pass", f"a running declared daemon must pass: {checks['daemon.gateway']}"
    assert report["ok"] is True

# --- 4. declared daemon down -> daemon.<name> WARN, ok STILL True --------------------------------
with tempfile.TemporaryDirectory(prefix="verify-inv-daemon-down-") as tmp:
    report = run_verify(build_harness(pathlib.Path(tmp), "", "gateway\tstopped\n"))
    checks = by_id(report)
    assert checks["daemon.gateway"]["status"] == "warn", \
        f"a declared-but-stopped daemon must be WARN, not fail: {checks['daemon.gateway']}"
    assert report["ok"] is True, "a warn-only daemon check must NOT clear ok"

print("verify_invariants=PASS")
