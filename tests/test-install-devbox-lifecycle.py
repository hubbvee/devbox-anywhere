#!/usr/bin/env python3
"""Disposable lifecycle tests for scripts/install-devbox without Docker or root writes."""
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (REPO / "scripts/install-devbox").read_text()


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
    docker = f'''#!/bin/sh
printf 'args=%s poison_root=%s poison_web=%s poison_password=%s\\n' "$*" "${{DEVBOX_DATA_ROOT-unset}}" "${{DEVBOX_WEB_BIND-unset}}" "${{DEVBOX_PASSWORD-unset}}" >> {log}
case "$1 $2" in
  "compose version") [ "{mode}" = compose-version-fail ] && exit 31; exit 0 ;;
esac
[ "$1" = info ] && {{ [ "{mode}" = daemon-fail ] && exit 32; exit 0; }}
[ "$1" = inspect ] && {{ [ "{mode}" = inspect-fail ] && exit 1; echo true; exit 0; }}
if [ "$1" = compose ]; then
  case " $* " in
    *" build --pull=false "*) [ "{mode}" = build-fail ] && exit 41 ;;
    *" up -d "*) [ "{mode}" = up-fail ] && exit 42 ;;
  esac
fi
if [ "$1" = cp ]; then
  case "{mode}:$*" in
    helper-devbox-fail:*scripts/devbox\ devbox:/tmp/devbox) exit 43 ;;
    helper-relink-fail:*scripts/devbox-relink\ devbox:/tmp/devbox-relink) exit 44 ;;
  esac
  exit 0
fi
if [ "$1" = exec ]; then
  case " $* " in
    *" /usr/bin/install "*"/home/coder/.local/bin/devbox "*) [ "{mode}" = install-devbox-fail ] && exit 45 ;;
    *" /usr/bin/install "*"/home/coder/.local/bin/devbox-relink "*) [ "{mode}" = install-relink-fail ] && exit 46 ;;
    *" /usr/bin/rm "*) [ "{mode}" = remove-fail ] && exit 47 ;;
    *" /bin/sh -c "*) [ "{mode}" = readiness-fail ] && exit 48 ;;
    *" /usr/bin/wget "*) [ "{mode}" = http-fail ] && exit 45 ;;
    *" /usr/bin/ssh-keyscan "*) [ "{mode}" = ssh-fail ] && exit 46 ;;
  esac
  exit 0
fi
exit 0
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
    subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=fixture, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=fixture, check=True)
    subprocess.run(["git", "add", "."], cwd=fixture, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=fixture, check=True)
    approved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture, text=True).strip()
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
assert success.returncode == 0, success.stderr
assert "Installation complete" in success.stdout
assert "TEST_GENERATED_PASSWORD" not in success.stdout + success.stderr
env_file = data / "install/compose.env"
assert env_file.exists()
assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
password_line = env_file.read_text().splitlines()[0]

# Rerun the same fixture to prove password preservation.
installer = data.parents[1] / "repo/scripts/install-devbox"
bindir = data.parents[1] / "bin"
approved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=installer.parents[1], text=True).strip()
env = os.environ | {
    "PATH": f"{bindir}:{os.environ['PATH']}",
    "DEVBOX_DATA_ROOT": "/etc",
    "DEVBOX_WEB_BIND": "0.0.0.0",
    "DEVBOX_PASSWORD": "AMBIENT_POISON",
}
rerun = subprocess.run(["bash", str(installer), "--yes", "--approved-commit", approved], env=env, capture_output=True, text=True)
assert rerun.returncode == 0, rerun.stderr
assert env_file.read_text().splitlines()[0] == password_line

logged = log.read_text()
for required in (
    "build --pull=false",
    "up -d",
    "exec --user coder --env PATH=/usr/bin:/bin devbox /usr/bin/install",
    "exec --env PATH=/usr/sbin:/usr/bin:/sbin:/bin devbox /usr/bin/rm",
    "/usr/bin/wget",
    "/usr/bin/ssh-keyscan",
    "/home/coder/.local/bin/devbox-relink",
    "/home/coder/.local/bin/devbox",
    "poison_root=unset poison_web=unset poison_password=unset",
):
    assert required in logged, required

assert logged.count("cp ") >= 4  # both helpers on first install and rerun
assert logged.count(" /home/coder/.local/bin/devbox poison_root=") >= 2
assert logged.count(" /home/coder/.local/bin/devbox-relink poison_root=") >= 2

for mode in (
    "compose-version-fail", "daemon-fail", "build-fail", "up-fail",
    "helper-devbox-fail", "helper-relink-fail", "install-devbox-fail",
    "install-relink-fail", "remove-fail", "readiness-fail", "inspect-fail",
    "http-fail", "ssh-fail",
):
    result, _, _ = run(mode)
    assert result.returncode != 0, mode
    assert "Installation complete" not in result.stdout, mode

print("install_devbox_lifecycle=PASS")
