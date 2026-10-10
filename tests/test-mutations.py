#!/usr/bin/env python3
"""Prove critical tests turn red for named invariant failures."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "tests/run.sh").read_text()
assert "python3 tests/test-runner-inventory.py\n" in RUNNER, "runner_inventory_guard_missing"


def named_red(output: str, expected: str) -> bool:
    forbidden = ("SyntaxError:", "NameError:", "ImportError:", "ModuleNotFoundError:", "TimeoutExpired")
    if any(item in output for item in forbidden):
        return False
    terminal = [line for line in output.splitlines() if line.startswith("AssertionError:")]
    return len(terminal) == 1 and expected in terminal[0]


assert named_red("Traceback\nAssertionError: runtime_http_probe\n", "runtime_http_probe"), "named_red_positive_control"
assert not named_red("Traceback\nNameError: runtime_http_probe\n", "runtime_http_probe"), "named_red_reject_name_error"
assert not named_red("AssertionError: other\nAssertionError: runtime_http_probe\n", "runtime_http_probe"), "named_red_reject_multiple"

BASELINES = (
    ("compose", ["python3", "tests/test-compose-model.py"]),
    ("installer", ["python3", "tests/test-install-devbox-lifecycle.py"]),
    ("harness", ["python3", "tests/test-agent-harness.py"]),
    ("operations", ["python3", "tests/test-agent-harness-operations.py"]),
    ("inventory", ["python3", "tests/test-runner-inventory.py"]),
)
for name, command in BASELINES:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"mutation_baseline_failed:{name}:{result.stdout}{result.stderr}"


def mutated(
    name: str,
    relative: str,
    old: str,
    new: str,
    test: list[str],
    expected_red: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"devbox-mutation-{name}-") as tmp:
        copy = pathlib.Path(tmp) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
        target = copy / relative
        source = target.read_text()
        count = source.count(old)
        assert count == 1, f"mutation_activation:{name}:count={count}"
        target.write_text(source.replace(old, new, 1))
        result = subprocess.run(test, cwd=copy, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        assert result.returncode != 0, f"mutation_falsely_passed:{name}"
        assert named_red(output, expected_red), (
            f"mutation_wrong_red:{name}:expected={expected_red!r}:"
            f"exit={result.returncode}:output={output[-2000:]!r}"
        )


CASES = [
    ("compose-extra-port", "stack/docker-compose.yml", "before public exposure\n    volumes:\n", 'before public exposure\n      - "0.0.0.0:9999:8080"\n    volumes:\n', ["python3", "tests/test-compose-model.py"], "ports must contain exactly"),
    ("compose-password-override", "stack/docker-compose.yml", "in .env}\n    ports:\n", 'in .env}\n      - "PASSWORD=unsafe-override"\n    ports:\n', ["python3", "tests/test-compose-model.py"], "environment must contain exactly"),
    ("compose-extra-mount", "stack/docker-compose.yml", "/ssh:/home/coder/.ssh\n", "/ssh:/home/coder/.ssh\n      - /tmp:/tmp\n", ["python3", "tests/test-compose-model.py"], "volume wiring/count drifted"),
    ("compose-host-network", "stack/docker-compose.yml", "    environment:\n      # Web login password", "    network_mode: host\n    environment:\n      # Web login password", ["python3", "tests/test-compose-model.py"], "devbox service keys drifted"),
    ("compose-extra-service", "stack/docker-compose.yml", "services:\n", "services:\n  attacker:\n    image: alpine\n", ["python3", "tests/test-compose-model.py"], "service set drifted"),
    ("browser-public-bind", "stack/docker-compose.yml", "${DEVBOX_BROWSER_BIND:-127.0.0.1}:8081:3000", "0.0.0.0:8081:3000", ["python3", "tests/test-browser-service.py"], "browser noVNC must bind"),
    ("browser-literal-password", "stack/docker-compose.yml", "PASSWORD=${DEVBOX_BROWSER_PASSWORD:?set DEVBOX_BROWSER_PASSWORD in .env}", "PASSWORD=hardcoded-secret", ["python3", "tests/test-browser-service.py"], "browser password"),
    ("compose-seed-drops-required-var", "tests/test-compose-model.py", '    "DEVBOX_BROWSER_PASSWORD=TEST_ONLY_NOT_A_SECRET\\n"\n', "", ["python3", "tests/test-compose-model.py"], "seed_missing_required_var:DEVBOX_BROWSER_PASSWORD"),
    ("harness-op-umask-host-inherited", "tests/test-agent-harness-operations.py", "os.umask(0o022)", "os.umask(0o002)", ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("browser-profile-removed", "stack/docker-compose.yml", "    profiles:\n      - browser\n", "", ["python3", "tests/test-browser-service.py"], "browser service must be gated"),
    ("installer-omit-devbox", "scripts/install-devbox", 'helpers="devbox devbox-daemon devbox-relink devbox-session devbox-turn devbox-worktree"', 'helpers="devbox-daemon devbox-relink devbox-session devbox-turn devbox-worktree"', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("installer-omit-daemon", "scripts/install-devbox", 'helpers="devbox devbox-daemon devbox-relink devbox-session devbox-turn devbox-worktree"', 'helpers="devbox devbox-relink devbox-session devbox-turn devbox-worktree"', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("installer-omit-relink", "scripts/install-devbox", 'helpers="devbox devbox-daemon devbox-relink devbox-session devbox-turn devbox-worktree"', 'helpers="devbox devbox-daemon devbox-session devbox-turn devbox-worktree"', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("installer-browser-profile-drop", "scripts/install-devbox", "  compose+=(--profile browser)", "  :", ["python3", "tests/test-install-devbox-lifecycle.py"], "browser_profile_missing"),
    ("installer-browser-password-regate", "scripts/install-devbox", "$browser_pw_line\nEOF\n  unset password\n", "EOF\n  unset password\n", ["python3", "tests/test-install-devbox-lifecycle.py"], "default_install_missing_browser_password"),
    ("installer-helper-order", "scripts/install-devbox", 'helpers="devbox devbox-daemon devbox-relink devbox-session devbox-turn devbox-worktree"', 'helpers="devbox-daemon devbox devbox-relink devbox-session devbox-turn devbox-worktree"', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("harness-omit-session-helper", "scripts/devbox-anywhere", 'for helper in ("devbox", "devbox-daemon", "devbox-relink", "devbox-session", "devbox-turn", "devbox-worktree"):', 'for helper in ("devbox", "devbox-daemon", "devbox-relink", "devbox-turn", "devbox-worktree"):', ["python3", "tests/test-agent-harness-operations.py"], "verify_check_ids"),
    ("harness-wget-argv", "scripts/devbox-anywhere", '"/usr/bin/wget", "-q", "--spider", "http://127.0.0.1:8080/"', '"/usr/bin/true"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-ssh-argv", "scripts/devbox-anywhere", '"/usr/bin/ssh-keyscan", "-T", "2", "-p", "22", "127.0.0.1"', '"/usr/bin/true"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-http-forced-true", "scripts/devbox-anywhere", "http_ok = docker_ok([", "http_ok = True or docker_ok([", ["python3", "tests/test-agent-harness-operations.py"], "runtime_http_probe"),
    ("harness-ssh-forced-true", "scripts/devbox-anywhere", "ssh_ok = docker_ok([", "ssh_ok = True or docker_ok([", ["python3", "tests/test-agent-harness-operations.py"], "runtime_ssh_probe"),
    ("harness-wrong-port", "scripts/devbox-anywhere", '"HostPort": "8080"', '"HostPort": "9999"', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-wrong-mount", "scripts/devbox-anywhere", '("/data/devbox/project", "/home/coder/project")', '("/data/devbox/project-WRONG", "/home/coder/project")', ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("installer-context", "scripts/install-devbox", 'docker_cmd=("${compose_env[@]}" "$DOCKER" --context default)', 'docker_cmd=("${compose_env[@]}" "$DOCKER")', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_exact_argv"),
    ("installer-config", "scripts/install-devbox", 'compose_env=(env -i PATH="$SAFE_PATH" HOME=/root DOCKER_CONFIG="$DOCKER_CONFIG")', 'compose_env=(env -i PATH="$SAFE_PATH" HOME=/root)', ["python3", "tests/test-install-devbox-lifecycle.py"], "docker_config"),
    ("installer-recovery-context", "scripts/install-devbox", "docker --context default logs devbox", "docker logs devbox", ["python3", "tests/test-install-devbox-lifecycle.py"], "recovery_docker_context"),
    ("installer-status-context", "scripts/install-devbox", "docker --context default compose --env-file", "docker compose --env-file", ["python3", "tests/test-install-devbox-lifecycle.py"], "status_docker_context"),
    ("harness-context", "scripts/devbox-anywhere", 'return run([docker, "--context", "default", *arguments], clean=True)', "return run([docker, *arguments], clean=True)", ["python3", "tests/test-agent-harness-operations.py"], "runtime_exact_argv"),
    ("harness-config", "scripts/devbox-anywhere", '"DOCKER_CONFIG": DOCKER_CONFIG,', '"IGNORED_DOCKER_CONFIG": DOCKER_CONFIG,', ["python3", "tests/test-agent-harness-operations.py"], "runtime_docker_config"),
    ("json-option-reflection", "scripts/devbox-anywhere", 'safe_message = "unknown option"', "safe_message = message", ["python3", "tests/test-agent-harness.py"], "json_unknown_option_redaction"),
    ("json-command-reflection", "scripts/devbox-anywhere", 'command = next((item for item in sys.argv[1:] if item in known), "unknown")', 'command = next((item for item in sys.argv[1:] if not item.startswith("-")), "unknown")', ["python3", "tests/test-agent-harness.py"], "json_command_redaction"),
    ("plan-browser-flag-drop", "scripts/devbox-anywhere", 'command.add_argument("--with-browser", action="store_true")', "pass", ["python3", "tests/test-agent-harness.py"], "recognized plan flag"),
    ("session-convention-drop", "scripts/devbox-session", '"$project"-?*) : ;;', '?*) : ;;', ["python3", "tests/test-session-registry.py"], "off-convention agent must fail"),
    ("session-dupe-accept", "scripts/devbox-session", '[ "$matches" -eq 1 ] || {', '[ "$matches" -ge 1 ] || {', ["python3", "tests/test-session-registry.py"], "duplicate agent must fail closed"),
    ("turn-take-steal", "scripts/devbox-turn", 'die "turn held by ${cur:-unknown} for $wt (use release, or wait for TTL=$TTL s)"', 'write_lock "$ld"', ["python3", "tests/test-turn-lock.py"], "second take must fail closed"),
    ("turn-take-missing-worktree", "scripts/devbox-turn", '[ -d "$wt" ] || die "worktree does not exist: $wt"', 'true', ["python3", "tests/test-turn-lock.py"], "take on a nonexistent worktree must fail"),
    ("turn-foreign-release", "scripts/devbox-turn", '[ "$cur" = "$HOLDER" ] || die "turn held by ${cur:-unknown}, not $HOLDER; refusing to release"', 'true', ["python3", "tests/test-turn-lock.py"], "non-holder release must fail"),
    ("worktree-dirty-remove", "scripts/devbox-worktree", 'die "worktree has uncommitted changes: $worktree (use --force to discard)"', 'true', ["python3", "tests/test-worktree-helper.py"], "dirty worktree must not be removed without --force"),
    ("worktree-convention-drop", "scripts/devbox-worktree", 'die "agent id must be \'${1}-<suffix>\': $2"', 'true', ["python3", "tests/test-worktree-helper.py"], "off-convention agent must be rejected"),
    ("worktree-postadd-ignore-failure", "scripts/devbox-worktree", 'exit "$hook_status"', 'true', ["python3", "tests/test-worktree-helper.py"], "a failing post-add hook must be surfaced"),
    ("status-dirty-blind", "scripts/devbox-session", '[ -n "$(git -C "$worktree" status --porcelain 2>/dev/null)" ] && dirty=true', ':', ["python3", "tests/test-session-status.py"], "status_dirty_true"),
    ("status-merged-blind", "scripts/devbox-session", 'if [ "$new" = false ] && git -C "$worktree" merge-base --is-ancestor "$branch" "$b" 2>/dev/null; then merged=true; fi', ':', ["python3", "tests/test-session-status.py"], "status_merged_true"),
    ("status-reapable-loosened", "scripts/devbox-session", 'if [ "$merged" = true ] && [ "$newness_known" = true ] && [ "$dirty" = false ] && [ "$turn" = free ] && [ "$activity" != working ]; then reapable=true; fi', 'reapable=true', ["python3", "tests/test-session-status.py"], "status_reapable_false_when_dirty"),
    ("status-activity-fabricated", "scripts/devbox-session", '[ -n "$pcmd" ] || { printf \'unknown\'; return; }', ':', ["python3", "tests/test-session-status.py"], "act_unknown_on_empty_cmd"),
    ('status-blocked-last-blank-line', 'scripts/devbox-session', 'tmux capture-pane -p -t "=$1:$2" 2>/dev/null | grep -n \'[^[:space:]]\' | tail -n1 | cut -d: -f2-', 'tmux capture-pane -p -t "=$1:$2" 2>/dev/null | grep -n \'\' | tail -n1 | cut -d: -f2-', ['python3', 'tests/test-session-activity-faketmux.py'], 'must read blocked'),
    ('status-fresh-reads-merged', 'scripts/devbox-session', 'if [ "$new" = false ] && git -C "$worktree" merge-base --is-ancestor "$branch" "$b" 2>/dev/null; then merged=true; fi', 'if git -C "$worktree" merge-base --is-ancestor "$branch" "$b" 2>/dev/null; then merged=true; fi', ['python3', 'tests/test-session-status.py'], 'fresh_agent_not_merged'),
    ('status-reapable-includes-working', 'scripts/devbox-session', '[ "$turn" = free ] && [ "$activity" != working ]; then reapable=true; fi', '[ "$turn" = free ]; then reapable=true; fi', ['python3', 'tests/test-session-status.py'], 'reapable_excludes_working'),
    ('status-table-hides-dirty', 'scripts/devbox-session', 'elif [ "$merged" = true ] && [ "$dirty" = true ]; then gs="merged+dirty"', 'elif [ "$merged" = true ] && [ "$dirty" = true ]; then gs="merged"', ['python3', 'tests/test-session-status.py'], 'merged+dirty'),
    ('status-new-hides-dirty', 'scripts/devbox-session', 'if [ "$new" = true ] && [ "$dirty" = true ]; then gs="new+dirty"\n          elif [ "$new" = true ]; then gs="new"', 'if [ "$new" = true ]; then gs="new"', ['python3', 'tests/test-session-status.py'], 'new+dirty'),
    ('status-legacy-reflog-fallback-dropped', 'scripts/devbox-session', '*"Created from"*) [ "$nlines" -eq 1 ] && new=true ;;', '*"Created from"*) : ;;', ['python3', 'tests/test-session-status.py'], 'legacy_fresh_is_new'),
    ("runner-omit-operations", "tests/run.sh", "python3 tests/test-agent-harness-operations.py\n", "", ["python3", "tests/test-runner-inventory.py"], "runner_inventory_mismatch"),
    ("runner-omit-inventory", "tests/run.sh", "python3 tests/test-runner-inventory.py\n", "", ["python3", "tests/test-mutations.py"], "runner_inventory_guard_missing"),
    ("relink-dropin-loading-removed", "scripts/devbox-relink", 'relink "$target" "$link"', ":", ["python3", "tests/test-relink-dropins.py"], "drop-in mytool relink missing"),
    ("relink-missing-source-not-skipped", "scripts/devbox-relink", 'echo "  skip (missing source): $link -> $target" >&2\n          continue', 'echo "  skip (missing source): $link -> $target" >&2\n          :', ["python3", "tests/test-relink-dropins.py"], "never create a dangling link"),
    ("relink-extra-field-guard-removed", "scripts/devbox-relink", 'if [ -z "$link" ] || [ -n "$extra" ]; then', 'if [ -z "$link" ]; then', ["python3", "tests/test-relink-dropins.py"], "never create a link at the truncated path"),
    ("installer-backup-removed", "scripts/install-devbox", 'cp -p "$dst" "$bak"', ":", ["python3", "tests/test-install-preserve.py"], "expected exactly one backup"),
    ("relink-targets-ignores-dangling", "scripts/devbox-anywhere", "            if dangling:", "            if False:", ["python3", "tests/test-verify-invariants.py"], "must be WARN"),
    ("relink-probe-writethrough-regressed", "scripts/devbox-anywhere", 'if [ ! -L "$l" ]; then printf \'DANGLING %s -> %s\\n\' "$l" "$t"; fi', 'if [ ! -L "$l" ] || [ ! -e "$l" ]; then printf \'DANGLING %s -> %s\\n\' "$l" "$t"; fi', ["python3", "tests/test-relink-targets-probe.py"], "fresh box must report no dangling targets"),
    ("relink-probe-loader-line-reparsed", "scripts/devbox-anywhere", 'grep -E \'^relink[[:space:]]+"\\$HOME/[^"]*"[[:space:]]+"\\$HOME/[^"]*"\'', "grep -E '^[[:space:]]*relink '", ["python3", "tests/test-relink-targets-probe.py"], "must not parse the loader call"),
    ("relink-missing-dir-source-mkdir", "scripts/devbox-relink", 'mkdir -p "$HOME/.local/share/gh-config" "$HOME/.local/share/terminfo"', ':', ["python3", "tests/test-relink-targets-probe.py"], "must land in the persisted store"),
    ("relink-probe-absent-link-passes", "scripts/devbox-anywhere", 'if [ ! -L "$l" ]; then printf \'DANGLING %s -> %s\\n\' "$l" "$t"; fi', 'if [ -e "$l" ] && [ ! -L "$l" ]; then printf \'DANGLING %s -> %s\\n\' "$l" "$t"; fi', ["python3", "tests/test-relink-targets-probe.py"], "an absent shipped link must be flagged"),
    ("sshd-penalty-exempt-removed", "stack/config/devbox-sshd.conf", 'PerSourcePenaltyExemptList 127.0.0.1,::1', '# PerSourcePenaltyExemptList 127.0.0.1,::1', ["python3", "tests/test-ssh-penalty-exempt.py"], "PerSourcePenaltyExemptList"),
    ("gate-charset-check-dropped", "scripts/devbox-status-gate", '  *[!A-Za-z0-9._\\ -]*) deny charset ;;\n', '', ["python3", "tests/test-status-gate.py"], "gate_deny_reason"),
    ("gate-length-check-dropped", "scripts/devbox-status-gate", '[ "${#req}" -le 80 ] || deny length', ':', ["python3", "tests/test-status-gate.py"], "gate_deny_reason"),
    ("gate-project-dash-dot-accepted", "scripts/devbox-status-gate", '    -*|.*) deny project ;;\n', '', ["python3", "tests/test-status-gate.py"], "gate_hostile_not_denied"),
    ("gate-env-scrub-dropped", "scripts/devbox-status-gate", 'exec /usr/bin/env -i HOME=', 'exec /usr/bin/env HOME=', ["python3", "tests/test-status-gate.py"], "gate_env_scrubbed"),
    ("gate-path-not-fixed", "scripts/devbox-status-gate", 'SAFE_PATH=/usr/bin:/bin\n', 'SAFE_PATH=$PATH\n', ["python3", "tests/test-status-gate.py"], "gate_fixed_path"),
    ("gate-helper-via-path", "scripts/devbox-status-gate", 'session=$bindir/devbox-session', 'session=$(command -v devbox-session || true)', ["python3", "tests/test-status-gate.py"], "gate_allowed_exec"),
    ("gate-symlink-helper-accepted", "scripts/devbox-status-gate", '  [ ! -L "$1" ] || return 1\n', '', ["python3", "tests/test-status-gate.py"], "gate_symlink_helper_denied"),
    ("gate-shared-dir-accepted", "scripts/devbox-status-gate", 'owned_not_shared "$bindir" || deny helper', ':', ["python3", "tests/test-status-gate.py"], "gate_shared_dir_denied"),
    ("gate-allow-log-fail-open", "scripts/devbox-status-gate", 'audit allow "$1" || deny log-failed', 'audit allow "$1" || true', ["python3", "tests/test-status-gate.py"], "gate_allow_fail_closed"),
    ("gate-deny-echoes-request", "scripts/devbox-status-gate", "printf 'devbox-status-gate: denied\\n' >&2", "printf 'devbox-status-gate: denied: %s\\n' \"$req\" >&2", ["python3", "tests/test-status-gate.py"], "gate_deny_no_echo"),
    ("gate-umask-loosened", "scripts/devbox-status-gate", 'umask 077\n', 'umask 022\n', ["python3", "tests/test-status-gate.py"], "gate_log_dir_mode"),
    ("gate-log-chmod-dropped", "scripts/devbox-status-gate", 'chmod 600 "$log" 2>/dev/null || return 1', ':', ["python3", "tests/test-status-gate.py"], "gate_log_mode_tightened"),
    ("gate-log-rotation-dropped", "scripts/devbox-status-gate", 'mv -f -- "$log" "$log.1" 2>/dev/null || return 1', ':', ["python3", "tests/test-status-gate.py"], "gate_log_rotated"),
    ("gate-log-unsanitized", "scripts/devbox-status-gate", "shown=$(printf '%s' \"${req:0:200}\" | LC_ALL=C tr -c ' -~' '?')", 'shown=${req:0:200}', ["python3", "tests/test-status-gate.py"], "gate_log_sanitized"),
    ("gate-eval-exec", "scripts/devbox-status-gate", 'exec /usr/bin/env -i HOME=', 'eval exec /usr/bin/env -i HOME=', ["python3", "tests/test-status-gate.py"], "gate_source_no_eval"),
]

for case in CASES:
    mutated(*case)

print(f"mutation_tests=PASS cases={len(CASES)} named_reds={len(CASES)}")
