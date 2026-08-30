#!/usr/bin/env python3
"""Contract for the opt-in interactive browser Compose service (--with-browser).

Verifies the service is present only under the "browser" Compose profile, binds noVNC to
loopback:8081, persists its profile under /data/devbox/browser, sources its password from
the owner-only env file (never a literal), and never binds a public interface. Docker is
unavailable on review hosts, so this is a strict static + rendered-model check like
test-compose-model.py; a real runtime smoke happens on a devbox.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import NoReturn

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "stack/docker-compose.yml"
text = COMPOSE.read_text()


def fail(message: str) -> NoReturn:
    raise AssertionError(message)


structural = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

# The browser service exists and is a second service alongside devbox.
service_names = [m.group(1) for line in structural if (m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", line))]
if service_names != ["devbox", "browser"]:
    fail(f"service set drifted: {service_names}")

# It is gated behind the "browser" profile so a default `up` never starts it.
if not re.search(r'(?ms)^  browser:\s*\n(?:.*\n)*?    profiles:\s*\n      - "?browser"?\s*$', text):
    fail("browser service must be gated behind the 'browser' Compose profile")

# noVNC binds loopback:8081 (host) -> 3000 (KasmVNC HTTP in the container).
if not re.search(r'(?m)^\s{6}- "\$\{DEVBOX_BROWSER_BIND:-127\.0\.0\.1\}:8081:3000"', text):
    fail("browser noVNC must bind ${DEVBOX_BROWSER_BIND:-127.0.0.1}:8081:3000")

# The VNC password comes from the env file, never a literal in the compose file.
if not re.search(r"(?m)^\s{6}- PASSWORD=\$\{DEVBOX_BROWSER_PASSWORD:\?", text):
    fail("browser password must come from DEVBOX_BROWSER_PASSWORD env var")
if re.search(r"(?mi)^\s{6}- (VNC_)?PASSWORD=(?!\$)", text):
    fail("browser password must not be a literal")

# Persistent profile under the fixed data root.
if f"${{DEVBOX_DATA_ROOT:-/data/devbox}}/browser:" not in text:
    fail("browser profile must persist under /data/devbox/browser")

# No public bind anywhere in the file.
if re.search(r'"0\.0\.0\.0:', text):
    fail("no service may bind 0.0.0.0")


def validate_rendered(raw: str) -> None:
    """Validate the rendered browser service when the profile is active."""
    model = json.loads(raw)
    services = model.get("services", {})
    browser = services.get("browser")
    if browser is None:
        fail("rendered model missing browser service")
    ports = browser.get("ports")
    if not isinstance(ports, list) or len(ports) != 1:
        fail("browser must publish exactly one port")
    item = ports[0]
    if (str(item.get("host_ip")), str(item.get("published"))) != ("127.0.0.1", "8081"):
        fail("browser noVNC port must be 127.0.0.1:8081")
    volumes = browser.get("volumes")
    norm = {(v.get("type"), v.get("source"), v.get("target")) for v in volumes if isinstance(v, dict)}
    if ("bind", "/data/devbox/browser", "/config") not in norm:
        fail("browser must bind /data/devbox/browser -> /config")


canonical_rendered = {
    "services": {
        "browser": {
            "profiles": ["browser"],
            "environment": {"PASSWORD": "TEST_ONLY_NOT_A_SECRET"},
            "ports": [{"host_ip": "127.0.0.1", "published": "8081", "target": 3000}],
            "volumes": [{"type": "bind", "source": "/data/devbox/browser", "target": "/config"}],
        }
    }
}
validate_rendered(json.dumps(canonical_rendered))

# Mutations the rendered validator must reject.
for label, mutate in (
    ("public bind", lambda m: m["services"]["browser"]["ports"].__setitem__(0, {"host_ip": "0.0.0.0", "published": "8081", "target": 8080})),
    ("wrong port", lambda m: m["services"]["browser"]["ports"].__setitem__(0, {"host_ip": "127.0.0.1", "published": "9999", "target": 8080})),
    ("no persistence", lambda m: m["services"]["browser"].__setitem__("volumes", [])),
):
    candidate = json.loads(json.dumps(canonical_rendered))
    mutate(candidate)
    try:
        validate_rendered(json.dumps(candidate))
    except AssertionError:
        pass
    else:
        fail(f"rendered validator accepted mutation: {label}")

print("browser_service=PASS")
