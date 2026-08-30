#!/usr/bin/env python3
"""Contract for the always-on headless browser capability baked into the image.

Docker is unavailable on review hosts, so this validates the image definition and the
in-container helper statically, mirroring test-compose-model.py's approach. A real build
smoke is performed separately on a devbox with a Docker daemon.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "stack/Dockerfile").read_text()
CHECK = ROOT / "stack/devbox-browser-check"


def fail(message: str) -> None:
    raise AssertionError(message)


# 1. A pinned Playwright version is installed globally so the capability is reproducible.
if not re.search(r"(?m)^ARG PLAYWRIGHT_VERSION=[0-9]+\.[0-9]+\.[0-9]+$", DOCKERFILE):
    fail("Dockerfile must pin PLAYWRIGHT_VERSION to an exact version")
if "playwright@${PLAYWRIGHT_VERSION}" not in DOCKERFILE:
    fail("Dockerfile must install the pinned playwright version")

# 2. The Chromium browser + its OS dependencies are installed at build time (not lazily
#    at first run, which would require network access on a locked-down devbox).
if "install --with-deps chromium" not in DOCKERFILE:
    fail("Dockerfile must install chromium with OS deps at build time")

# 3. A stable browser path is exported so the helper and agents can find it.
if not re.search(r"(?m)^ENV PLAYWRIGHT_BROWSERS_PATH=", DOCKERFILE):
    fail("Dockerfile must export a stable PLAYWRIGHT_BROWSERS_PATH")

# 4. The smoke helper is shipped and made executable in the image. It lives under stack/
#    (the Docker build context) so the COPY can reach it, unlike scripts/ runtime helpers
#    which are docker-cp'd in after build.
if "COPY devbox-browser-check /usr/local/bin/devbox-browser-check" not in DOCKERFILE:
    fail("Dockerfile must install the devbox-browser-check helper from the build context")
if "chmod +x /usr/local/bin/devbox-browser-check" not in DOCKERFILE:
    fail("Dockerfile must make devbox-browser-check executable")

# 5. The helper exists, is a POSIX-sh script, launches headless Chromium, and fails loud.
if not CHECK.is_file():
    fail("stack/devbox-browser-check must exist")
check_text = CHECK.read_text()
if not check_text.startswith("#!/usr/bin/env node") and not check_text.startswith("#!/usr/bin/env bash") and not check_text.startswith("#!/bin/sh"):
    fail("devbox-browser-check must have a supported shebang")
# It must actually drive a headless browser, not just print a version string.
if "chromium" not in check_text:
    fail("devbox-browser-check must reference chromium")
if "set -e" not in check_text and check_text.startswith("#!/bin/sh"):
    fail("POSIX-sh helper must use set -e to fail loud")

# 6. Playwright must be require()-able: installed into a fixed module dir (not `npm i -g`,
#    which Node's require() does not search) and the helper must point NODE_PATH there.
if 'DEVBOX_BROWSER_HOME=' not in DOCKERFILE:
    fail("Dockerfile must set DEVBOX_BROWSER_HOME for a fixed playwright module dir")
if 'npm install -g "playwright' in DOCKERFILE:
    fail("playwright must not be installed with npm -g (require() cannot resolve it)")
if 'npm install "playwright@${PLAYWRIGHT_VERSION}"' not in DOCKERFILE:
    fail("Dockerfile must install playwright into DEVBOX_BROWSER_HOME/node_modules")
if "NODE_PATH" not in check_text or "DEVBOX_BROWSER_HOME" not in check_text:
    fail("helper must export NODE_PATH from DEVBOX_BROWSER_HOME so require(playwright) resolves")

print("headless_browser=PASS")
