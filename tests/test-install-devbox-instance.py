#!/usr/bin/env python3
"""Named-instance contract for scripts/install-devbox (--instance), without Docker or root writes.

A named instance is a second, independent devbox on the same server: data root
/data/devbox-NAME, container devbox-NAME, Compose project devbox-NAME passed explicitly on
every Compose call, and its own loopback host ports. The default install is pinned unchanged by
test-install-devbox-lifecycle.py; this file pins the instance path with the same fixture.
"""
from __future__ import annotations

import json
import pathlib
import re
import stat
import subprocess
from typing import Any, Callable, cast

REPO = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = REPO / "scripts/install-devbox"
SHA = "0123456789abcdef0123456789abcdef01234567"

# Reuse the lifecycle fixture builder (same pattern as test-source-trust.py): only the helper
# definitions are executed, not the lifecycle assertions.
namespace: dict[str, object] = {
    "__name__": "fixture_helpers",
    "__file__": str(pathlib.Path(__file__).with_name("test-install-devbox-lifecycle.py")),
}
source = pathlib.Path(__file__).with_name("test-install-devbox-lifecycle.py").read_text()
exec(compile(source.split("success, log, data = run", 1)[0], "fixture_helpers", "exec"), namespace)
prepare = cast(Callable[..., Any], namespace["prepare"])
INSTALL_BLOB = cast(str, namespace["INSTALL_BLOB"])


def dry(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER), "--dry-run", "--yes", "--approved-commit", SHA, *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )


# --- 1. The name regex is one contract shared with the harness. ---------------------------------
installer_text = INSTALLER.read_text()
harness_text = (REPO / "scripts/devbox-anywhere").read_text()
assert "INSTANCE_RE='^[a-z][a-z0-9]{0,14}$'" in installer_text, "instance_regex_shared"
assert 'INSTANCE_PATTERN = r"[a-z][a-z0-9]{0,14}"' in harness_text, "instance_regex_shared"
assert 'RESERVED_INSTANCES="browser default devbox"' in installer_text, "instance_reserved_shared"
assert 'RESERVED_INSTANCES = frozenset({"browser", "default", "devbox"})' in harness_text, "instance_reserved_shared"

# --- 2. Dry-run plan for an instance: resolved names, paths and ports; never a secret. ----------
plan = dry("--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022")
assert plan.returncode == 0, "instance_dry_run: " + plan.stderr
for expected in (
    "persistent data: /data/devbox-myapp",
    "browser: 127.0.0.1:9080 (HTTP",
    "SSH: 127.0.0.1:9022 (key-only",
    "credentials: /data/devbox-myapp/install/compose.env",
    "instance: myapp",
    "Compose project: devbox-myapp",
    "container: devbox-myapp\n",
    "DEVBOX_DATA_ROOT=/data/devbox-myapp\n",
    "DEVBOX_INSTANCE=myapp\n",
    "DEVBOX_PROJECT=devbox-myapp\n",
    "DEVBOX_CONTAINER=devbox-myapp\n",
    "DEVBOX_WEB_PORT=9080\n",
    "DEVBOX_SSH_PORT=9022\n",
    "port: 127.0.0.1:9080:8080\n",
    "port: 127.0.0.1:9022:22\n",
    "volume: /data/devbox-myapp/project:/home/coder/project\n",
):
    assert expected in plan.stdout, f"instance_dry_run_plan:{expected!r}"
assert "DEVBOX_BROWSER_PORT" not in plan.stdout, "instance_dry_run_browser_off"
assert not re.search(r"DEVBOX_PASSWORD=[^<]", plan.stdout), "instance_dry_run_secret"
assert "/data/devbox/" not in plan.stdout, "instance_dry_run_default_root"

browser_plan = dry("--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--with-browser", "--browser-port", "9081")
assert browser_plan.returncode == 0, "instance_dry_run_browser: " + browser_plan.stderr
for expected in (
    "container: devbox-myapp (browser: devbox-myapp-browser)",
    "GUI browser (optional): 127.0.0.1:9081 noVNC (enabled)",
    "DEVBOX_BROWSER_PORT=9081\n",
    "port: 127.0.0.1:9081:3000\n",
    "volume: /data/devbox-myapp/browser:/config\n",
):
    assert expected in browser_plan.stdout, f"instance_dry_run_browser_plan:{expected!r}"
assert not re.search(r"PASSWORD=[^<]", browser_plan.stdout), "instance_dry_run_secret"

exposed = dry("--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--expose-ssh")
assert exposed.returncode == 0 and "port: 0.0.0.0:9022:22" in exposed.stdout, "instance_expose_ssh"
assert "port: 127.0.0.1:9080:8080" in exposed.stdout, "instance_expose_ssh_keeps_web_loopback"
assert "Restrict port 9022 with a firewall" in exposed.stdout, "instance_expose_ssh_warning"


def rejected(args: list[str], label: str) -> None:
    result = dry(*args)
    assert result.returncode != 0, f"{label}:{args!r}"
    assert "installation plan" not in result.stdout, f"{label}:plan_printed:{args!r}"


# --- 3. Instance name validation (allow-list regex + reserved names). ---------------------------
PORTS = ["--web-port", "9080", "--ssh-port", "9022"]
for bad_name in (
    "MyApp", "myApp", "my-app", "my/app", "../app", "my.app", ".", "my_app", "1app", "a" * 16,
    "app\n", " app", "café", "browser", "default", "devbox",
):
    rejected(["--instance", bad_name, *PORTS], "instance_name_validation")
rejected(["--instance", "", *PORTS], "instance_name_validation")
for good_name in ("a", "a" * 15, "app2", "z9"):
    assert dry("--instance", good_name, *PORTS).returncode == 0, f"instance_name_accepted:{good_name}"
rejected(["--instance", "myapp", "--instance", "other", *PORTS], "instance_option_repeated")

# --- 4. Port validation: required, decimal 1024-65535, distinct, never a default port. ----------
for args in (
    ["--instance", "myapp"],
    ["--instance", "myapp", "--web-port", "9080"],
    ["--instance", "myapp", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9080"],
    ["--instance", "myapp", "--web-port", "1023", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "65536", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "0", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "09080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080x", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "+9080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", " 9080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "1e4", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "$((1))"],
    ["--instance", "myapp", "--web-port", "8080", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "2222"],
    ["--instance", "myapp", "--web-port", "8081", "--ssh-port", "9022"],
    ["--instance", "myapp", "--web-port", "9080", "--ssh-port", "9022", "--web-port", "9090"],
    ["--instance", "myapp", *PORTS, "--with-browser"],
    ["--instance", "myapp", *PORTS, "--browser-port", "9081"],
    ["--instance", "myapp", *PORTS, "--with-browser", "--browser-port", "9080"],
    ["--instance", "myapp", *PORTS, "--with-browser", "--browser-port", "8081"],
):
    rejected(args, "instance_port_validation")

# Port options without --instance are refused; the default instance has fixed ports.
for args in (["--web-port", "9080"], ["--ssh-port", "9022"], ["--with-browser", "--browser-port", "9081"]):
    rejected(args, "port_flags_require_instance")
# The removed arbitrary data-root option stays removed, with or without an instance.
rejected(["--data-root", "/tmp/devbox"], "data_root_rejected")
rejected(["--instance", "myapp", *PORTS, "--data-root", "/tmp/devbox"], "data_root_rejected")


# --- 5. Exact Docker argv for an instance install, then an idempotent re-run. ------------------
def install(instance_args: list[str], mode: str = "success", setup: Callable[[pathlib.Path], None] | None = None):
    installer, env, log, data, approved = prepare(mode, instance="myapp")
    root = data.parents[1]
    if setup:
        setup(root)
    result = subprocess.run(
        ["bash", str(installer), "--yes", "--approved-commit", approved, *instance_args],
        env=env, capture_output=True, text=True,
    )
    return result, installer, env, log, data, approved


INSTANCE_ARGS = ["--instance", "myapp", *PORTS]
result, installer, env, log, data, approved = install(INSTANCE_ARGS)
assert result.returncode == 0, "instance_docker_exact_argv: " + result.stderr
assert "Installation complete" in result.stdout
fixture = installer.parents[1]
instance_root = data.parent / "devbox-myapp"
env_file = instance_root / "install/compose.env"
prefix = ["--context", "default"]
compose = prefix + ["compose", "-p", "devbox-myapp", "--env-file", str(env_file), "-f", str(fixture / "stack/docker-compose.yml")]
expected_argv: list[list[str]] = [
    prefix + ["compose", "version"],
    prefix + ["info"],
    prefix + ["container", "ls", "--all", "--format", '{{.Names}} {{.Label "com.docker.compose.project"}}'],
    compose + ["build", "--pull=false"],
    compose + ["up", "-d"],
]
helpers = ["devbox", "devbox-daemon", "devbox-relink", "devbox-session", "devbox-turn", "devbox-worktree"]
for helper in helpers:
    expected_argv += [
        prefix + ["cp", str(fixture / f"scripts/{helper}"), f"devbox-myapp:/tmp/{helper}"],
        prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/bin/sh", "-c", INSTALL_BLOB, "_", helper, "/home/coder/.local/bin"],
        prefix + ["exec", "--user", "root", "--env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "devbox-myapp", "/usr/bin/rm", "-f", f"/tmp/{helper}"],
    ]
readiness = "/usr/bin/tmux -V >/dev/null" + "".join(f' && /usr/bin/test -x "$HOME/.local/bin/{helper}"' for helper in helpers)
expected_argv += [
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/usr/bin/mkdir", "-p", "-m", "0700", "/home/coder/.local/share/devbox-relink.d"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/usr/bin/mkdir", "-p", "-m", "0700", "/home/coder/.local/share/devbox-daemons.d"],
    prefix + ["inspect", "-f", "{{.State.Running}}", "devbox-myapp"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/bin/sh", "-c", readiness],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"],
    prefix + ["exec", "--user", "coder", "--env", "PATH=/usr/bin:/bin", "devbox-myapp", "/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"],
]
records = [json.loads(line) for line in log.read_text().splitlines()]
assert [record["args"] for record in records] == expected_argv, "instance_docker_exact_order"
for record in records:
    args = record["args"]
    if "compose" in args and args != prefix + ["compose", "version"]:
        assert args[args.index("compose") + 1:args.index("compose") + 3] == ["-p", "devbox-myapp"], "instance_project_explicit"
    assert record["docker_config"] == "/nonexistent/devbox-anywhere-docker-config", "docker_config"
    assert record["poison_root"] is None and record["poison_web"] is None and record["poison_password"] is None, "docker_ambient_env"

# compose.env: owner-only, derived from the name, persists every setting the harness reads.
assert stat.S_IMODE(env_file.stat().st_mode) == 0o600, "instance_env_mode"
env_lines = env_file.read_text().splitlines()
assert env_lines[0].startswith("DEVBOX_PASSWORD="), "instance_env_password_first"
assert env_lines[1:] == [
    f"DEVBOX_DATA_ROOT={instance_root}",
    "DEVBOX_WEB_BIND=127.0.0.1",
    "DEVBOX_SSH_BIND=127.0.0.1",
    "DEVBOX_BROWSER_BIND=127.0.0.1",
    "DEVBOX_BROWSER_PASSWORD=TEST_GENERATED_PASSWORD_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
    "DEVBOX_INSTANCE=myapp",
    "DEVBOX_PROJECT=devbox-myapp",
    "DEVBOX_CONTAINER=devbox-myapp",
    "DEVBOX_WEB_PORT=9080",
    "DEVBOX_SSH_PORT=9022",
], "instance_env_settings"
for leaf in ("project", "dot-local", "claude", "codex", "ssh"):
    assert (instance_root / leaf).is_dir(), f"instance_data_dir:{leaf}"
assert not data.exists(), "instance_touched_default_root"
assert "TEST_GENERATED_PASSWORD" not in result.stdout + result.stderr, "instance_password_leak"

# Final instructions name the instance's ports, container project and tunnels.
for expected in (
    "Browser (local/server): http://127.0.0.1:9080",
    f"docker --context default compose -p devbox-myapp --env-file '{env_file}' -f",
    "1. ssh -L 9022:127.0.0.1:9022 HOST_USER@SERVER_ADDRESS",
    "2. In another terminal: ssh -p 9022 coder@127.0.0.1",
    "Do not expose port 9080 directly.",
):
    assert expected in result.stdout, f"instance_status_project:{expected!r}"
for stale in ("127.0.0.1:8080", "ssh -L 2222", "-p 2222", "port 8080"):
    assert stale not in result.stdout, f"instance_default_port_printed:{stale!r}"

# Re-run: the instance's own listeners (recorded ports) are not a collision; password preserved.
password_line = env_lines[0]
root = data.parents[1]
(root / "listening.txt").write_text(
    "LISTEN 0 4096 127.0.0.1:9080 0.0.0.0:*\nLISTEN 0 128 127.0.0.1:9022 0.0.0.0:*\n"
)
(root / "containers.txt").write_text("devbox-myapp devbox-myapp\ndevbox stack\n")
rerun = subprocess.run(
    ["bash", str(installer), "--yes", "--approved-commit", approved, *INSTANCE_ARGS],
    env=env, capture_output=True, text=True,
)
assert rerun.returncode == 0, "instance_rerun_owned_ports: " + rerun.stderr
assert env_file.read_text().splitlines()[0] == password_line, "instance_rerun_password"
rerun_records = [json.loads(line) for line in log.read_text().splitlines()][len(records):]
assert [record["args"] for record in rerun_records] == expected_argv, "instance_docker_exact_order:rerun"

# --- 6. Port collision refusal: a chosen port already listening stops before any build. --------
for listening in (
    "LISTEN 0 4096 127.0.0.1:9080 0.0.0.0:*\n",
    "LISTEN 0 4096 0.0.0.0:9022 0.0.0.0:*\n",
    "LISTEN 0 4096 [::]:9022 [::]:*\n",
    "LISTEN 0 4096 *:9080 *:*\n",
):
    collided, _, _, c_log, c_data, _ = install(
        INSTANCE_ARGS, setup=lambda r, text=listening: (r / "listening.txt").write_text(text)
    )
    assert collided.returncode != 0, f"instance_port_collision:{listening!r}"
    assert "already in use" in collided.stderr, f"instance_port_collision:{listening!r}"
    calls = [json.loads(line)["args"] for line in c_log.read_text().splitlines()]
    assert not any("build" in call or "up" in call for call in calls), "instance_port_collision_built"
    assert not (c_data.parent / "devbox-myapp/install/compose.env").exists(), "instance_port_collision_wrote_env"
# A port merely sharing digits is not a collision.
near, *_ = install(INSTANCE_ARGS, setup=lambda r: (r / "listening.txt").write_text("LISTEN 0 1 127.0.0.1:19080 0.0.0.0:*\n"))
assert near.returncode == 0, "instance_port_collision_exact: " + near.stderr
# The check fails closed when ss fails or prints something unexpected.
broken, *_ = install(INSTANCE_ARGS, setup=lambda r: (r / "ss-fail").write_text(""))
assert broken.returncode != 0 and "could not list listening TCP ports" in broken.stderr, "instance_port_check_fail_closed"
garbled, *_ = install(INSTANCE_ARGS, setup=lambda r: (r / "listening.txt").write_text("LISTEN 0 1 garbage peer\n"))
assert garbled.returncode != 0 and "unexpected listening socket" in garbled.stderr, "instance_port_check_fail_closed"

# --- 7. Never adopt a container that is not this instance's Compose project. ------------------
for listing in (
    "devbox-myapp \n",
    "devbox-myapp stack\n",
    "devbox-myapp devbox-other\n",
    "devbox-myapp-browser something\n",
):
    hijack, _, _, h_log, _, _ = install(INSTANCE_ARGS, setup=lambda r, text=listing: (r / "containers.txt").write_text(text))
    assert hijack.returncode != 0, f"instance_container_hijack:{listing!r}"
    assert "is not managed by Compose project devbox-myapp" in hijack.stderr, f"instance_container_hijack:{listing!r}"
    calls = [json.loads(line)["args"] for line in h_log.read_text().splitlines()]
    assert not any("build" in call or "up" in call for call in calls), "instance_container_hijack_built"
unrelated, *_ = install(INSTANCE_ARGS, setup=lambda r: (r / "containers.txt").write_text("devbox stack\ndevbox-myappx other\ndevbox-browser stack\n"))
assert unrelated.returncode == 0, "instance_container_unrelated: " + unrelated.stderr
listing_failed, *_ = install(INSTANCE_ARGS, mode="containers-fail")
assert listing_failed.returncode != 0 and "could not list existing containers" in listing_failed.stderr, "instance_container_list_fail_closed"

# --- 8. Instance with the browser profile: profile + project on every Compose call. -------------
b_result, b_installer, _, b_log, b_data, _ = install([*INSTANCE_ARGS, "--with-browser", "--browser-port", "9081"])
assert b_result.returncode == 0, "instance_browser_install: " + b_result.stderr
b_calls = [json.loads(line)["args"] for line in b_log.read_text().splitlines()]
b_compose = [call for call in b_calls if "compose" in call and ("build" in call or "up" in call)]
assert len(b_compose) == 2, "instance_browser_compose_calls"
for call in b_compose:
    assert call[3:5] == ["-p", "devbox-myapp"] and call[-3:-1] in (["browser", "build"], ["browser", "up"]), "instance_browser_profile"
b_env = (b_data.parent / "devbox-myapp/install/compose.env").read_text()
assert "DEVBOX_BROWSER_PORT=9081\n" in b_env and b_env.count("DEVBOX_BROWSER_PASSWORD=") == 1, "instance_browser_env"
assert (b_data.parent / "devbox-myapp/browser").is_dir(), "instance_browser_data_dir"
assert "ssh -L 9081:127.0.0.1:9081 HOST_USER@SERVER_ADDRESS then open http://127.0.0.1:9081" in b_result.stdout, "instance_browser_tunnel"
assert "Never expose port 9081 publicly." in b_result.stdout, "instance_browser_warning"

# Failure path names the instance container in the recovery hint.
failed, *_ = install(INSTANCE_ARGS, mode="http-fail")
assert failed.returncode != 0 and "docker --context default logs devbox-myapp" in failed.stderr, "instance_recovery_container"

print("install_devbox_instance=PASS")
