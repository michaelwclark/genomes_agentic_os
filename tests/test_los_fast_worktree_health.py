from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from genomes_agentic_os.development_delivery import validate_profile


SOURCE_ROOT = Path(__file__).parents[1]
WRAPPER = SOURCE_ROOT / "harness/bin/agentic-os-los-fast-worktree-health.py"


def test_los_runtime_config_example_is_a_valid_identity_bound_profile() -> None:
    profile = yaml.safe_load(
        (
            SOURCE_ROOT
            / "harness/shared_factory/00-programs/development_delivery/templates/development.yml"
        ).read_text(encoding="utf-8")
    )
    overlay = yaml.safe_load(
        (
            SOURCE_ROOT
            / "harness/shared_factory/00-programs/auto_dev/config/examples/los/los_app_los_django/development-runtime.yml"
        ).read_text(encoding="utf-8")
    )
    profile["runtime"] = overlay["runtime"]
    profile["runtime"]["teardown_command"] = profile["runtime"][
        "teardown_command"
    ].replace("__AGENTIC_OS_ROOT__", "/example/agentic-os")
    profile["runtime"]["readback_command"] = profile["runtime"][
        "readback_command"
    ].replace("__AGENTIC_OS_ROOT__", "/example/agentic-os")

    assert validate_profile(profile) == []
    assert overlay["review"]["self"]["family_scope"] == "required_targets"
    assert overlay["review"]["self"]["finding_propagation"] == {
        "copilot": "all_required_targets",
        "blocking": "all_required_targets",
    }
    assert set(overlay["review"]["self"]["dev_standards"].values()) == {"required"}
    assert overlay["review"]["self"]["threads"]["human"] == "never_auto_resolve"
    assert overlay["merge"]["ours"] == {
        "strategy": "squash",
        "provider_authority": "admin_bypass",
        "family_gate": "all_required_targets_ready",
        "order": ["hotfix", "release", "develop"],
    }
    context = {
        "domain": "los",
        "project": "los_app_los_django",
        "repository_root": "/example/los-app-los-django",
        "worktree": "072126-flywl-1234",
        "worktree_path": "/example/worktrees/072126-flywl-1234",
        "runtime_identity": "los-los_app_los_django-072126-flywl-1234",
    }
    for field in ("teardown_command", "readback_command"):
        command = profile["runtime"][field].format(**context)
        assert context["runtime_identity"] in command
        assert str(context["repository_root"]) in command
        assert str(context["worktree_path"]) in command
        assert "agentic-os-los-fast-worktree-health.py" in command

    components = yaml.safe_load(
        (
            SOURCE_ROOT / "harness/shared_factory/00-programs/auto_dev/components.yml"
        ).read_text(encoding="utf-8")
    )
    adapter = next(
        row
        for row in components["runtime_adapters"]
        if row["id"] == "los_fast_worktree_health"
    )
    assert SOURCE_ROOT / adapter["path"] == WRAPPER
    assert adapter["config_example"].endswith(
        "los/los_app_los_django/development-runtime.yml"
    )

    preflight = json.loads(
        (
            SOURCE_ROOT
            / "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-health-preflight.json"
        ).read_text(encoding="utf-8")
    )
    assert preflight["runtime"]["provider"] == "los_fast_worktree"
    for field in ("teardown_command", "readback_command"):
        command = preflight["runtime"][field]
        assert "agentic-os-los-fast-worktree-health.py" in command
        assert "status.sh" not in command


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "072126-flywl-1234"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    scripts = repository / "scripts/fast-worktree"
    scripts.mkdir(parents=True)
    (scripts / "down.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" > \"$FWT_STATE_DIR/down.args\"\n"
        "rm -f \"$FWT_STATE_DIR/registry.tsv\" .env.worktree\n",
        encoding="utf-8",
    )
    (scripts / "status.sh").write_text(
        "#!/usr/bin/env bash\necho '(infra down; cannot enumerate)'\n",
        encoding="utf-8",
    )
    return repository, repository.name


def _fake_docker(tmp_path: Path) -> Path:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker = binary_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
infra = os.environ.get("LOS_INFRA_NAME", "los-infra")
postgres = os.environ.get("FWT_INFRA_POSTGRES_CONTAINER", f"{infra}_postgres")
redis = f"{infra}_redis"
valkey = f"{infra}_valkey"

if args[:2] == ["inspect", "--format"] and args[-1] in {postgres, redis, valkey}:
    if os.environ.get("FAKE_INFRA_RUNNING") == "1":
        print("true")
        raise SystemExit(0)
    raise SystemExit(1)
if args and args[0] == "inspect":
    raise SystemExit(1)
if args[:2] == ["ps", "-a"]:
    print(os.environ.get("FAKE_COMPOSE_CONTAINERS", ""))
    raise SystemExit(0)
if args[:2] == ["network", "ls"]:
    if os.environ.get("FAKE_NETWORK_ENUM_ERROR") == "1":
        print("network enumeration failed", file=sys.stderr)
        raise SystemExit(1)
    if any(value.startswith("label=") for value in args):
        print(os.environ.get("FAKE_NETWORK_LABEL_ROWS", os.environ.get("FAKE_PROJECT_NETWORKS", "")))
    else:
        print(os.environ.get("FAKE_NETWORK_NAME_ROWS", os.environ.get("FAKE_PROJECT_NETWORKS", "")))
    raise SystemExit(0)
if args[:2] == ["volume", "ls"]:
    if os.environ.get("FAKE_VOLUME_ENUM_ERROR") == "1":
        print("volume enumeration failed", file=sys.stderr)
        raise SystemExit(1)
    if any(value.startswith("label=") for value in args):
        print(os.environ.get("FAKE_VOLUME_LABEL_ROWS", os.environ.get("FAKE_PROJECT_VOLUMES", "")))
    else:
        print(os.environ.get("FAKE_VOLUME_NAME_ROWS", os.environ.get("FAKE_PROJECT_VOLUMES", "")))
    raise SystemExit(0)
if args[:3] == ["exec", "-i", postgres]:
    print(os.environ.get("FAKE_DB_COUNT", "0"))
    raise SystemExit(0)
if len(args) >= 2 and args[:2] == ["exec", redis]:
    if "CONFIG" in args:
        print("databases")
        print(os.environ.get("FAKE_CACHE_DATABASES", "1"))
        raise SystemExit(0)
    database = args[args.index("-n") + 1]
    print(os.environ.get(f"FAKE_REDIS_DB_{database}_COUNT", os.environ.get("FAKE_REDIS_COUNT", "0")))
    raise SystemExit(0)
if len(args) >= 2 and args[:2] == ["exec", valkey]:
    if "CONFIG" in args:
        print("databases")
        print(os.environ.get("FAKE_CACHE_DATABASES", "1"))
        raise SystemExit(0)
    database = args[args.index("-n") + 1]
    print(os.environ.get(f"FAKE_VALKEY_DB_{database}_COUNT", os.environ.get("FAKE_VALKEY_COUNT", "0")))
    raise SystemExit(0)
print(f"unexpected docker call: {args}", file=sys.stderr)
raise SystemExit(97)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return binary_dir


def _environment(tmp_path: Path, binary_dir: Path, identity: str) -> tuple[dict[str, str], Path]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "AUTO_DEV_RUNTIME_ID": identity,
            "FWT_STATE_DIR": str(state_dir),
            "PATH": f"{binary_dir}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    return env, state_dir


def _command(action: str, repository: Path, worktree: str, identity: str) -> list[str]:
    return [
        sys.executable,
        str(WRAPPER),
        action,
        "--domain",
        "los",
        "--project",
        "los_app_los_django",
        "--repository-root",
        str(repository),
        "--worktree",
        worktree,
        "--worktree-path",
        str(repository),
        "--runtime-identity",
        identity,
    ]


def test_readback_fails_when_infra_down_even_if_status_hides_residuals(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, state_dir = _environment(tmp_path, binary_dir, identity)
    env.update(
        {
            "FAKE_INFRA_RUNNING": "0",
            "FAKE_DB_COUNT": "1",
            "FAKE_REDIS_COUNT": "2",
            "FAKE_VALKEY_COUNT": "3",
        }
    )
    (state_dir / "registry.tsv").write_text(
        f"1\t{worktree}\t{repository}\t2026-07-21T00:00:00Z\n",
        encoding="utf-8",
    )
    (repository / ".env.worktree").write_text(
        f"LOS_STACK_NAME=los-{worktree}\nFWT_SLUG={worktree}\n",
        encoding="utf-8",
    )

    legacy_status = subprocess.run(
        [
            "bash",
            "-lc",
            f"! bash scripts/fast-worktree/status.sh | grep -F -- '{worktree}'",
        ],
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert legacy_status.returncode == 0

    result = subprocess.run(
        _command("readback", repository, worktree, identity),
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "database/cache absence cannot be proved while shared infrastructure is down" in result.stderr


def test_readback_proves_exact_database_and_both_cache_namespaces_absent(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, _ = _environment(tmp_path, binary_dir, identity)
    env["FAKE_INFRA_RUNNING"] = "1"

    result = subprocess.run(
        _command("readback", repository, worktree, identity),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"identity={identity}" in result.stdout
    assert f"database=los_{worktree.replace('-', '_')}" in result.stdout
    assert "compose=containers,networks,volumes" in result.stdout
    assert "caches=redis,valkey" in result.stdout


def test_readback_blocks_on_exact_database_or_cache_residuals(tmp_path: Path) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    base_env, _ = _environment(tmp_path, binary_dir, identity)
    base_env["FAKE_INFRA_RUNNING"] = "1"

    for variable, value, expected in (
        ("FAKE_DB_COUNT", "1", "target-local database still exists"),
        ("FAKE_REDIS_COUNT", "2", "target-local cache namespace"),
        ("FAKE_VALKEY_COUNT", "3", "target-local cache namespace"),
    ):
        env = dict(base_env)
        env[variable] = value
        result = subprocess.run(
            _command("readback", repository, worktree, identity),
            cwd=repository,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert expected in result.stderr

    env = dict(base_env)
    env.update({"FAKE_CACHE_DATABASES": "2", "FAKE_REDIS_DB_1_COUNT": "4"})
    result = subprocess.run(
        _command("readback", repository, worktree, identity),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "still has 4 keys" in result.stderr


def test_readback_blocks_on_exact_compose_network_or_volume_residuals(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    base_env, _ = _environment(tmp_path, binary_dir, identity)
    base_env["FAKE_INFRA_RUNNING"] = "1"
    stack_name = f"los-{worktree}"

    for variable, value, expected in (
        ("FAKE_PROJECT_NETWORKS", f"{stack_name}_default", "still has networks"),
        ("FAKE_PROJECT_VOLUMES", f"{stack_name}_db", "still has volumes"),
    ):
        env = dict(base_env)
        env[variable] = value
        result = subprocess.run(
            _command("readback", repository, worktree, identity),
            cwd=repository,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert expected in result.stderr


def test_readback_fails_closed_on_network_or_volume_enumeration_errors(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    base_env, _ = _environment(tmp_path, binary_dir, identity)
    base_env["FAKE_INFRA_RUNNING"] = "1"

    for variable, expected in (
        ("FAKE_NETWORK_ENUM_ERROR", "cannot enumerate networks"),
        ("FAKE_VOLUME_ENUM_ERROR", "cannot enumerate volumes"),
    ):
        env = dict(base_env)
        env[variable] = "1"
        result = subprocess.run(
            _command("readback", repository, worktree, identity),
            cwd=repository,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert expected in result.stderr


def test_readback_does_not_treat_shared_external_network_as_project_owned(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, _ = _environment(tmp_path, binary_dir, identity)
    env.update(
        {
            "FAKE_INFRA_RUNNING": "1",
            "FAKE_NETWORK_LABEL_ROWS": "",
            "FAKE_NETWORK_NAME_ROWS": "los-infra_network",
        }
    )

    result = subprocess.run(
        _command("readback", repository, worktree, identity),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_teardown_delegates_exact_slug_then_requires_absence_readback(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, state_dir = _environment(tmp_path, binary_dir, identity)
    env["FAKE_INFRA_RUNNING"] = "1"
    (state_dir / "registry.tsv").write_text(
        f"1\t{worktree}\t{repository}\t2026-07-21T00:00:00Z\n",
        encoding="utf-8",
    )
    (repository / ".env.worktree").write_text(
        f"LOS_STACK_NAME=los-{worktree}\nFWT_SLUG={worktree}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        _command("teardown", repository, worktree, identity),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (state_dir / "down.args").read_text(encoding="utf-8").strip() == f"--slug {worktree}"
    assert not (repository / ".env.worktree").exists()


def test_teardown_blocks_when_container_fallback_leaves_compose_network(
    tmp_path: Path,
) -> None:
    repository, worktree = _repository(tmp_path)
    identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, state_dir = _environment(tmp_path, binary_dir, identity)
    env.update(
        {
            "FAKE_INFRA_RUNNING": "1",
            "FAKE_PROJECT_NETWORKS": f"los-{worktree}_default",
        }
    )
    (state_dir / "registry.tsv").write_text(
        f"1\t{worktree}\t{repository}\t2026-07-21T00:00:00Z\n",
        encoding="utf-8",
    )
    (repository / ".env.worktree").write_text(
        f"LOS_STACK_NAME=los-{worktree}\nFWT_SLUG={worktree}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        _command("teardown", repository, worktree, identity),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "still has networks" in result.stderr
    assert (state_dir / "down.args").is_file()


def test_identity_mismatch_blocks_before_docker_or_teardown(tmp_path: Path) -> None:
    repository, worktree = _repository(tmp_path)
    declared_identity = f"los-los_app_los_django-{worktree}"
    binary_dir = _fake_docker(tmp_path)
    env, state_dir = _environment(tmp_path, binary_dir, declared_identity)
    env["FAKE_INFRA_RUNNING"] = "1"

    result = subprocess.run(
        _command("teardown", repository, worktree, "los-los_app_los_django-other"),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "runtime identity does not equal" in result.stderr
    assert not (state_dir / "down.args").exists()
