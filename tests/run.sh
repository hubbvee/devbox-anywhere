#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
tests/test-install-devbox.sh
python3 tests/test-compose-model.py
python3 tests/test-install-devbox-lifecycle.py
python3 tests/test-source-trust.py
python3 tests/test-mutations.py
printf 'tests=PASS\n'