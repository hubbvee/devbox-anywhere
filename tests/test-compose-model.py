#!/usr/bin/env python3
"""Check exact Compose wiring; render it too when Docker Compose is available."""
from __future__ import annotations

import os
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "stack/docker-compose.yml"
text = COMPOSE.read_text()


def fail(message: str) -> None:
    raise AssertionError(message)


# Values the installer guarantees in the generated .env. Every `${VAR:?...}` in the Compose
# file must be covered here: current Compose interpolates EVERY profile during `config`, so
# a required variable belonging to an unselected profile (browser) still has to be present
# for the file to render. install-devbox already guarantees this for real installs; this
# seed must mirror that guarantee or the render check tests a shape no install ever has.
ENV_SEED = (
    "DEVBOX_PASSWORD=TEST_ONLY_NOT_A_SECRET\n"
    "DEVBOX_BROWSER_PASSWORD=TEST_ONLY_NOT_A_SECRET\n"
    "DEVBOX_DATA_ROOT=/data/devbox\n"
    "DEVBOX_WEB_BIND=127.0.0.1\n"
    "DEVBOX_SSH_BIND=127.0.0.1\n"
)

# A named instance (install-devbox --instance myapp) adds these non-secret values on top.
# Derived from ENV_SEED so the required-variable coverage check above governs both seeds.
INSTANCE_SEED = ENV_SEED.replace("DEVBOX_DATA_ROOT=/data/devbox\n", "DEVBOX_DATA_ROOT=/data/devbox-myapp\n") + (
    "DEVBOX_BROWSER_BIND=127.0.0.1\n"
    "DEVBOX_INSTANCE=myapp\n"
    "DEVBOX_PROJECT=devbox-myapp\n"
    "COMPOSE_PROJECT_NAME=devbox-myapp\n"
    "DEVBOX_CONTAINER=devbox-myapp\n"
    "DEVBOX_WEB_PORT=9080\n"
    "DEVBOX_SSH_PORT=9022\n"
    "DEVBOX_BROWSER_PORT=9081\n"
)

# Pin every variable the file may interpolate: a new variable is new attack surface (it
# could re-point a bind, a mount or a name) and must be reviewed here deliberately.
_referenced = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", text))
if _referenced != {
    "DEVBOX_PASSWORD", "DEVBOX_BROWSER_PASSWORD", "DEVBOX_DATA_ROOT", "DEVBOX_CONTAINER",
    "DEVBOX_WEB_BIND", "DEVBOX_WEB_PORT", "DEVBOX_SSH_BIND", "DEVBOX_SSH_PORT",
    "DEVBOX_BROWSER_BIND", "DEVBOX_BROWSER_PORT",
}:
    fail(f"interpolated variable set drifted: {sorted(_referenced)}")

_required = set(re.findall(r"\$\{([A-Z_]+):\?", text))
_seeded = {line.split("=", 1)[0] for line in ENV_SEED.splitlines() if line}
_uncovered = sorted(_required - _seeded)
if _uncovered:
    fail(f"seed_missing_required_var:{','.join(_uncovered)}")


# Enforce the complete schema used by this deliberately small Compose file. This catches
# extra services and behavior-changing keys such as privileged/network_mode/cap_add.
structural = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
top_keys = [m.group(1) for line in structural if (m := re.match(r"^([A-Za-z][\w-]*):\s*$", line))]
if top_keys != ["services"]:
    fail(f"top-level Compose keys drifted: {top_keys}")
service_names = [m.group(1) for line in structural if (m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", line))]
if service_names != ["devbox", "browser"]:
    fail(f"service set drifted: {service_names}")
# Enforce the devbox service's exact key set. Slice to just the devbox block so the
# optional profiled browser service does not bleed into this check.
devbox_block = text.split("\n  browser:", 1)[0]
devbox_structural = [line for line in devbox_block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
service_keys = [m.group(1) for line in devbox_structural if (m := re.match(r"^    ([A-Za-z][\w-]*):", line))]
if service_keys != ["build", "container_name", "restart", "environment", "ports", "volumes"]:
    fail(f"devbox service keys drifted: {service_keys}")


# This strict structural check is intentionally standard-library-only so the canonical
# runner catches wiring drift even on review hosts that do not have Docker or PyYAML.
required_once = {
    r"(?m)^\s{4}build: \.$": "build context",
    r"(?m)^\s{4}container_name: \$\{DEVBOX_CONTAINER:-devbox\}$": "container name",
    r"(?m)^\s{4}restart: unless-stopped$": "restart policy",
    r"(?m)^\s{6}- PASSWORD=\$\{DEVBOX_PASSWORD:\?set DEVBOX_PASSWORD in \.env\}$": "password",
    r'(?m)^\s{6}- "\$\{DEVBOX_WEB_BIND:-127\.0\.0\.1\}:\$\{DEVBOX_WEB_PORT:-8080\}:8080"': "web port",
    r'(?m)^\s{6}- "\$\{DEVBOX_SSH_BIND:-127\.0\.0\.1\}:\$\{DEVBOX_SSH_PORT:-2222\}:22"': "SSH port",
}
for pattern, label in required_once.items():
    if len(re.findall(pattern, devbox_block)) != 1:
        fail(f"{label} wiring drifted")


def list_items(section: str) -> list[str]:
    match = re.search(
        rf"(?ms)^\s{{4}}{re.escape(section)}:\s*\n(?P<body>.*?)(?=^\s{{4}}[A-Za-z][^\n]*:\s*(?:#.*)?$|^\s{{2}}[A-Za-z][^\n]*:\s*$|\Z)",
        devbox_block,
    )
    if not match:
        fail(f"missing {section} section")
    assert match is not None
    return re.findall(r'(?m)^\s{6}-\s+"?([^"\n]+)"?\s*(?:#.*)?$', match.group("body"))


if list_items("environment") != ["PASSWORD=${DEVBOX_PASSWORD:?set DEVBOX_PASSWORD in .env}"]:
    fail("environment must contain exactly the approved password mapping")
if list_items("ports") != [
    "${DEVBOX_WEB_BIND:-127.0.0.1}:${DEVBOX_WEB_PORT:-8080}:8080",
    "${DEVBOX_SSH_BIND:-127.0.0.1}:${DEVBOX_SSH_PORT:-2222}:22",
]:
    fail("ports must contain exactly the approved web and SSH mappings")

expected_volumes = {
    "project": "/home/coder/project",
    "dot-local": "/home/coder/.local",
    "claude": "/home/coder/.claude",
    "codex": "/home/coder/.codex",
    "ssh": "/home/coder/.ssh",
}
volume_lines = list_items("volumes")
expected_lines = {
    f"${{DEVBOX_DATA_ROOT:-/data/devbox}}/{leaf}:{target}"
    for leaf, target in expected_volumes.items()
}
if set(volume_lines) != expected_lines or len(volume_lines) != len(expected_lines):
    fail("volume wiring/count drifted")


def interpolate(source: str, env: dict[str, str]) -> str:
    """Stdlib model of Compose interpolation for the only forms this file uses.

    Supports ${VAR}, ${VAR:-default} and ${VAR:?message}; any other form fails closed, so
    the instance rendering below is checked even on hosts without Docker Compose."""
    def substitute(match: re.Match[str]) -> str:
        name, operator, argument = match.group(1), match.group(2), match.group(3)
        value = env.get(name, "")
        if operator is None:
            return value
        if operator == ":-":
            return value or argument
        if not value:
            fail(f"render_required_missing:{name}")
        return value
    rendered = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?)([^}]*))?\}", substitute, source)
    if "${" in rendered or re.search(r"\$[A-Za-z_]", rendered):
        fail("render_unsupported_interpolation")
    return rendered


def seed_env(seed: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in seed.splitlines() if line)


def rendered_wiring(env: dict[str, str]) -> dict[str, list[str]]:
    """Container names and port strings of each service after stdlib interpolation."""
    rendered = [line for line in interpolate(text, env).splitlines() if not line.lstrip().startswith("#")]
    wiring: dict[str, list[str]] = {}
    service = ""
    in_ports = False
    for line in rendered:
        if (m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", line)):
            service = m.group(1)
            wiring[service] = []
            in_ports = False
            continue
        if (m := re.match(r"^    container_name: (\S+)$", line)):
            wiring[service].append(f"name={m.group(1)}")
        if re.match(r"^    [A-Za-z]", line):
            in_ports = line.strip() == "ports:"
            continue
        if in_ports and (m := re.match(r'^\s{6}- "([^"]+)"', line)):
            wiring[service].append(f"port={m.group(1)}")
    return wiring


# Default rendering reproduces the historical literals exactly (existing installs unchanged).
if rendered_wiring(seed_env(ENV_SEED)) != {
    "devbox": ["name=devbox", "port=127.0.0.1:8080:8080", "port=127.0.0.1:2222:22"],
    "browser": ["name=devbox-browser", "port=127.0.0.1:8081:3000"],
}:
    fail("default_rendering_drifted")
# A named instance gets its own container names and host ports, still loopback-only.
if rendered_wiring(seed_env(INSTANCE_SEED)) != {
    "devbox": ["name=devbox-myapp", "port=127.0.0.1:9080:8080", "port=127.0.0.1:9022:22"],
    "browser": ["name=devbox-myapp-browser", "port=127.0.0.1:9081:3000"],
}:
    fail("instance_rendering_drifted")
if "/data/devbox-myapp/project:/home/coder/project" not in interpolate(text, seed_env(INSTANCE_SEED)):
    fail("instance_rendering_data_root_drifted")


def validate_rendered(
    raw: str,
    container: str = "devbox",
    data_root: str = "/data/devbox",
    web_port: str = "8080",
    ssh_port: str = "2222",
) -> None:
    """Validate normalized Compose JSON, not merely parser exit status."""
    model = json.loads(raw)
    services = model.get("services")
    if not isinstance(services, dict) or set(services) != {"devbox"}:
        fail("rendered service set drifted")
    service = services["devbox"]
    if service.get("container_name") != container:
        fail("rendered container name drifted")
    if service.get("environment") != {"PASSWORD": "TEST_ONLY_NOT_A_SECRET"}:
        fail("rendered password environment drifted")
    build = service.get("build")
    if not isinstance(build, dict) or pathlib.Path(build.get("context", "")).resolve() != (ROOT / "stack").resolve():
        fail("rendered build context drifted")
    ports = service.get("ports")
    if not isinstance(ports, list) or len(ports) != 2:
        fail("rendered port count drifted")
    normalized_ports: set[tuple[str, str, int]] = set()
    for item in ports:
        if not isinstance(item, dict):
            fail("rendered port entry is not an object")
        host_ip = item.get("host_ip")
        published = item.get("published")
        target = item.get("target")
        if host_ip is None or published is None or target is None:
            fail("rendered port entry is incomplete")
        assert target is not None
        normalized_ports.add((str(host_ip), str(published), int(str(target))))
    if normalized_ports != {
        ("127.0.0.1", web_port, 8080),
        ("127.0.0.1", ssh_port, 22),
    }:
        fail("rendered port semantics drifted")
    volumes = service.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 5:
        fail("rendered volume count drifted")
    normalized_volumes = {
        (item.get("type"), item.get("source"), item.get("target"))
        for item in volumes
        if isinstance(item, dict)
    }
    expected_rendered_volumes = {
        ("bind", f"{data_root}/{leaf}", target)
        for leaf, target in expected_volumes.items()
    }
    if normalized_volumes != expected_rendered_volumes:
        fail("rendered volume semantics drifted")


# Always exercise the rendered-model validator, including on review hosts without Docker.
canonical_rendered = {
    "services": {
        "devbox": {
            "build": {"context": str((ROOT / "stack").resolve())},
            "container_name": "devbox",
            "environment": {"PASSWORD": "TEST_ONLY_NOT_A_SECRET"},
            "ports": [
                {"host_ip": "127.0.0.1", "published": "8080", "target": 8080},
                {"host_ip": "127.0.0.1", "published": "2222", "target": 22},
            ],
            "volumes": [
                {"type": "bind", "source": f"/data/devbox/{leaf}", "target": target}
                for leaf, target in expected_volumes.items()
            ],
        }
    }
}
validate_rendered(json.dumps(canonical_rendered))

for label, mutate in (
    ("extra service", lambda m: m["services"].update({"attacker": {}})),
    ("password", lambda m: m["services"]["devbox"]["environment"].update({"PASSWORD": "wrong"})),
    ("container name", lambda m: m["services"]["devbox"].update({"container_name": "devbox-other"})),
    ("build", lambda m: m["services"]["devbox"]["build"].update({"context": "/tmp"})),
    ("port", lambda m: m["services"]["devbox"]["ports"].append({"host_ip": "0.0.0.0", "published": "9999", "target": 8080})),
    ("volume", lambda m: m["services"]["devbox"]["volumes"].append({"type": "bind", "source": "/tmp", "target": "/tmp"})),
):
    candidate = json.loads(json.dumps(canonical_rendered))
    mutate(candidate)
    try:
        validate_rendered(json.dumps(candidate))
    except AssertionError:
        pass
    else:
        fail(f"rendered validator accepted mutation: {label}")

# When available, ask Compose itself to parse and interpolate the checked file.
docker = shutil.which("docker")
if docker:
    probe = subprocess.run(
        [docker, "compose", "version"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        with tempfile.TemporaryDirectory(prefix="compose-model-") as tmp:
            env_file = pathlib.Path(tmp) / "compose.env"
            env_file.write_text(ENV_SEED)
            clean_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", "/tmp"),
            }
            rendered = subprocess.run(
                [docker, "compose", "--env-file", str(env_file), "-f", str(COMPOSE), "config", "--format", "json"],
                env=clean_env,
                capture_output=True,
                text=True,
            )
            if rendered.returncode != 0:
                fail(f"docker compose config failed: {rendered.stderr.strip()}")
            validate_rendered(rendered.stdout)
            # Without -p the project stays directory-derived, exactly as for existing installs.
            if json.loads(rendered.stdout).get("name") != "stack":
                fail("default project name drifted")
            instance_env = pathlib.Path(tmp) / "instance.env"
            instance_env.write_text(INSTANCE_SEED)
            rendered = subprocess.run(
                [docker, "compose", "-p", "devbox-myapp", "--env-file", str(instance_env), "-f", str(COMPOSE), "config", "--format", "json"],
                env=clean_env,
                capture_output=True,
                text=True,
            )
            if rendered.returncode != 0:
                fail(f"docker compose config failed for an instance: {rendered.stderr.strip()}")
            validate_rendered(rendered.stdout, "devbox-myapp", "/data/devbox-myapp", "9080", "9022")
            if json.loads(rendered.stdout).get("name") != "devbox-myapp":
                fail("instance project name drifted")
            # Defense in depth: a manual command with the instance env file but WITHOUT -p still
            # resolves the instance's project (COMPOSE_PROJECT_NAME), never the default "stack".
            rendered = subprocess.run(
                [docker, "compose", "--env-file", str(instance_env), "-f", str(COMPOSE), "config", "--format", "json"],
                env=clean_env,
                capture_output=True,
                text=True,
            )
            if rendered.returncode != 0:
                fail(f"docker compose config failed for an instance without -p: {rendered.stderr.strip()}")
            validate_rendered(rendered.stdout, "devbox-myapp", "/data/devbox-myapp", "9080", "9022")
            if json.loads(rendered.stdout).get("name") != "devbox-myapp":
                fail("instance env file does not pin the project name")

print("compose_model=PASS")