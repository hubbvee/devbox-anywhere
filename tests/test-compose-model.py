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


# Enforce the complete schema used by this deliberately small Compose file. This catches
# extra services and behavior-changing keys such as privileged/network_mode/cap_add.
structural = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
top_keys = [m.group(1) for line in structural if (m := re.match(r"^([A-Za-z][\w-]*):\s*$", line))]
if top_keys != ["services"]:
    fail(f"top-level Compose keys drifted: {top_keys}")
service_names = [m.group(1) for line in structural if (m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", line))]
if service_names != ["devbox"]:
    fail(f"service set drifted: {service_names}")
service_keys = [m.group(1) for line in structural if (m := re.match(r"^    ([A-Za-z][\w-]*):", line))]
if service_keys != ["build", "container_name", "restart", "environment", "ports", "volumes"]:
    fail(f"devbox service keys drifted: {service_keys}")


# This strict structural check is intentionally standard-library-only so the canonical
# runner catches wiring drift even on review hosts that do not have Docker or PyYAML.
required_once = {
    r"(?m)^\s{4}build: \.$": "build context",
    r"(?m)^\s{4}container_name: devbox$": "container name",
    r"(?m)^\s{4}restart: unless-stopped$": "restart policy",
    r"(?m)^\s{6}- PASSWORD=\$\{DEVBOX_PASSWORD:\?set DEVBOX_PASSWORD in \.env\}$": "password",
    r'(?m)^\s{6}- "\$\{DEVBOX_WEB_BIND:-127\.0\.0\.1\}:8080:8080"': "web port",
    r'(?m)^\s{6}- "\$\{DEVBOX_SSH_BIND:-127\.0\.0\.1\}:2222:22"': "SSH port",
}
for pattern, label in required_once.items():
    if len(re.findall(pattern, text)) != 1:
        fail(f"{label} wiring drifted")


def list_items(section: str) -> list[str]:
    match = re.search(
        rf"(?ms)^\s{{4}}{re.escape(section)}:\s*\n(?P<body>.*?)(?=^\s{{4}}[A-Za-z][^\n]*:\s*(?:#.*)?$|\Z)",
        text,
    )
    if not match:
        fail(f"missing {section} section")
    assert match is not None
    return re.findall(r'(?m)^\s{6}-\s+"?([^"\n]+)"?\s*(?:#.*)?$', match.group("body"))


if list_items("environment") != ["PASSWORD=${DEVBOX_PASSWORD:?set DEVBOX_PASSWORD in .env}"]:
    fail("environment must contain exactly the approved password mapping")
if list_items("ports") != [
    "${DEVBOX_WEB_BIND:-127.0.0.1}:8080:8080",
    "${DEVBOX_SSH_BIND:-127.0.0.1}:2222:22",
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


def validate_rendered(raw: str) -> None:
    """Validate normalized Compose JSON, not merely parser exit status."""
    model = json.loads(raw)
    services = model.get("services")
    if not isinstance(services, dict) or set(services) != {"devbox"}:
        fail("rendered service set drifted")
    service = services["devbox"]
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
        ("127.0.0.1", "8080", 8080),
        ("127.0.0.1", "2222", 22),
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
        ("bind", f"/data/devbox/{leaf}", target)
        for leaf, target in expected_volumes.items()
    }
    if normalized_volumes != expected_rendered_volumes:
        fail("rendered volume semantics drifted")


# Always exercise the rendered-model validator, including on review hosts without Docker.
canonical_rendered = {
    "services": {
        "devbox": {
            "build": {"context": str((ROOT / "stack").resolve())},
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
            env_file.write_text(
                "DEVBOX_PASSWORD=TEST_ONLY_NOT_A_SECRET\n"
                "DEVBOX_DATA_ROOT=/data/devbox\n"
                "DEVBOX_WEB_BIND=127.0.0.1\n"
                "DEVBOX_SSH_BIND=127.0.0.1\n"
            )
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

print("compose_model=PASS")