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

# Named instance (opt-in): everything derives from the validated name; ports are explicit.
grep -q -- '--instance NAME' <<<"$help" || fail "help omits --instance"
grep -q -- '--web-port N' <<<"$help" || fail "help omits --web-port"
grep -q -- '--ssh-port N' <<<"$help" || fail "help omits --ssh-port"
grep -q -- '--browser-port N' <<<"$help" || fail "help omits --browser-port"
ports=(--web-port 9080 --ssh-port 9022)
instance_plan=$($INSTALLER --dry-run --yes --approved-commit "$SHA" --instance myapp "${ports[@]}")
grep -q 'port: 127.0.0.1:9080:8080' <<<"$instance_plan" || fail "instance web port is not loopback 9080"
grep -q 'port: 127.0.0.1:9022:22' <<<"$instance_plan" || fail "instance SSH port is not loopback 9022"
grep -q '/data/devbox-myapp/project:/home/coder/project' <<<"$instance_plan" || fail "instance data root is missing"
grep -q 'Compose project: devbox-myapp' <<<"$instance_plan" || fail "instance project is missing"
grep -q 'DEVBOX_CONTAINER=devbox-myapp' <<<"$instance_plan" || fail "instance container is missing"
! grep -Eq 'PASSWORD=[^<]' <<<"$instance_plan" || fail "instance dry run disclosed a password"
! grep -q '/data/devbox/' <<<"$instance_plan" || fail "instance dry run references the default data root"

reject() {
  if $INSTALLER --dry-run --yes --approved-commit "$SHA" "$@" >/dev/null 2>&1; then
    fail "accepted: $*"
  fi
}
for name in MyApp my-app my/app ../app my.app 1app aaaaaaaaaaaaaaaa browser default devbox ''; do
  reject --instance "$name" "${ports[@]}"
done
reject --instance myapp
reject --instance myapp --web-port 9080
reject --instance myapp --ssh-port 9022
reject --instance myapp --web-port 9080 --ssh-port 9080
reject --instance myapp --web-port 1023 --ssh-port 9022
reject --instance myapp --web-port 65536 --ssh-port 9022
reject --instance myapp --web-port 09080 --ssh-port 9022
reject --instance myapp --web-port 8080 --ssh-port 9022
reject --instance myapp --web-port 9080 --ssh-port 2222
reject --instance myapp --web-port 8081 --ssh-port 9022
reject --instance myapp "${ports[@]}" --with-browser
reject --instance myapp "${ports[@]}" --browser-port 9081
reject --instance myapp "${ports[@]}" --with-browser --browser-port 9022
reject --web-port 9080
reject --ssh-port 9022
reject --with-browser --browser-port 9081
reject --instance myapp "${ports[@]}" --data-root /tmp/devbox

if $INSTALLER --dry-run --approved-commit "$SHA" </dev/null >/dev/null 2>&1; then
  fail "noninteractive run proceeded without --yes"
fi

if $INSTALLER --dry-run --yes --approved-commit main >/dev/null 2>&1; then
  fail "non-exact approved commit was accepted"
fi

printf 'install_devbox_acceptance=PASS\n'
