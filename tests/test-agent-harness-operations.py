#!/usr/bin/env python3
"""Behavioral contract for plan, verify, and diagnose harness commands."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_HARNESS = ROOT / "scripts" / "devbox-anywhere"
HARNESS = SOURCE_HARNESS
SHA = "c2c1caeebfc55047233cbdeae11670e07cbede75"

def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(HARNESS), *args], cwd=ROOT, env=env, capture_output=True, text=True)


bad_sha = run("plan", "--json", "--approved-commit", "main")
assert bad_sha.returncode == 2
bad_sha_report = json.loads(bad_sha.stdout)
assert bad_sha_report["ok"] is False
assert "40-character" in bad_sha_report["error"]["message"]

missing_sha = run("plan", "--json", "--approved-commit", "0" * 40)
assert missing_sha.returncode == 1
missing_report = json.loads(missing_sha.stdout)
assert missing_report["ok"] is False
assert "not present" in missing_report["error"]["message"]

plan = run("plan", "--json", "--approved-commit", SHA)
assert plan.returncode == 0, plan.stderr
plan_report = json.loads(plan.stdout)
assert plan_report["ok"] is True
assert plan_report["mutates"] is False
assert plan_report["approved_commit"] == SHA
assert plan_report["network"] == {"web_bind": "127.0.0.1", "ssh_bind": "127.0.0.1"}
assert plan_report["approval_required"] == ["sudo", "container build/start"]
assert plan_report["install_command"].startswith("sudo /opt/devbox-anywhere/scripts/install-devbox ")
assert "--expose-ssh" not in plan_report["install_command"]

public_plan = run("plan", "--json", "--approved-commit", SHA, "--expose-ssh")
assert public_plan.returncode == 0, public_plan.stderr
public_report = json.loads(public_plan.stdout)
assert public_report["network"]["ssh_bind"] == "0.0.0.0"
assert "firewall/public SSH exposure" in public_report["approval_required"]
assert "--expose-ssh" in public_report["install_command"]

with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    fake_bin = root / "bin"
    fake_bin.mkdir()
    docker_log = root / "docker-calls.jsonl"
    docker = fake_bin / "docker"
    docker.write_text(f'''#!/usr/bin/python3
import json, os, pathlib, sys
args = sys.argv[1:]
with pathlib.Path({str(docker_log)!r}).open("a") as stream:
    stream.write(json.dumps({{"args": args, "docker_config": os.environ.get("DOCKER_CONFIG")}}) + "\\n")
if args == ["--context", "default", "inspect", "-f", "{{{{.State.Running}}}}", "devbox"]:
    print("true")
elif args == ["--context", "default", "inspect", "--format", "{{{{json .NetworkSettings.Ports}}}}", "devbox"]:
    print(json.dumps({{"8080/tcp": [{{"HostIp": "127.0.0.1", "HostPort": "8080"}}], "22/tcp": [{{"HostIp": "127.0.0.1", "HostPort": "2222"}}]}}))
elif args == ["--context", "default", "inspect", "--format", "{{{{json .Mounts}}}}", "devbox"]:
    print(json.dumps([
        {{"Type": "bind", "Source": "/data/devbox/project", "Destination": "/home/coder/project", "RW": True}},
        {{"Type": "bind", "Source": "/data/devbox/dot-local", "Destination": "/home/coder/.local", "RW": True}},
        {{"Type": "bind", "Source": "/data/devbox/claude", "Destination": "/home/coder/.claude", "RW": True}},
        {{"Type": "bind", "Source": "/data/devbox/codex", "Destination": "/home/coder/.codex", "RW": True}},
        {{"Type": "bind", "Source": "/data/devbox/ssh", "Destination": "/home/coder/.ssh", "RW": True}},
    ]))
elif args in [
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-relink"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"],
]:
    pass
else:
    raise SystemExit(64)
''')
    docker.chmod(0o755)
    harness_copy = root / "devbox-anywhere"
    harness_text = SOURCE_HARNESS.read_text()
    harness_text = harness_text.replace(
        'SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
        f'SAFE_PATH = "{fake_bin}:/usr/bin:/bin"',
    )
    harness_text = harness_text.replace(
        'SOURCE_ROOT = pathlib.Path("/opt/devbox-anywhere")',
        f'SOURCE_ROOT = pathlib.Path("{ROOT}")',
    )
    harness_text = harness_text.replace(
        'STATE_DIR = pathlib.Path("/data/devbox/install")',
        f'STATE_DIR = pathlib.Path("{root / "install"}")',
    )
    harness_text = harness_text.replace(
        'STATE_ANCESTRY = (pathlib.Path("/data"), pathlib.Path("/data/devbox"), STATE_DIR)',
        'STATE_ANCESTRY = (STATE_DIR,)',
    )
    harness_text = harness_text.replace("EXPECTED_STATE_OWNER = 0", f"EXPECTED_STATE_OWNER = {os.getuid()}")
    harness_copy.write_text(harness_text)
    harness_copy.chmod(0o755)
    HARNESS = harness_copy
    env = os.environ.copy()
    (root / "install").mkdir()
    env_file = root / "install" / "compose.env"
    env_file.write_text(
        "DEVBOX_PASSWORD=TEST_SECRET_MUST_NOT_APPEAR\n"
        "DEVBOX_DATA_ROOT=/data/devbox\n"
        "DEVBOX_WEB_BIND=127.0.0.1\n"
        "DEVBOX_SSH_BIND=127.0.0.1\n"
    )
    env_file.chmod(0o600)

    verified = run("verify", "--json", env=env)
    assert verified.returncode == 0, "runtime_exact_argv: " + verified.stderr
    verify_report = json.loads(verified.stdout)
    assert verify_report["ok"] is True
    ids = {item["id"] for item in verify_report["checks"] if item["status"] == "pass"}
    assert ids == {
        "state.file", "container.running", "helper.devbox", "helper.devbox-relink",
        "service.http", "service.ssh", "network.bindings", "storage.mounts",
    }
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in verified.stdout + verified.stderr
    calls = [json.loads(line) for line in docker_log.read_text().splitlines()]
    assert all(call["args"][:2] == ["--context", "default"] for call in calls)
    assert all(call["docker_config"] == "/nonexistent/devbox-anywhere-docker-config" for call in calls), "runtime_docker_config"
    argv = [call["args"] for call in calls]
    assert ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"] in argv, "runtime_http_probe"
    assert ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"] in argv, "runtime_ssh_probe"

    env["DOCKER_HOST"] = "tcp://attacker.invalid:2375"
    poisoned = run("verify", "--json", env=env)
    assert poisoned.returncode == 0, poisoned.stderr
    assert json.loads(poisoned.stdout)["ok"] is True
    env.pop("DOCKER_HOST")

    env_file.chmod(0o644)
    unsafe_state = run("verify", "--json", env=env)
    assert unsafe_state.returncode == 1
    unsafe_report = json.loads(unsafe_state.stdout)
    assert {item["id"]: item["status"] for item in unsafe_report["checks"]}["state.file"] == "fail"
    assert unsafe_report["network"] == {"web_bind": "unknown", "ssh_bind": "unknown"}
    env_file.chmod(0o600)

    (root / "install").chmod(0o777)
    unsafe_ancestry = run("verify", "--json", env=env)
    assert unsafe_ancestry.returncode == 1
    assert {item["id"]: item["status"] for item in json.loads(unsafe_ancestry.stdout)["checks"]}["state.file"] == "fail"
    (root / "install").chmod(0o700)

    safe_content = env_file.read_text()
    env_file.write_text(safe_content.replace("DEVBOX_WEB_BIND=127.0.0.1", "DEVBOX_WEB_BIND=0.0.0.0"))
    unsafe_value = run("verify", "--json", env=env)
    assert unsafe_value.returncode == 1
    assert {item["id"]: item["status"] for item in json.loads(unsafe_value.stdout)["checks"]}["state.file"] == "fail"
    env_file.write_text(safe_content + "DEVBOX_WEB_BIND=127.0.0.1\n")
    duplicate_value = run("verify", "--json", env=env)
    assert duplicate_value.returncode == 1
    env_file.write_text(safe_content)

    docker.write_text("""#!/bin/sh
case "$*" in
  *"inspect -f"*) printf 'false\\n'; exit 0 ;;
  *) exit 0 ;;
esac
""")
    false_state = run("verify", "--json", env=env)
    assert false_state.returncode == 1
    false_report = json.loads(false_state.stdout)
    assert {item["id"]: item["status"] for item in false_report["checks"]}["container.running"] == "fail"

    docker.write_text("""#!/bin/sh
case "$*" in
  *"inspect -f"*) printf 'true\\n'; exit 0 ;;
  *"inspect --format"*) printf '{"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8080"}],"22/tcp":[{"HostIp":"127.0.0.1","HostPort":"2222"}]}\\n'; exit 0 ;;
  *) exit 0 ;;
esac
""")
    unsafe_bind = run("verify", "--json", env=env)
    assert unsafe_bind.returncode == 1
    unsafe_bind_report = json.loads(unsafe_bind.stdout)
    assert {item["id"]: item["status"] for item in unsafe_bind_report["checks"]}["network.bindings"] == "fail"

    docker.write_text("""#!/bin/sh
case "$*" in
  *"inspect -f"*) printf 'true\\n'; exit 0 ;;
  *"inspect --format"*) printf '{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"8080"}],"22/tcp":[{"HostIp":"127.0.0.1","HostPort":"2222"}]}\\n'; exit 0 ;;
  *".Mounts"*) printf '[{"Type":"bind","Source":"/etc","Destination":"/home/coder/project","RW":true}]\\n'; exit 0 ;;
  *"test -x"*|*"wget -q --spider"*|*"ssh-keyscan"*) exit 0 ;;
  *) exit 64 ;;
esac
""")
    unsafe_mount = run("verify", "--json", env=env)
    assert unsafe_mount.returncode == 1
    unsafe_mount_report = json.loads(unsafe_mount.stdout)
    assert {item["id"]: item["status"] for item in unsafe_mount_report["checks"]}["storage.mounts"] == "fail"

    docker.write_text("#!/bin/sh\nexit 1\n")
    failed = run("diagnose", "--json", env=env)
    assert failed.returncode == 1
    diagnosis = json.loads(failed.stdout)
    assert diagnosis["ok"] is False
    assert diagnosis["recovery_commands"]
    serialized = json.dumps(diagnosis)
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in serialized
    assert "env -i PATH=" in serialized
    assert "docker --context default logs devbox" in serialized
    assert "DOCKER_CONFIG=/nonexistent/devbox-anywhere-docker-config" in serialized
    assert "DEVBOX_PASSWORD=" not in serialized
    HARNESS = SOURCE_HARNESS

print("agent_harness_operations=PASS")
