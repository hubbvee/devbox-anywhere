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
SHA = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
assert len(SHA) == 40

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
assert "instance" not in plan_report and plan_report["data_root"] == "/data/devbox", "default_report_unchanged"
assert "--instance" not in plan_report["install_command"], "default_report_unchanged"

public_plan = run("plan", "--json", "--approved-commit", SHA, "--expose-ssh")
assert public_plan.returncode == 0, public_plan.stderr
public_report = json.loads(public_plan.stdout)
assert public_report["network"]["ssh_bind"] == "0.0.0.0"
assert "firewall/public SSH exposure" in public_report["approval_required"]
assert "--expose-ssh" in public_report["install_command"]

with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    # Hermeticity: pin the fixture umask so fabricated state dirs get host-independent
    # modes. Without this, a host umask of 0002 makes the install/ dir group-writable
    # (0775) and the harness correctly rejects it, failing this test only on such hosts.
    os.umask(0o022)
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
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-daemon"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-relink"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-session"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-turn"],
    ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/test", "-x", "/home/coder/.local/bin/devbox-worktree"],
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
        "state.file", "container.running", "helper.devbox", "helper.devbox-daemon", "helper.devbox-relink",
        "helper.devbox-session", "helper.devbox-turn", "helper.devbox-worktree",
        "service.http", "service.ssh", "network.bindings", "storage.mounts",
    }, "verify_check_ids"
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in verified.stdout + verified.stderr
    assert "instance" not in verify_report, "default_report_unchanged"
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
    assert "instance" not in diagnosis, "default_report_unchanged"
    assert f"compose --env-file {root / 'install' / 'compose.env'} -f" in serialized, "default_report_unchanged"
    HARNESS = SOURCE_HARNESS

# --- Named instances (--instance NAME) ------------------------------------------------------------
# Invalid names are refused with exit 2 on every command, and never echoed back.
for command_args in (["preflight"], ["verify"], ["diagnose"], ["plan", "--approved-commit", SHA, "--web-port", "9080", "--ssh-port", "9022"]):
    for bad_name in ("MyApp", "my-app", "../etc", "my/app", "my.app", "a" * 16, "", "browser", "default", "devbox", "1app", "app\n"):
        rejected_name = run(*command_args, "--json", "--instance", bad_name)
        assert rejected_name.returncode == 2, f"harness_instance_validation:{command_args[0]}:{bad_name!r}"
        rejected_report = json.loads(rejected_name.stdout)
        assert rejected_report["ok"] is False and rejected_report["command"] == command_args[0], "harness_instance_validation"
        if bad_name:
            assert bad_name not in rejected_report["error"]["message"], "harness_instance_redaction"

# plan --instance: the install command carries the instance and its ports; nothing else changes.
instance_plan = run("plan", "--json", "--approved-commit", SHA, "--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022")
assert instance_plan.returncode == 0, "harness_instance_plan: " + instance_plan.stdout + instance_plan.stderr
instance_plan_report = json.loads(instance_plan.stdout)
assert instance_plan_report["data_root"] == "/data/devbox-myapp", "harness_instance_plan"
assert instance_plan_report["network"] == {"web_bind": "127.0.0.1", "ssh_bind": "127.0.0.1"}, "harness_instance_plan"
assert instance_plan_report["approval_required"] == ["sudo", "container build/start"], "harness_instance_plan"
assert instance_plan_report["install_command"] == (
    f"sudo /opt/devbox-anywhere/scripts/install-devbox --yes --approved-commit {SHA}"
    " --instance myapp --web-port 9080 --ssh-port 9022"
), "harness_instance_plan"
assert instance_plan_report["instance"] == {
    "name": "myapp", "project": "devbox-myapp", "container": "devbox-myapp",
    "data_root": "/data/devbox-myapp", "web_port": "9080", "ssh_port": "9022",
}, "harness_instance_plan"
assert instance_plan_report["schema_version"] == 2, "harness_instance_schema"
browser_instance_plan = run(
    "plan", "--json", "--approved-commit", SHA, "--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022",
    "--with-browser", "--browser-port", "9081", "--expose-ssh",
)
assert browser_instance_plan.returncode == 0, browser_instance_plan.stdout + browser_instance_plan.stderr
browser_instance_report = json.loads(browser_instance_plan.stdout)
assert browser_instance_report["network"] == {"web_bind": "127.0.0.1", "ssh_bind": "0.0.0.0", "browser_bind": "127.0.0.1:9081"}, "harness_instance_plan_browser"
assert browser_instance_report["install_command"].endswith(
    " --expose-ssh --with-browser --instance myapp --web-port 9080 --ssh-port 9022 --browser-port 9081"
), "harness_instance_plan_browser"
assert browser_instance_report["instance"]["browser_port"] == "9081", "harness_instance_plan_browser"
text_plan = run("plan", "--approved-commit", SHA, "--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022")
assert "Web: 127.0.0.1:9080; SSH: 127.0.0.1:9022" in text_plan.stdout, "harness_instance_plan_text"
for bad_ports in (
    ["--web-port", "9080", "--ssh-port", "9022"],
    ["--instance", "myapp"],
    ["--instance", "myapp", "--web-port", "9080"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9080"],
    ["--instance", "myapp", "--web-port", "8080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "2222"],
    ["--instance", "myapp", "--web-port", "8081", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "1023", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "65536", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "09080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", " 9080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--with-browser"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--browser-port", "9081"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--with-browser", "--browser-port", "9022"],
):
    refused = run("plan", "--json", "--approved-commit", SHA, *bad_ports)
    assert refused.returncode == 2, f"harness_plan_port_validation:{bad_ports!r}"
    assert json.loads(refused.stdout)["ok"] is False, "harness_plan_port_validation"

INSTANCE_MOUNTS = [
    {"Type": "bind", "Source": f"/data/devbox-myapp/{leaf}", "Destination": destination, "RW": True}
    for leaf, destination in (
        ("project", "/home/coder/project"), ("dot-local", "/home/coder/.local"), ("claude", "/home/coder/.claude"),
        ("codex", "/home/coder/.codex"), ("ssh", "/home/coder/.ssh"),
    )
]
INSTANCE_ENV = (
    "DEVBOX_PASSWORD=TEST_SECRET_MUST_NOT_APPEAR\n"
    "DEVBOX_DATA_ROOT=/data/devbox-myapp\n"
    "DEVBOX_WEB_BIND=127.0.0.1\n"
    "DEVBOX_SSH_BIND=127.0.0.1\n"
    "DEVBOX_BROWSER_BIND=127.0.0.1\n"
    "DEVBOX_BROWSER_PASSWORD=TEST_SECRET_MUST_NOT_APPEAR\n"
    "DEVBOX_INSTANCE=myapp\n"
    "DEVBOX_PROJECT=devbox-myapp\n"
    "DEVBOX_CONTAINER=devbox-myapp\n"
    "DEVBOX_WEB_PORT=9080\n"
    "DEVBOX_SSH_PORT=9022\n"
)


def instance_docker(path: pathlib.Path, log: pathlib.Path, project: str = "devbox-myapp", web_port: str = "9080") -> None:
    """Fake docker that answers ONLY the exact instance argv; anything else (e.g. the default
    container name) exits 64 and turns the corresponding check red."""
    exec_prefix = ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp"]
    passing = [exec_prefix + ["/usr/bin/test", "-x", f"/home/coder/.local/bin/{helper}"] for helper in (
        "devbox", "devbox-daemon", "devbox-relink", "devbox-session", "devbox-turn", "devbox-worktree")]
    passing += [
        exec_prefix + ["/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"],
        exec_prefix + ["/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"],
    ]
    path.write_text(f'''#!/usr/bin/python3
import json, pathlib, sys
args = sys.argv[1:]
with pathlib.Path({str(log)!r}).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
outputs = {{
    ("--context", "default", "inspect", "--format", '{{{{index .Config.Labels "com.docker.compose.project"}}}}', "devbox-myapp"): {project!r},
    ("--context", "default", "inspect", "-f", "{{{{.State.Running}}}}", "devbox-myapp"): "true",
    ("--context", "default", "inspect", "--format", "{{{{json .NetworkSettings.Ports}}}}", "devbox-myapp"): json.dumps(
        {{"8080/tcp": [{{"HostIp": "127.0.0.1", "HostPort": {web_port!r}}}], "22/tcp": [{{"HostIp": "127.0.0.1", "HostPort": "9022"}}]}}),
    ("--context", "default", "inspect", "--format", "{{{{json .Mounts}}}}", "devbox-myapp"): json.dumps({INSTANCE_MOUNTS!r}),
}}
if tuple(args) in outputs:
    print(outputs[tuple(args)])
elif args in {passing!r}:
    pass
elif len(args) > 9 and args[:8] == {exec_prefix!r} and args[8:10] == ["/bin/sh", "-c"]:
    pass
else:
    raise SystemExit(64)
''')
    path.chmod(0o755)


with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    # Process umask was pinned to 0o022 by the default block above.
    fake_bin = root / "bin"
    fake_bin.mkdir()
    docker_log = root / "docker-calls.jsonl"
    docker = fake_bin / "docker"
    instance_docker(docker, docker_log)
    harness_text = SOURCE_HARNESS.read_text()
    for old, new in (
        ('SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"', f'SAFE_PATH = "{fake_bin}:/usr/bin:/bin"'),
        ('SOURCE_ROOT = pathlib.Path("/opt/devbox-anywhere")', f'SOURCE_ROOT = pathlib.Path("{ROOT}")'),
        ('STATE_DIR = pathlib.Path("/data/devbox/install")', f'STATE_DIR = pathlib.Path("{root / "devbox" / "install"}")'),
        ('STATE_ANCESTRY = (pathlib.Path("/data"), pathlib.Path("/data/devbox"), STATE_DIR)', 'STATE_ANCESTRY = (STATE_DIR,)'),
        ('INSTANCE_PARENT = pathlib.Path("/data")', f'INSTANCE_PARENT = pathlib.Path("{root}")'),
        ("EXPECTED_STATE_OWNER = 0", f"EXPECTED_STATE_OWNER = {os.getuid()}"),
    ):
        assert harness_text.count(old) == 1, f"fixture_patch:{old}"
        harness_text = harness_text.replace(old, new)
    harness_copy = root / "devbox-anywhere"
    harness_copy.write_text(harness_text)
    harness_copy.chmod(0o755)
    HARNESS = harness_copy
    state = root / "devbox-myapp" / "install"
    state.mkdir(parents=True)
    env_file = state / "compose.env"
    env_file.write_text(INSTANCE_ENV)
    env_file.chmod(0o600)

    def checks_of(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
        return {item["id"]: item["status"] for item in json.loads(result.stdout)["checks"]}

    instance_verified = run("verify", "--json", "--instance", "myapp")
    assert instance_verified.returncode == 0, "harness_instance_runtime_argv: " + instance_verified.stdout + instance_verified.stderr
    instance_report = json.loads(instance_verified.stdout)
    assert {item["id"] for item in instance_report["checks"] if item["status"] == "pass"} == {
        "state.file", "container.project", "container.running", "helper.devbox", "helper.devbox-daemon",
        "helper.devbox-relink", "helper.devbox-session", "helper.devbox-turn", "helper.devbox-worktree",
        "service.http", "service.ssh", "network.bindings", "storage.mounts", "relink.targets",
    }, "harness_instance_check_ids"
    assert instance_report["instance"] == {
        "name": "myapp", "project": "devbox-myapp", "container": "devbox-myapp",
        "data_root": "/data/devbox-myapp", "web_port": "9080", "ssh_port": "9022",
    }, "harness_instance_report"
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in instance_verified.stdout + instance_verified.stderr
    instance_calls = [json.loads(line) for line in docker_log.read_text().splitlines()]
    assert instance_calls and all("devbox" not in call for call in instance_calls), "harness_instance_default_container"
    assert ["--context", "default", "exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"] in instance_calls, "harness_instance_runtime_argv"

    # Default verify in the same harness never reads the instance's state or container.
    default_from_instance_box = run("verify", "--json")
    assert default_from_instance_box.returncode == 1, "harness_instance_isolation"
    default_checks = checks_of(default_from_instance_box)
    assert default_checks["state.file"] == "fail" and default_checks["container.running"] == "fail", "harness_instance_isolation"

    # A container that reuses the name but belongs to another project is reported, never trusted.
    instance_docker(docker, docker_log, project="stack")
    hijacked = run("verify", "--json", "--instance", "myapp")
    assert hijacked.returncode == 1 and checks_of(hijacked)["container.project"] == "fail", "harness_instance_project_label"
    instance_docker(docker, docker_log, web_port="8080")
    wrong_port = run("verify", "--json", "--instance", "myapp")
    assert wrong_port.returncode == 1 and checks_of(wrong_port)["network.bindings"] == "fail", "harness_instance_port_binding"
    instance_docker(docker, docker_log)

    # The instance state file is validated against the name it was derived from.
    for old, new in (
        ("DEVBOX_INSTANCE=myapp", "DEVBOX_INSTANCE=other"),
        ("DEVBOX_PROJECT=devbox-myapp", "DEVBOX_PROJECT=stack"),
        ("DEVBOX_CONTAINER=devbox-myapp", "DEVBOX_CONTAINER=devbox"),
        ("DEVBOX_DATA_ROOT=/data/devbox-myapp", "DEVBOX_DATA_ROOT=/data/devbox"),
        ("DEVBOX_WEB_PORT=9080", "DEVBOX_WEB_PORT=8080"),
        ("DEVBOX_SSH_PORT=9022", "DEVBOX_SSH_PORT=9080"),
        ("DEVBOX_SSH_PORT=9022", "DEVBOX_SSH_PORT=022"),
        ("DEVBOX_WEB_PORT=9080\n", ""),
        ("DEVBOX_SSH_PORT=9022\n", "DEVBOX_SSH_PORT=9022\nDEVBOX_SSH_PORT=9023\n"),
    ):
        env_file.write_text(INSTANCE_ENV.replace(old, new, 1))
        bad_state = run("verify", "--json", "--instance", "myapp")
        assert bad_state.returncode == 1 and checks_of(bad_state)["state.file"] == "fail", f"harness_instance_state:{new!r}"
    env_file.write_text(INSTANCE_ENV)

    preflight_report = json.loads(run("preflight", "--json", "--instance", "myapp").stdout)
    assert preflight_report["instance"] == {
        "name": "myapp", "project": "devbox-myapp", "container": "devbox-myapp", "data_root": "/data/devbox-myapp",
    }, "harness_instance_preflight"

    docker.write_text("#!/bin/sh\nexit 1\n")
    instance_diagnosis = run("diagnose", "--json", "--instance", "myapp")
    assert instance_diagnosis.returncode == 1
    instance_diagnosis_report = json.loads(instance_diagnosis.stdout)
    recovery = instance_diagnosis_report["recovery_commands"]
    assert recovery[0].endswith("docker --context default logs devbox-myapp"), "harness_instance_recovery"
    assert f"docker --context default compose -p devbox-myapp --env-file {env_file} -f " in recovery[1], "harness_instance_recovery"
    assert recovery[2] == "./scripts/devbox-anywhere verify --json --instance myapp", "harness_instance_recovery"
    assert instance_diagnosis_report["instance"]["name"] == "myapp", "harness_instance_recovery"
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in instance_diagnosis.stdout, "harness_instance_recovery"
    HARNESS = SOURCE_HARNESS

print("agent_harness_operations=PASS")
