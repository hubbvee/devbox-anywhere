#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALLER="$ROOT/scripts/install-devbox"
SHA=0123456789abcdef0123456789abcdef01234567

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -x "$INSTALLER" ]] || fail "installer is missing or not executable"

help=$($INSTALLER --help)
grep -q -- '--yes' <<<"$help" || fail "help omits --yes"
grep -q -- '--dry-run' <<<"$help" || fail "help omits --dry-run"
grep -q -- '--expose-ssh' <<<"$help" || fail "help omits explicit SSH exposure option"
grep -q 'must not be a symlink' "$INSTALLER" || fail "installer omits symlink refusal"

plan=$($INSTALLER --dry-run --yes --approved-commit "$SHA")
grep -q '127.0.0.1:8080:8080' <<<"$plan" || fail "web UI is not loopback-only by default"
grep -q '127.0.0.1:2222:22' <<<"$plan" || fail "SSH is not loopback-only by default"
grep -q '/data/devbox/project:/home/coder/project' <<<"$plan" || fail "fixed data root is missing"
! grep -Eq 'DEVBOX_PASSWORD=[^<]' <<<"$plan" || fail "dry run disclosed or invented a password"

public_plan=$($INSTALLER --dry-run --yes --expose-ssh --approved-commit "$SHA")
grep -q '0.0.0.0:2222:22' <<<"$public_plan" || fail "explicit SSH exposure was not applied"

if $INSTALLER --dry-run --yes --approved-commit "$SHA" --web-bind 0.0.0.0 >/dev/null 2>&1; then
  fail "an arbitrary public web bind was accepted"
fi

if $INSTALLER --dry-run --yes --approved-commit "$SHA" --data-root /tmp/devbox >/dev/null 2>&1; then
  fail "removed arbitrary data-root option was accepted"
fi

if $INSTALLER --dry-run --approved-commit "$SHA" </dev/null >/dev/null 2>&1; then
  fail "noninteractive run proceeded without --yes"
fi

if $INSTALLER --dry-run --yes --approved-commit main >/dev/null 2>&1; then
  fail "non-exact approved commit was accepted"
fi

printf 'install_devbox_acceptance=PASS\n'
