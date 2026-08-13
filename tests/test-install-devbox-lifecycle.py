#!/usr/bin/env python3
"""Disposable lifecycle tests for scripts/install-devbox without Docker or root writes."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (REPO / "scripts/install-devbox").read_text()
GIT_ENV = os.environ.copy()
for key in tuple(GIT_ENV):
    if key.startswith("GIT_"):
        GIT_ENV.pop(key)


def prepare(mode: str) -> tuple[pathlib.Path, dict[str, str], pathlib.Path, pathlib.Path, str]:
    root = pathlib.Path(tempfile.mkdtemp(prefix="install-devbox-test-"))
    fixture = root / "repo"
    shutil.copytree(REPO / "scripts", fixture / "scripts")
    shutil.copytree(REPO / "stack", fixture / "stack")
    data = root / "data" / "devbox"
    installer = fixture / "scripts/install-devbox"
    text = installer.read_text()
    text = text.replace("DATA_ROOT=/data/devbox", f"DATA_ROOT={data}")
    text = text.replace(
        'if ((EUID != 0)); then die "run this installer with sudo so it can prepare $DATA_ROOT"; fi',
        ': # test-only neutralized EUID guard',
    )
    text = text.replace("[[ $REPO_ROOT == /opt/devbox-anywhere ]]", f"[[ $REPO_ROOT == {fixture} ]]")
    text = text.replace("[[ ! -L /opt && $(stat -c %u /opt) == 0 ]]", f"[[ ! -L {root} && $(stat -c %u {root}) == 0 ]]")
    text = text.replace("stat -c %a /opt", f"stat -c %a {root}")
    text = text.replace("[[ ! -L /data ]]", f"[[ ! -L {data.parent} ]]")
    text = text.replace("for attempt in $(seq 1 30); do", "for attempt in $(seq 1 2); do")
    text = text.replace("[[ $attempt -lt 30 ]]", "[[ $attempt -lt 2 ]]")
    text = text.replace("sleep 2", ": # test-only no sleep")
    text = text.replace("install -d -o 0 -g 0 -m 0755 /data", f'install -d -o 0 -g 0 -m 0755 "{data.parent}"')
    text = text.replace("stat -c %u /data", f'stat -c %u "{data.parent}"')
    text = text.replace("stat -c %a /data", f'stat -c %a "{data.parent}"')
    text = text.replace('die "/data must', f'die "{data.parent} must')
    installer.write_text(text)
    installer.chmod(0o755)

    bindir = root / "bin"
    bindir.mkdir()
    text = text.replace(
        "SAFE_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        f"SAFE_PATH={bindir}:/usr/bin:/bin",
    )
    installer.write_text(text)
    log = root / "docker.log"
    (bindir / "uname").write_text("#!/bin/sh\necho Linux\n")
    (bindir / "openssl").write_text(
        "#!/bin/sh\nprintf %s TEST_GENERATED_PASSWORD_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n"
    )
    env_file = data / "install/compose.env"
    compose_file = fixture / "stack/docker-compose.yml"
    docker = f'''#!/usr/bin/python3
import json, os, pathlib, sys
args = sys.argv[1:]
record = {{"args": args, "docker_config": os.environ.get("DOCKER_CONFIG"),
          "poison_root": os.environ.get("DEVBOX_DATA_ROOT"),
          "poison_web": os.environ.get("DEVBOX_WEB_BIND"),
          "poison_password": os.environ.get("DEVBOX_PASSWORD")}}
with pathlib.Path({str(log)!r}).open("a") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\\n")
prefix = ["--context", "default"]
compose = prefix + ["compose", "--env-file", {str(env_file)!r}, "-f", {str(compose_file)!r}]
known = {{
    tuple(prefix + ["compose", "version"]): ("compose-version-fail", 31, None),
    tuple(prefix + ["info"]): ("daemon-fail", 32, None),
    tuple(compose + ["build", "--pull=false"]): ("build-fail", 41, None),
    tuple(compose + ["up", "-d"]): ("up-fail", 42, None),
    tuple(prefix + ["cp", {str(fixture / 'scripts/devbox')!r}, "devbox:/tmp/devbox"]): ("helper-devbox-fail", 43, None),
    tuple(prefix + ["cp", {str(fixture / 'scripts/devbox-relink')!r}, "devbox:/tmp/devbox-relink"]): ("helper-relink-fail", 44, None),
    tuple(prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/install", "-m", "0755", "/tmp/devbox", "/home/coder/.local/bin/devbox"]): ("install-devbox-fail", 45, None),
    tuple(prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/install", "-m", "0755", "/tmp/devbox-relink", "/home/coder/.local/bin/devbox-relink"]): ("install-relink-fail", 46, None),
    tuple(prefix + ["exec", "--env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "devbox", "/usr/bin/rm", "-f", "/tmp/devbox"]): ("remove-fail", 47, None),
    tuple(prefix + ["exec", "--env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "devbox", "/usr/bin/rm", "-f", "/tmp/devbox-relink"]): ("remove-fail", 47, None),
    tuple(prefix + ["inspect", "-f", "{{{{.State.Running}}}}", "devbox"]): ("inspect-fail", 1, "true"),
    tuple(prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/bin/sh", "-c", '/usr/bin/tmux -V >/dev/null && /usr/bin/test -x "$HOME/.local/bin/devbox" && /usr/bin/test -x "$HOME/.local/bin/devbox-relink"']): ("readiness-fail", 48, None),
    tuple(prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"]): ("http-fail", 45, None),
    tuple(prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"]): ("ssh-fail", 46, None),
}}
rule = known.get(tuple(args))
if rule is None:
    print("INVARIANT_DOCKER_EXACT_ARGV", file=sys.stderr)
    raise SystemExit(64)
fail_mode, fail_code, output = rule
if {mode!r} == fail_mode:
    raise SystemExit(fail_code)
if output is not None:
    print(output)
'''
    (bindir / "docker").write_text(docker)
    real_install = shutil.which("install")
    assert real_install
    (bindir / "install").write_text(
        f'''#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o|-g) shift 2;; *) out="$out $(printf %q "$1")"; shift;; esac
done
eval exec {real_install} $out
'''
    )
    # GNU stat compatibility for the Linux-only installer while tests run on macOS.
    (bindir / "stat").write_text(
        '''#!/bin/sh
fmt=$2
path=$3
case "$fmt" in
  %u) printf '0\\n' ;;
  %a) case "$path" in */install|*/compose.env) printf '700\\n';; *) printf '755\\n';; esac ;;
  *) exit 2 ;;
esac
'''
    )
    for path in bindir.iterdir():
        path.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=fixture, env=GIT_ENV, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=fixture, env=GIT_ENV, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=fixture, env=GIT_ENV, check=True)
    subprocess.run(["git", "add", "."], cwd=fixture, env=GIT_ENV, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=fixture, env=GIT_ENV, check=True)
    approved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture, env=GIT_ENV, text=True).strip()
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "DEVBOX_DATA_ROOT": "/etc",
        "DEVBOX_WEB_BIND": "0.0.0.0",
        "DEVBOX_PASSWORD": "AMBIENT_POISON",
    }
    return installer, env, log, data, approved


def run(mode: str) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, pathlib.Path]:
    installer, env, log, data, approved = prepare(mode)
    result = subprocess.run(
        ["bash", str(installer), "--yes", "--approved-commit", approved], env=env, capture_output=True, text=True
    )
    return result, log, data


success, log, data = run("success")
assert success.returncode == 0, "docker_exact_argv: " + success.stderr
assert "Installation complete" in success.stdout
assert "DOCKER_CONFIG=/nonexistent/devbox-anywhere-docker-config" in success.stdout, "status_docker_config"
assert "docker --context default compose" in success.stdout, "status_docker_context"
assert "TEST_GENERATED_PASSWORD" not in success.stdout + success.stderr
env_file = data / "install/compose.env"
assert env_file.exists()
assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
password_line = env_file.read_text().splitlines()[0]

# Rerun the same fixture to prove password preservation.
installer = data.parents[1] / "repo/scripts/install-devbox"
bindir = data.parents[1] / "bin"
approved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=installer.parents[1], env=GIT_ENV, text=True).strip()
env = os.environ | {
    "PATH": f"{bindir}:{os.environ['PATH']}",
    "DEVBOX_DATA_ROOT": "/etc",
    "DEVBOX_WEB_BIND": "0.0.0.0",
    "DEVBOX_PASSWORD": "AMBIENT_POISON",
}
rerun = subprocess.run(["bash", str(installer), "--yes", "--approved-commit", approved], env=env, capture_output=True, text=True)
assert rerun.returncode == 0, rerun.stderr
assert env_file.read_text().splitlines()[0] == password_line

records = [json.loads(line) for line in log.read_text().splitlines()]
assert len(records) == 28, f"docker_exact_call_count: {len(records)}"
prefix = ["--context", "default"]
compose = prefix + ["compose", "--env-file", str(env_file), "-f", str(installer.parents[1] / "stack/docker-compose.yml")]
expected_argv = [
    prefix + ["compose", "version"],
    prefix + ["info"],
    compose + ["build", "--pull=false"],
    compose + ["up", "-d"],
    prefix + ["cp", str(installer.parents[1] / "scripts/devbox"), "devbox:/tmp/devbox"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/install", "-m", "0755", "/tmp/devbox", "/home/coder/.local/bin/devbox"],
    prefix + ["exec", "--env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "devbox", "/usr/bin/rm", "-f", "/tmp/devbox"],
    prefix + ["cp", str(installer.parents[1] / "scripts/devbox-relink"), "devbox:/tmp/devbox-relink"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/install", "-m", "0755", "/tmp/devbox-relink", "/home/coder/.local/bin/devbox-relink"],
    prefix + ["exec", "--env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "devbox", "/usr/bin/rm", "-f", "/tmp/devbox-relink"],
    prefix + ["inspect", "-f", "{{.State.Running}}", "devbox"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/bin/sh", "-c", '/usr/bin/tmux -V >/dev/null && /usr/bin/test -x "$HOME/.local/bin/devbox" && /usr/bin/test -x "$HOME/.local/bin/devbox-relink"'],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox", "/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"],
]
assert [record["args"] for record in records[:14]] == expected_argv, "docker_exact_order:first_install"
assert [record["args"] for record in records[14:]] == expected_argv, "docker_exact_order:rerun"
for record in records:
    assert record["args"][:2] == ["--context", "default"], "docker_context"
    assert record["docker_config"] == "/nonexistent/devbox-anywhere-docker-config", "docker_config"
    assert record["poison_root"] is None and record["poison_web"] is None and record["poison_password"] is None, "docker_ambient_env"

for mode in (
    "compose-version-fail", "daemon-fail", "build-fail", "up-fail",
    "helper-devbox-fail", "helper-relink-fail", "install-devbox-fail",
    "install-relink-fail", "remove-fail", "readiness-fail", "inspect-fail",
    "http-fail", "ssh-fail",
):
    result, _, _ = run(mode)
    assert result.returncode != 0, mode
    assert "Installation complete" not in result.stdout, mode
    if mode in {"readiness-fail", "inspect-fail", "http-fail", "ssh-fail"}:
        assert "DOCKER_CONFIG=/nonexistent/devbox-anywhere-docker-config" in result.stderr, "recovery_docker_config"
        assert "docker --context default logs devbox" in result.stderr, "recovery_docker_context"

print("install_devbox_lifecycle=PASS")
