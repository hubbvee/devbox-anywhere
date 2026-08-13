#!/usr/bin/env python3
"""Functional proof for privileged source and environment trust gates."""
from __future__ import annotations

import pathlib
import subprocess
from typing import Any, Callable, cast

# Reuse the lifecycle fixture builder; importing runs its tests too, so this module is
# loaded only by the canonical runner after the lifecycle suite has already passed.
namespace: dict[str, object] = {
    "__name__": "fixture_helpers",
    "__file__": str(pathlib.Path(__file__).with_name("test-install-devbox-lifecycle.py")),
}
source = pathlib.Path(__file__).with_name("test-install-devbox-lifecycle.py").read_text()
exec(compile(source.split("success, log, data = run", 1)[0], "fixture_helpers", "exec"), namespace)
prepare = cast(Callable[..., Any], namespace["prepare"])


def invoke(installer, env, approved):
    return subprocess.run(
        ["bash", str(installer), "--yes", "--approved-commit", approved],
        env=env,
        capture_output=True,
        text=True,
    )


def expect_rejected(mutator, expected: str):
    installer, env, _, _, approved = prepare("success")
    mutator(installer.parents[1], env, approved)
    result = invoke(installer, env, approved)
    assert result.returncode != 0, (expected, result.stdout, result.stderr)
    assert expected in result.stderr, (expected, result.stderr)
    assert "Installation complete" not in result.stdout


expect_rejected(
    lambda repo, env, approved: (repo / "stack/docker-compose.yml").write_text("services: {}\n"),
    "approved checkout is not clean",
)
expect_rejected(
    lambda repo, env, approved: (repo / "UNTRACKED").write_text("unexpected\n"),
    "approved checkout is not clean",
)


def hidden_change(repo, env, approved):
    subprocess.run(["git", "update-index", "--skip-worktree", "stack/docker-compose.yml"], cwd=repo, check=True)
    (repo / "stack/docker-compose.yml").write_text("services: {}\n")


expect_rejected(hidden_change, "checkout bytes differ from approved commit")

# Valid-shape but mismatched exact SHA.
installer, env, _, _, approved = prepare("success")
wrong = "0" * 40 if approved != "0" * 40 else "1" * 40
result = invoke(installer, env, wrong)
assert result.returncode != 0 and "does not match approved commit" in result.stderr

# Fixture stat mock can simulate unsafe source ownership and permissions.
def stat_poison(repo, env, approved, output):
    stat_script = pathlib.Path(env["PATH"].split(":", 1)[0]) / "stat"
    target = repo / "stack/Dockerfile"
    stat_script.write_text(
        f'''#!/bin/sh
fmt=$2
path=$3
case "$fmt" in
  %u) [ "$path" = "{target}" ] && printf '{output[0]}\\n' || printf '0\\n' ;;
  %a)
    if [ "$path" = "{target}" ]; then printf '{output[1]}\\n'
    else case "$path" in */install|*/compose.env) printf '700\\n';; *) printf '755\\n';; esac
    fi ;;
  *) exit 2 ;;
esac
'''
    )


expect_rejected(lambda repo, env, approved: stat_poison(repo, env, approved, ("1000", "755")), "source input is not root-owned")
expect_rejected(lambda repo, env, approved: stat_poison(repo, env, approved, ("0", "777")), "source input is group/other writable")

# Hostile ambient Git/Docker variables must not reach either command. Successful install
# plus mock log's unset poison fields proves Docker sanitization; a fake fsmonitor marker
# proves Git config injection was ignored.
installer, env, log, _, approved = prepare("success")
marker = installer.parents[2] / "FS_MONITOR_EXECUTED"
env.update(
    {
        "GIT_DIR": "/tmp/attacker-git-dir",
        "GIT_WORK_TREE": "/tmp/attacker-worktree",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": f"touch {marker}",
        "DOCKER_HOST": "tcp://attacker.invalid:2375",
        "DOCKER_CONTEXT": "attacker",
        "DOCKER_CONFIG": "/tmp/attacker-docker-config",
    }
)
result = invoke(installer, env, approved)
assert result.returncode == 0, result.stderr
assert not marker.exists()
assert "poison_root=unset poison_web=unset poison_password=unset" in log.read_text()

print("source_trust=PASS")
