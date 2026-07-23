#!/usr/bin/env python3
"""Fail-closed Auto-Dev Health teardown/readback for an LOS fast worktree.

This wrapper deliberately does not infer absence from ``status.sh`` output.
It binds the frozen Auto-Dev runtime identity to one LOS worktree, delegates
the existing target-local teardown, and then proves that the exact compose
project, database, cache namespaces, registry row, and worktree env file are
absent. Compose-project networks and volumes must also be absent; the shared
external LOS infrastructure network is never selected. Shared infrastructure
must be running for database/cache absence to be provable; unavailable
infrastructure is a blocking result, never success.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


class HealthProofError(RuntimeError):
    """The exact LOS runtime could not be identified or proved absent."""


_DOMAIN = "los"
_PROJECT = "los_app_los_django"
_CONTAINER_SUFFIXES = (
    "django",
    "celeryworker",
    "celerybeat",
    "npm_build_ui_vue3",
    "npm_build_ui",
)
_CACHE_COUNT_SCRIPT = (
    "local cursor='0'; local count=0; repeat "
    "local result=redis.call('SCAN',cursor,'MATCH',ARGV[1],'COUNT',1000); "
    "cursor=result[1]; count=count+#result[2] until cursor=='0'; return count"
)


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HealthProofError(f"cannot execute {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise HealthProofError(f"command failed ({' '.join(command)}): {detail}")
    return result


def _git_path(root: Path, flag: str) -> Path:
    result = _run(["git", "-C", str(root), "rev-parse", flag], check=True)
    value = Path(result.stdout.strip())
    if not value.is_absolute():
        value = root / value
    return value.resolve()


def _normalize_slug(worktree: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", worktree.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:40]
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", slug):
        raise HealthProofError("worktree name does not resolve to a safe LOS fast-worktree slug")
    return slug


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _registry_rows(state_dir: Path, slug: str) -> list[list[str]]:
    registry = state_dir / "registry.tsv"
    if not registry.is_file():
        return []
    rows: list[list[str]] = []
    for line in registry.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[1] == slug:
            rows.append(fields)
    return rows


def _validate_identity(args: argparse.Namespace) -> tuple[Path, Path, str, str, str]:
    if args.domain != _DOMAIN or args.project != _PROJECT:
        raise HealthProofError(
            f"this wrapper is scoped only to {_DOMAIN}/{_PROJECT}; "
            f"received {args.domain}/{args.project}"
        )
    expected_identity = f"{args.domain}-{args.project}-{args.worktree}"
    env_identity = os.environ.get("AUTO_DEV_RUNTIME_ID", "")
    if args.runtime_identity != expected_identity:
        raise HealthProofError(
            "runtime identity does not equal the declared domain-project-worktree identity"
        )
    if env_identity != expected_identity:
        raise HealthProofError(
            "AUTO_DEV_RUNTIME_ID does not equal the declared domain-project-worktree identity"
        )

    repository_root = Path(args.repository_root).expanduser().resolve()
    if not repository_root.is_dir():
        raise HealthProofError(
            f"configured repository root is not a directory: {repository_root}"
        )

    declared_worktree_path = Path(args.worktree_path).expanduser()
    if declared_worktree_path.name != args.worktree:
        raise HealthProofError(
            "registered worktree path basename does not equal the declared worktree identity"
        )
    worktree_path = declared_worktree_path.resolve()
    if not worktree_path.is_dir():
        raise HealthProofError(f"registered worktree path is not a directory: {worktree_path}")

    actual_worktree_root = _git_path(worktree_path, "--show-toplevel")
    if actual_worktree_root != worktree_path:
        raise HealthProofError("worktree path is not the exact Git worktree root")
    if _git_path(repository_root, "--git-common-dir") != _git_path(
        worktree_path, "--git-common-dir"
    ):
        raise HealthProofError("worktree does not belong to the canonical repository")

    slug = _normalize_slug(args.worktree)
    stack_name = f"los-{slug}"
    database_name = f"los_{slug.replace('-', '_')}"
    state_dir = Path(
        os.environ.get("FWT_STATE_DIR", str(Path.home() / ".los-fast-worktree"))
    ).expanduser()
    rows = _registry_rows(state_dir, slug)
    if len(rows) > 1:
        raise HealthProofError(f"multiple LOS fast-worktree registry rows match slug {slug}")
    if rows and Path(rows[0][2]).expanduser().resolve() != worktree_path:
        raise HealthProofError(
            "LOS fast-worktree registry row points at a different worktree path"
        )

    env_values = _parse_env_file(worktree_path / ".env.worktree")
    if env_values and (
        env_values.get("FWT_SLUG") != slug
        or env_values.get("LOS_STACK_NAME") != stack_name
    ):
        raise HealthProofError(
            "worktree .env.worktree identity does not match the declared runtime"
        )
    return repository_root, worktree_path, slug, stack_name, database_name


def _require_running(container: str, purpose: str) -> None:
    result = _run(["docker", "inspect", "--format", "{{.State.Running}}", container])
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise HealthProofError(
            f"shared {purpose} container {container} is unavailable; "
            "database/cache absence cannot be proved while shared infrastructure is down"
        )


def _query_database_count(container: str, database_name: str) -> int:
    sql = f"SELECT count(*) FROM pg_database WHERE datname='{database_name}';"
    result = _run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-tAq",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-c",
            sql,
        ]
    )
    if result.returncode != 0:
        raise HealthProofError(
            f"cannot query shared Postgres for exact database {database_name}: "
            f"{result.stderr.strip() or 'query failed'}"
        )
    try:
        return int(result.stdout.strip())
    except (IndexError, ValueError) as exc:
        raise HealthProofError(
            f"unexpected Postgres absence readback for {database_name}"
        ) from exc


def _query_cache_count(container: str, pattern: str) -> int:
    config = _run(
        [
            "docker",
            "exec",
            container,
            "redis-cli",
            "--raw",
            "CONFIG",
            "GET",
            "databases",
        ]
    )
    if config.returncode != 0:
        raise HealthProofError(
            f"cannot enumerate logical databases in cache container {container}: "
            f"{config.stderr.strip() or 'query failed'}"
        )
    try:
        database_count = int(config.stdout.splitlines()[-1].strip())
    except (IndexError, ValueError) as exc:
        raise HealthProofError(
            f"unexpected logical-database readback from cache container {container}"
        ) from exc
    if not 1 <= database_count <= 1024:
        raise HealthProofError(
            f"unsafe logical-database count from cache container {container}: {database_count}"
        )

    total = 0
    for database in range(database_count):
        result = _run(
            [
                "docker",
                "exec",
                container,
                "redis-cli",
                "-n",
                str(database),
                "--raw",
                "EVAL",
                _CACHE_COUNT_SCRIPT,
                "0",
                pattern,
            ]
        )
        if result.returncode != 0:
            raise HealthProofError(
                f"cannot query cache container {container} database {database} for exact "
                f"namespace {pattern}: {result.stderr.strip() or 'query failed'}"
            )
        try:
            total += int(result.stdout.strip())
        except ValueError as exc:
            raise HealthProofError(
                f"unexpected cache absence readback from {container} database {database} "
                f"for {pattern}"
            ) from exc
    return total


def _prove_no_compose_resources(resource: str, stack_name: str) -> None:
    """Prove one exact Compose project owns no residual network or volume."""

    label_rows = _run(
        [
            "docker",
            resource,
            "ls",
            "--filter",
            f"label=com.docker.compose.project={stack_name}",
            "--format",
            "{{.Name}}",
        ]
    )
    if label_rows.returncode != 0:
        raise HealthProofError(
            f"cannot enumerate {resource}s for the exact compose project {stack_name}"
        )
    labeled = [line.strip() for line in label_rows.stdout.splitlines() if line.strip()]
    if labeled:
        raise HealthProofError(
            f"compose project {stack_name} still has {resource}s: {', '.join(labeled)}"
        )

    # External/shared resources are not project-labeled. Check only the exact
    # Compose-owned naming prefix as a belt-and-suspenders guard for an older or
    # partially removed resource whose label is unavailable.
    name_rows = _run(
        [
            "docker",
            resource,
            "ls",
            "--filter",
            f"name={stack_name}_",
            "--format",
            "{{.Name}}",
        ]
    )
    if name_rows.returncode != 0:
        raise HealthProofError(
            f"cannot enumerate exact {resource} name prefix for {stack_name}"
        )
    prefix = f"{stack_name}_"
    named = [
        line.strip()
        for line in name_rows.stdout.splitlines()
        if line.strip().startswith(prefix)
    ]
    if named:
        raise HealthProofError(
            f"target-local compose {resource} prefix still exists: {', '.join(named)}"
        )


def _prove_absent(
    *,
    worktree_path: Path,
    slug: str,
    stack_name: str,
    database_name: str,
) -> None:
    infra_name = os.environ.get("LOS_INFRA_NAME", "los-infra")
    postgres = os.environ.get("FWT_INFRA_POSTGRES_CONTAINER", f"{infra_name}_postgres")
    redis = f"{infra_name}_redis"
    valkey = f"{infra_name}_valkey"

    # These checks are intentionally first.  A stopped service is unknown,
    # not proof that its target-local data is absent.
    _require_running(postgres, "Postgres")
    _require_running(redis, "Redis")
    _require_running(valkey, "Valkey")

    project_rows = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={stack_name}",
            "--format",
            "{{.ID}}",
        ]
    )
    if project_rows.returncode != 0:
        raise HealthProofError("cannot enumerate containers for the exact compose project")
    if project_rows.stdout.strip():
        raise HealthProofError(f"compose project {stack_name} still has containers")
    prefix_rows = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^/{stack_name}_",
            "--format",
            "{{.ID}}",
        ]
    )
    if prefix_rows.returncode != 0:
        raise HealthProofError(f"cannot enumerate container prefix for {stack_name}")
    if prefix_rows.stdout.strip():
        raise HealthProofError(f"target-local container prefix still exists: {stack_name}_")
    for suffix in _CONTAINER_SUFFIXES:
        container = f"{stack_name}_{suffix}"
        named_rows = _run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=^/{container}$",
                "--format",
                "{{.ID}}",
            ]
        )
        if named_rows.returncode != 0:
            raise HealthProofError(f"cannot enumerate exact container name {container}")
        if named_rows.stdout.strip():
            raise HealthProofError(f"target-local container still exists: {container}")

    _prove_no_compose_resources("network", stack_name)
    _prove_no_compose_resources("volume", stack_name)

    database_count = _query_database_count(postgres, database_name)
    if database_count != 0:
        raise HealthProofError(f"target-local database still exists: {database_name}")
    cache_pattern = f"{stack_name}:*"
    for container in (redis, valkey):
        cache_count = _query_cache_count(container, cache_pattern)
        if cache_count != 0:
            raise HealthProofError(
                f"target-local cache namespace {cache_pattern} still has {cache_count} keys "
                f"in {container}"
            )

    state_dir = Path(
        os.environ.get("FWT_STATE_DIR", str(Path.home() / ".los-fast-worktree"))
    ).expanduser()
    if _registry_rows(state_dir, slug):
        raise HealthProofError(f"LOS fast-worktree registry still contains slug {slug}")
    if (worktree_path / ".env.worktree").exists():
        raise HealthProofError("target worktree still contains .env.worktree")


def _teardown(
    repository_root: Path,
    worktree_path: Path,
    worktree: str,
    slug: str,
    stack_name: str,
    database_name: str,
) -> None:
    # Prove every shared data plane is queryable before allowing down.sh to
    # remove containers/registry state.  This avoids reporting a partial
    # teardown as success when Postgres or either cache is unavailable.
    infra_name = os.environ.get("LOS_INFRA_NAME", "los-infra")
    _require_running(
        os.environ.get("FWT_INFRA_POSTGRES_CONTAINER", f"{infra_name}_postgres"),
        "Postgres",
    )
    _require_running(f"{infra_name}_redis", "Redis")
    _require_running(f"{infra_name}_valkey", "Valkey")
    # A running container is not necessarily queryable.  Prove every data
    # plane can answer the exact scoped query before allowing target-local
    # teardown to remove the easier-to-reconstruct container/registry state.
    postgres = os.environ.get("FWT_INFRA_POSTGRES_CONTAINER", f"{infra_name}_postgres")
    _query_database_count(postgres, database_name)
    _query_cache_count(f"{infra_name}_redis", f"{stack_name}:*")
    _query_cache_count(f"{infra_name}_valkey", f"{stack_name}:*")

    down = repository_root / "scripts" / "fast-worktree" / "down.sh"
    if not down.is_file():
        raise HealthProofError(f"LOS fast-worktree teardown script is missing: {down}")
    result = _run(["bash", str(down), "--slug", worktree], cwd=worktree_path)
    if result.returncode != 0:
        raise HealthProofError(
            f"target-local LOS teardown failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    _prove_absent(
        worktree_path=worktree_path,
        slug=slug,
        stack_name=stack_name,
        database_name=database_name,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tear down or prove absent one identity-bound LOS fast-worktree runtime."
        )
    )
    parser.add_argument("action", choices=("teardown", "readback"))
    parser.add_argument("--domain", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--runtime-identity", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository_root, worktree_path, slug, stack_name, database_name = _validate_identity(
            args
        )
        if args.action == "teardown":
            _teardown(
                repository_root,
                worktree_path,
                args.worktree,
                slug,
                stack_name,
                database_name,
            )
        else:
            _prove_absent(
                worktree_path=worktree_path,
                slug=slug,
                stack_name=stack_name,
                database_name=database_name,
            )
    except HealthProofError as exc:
        print(f"LOS Auto-Dev Health blocked: {exc}", file=sys.stderr)
        return 2
    print(
        f"LOS Auto-Dev Health verified absent: identity={args.runtime_identity} "
        f"stack={stack_name} compose=containers,networks,volumes "
        f"database={database_name} caches=redis,valkey"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
