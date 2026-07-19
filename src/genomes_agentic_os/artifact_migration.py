"""Transactional migration for date-prefixed durable artifact names."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tarfile
from typing import Any, Iterable

import yaml

from .artifact_naming import (
    dated_name,
    filesystem_timestamp,
    has_date_prefix,
    legacy_date_from_name,
    load_artifact_naming_policy,
    parse_timestamp,
    strip_legacy_date,
)
from .long_running import (
    TERMINAL_RECEIPT_SCHEMA,
    DurableRunProgress as _MigrationProgress,
    MutationLock as _MutationLock,
    SignalGuard as _SignalRollback,
    atomic_json as _atomic_json,
    utc_now as _utc_now,
)
from .scaffold import expand_path, load_project_code_settings, project_worktree_naming_policy
from .state import work_items as state_work_items
from .state.db import connect, default_db_path


MIGRATION_SCHEMA = "artifact-date-prefix-migration/v1"
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".toml", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}
HISTORICAL_DIR_NAMES = {
    "artifacts",
    "async-runs",
    "development-runs",
    "runs",
    "snapshots",
    "thread-closeouts",
    "worker-runs",
    "worklogs",
}
DEFAULT_MAX_REFERENCE_FILES = 25_000
DEFAULT_MAX_REFERENCE_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_BACKUP_FILES = 100_000
DEFAULT_MAX_BACKUP_BYTES = 10 * 1024 * 1024 * 1024


def _project_roots(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in (
        "domains/*/projects/*",
        "domains/*/02-projects/*",
        "*/02-projects/*",
    ):
        candidates.extend(path for path in root.glob(pattern) if path.is_dir())
    shared = root / "harness" / "shared_factory" / "02-projects"
    if shared.is_dir():
        candidates.extend(path for path in shared.iterdir() if path.is_dir())
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in sorted(candidates):
        key = str(candidate.resolve())
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _domain_roots(root: Path) -> list[Path]:
    candidates = [path for path in (root / "domains").glob("*") if path.is_dir()]
    candidates.extend(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "domain.yml").is_file() and path.parent == root
    )
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in sorted(candidates):
        key = str(candidate.resolve())
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _metadata_created_at(path: Path) -> datetime:
    metadata_path = path if path.is_file() else path / "work.yml"
    if metadata_path.is_file():
        text = metadata_path.read_text(encoding="utf-8", errors="replace")
        if metadata_path.suffix == ".md" and text.startswith("---\n"):
            try:
                text = text.split("---", 2)[1]
            except IndexError:
                text = ""
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            data = {}
        if isinstance(data, dict) and data.get("created_at"):
            return parse_timestamp(
                data["created_at"], fallback=filesystem_timestamp(path)
            )
    return filesystem_timestamp(path)


def _move(
    kind: str,
    source: Path,
    destination: Path,
    when: datetime,
    *,
    method: str = "rename",
) -> dict[str, str]:
    return {
        "kind": kind,
        "source": str(source),
        "destination": str(destination),
        "created_at": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "method": method,
    }


def _is_linked_git_worktree(path: Path) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    probe = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--git-dir", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return False
    values = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if len(values) != 2:
        return False

    def resolve_git_path(value: str) -> Path:
        candidate = Path(value)
        return (
            candidate.resolve()
            if candidate.is_absolute()
            else (path / candidate).resolve()
        )

    git_dir, common_dir = (resolve_git_path(value) for value in values)
    return git_dir != common_dir


def _initialized_submodule_paths(path: Path) -> list[Path]:
    if not (path / ".gitmodules").is_file():
        return []
    probe = subprocess.run(
        ["git", "-C", str(path), "submodule", "status", "--recursive"],
        capture_output=True,
        text=True,
        check=False,
    )
    result: list[Path] = []
    for line in probe.stdout.splitlines():
        match = re.match(r"^[ +U][0-9a-f]+\s+(.+?)(?:\s+\(|$)", line)
        if match and (path / match.group(1) / ".git").is_file():
            result.append(Path(match.group(1)))
    # A worktree may already contain stale relative submodule gitdir pointers,
    # which makes `git submodule status` fail before it can report anything.
    # The initialized checkout remains detectable from its nested .git files.
    for current, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        current_path = Path(current)
        if (
            current_path != path
            and ".git" in files
            and (current_path / ".git").is_file()
        ):
            result.append(current_path.relative_to(path))
    return sorted(set(result))


def _final_path(path: Path, parent_moves: Iterable[dict[str, str]]) -> Path:
    value = str(path)
    for move in sorted(
        parent_moves, key=lambda item: len(item["source"]), reverse=True
    ):
        source = move["source"]
        if value == source or value.startswith(source + os.sep):
            return Path(move["destination"] + value[len(source) :])
    return path


def _named_artifact_roots(root: Path, name: str) -> list[Path]:
    result: list[Path] = []
    for current, dirs, _files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            entry
            for entry in dirs
            if entry not in SKIP_DIRS and entry not in {"lib", "worktrees"}
        ]
        if current_path.name == name:
            result.append(current_path)
            dirs[:] = []
    return sorted(result)


def build_artifact_naming_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    policy = load_artifact_naming_policy(os_root)
    moves: list[dict[str, str]] = []

    for project in _project_roots(os_root):
        work_items = project / "work-items"
        for lane in ("01-intake", "02-active", "03-complete"):
            lane_root = work_items / lane
            if not lane_root.is_dir():
                continue
            for item in sorted(lane_root.iterdir()):
                if (
                    item.name.startswith(".")
                    or item.name == "README.md"
                    or has_date_prefix(item.name, policy)
                ):
                    continue
                when = _metadata_created_at(item)
                destination = item.with_name(
                    dated_name(
                        item.name,
                        when=when,
                        policy=policy,
                        scope="work_items",
                        force=True,
                    )
                )
                moves.append(_move("work_item", item, destination, when))

        worktree_root = project / "worktrees"
        if worktree_root.is_dir():
            worktree_policy = project_worktree_naming_policy(
                os_root,
                load_project_code_settings(project),
            )
            if not worktree_policy.enabled_for("worktrees"):
                continue
            index_data: dict[str, Any] = {}
            index_path = worktree_root / "index.yml"
            if index_path.is_file():
                loaded = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
                index_data = loaded if isinstance(loaded, dict) else {}
            registered = {
                str(entry.get("id") or ""): entry
                for entry in index_data.get("worktrees", [])
                if isinstance(entry, dict)
            }
            for checkout in sorted(worktree_root.iterdir()):
                if checkout.name in {
                    "README.md",
                    "index.yml",
                    "closed.yml",
                } or checkout.name.startswith("."):
                    continue
                if has_date_prefix(checkout.name, worktree_policy):
                    continue
                entry = registered.get(checkout.name, {})
                when = parse_timestamp(
                    entry.get("created_at"), fallback=filesystem_timestamp(checkout)
                )
                destination = checkout.with_name(
                    dated_name(
                        checkout.name,
                        when=when,
                        policy=worktree_policy,
                        scope="worktrees",
                        force=True,
                    )
                )
                if _is_linked_git_worktree(checkout):
                    method = (
                        "git_worktree_repair"
                        if _initialized_submodule_paths(checkout)
                        else "git_worktree"
                    )
                else:
                    method = "rename"
                moves.append(
                    _move("worktree", checkout, destination, when, method=method)
                )

    parent_moves = [move for move in moves if move["kind"] == "work_item"]
    conversation_roots: set[Path] = set()
    for project in _project_roots(os_root):
        for candidate in (project / "logs" / "conversations",):
            if candidate.is_dir():
                conversation_roots.add(candidate)
        work_items = project / "work-items"
        if work_items.is_dir():
            for candidate in work_items.glob("*/*/logs/conversations"):
                if candidate.is_dir():
                    conversation_roots.add(candidate)
            for candidate in work_items.glob("*/*.logs/conversations"):
                if candidate.is_dir():
                    conversation_roots.add(candidate)
    for domain in _domain_roots(os_root):
        candidate = domain / "06-runs-and-logs" / "conversations"
        if candidate.is_dir():
            conversation_roots.add(candidate)
    for candidate in (
        os_root / "harness" / "logs" / "conversations",
        os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "conversations",
    ):
        if candidate.is_dir():
            conversation_roots.add(candidate)

    for conversation_root in (
        sorted(conversation_roots) if policy.enabled_for("conversation_logs") else []
    ):
        for source_before_parent_move in sorted(conversation_root.iterdir()):
            if (
                not source_before_parent_move.is_file()
                or source_before_parent_move.name == "README.md"
                or has_date_prefix(source_before_parent_move.name, policy)
            ):
                continue
            when = legacy_date_from_name(
                source_before_parent_move.name
            ) or filesystem_timestamp(source_before_parent_move)
            new_name = dated_name(
                strip_legacy_date(source_before_parent_move.name),
                when=when,
                policy=policy,
                scope="conversation_logs",
                force=True,
            )
            source = _final_path(source_before_parent_move, parent_moves)
            moves.append(
                _move("conversation_log", source, source.with_name(new_name), when)
            )

    for project in (
        _project_roots(os_root) if policy.enabled_for("thread_closeouts") else []
    ):
        work_items = project / "work-items"
        if not work_items.is_dir():
            continue
        for closeout_root in sorted(work_items.glob("*/*/artifacts/thread-closeouts")):
            if not closeout_root.is_dir():
                continue
            for closeout_before_parent_move in sorted(
                path for path in closeout_root.iterdir() if path.is_dir()
            ):
                if has_date_prefix(closeout_before_parent_move.name, policy):
                    continue
                when = legacy_date_from_name(
                    closeout_before_parent_move.name
                ) or filesystem_timestamp(closeout_before_parent_move)
                source = _final_path(closeout_before_parent_move, parent_moves)
                new_name = dated_name(
                    strip_legacy_date(closeout_before_parent_move.name),
                    when=when,
                    policy=policy,
                    scope="thread_closeouts",
                    force=True,
                )
                moves.append(
                    _move("thread_closeout", source, source.with_name(new_name), when)
                )

    for async_root in (
        _named_artifact_roots(os_root, "async-runs")
        if policy.enabled_for("async_runs")
        else []
    ):
        for run_before_parent_move in sorted(
            path for path in async_root.iterdir() if path.is_dir()
        ):
            if has_date_prefix(run_before_parent_move.name, policy):
                continue
            when = legacy_date_from_name(
                run_before_parent_move.name
            ) or filesystem_timestamp(run_before_parent_move)
            source = _final_path(run_before_parent_move, parent_moves)
            new_name = dated_name(
                strip_legacy_date(run_before_parent_move.name),
                when=when,
                policy=policy,
                scope="async_runs",
                force=True,
            )
            moves.append(_move("async_run", source, source.with_name(new_name), when))

    for domain in _domain_roots(os_root) if policy.enabled_for("run_logs") else []:
        runs_root = domain / "06-runs-and-logs" / "runs"
        if not runs_root.is_dir():
            continue
        for run in sorted(runs_root.iterdir()):
            if (
                not run.is_dir()
                or run.name.startswith(".")
                or has_date_prefix(run.name, policy)
            ):
                continue
            when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
            new_name = dated_name(
                strip_legacy_date(run.name),
                when=when,
                policy=policy,
                scope="run_logs",
                force=True,
            )
            moves.append(_move("run_log", run, run.with_name(new_name), when))

    reports_root = (
        os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "reports"
    )
    if reports_root.is_dir() and policy.enabled_for("report_runs"):
        for report_root in sorted(
            path for path in reports_root.iterdir() if path.is_dir()
        ):
            for run in sorted(path for path in report_root.iterdir() if path.is_dir()):
                if has_date_prefix(run.name, policy):
                    continue
                when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
                new_name = dated_name(
                    strip_legacy_date(run.name),
                    when=when,
                    policy=policy,
                    scope="report_runs",
                    force=True,
                )
                moves.append(_move("report_run", run, run.with_name(new_name), when))

    for project in (
        _project_roots(os_root) if policy.enabled_for("development_runs") else []
    ):
        development_root = project / "state" / "development-runs"
        if not development_root.is_dir():
            continue
        for run in sorted(path for path in development_root.iterdir() if path.is_dir()):
            if has_date_prefix(run.name, policy):
                continue
            when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
            new_name = dated_name(
                strip_legacy_date(run.name),
                when=when,
                policy=policy,
                scope="development_runs",
                force=True,
            )
            moves.append(_move("development_run", run, run.with_name(new_name), when))

    moves = [move for move in moves if move["source"] != move["destination"]]
    collisions = [
        {**move, "collision_reason": "destination_exists"}
        for move in moves
        if Path(move["destination"]).exists()
    ]
    by_destination: dict[str, list[dict[str, str]]] = {}
    for move in moves:
        by_destination.setdefault(move["destination"], []).append(move)
    for destination, candidates in by_destination.items():
        if len(candidates) > 1:
            collisions.extend(
                {
                    **move,
                    "collision_reason": "duplicate_planned_destination",
                    "destination": destination,
                }
                for move in candidates
            )
    counts: dict[str, int] = {}
    for move in moves:
        counts[move["kind"]] = counts.get(move["kind"], 0) + 1
    payload = {
        "schema": MIGRATION_SCHEMA,
        "root": str(os_root),
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "policy": {
            "enabled": policy.enabled,
            "date_format": policy.date_format,
            "separator": policy.separator,
            "scopes": dict(policy.scopes),
        },
        "counts": counts,
        "move_count": len(moves),
        "moves": moves,
        "collisions": collisions,
    }
    hash_payload = {
        key: value for key, value in payload.items() if key != "generated_at"
    }
    payload["plan_sha256"] = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True).encode()
    ).hexdigest()
    return payload


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_immutable_history(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    if "06-runs-and-logs" in parts:
        return True
    if "worktrees" in parts:
        return True
    if parts[:2] == ("harness", "logs"):
        return True
    if parts[:3] == ("harness", "shared_factory", "01-inbox"):
        return True
    if parts[:2] == ("runtime", "artifacts"):
        return True
    if parts[:2] in {("runtime", "legacy"), ("runtime", "tools")}:
        return True
    if len(parts) >= 2 and parts[:2] == ("runtime", "state") and "watchers" in parts:
        return True
    if "team_prs" in parts or "secrets" in parts:
        return True
    if any(name == "logs" or name.endswith(".logs") for name in parts):
        return True
    if "04-automations" in parts and "state" in parts:
        return True
    if "work-items" in parts:
        lane_index = parts.index("work-items") + 1
        if lane_index < len(parts) and parts[lane_index] == "03-complete":
            return True
    if any(name in parts for name in HISTORICAL_DIR_NAMES):
        return True
    return any(
        parts[index : index + 2] == ("logs", "conversations")
        for index in range(len(parts) - 1)
    )


def _minimal_backup_paths(
    root: Path,
    plan: dict[str, Any],
    *,
    include_move_sources: bool = True,
) -> list[Path]:
    """Return mutable inputs plus move sources unless a verified full backup exists."""
    candidates = (
        [Path(move["source"]) for move in plan["moves"]] if include_move_sources else []
    )
    control = root / "harness" / "shared_factory" / "00-control-plane"
    candidates.extend(
        path
        for path in (control / "state.db", control / "active-now.json")
        if path.exists()
    )
    candidates.extend(path for path in _iter_reference_files(root) if path.is_file())
    candidates.extend(
        path
        for project in _project_roots(root)
        for path in (
            project / "worktrees" / "index.yml",
            project / "worktrees" / "closed.yml",
            project / "config" / "worktrees.yml",
        )
        if path.exists()
    )
    unique = sorted(set(candidates), key=lambda value: (len(value.parts), str(value)))
    selected: list[Path] = []
    selected_directories: list[Path] = []
    for candidate in unique:
        if any(_is_within(candidate, parent) for parent in selected_directories):
            continue
        selected.append(candidate)
        if candidate.is_dir():
            selected_directories.append(candidate)
    return selected


def _path_stats(paths: Iterable[Path], *, file_limit: int) -> dict[str, Any]:
    files = 0
    size = 0
    truncated = False
    for path in paths:
        if path.is_symlink():
            files += 1
            continue
        if path.is_file():
            files += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
            continue
        if not path.is_dir():
            continue
        for current, dirs, names in os.walk(path, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            current_path = Path(current)
            for name in names:
                files += 1
                try:
                    size += (current_path / name).stat().st_size
                except OSError:
                    pass
                if files >= file_limit:
                    truncated = True
                    return {"files": files, "bytes": size, "truncated": truncated}
    return {"files": files, "bytes": size, "truncated": truncated}


def build_artifact_migration_preflight(
    root: str | Path,
    plan: dict[str, Any] | None = None,
    *,
    include_move_sources_in_backup: bool = True,
    recovery_backup_archive: str | Path | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    migration_plan = plan or build_artifact_naming_plan(os_root)
    reference_files = list(_iter_reference_files(os_root))
    reference_bytes = sum(path.stat().st_size for path in reference_files)
    targeted_files: list[Path] = []
    for scope in _targeted_reference_scopes(os_root, migration_plan["moves"]):
        targeted_files.extend(_iter_reference_files(scope, history_root=os_root))
    targeted_bytes = sum(path.stat().st_size for path in targeted_files)
    backup_paths = _minimal_backup_paths(
        os_root,
        migration_plan,
        include_move_sources=include_move_sources_in_backup,
    )
    backup = _path_stats(backup_paths, file_limit=DEFAULT_MAX_BACKUP_FILES)
    replacements = _reference_replacements(os_root, migration_plan["moves"])
    recovery_evidence: dict[str, Any] | None = None
    if recovery_backup_archive:
        recovery_path = expand_path(recovery_backup_archive)
        if not recovery_path.is_file():
            raise FileNotFoundError(
                f"recovery backup archive does not exist: {recovery_path}"
            )
        with tarfile.open(recovery_path, "r:gz") as recovery_tar:
            first_member = recovery_tar.next()
        if first_member is None:
            raise ValueError(f"recovery backup archive is empty: {recovery_path}")
        recovery_stat = recovery_path.stat()
        recovery_evidence = {
            "path": str(recovery_path),
            "bytes": recovery_stat.st_size,
            "first_member": first_member.name,
        }
    risks: list[str] = []
    if len(reference_files) > DEFAULT_MAX_REFERENCE_FILES:
        risks.append("reference_file_budget_exceeded")
    if reference_bytes > DEFAULT_MAX_REFERENCE_BYTES:
        risks.append("reference_byte_budget_exceeded")
    if backup["truncated"] or backup["files"] >= DEFAULT_MAX_BACKUP_FILES:
        risks.append("backup_file_inventory_truncated")
    if backup["bytes"] > DEFAULT_MAX_BACKUP_BYTES:
        risks.append("backup_byte_budget_exceeded")
    return {
        "schema": "artifact-date-prefix-preflight/v1",
        "generated_at": _utc_now(),
        "plan_sha256": migration_plan["plan_sha256"],
        "move_count": migration_plan["move_count"],
        "replacement_token_count": len(replacements),
        "eligible_reference_files": len(reference_files),
        "eligible_reference_bytes": reference_bytes,
        "targeted_reference_pass_files": len(targeted_files),
        "targeted_reference_pass_bytes": targeted_bytes,
        "rewrite_pass_files": len(reference_files) + len(targeted_files),
        "rewrite_pass_bytes": reference_bytes + targeted_bytes,
        "backup_files": backup["files"],
        "backup_bytes": backup["bytes"],
        "backup_inventory_truncated": backup["truncated"],
        "move_sources_in_backup": include_move_sources_in_backup,
        "recovery_backup": recovery_evidence,
        "budgets": {
            "max_reference_files": DEFAULT_MAX_REFERENCE_FILES,
            "max_reference_bytes": DEFAULT_MAX_REFERENCE_BYTES,
            "max_backup_files": DEFAULT_MAX_BACKUP_FILES,
            "max_backup_bytes": DEFAULT_MAX_BACKUP_BYTES,
        },
        "risks": risks,
        "safe_to_apply": not risks,
    }


def create_migration_backup(
    root: Path,
    backup_dir: Path,
    plan: dict[str, Any],
    *,
    include_move_sources: bool = True,
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest = backup_dir / "migration-plan.json"
    manifest.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = backup_dir / "mutable-state.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as tar:
        for path in _minimal_backup_paths(
            root, plan, include_move_sources=include_move_sources
        ):
            if path.exists() or path.is_symlink():
                tar.add(path, arcname=str(path.relative_to(root)), recursive=True)
    return archive


def extract_migration_backup(archive: Path, root: Path) -> None:
    """Restore a trusted migration archive over operator-owned read-only files."""
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"unsafe backup member path: {member.name}")
            destination = root / member_path
            if (
                destination.exists()
                and destination.is_file()
                and not destination.is_symlink()
            ):
                destination.chmod(destination.stat().st_mode | 0o200)
            tar.extract(member, root)


def _perform_move(move: dict[str, str]) -> None:
    source = Path(move["source"])
    destination = Path(move["destination"])
    if not source.exists() and not source.is_symlink():
        raise FileNotFoundError(f"migration source disappeared: {source}")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"migration destination exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if move["method"] in {"git_worktree", "git_worktree_repair"}:
        common = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = (source / common_path).resolve()
        repository = common_path.parent if common_path.name == ".git" else common_path
        if move["method"] == "git_worktree":
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "worktree",
                    "move",
                    str(source),
                    str(destination),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            submodules = _initialized_submodule_paths(source)
            source.rename(destination)
            try:
                _repair_moved_worktree(repository, destination, submodules)
            except Exception:
                destination.rename(source)
                _repair_moved_worktree(repository, source, submodules)
                raise
    else:
        source.rename(destination)


def _repair_moved_worktree(
    repository: Path, worktree: Path, submodules: list[Path]
) -> None:
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "repair", str(worktree)],
        capture_output=True,
        text=True,
        check=True,
    )
    worktree_git_file = worktree / ".git"
    worktree_match = re.match(
        r"gitdir:\s*(.+)", worktree_git_file.read_text(encoding="utf-8").strip()
    )
    if not worktree_match:
        raise ValueError(f"invalid worktree gitdir file: {worktree_git_file}")
    worktree_git_dir = Path(worktree_match.group(1))
    if not worktree_git_dir.is_absolute():
        worktree_git_dir = (worktree / worktree_git_dir).resolve()
    for relative in submodules:
        submodule_root = worktree / relative
        git_file = submodule_root / ".git"
        match = re.match(
            r"gitdir:\s*(.+)", git_file.read_text(encoding="utf-8").strip()
        )
        if not match:
            raise ValueError(f"invalid submodule gitdir file: {git_file}")
        git_dir = Path(match.group(1))
        if not git_dir.is_absolute():
            git_dir = (submodule_root / git_dir).resolve()
        if not git_dir.is_dir():
            normalized = match.group(1).replace("\\", "/")
            marker = f"/.git/worktrees/{worktree_git_dir.name}/"
            if marker not in normalized:
                raise FileNotFoundError(
                    f"cannot recover stale submodule gitdir: {git_file}"
                )
            git_dir = worktree_git_dir / normalized.split(marker, 1)[1]
        if not git_dir.is_dir():
            raise FileNotFoundError(f"submodule gitdir is missing: {git_dir}")
        git_file.write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "config",
                "--file",
                str(git_dir / "config"),
                "core.worktree",
                str(submodule_root.resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )


def _reference_replacements(
    root: Path, moves: list[dict[str, str]]
) -> list[tuple[str, str]]:
    replacements: dict[str, str] = {}
    for move in moves:
        source = Path(move["source"])
        destination = Path(move["destination"])
        replacements[str(source)] = str(destination)
        try:
            replacements[str(source.relative_to(root))] = str(
                destination.relative_to(root)
            )
        except ValueError:
            pass
    return sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)


def _project_for_path(root: Path, path: Path) -> tuple[str, str, Path] | None:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if (
        len(parts) >= 4
        and parts[0] == "domains"
        and parts[2] in {"projects", "02-projects"}
    ):
        return parts[1], parts[3], root.joinpath(*parts[:4])
    if len(parts) >= 5 and parts[:3] == ("harness", "shared_factory", "02-projects"):
        return "shared_factory", parts[3], root.joinpath(*parts[:4])
    if len(parts) >= 3 and parts[1] == "02-projects":
        return parts[0], parts[2], root.joinpath(*parts[:3])
    return None


def _targeted_reference_scopes(
    root: Path, moves: list[dict[str, str]]
) -> dict[Path, dict[str, str]]:
    scopes: dict[Path, dict[str, str]] = {}
    for move in moves:
        source = Path(move["source"])
        destination = Path(move["destination"])
        kind = move["kind"]
        scope: Path | None = None
        project = _project_for_path(root, destination)
        if project and kind in {
            "work_item",
            "conversation_log",
            "async_run",
            "development_run",
            "thread_closeout",
        }:
            scope = project[2]
        elif kind == "run_log":
            current = destination
            while current != root and current.name != "06-runs-and-logs":
                current = current.parent
            scope = (
                current.parent
                if current.name == "06-runs-and-logs"
                else destination.parent
            )
        elif kind == "report_run":
            scope = root / "harness"
        elif kind == "conversation_log":
            scope = destination.parent
        elif kind == "async_run":
            scope = destination.parent
        if scope is not None:
            scopes.setdefault(scope, {})[source.name] = destination.name
    return scopes


def _iter_reference_files(
    root: Path, *, history_root: Path | None = None
) -> Iterable[Path]:
    immutable_root = history_root or root
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and name != "lib"]
        if _is_immutable_history(immutable_root, current_path):
            dirs[:] = []
        for filename in files:
            path = current_path / filename
            if (
                _is_immutable_history(immutable_root, path)
                or path.suffix.lower() not in TEXT_SUFFIXES
            ):
                continue
            try:
                if path.stat().st_size <= 10 * 1024 * 1024:
                    yield path
            except OSError:
                continue


class _FixedStringMatcher:
    """Longest-token fixed-string replacement without a giant regex."""

    _VALUE = ""

    def __init__(self, replacements: list[tuple[str, str]]) -> None:
        mapping = dict(replacements)
        protected_destinations = set(mapping.values()) - set(mapping)
        self.root: dict[str, Any] = {}
        for token in sorted(set(mapping) | protected_destinations):
            if not token:
                continue
            node = self.root
            for character in token:
                node = node.setdefault(character, {})
            node[self._VALUE] = mapping.get(token, token)

    def replace(self, value: str) -> str:
        if not self.root or not value:
            return value
        output: list[str] = []
        index = 0
        length = len(value)
        while index < length:
            node = self.root.get(value[index])
            if node is None:
                output.append(value[index])
                index += 1
                continue
            cursor = index + 1
            matched_end = cursor if self._VALUE in node else -1
            matched_value = node.get(self._VALUE)
            while cursor < length and value[cursor] in node:
                node = node[value[cursor]]
                cursor += 1
                if self._VALUE in node:
                    matched_end = cursor
                    matched_value = node[self._VALUE]
            if matched_end >= 0:
                output.append(str(matched_value))
                index = matched_end
            else:
                output.append(value[index])
                index += 1
        return "".join(output)


def _replacement_engine(
    replacements: list[tuple[str, str]],
) -> tuple[_FixedStringMatcher | None, Any]:
    if not replacements:
        return None, lambda value: value
    matcher = _FixedStringMatcher(replacements)
    return matcher, matcher.replace


def _rewrite_text_references(
    root: Path,
    replacements: list[tuple[str, str]],
    *,
    progress: _MigrationProgress | None = None,
    history_root: Path | None = None,
) -> list[str]:
    pattern, replace = _replacement_engine(replacements)
    if pattern is None:
        return []

    changed: list[str] = []
    base_files = int(progress.payload.get("files_completed", 0)) if progress else 0
    base_bytes = int(progress.payload.get("bytes_completed", 0)) if progress else 0
    completed_files = 0
    completed_bytes = 0
    for path in _iter_reference_files(root, history_root=history_root):
        before = path.read_text(encoding="utf-8", errors="replace")
        after = replace(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(str(path))
        completed_files += 1
        completed_bytes += len(before.encode("utf-8"))
        if progress and completed_files % 100 == 0:
            progress.update(
                files_completed=base_files + completed_files,
                bytes_completed=base_bytes + completed_bytes,
                current_path=str(path),
            )
    if progress:
        progress.update(
            files_completed=base_files + completed_files,
            bytes_completed=base_bytes + completed_bytes,
            current_path=None,
            force=True,
        )
    return changed


def _rewrite_targeted_references(
    root: Path,
    moves: list[dict[str, str]],
    *,
    progress: _MigrationProgress | None = None,
) -> list[str]:
    changed: list[str] = []
    for scope, mapping in _targeted_reference_scopes(root, moves).items():
        replacements = sorted(
            mapping.items(), key=lambda pair: len(pair[0]), reverse=True
        )
        changed.extend(
            _rewrite_text_references(
                scope,
                replacements,
                progress=progress,
                history_root=root,
            )
        )
    return sorted(set(changed))


def _replace_exact_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_values(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_exact_values(item, replacements)
            for key, item in value.items()
        }
    return value


def _rewrite_worktree_registry_ids(
    root: Path, moves: list[dict[str, str]]
) -> list[str]:
    by_project: dict[Path, dict[str, str]] = {}
    for move in moves:
        if move["kind"] != "worktree":
            continue
        project = _project_for_path(root, Path(move["destination"]))
        if project:
            source_name = Path(move["source"]).name
            destination_name = Path(move["destination"]).name
            mapping = by_project.setdefault(project[2], {})
            mapping[source_name] = destination_name
            mapping[f"worktrees/{source_name}"] = f"worktrees/{destination_name}"
    changed: list[str] = []
    for project_root, replacements in by_project.items():
        for path in (
            project_root / "worktrees" / "index.yml",
            project_root / "worktrees" / "closed.yml",
            project_root / "config" / "worktrees.yml",
        ):
            if not path.is_file():
                continue
            before = yaml.safe_load(path.read_text(encoding="utf-8"))
            after = _replace_exact_values(before, replacements)
            if after != before:
                path.write_text(
                    yaml.safe_dump(after, sort_keys=False), encoding="utf-8"
                )
                changed.append(str(path))
    return changed


def _sqlite_reference_replacements(
    root: Path, moves: list[dict[str, str]]
) -> list[tuple[str, str]]:
    replacements = dict(_reference_replacements(root, moves))
    for move in moves:
        if move["kind"] != "work_item":
            continue
        source = Path(move["source"])
        destination = Path(move["destination"])
        project = _project_for_path(root, destination)
        if project:
            domain, project_name, _ = project
            replacements[f"{domain}:{project_name}:{source.name}"] = (
                f"{domain}:{project_name}:{destination.name}"
            )
    return sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)


def _rewrite_sqlite_references(
    db_path: Path, replacements: list[tuple[str, str]]
) -> int:
    if not db_path.is_file():
        return 0
    pattern, replace = _replacement_engine(replacements)
    if pattern is None:
        return 0
    changed = 0
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_")
        ]
        for table in tables:
            columns = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
                if str(row[2]).upper() in {"", "TEXT"}
            ]
            for column in columns:
                try:
                    rows = conn.execute(
                        f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                updates = []
                for rowid, value in rows:
                    if not isinstance(value, str):
                        continue
                    updated = replace(value)
                    if updated != value:
                        updates.append((updated, rowid))
                if updates:
                    conn.executemany(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?',
                        updates,
                    )
                    changed += len(updates)
        conn.commit()
    finally:
        conn.close()
    return changed


def _reverse_moves(moves: Iterable[dict[str, str]]) -> list[str]:
    failures: list[str] = []
    for move in reversed(list(moves)):
        destination = Path(move["destination"])
        source = Path(move["source"])
        if not destination.exists() and not destination.is_symlink():
            continue
        reverse = {**move, "source": str(destination), "destination": str(source)}
        try:
            _perform_move(reverse)
        except Exception as error:
            # The backup remains the authoritative recovery surface if git or
            # filesystem state changed again during rollback.
            failures.append(
                f"{destination} -> {source}: {type(error).__name__}: {error}"[:2000]
            )
    return failures


def _terminal_receipt(
    path: Path,
    *,
    run_id: str,
    status: str,
    plan: dict[str, Any] | None,
    progress: _MigrationProgress | None,
    error: BaseException | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "run_id": run_id,
        "status": status,
        "finished_at": _utc_now(),
        "plan_sha256": plan.get("plan_sha256") if plan else None,
        "move_count": plan.get("move_count", 0) if plan else 0,
        "error_type": type(error).__name__ if error else None,
        "error": str(error)[:2000] if error else None,
        **extra,
    }
    _atomic_json(path, payload)
    if progress:
        progress.event("run_terminal", status=status, terminal_receipt=str(path))
        progress.update(status=status, phase="terminal", current_path=None, force=True)
    return payload


def apply_artifact_naming_plan(
    root: str | Path,
    *,
    backup_dir: str | Path | None = None,
    allow_high_risk: bool = False,
    recovery_backup_archive: str | Path | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    now = datetime.now(timezone.utc)
    policy = load_artifact_naming_policy(os_root)
    run_id = f"artifact-date-prefix-{now.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
    receipt_name = dated_name(
        f"{now.strftime('%H%M%SZ')}-{os.getpid()}-artifact-date-prefix-migration",
        when=now,
        policy=policy,
        scope="run_logs",
    )
    receipt_dir = (
        os_root
        / "harness"
        / "shared_factory"
        / "06-runs-and-logs"
        / "migrations"
        / receipt_name
    )
    receipt_dir.mkdir(parents=True, exist_ok=False)
    terminal_path = receipt_dir / "terminal-receipt.json"
    lock = _MutationLock(
        os_root
        / "harness"
        / "shared_factory"
        / "00-control-plane"
        / "locks"
        / "artifact-date-prefix-migration.lock",
        run_id=run_id,
        operation="artifact-date-prefix-migration",
    )
    signal_rollback = _SignalRollback()
    lock_acquired = False
    signal_guard_entered = False
    plan: dict[str, Any] | None = None
    progress: _MigrationProgress | None = None
    completed: list[dict[str, str]] = []
    archive: Path | None = None
    backup: Path | None = None
    preflight: dict[str, Any] | None = None
    recovery_archive = (
        expand_path(recovery_backup_archive) if recovery_backup_archive else None
    )
    try:
        signal_rollback.__enter__()
        signal_guard_entered = True
        lock.acquire()
        lock_acquired = True
        plan = build_artifact_naming_plan(os_root)
        progress = _MigrationProgress(
            receipt_dir / "progress.json",
            run_id=run_id,
            operation="artifact-date-prefix-migration",
            items_total=plan["move_count"],
            metadata={"plan_sha256": plan["plan_sha256"]},
        )
        if plan["collisions"]:
            raise ValueError(
                f"artifact naming migration has {len(plan['collisions'])} destination collision(s)"
            )
        if recovery_archive and not recovery_archive.is_file():
            raise FileNotFoundError(
                f"recovery backup archive does not exist: {recovery_archive}"
            )
        preflight = build_artifact_migration_preflight(
            os_root,
            plan,
            include_move_sources_in_backup=recovery_archive is None,
            recovery_backup_archive=recovery_archive,
        )
        _atomic_json(receipt_dir / "preflight.json", preflight)
        progress.update(
            phase="preflight",
            files_total=preflight["rewrite_pass_files"],
            bytes_total=preflight["rewrite_pass_bytes"],
            force=True,
        )
        if preflight["risks"] and not allow_high_risk:
            raise RuntimeError(
                "artifact naming preflight requires explicit --allow-high-risk: "
                + ", ".join(preflight["risks"])
            )

        backup_name = dated_name(
            f"{now.strftime('%H%M%SZ')}-{os.getpid()}-artifact-date-prefix-backup",
            when=now,
            policy=policy,
            scope="run_logs",
        )
        backup = (
            expand_path(backup_dir)
            if backup_dir
            else Path("~/backups/agentic_os").expanduser() / backup_name
        )
        progress.update(phase="backup", current_path=str(backup), force=True)
        archive = create_migration_backup(
            os_root,
            backup,
            plan,
            include_move_sources=recovery_archive is None,
        )
        progress.update(phase="move", current_path=None, force=True)

        with _SignalRollback():
            for move in plan["moves"]:
                progress.event("move_started", index=len(completed) + 1, move=move)
                progress.update(current_path=move["source"], force=True)
                _perform_move(move)
                completed.append(move)
                progress.event("move_completed", index=len(completed), move=move)
                progress.update(
                    items_completed=len(completed), current_path=None, force=True
                )
            replacements = _reference_replacements(os_root, plan["moves"])
            progress.update(
                phase="rewrite_references",
                files_completed=0,
                bytes_completed=0,
                force=True,
            )
            changed_files = _rewrite_text_references(
                os_root, replacements, progress=progress
            )
            changed_files.extend(
                _rewrite_targeted_references(os_root, plan["moves"], progress=progress)
            )
            changed_files.extend(_rewrite_worktree_registry_ids(os_root, plan["moves"]))
            changed_files = sorted(set(changed_files))
            progress.update(
                phase="rewrite_state",
                current_path=str(default_db_path(os_root)),
                force=True,
            )
            sqlite_updates = _rewrite_sqlite_references(
                default_db_path(os_root),
                _sqlite_reference_replacements(os_root, plan["moves"]),
            )
            conn = connect(default_db_path(os_root))
            try:
                projection = state_work_items.write_active_projection(conn, os_root)
            finally:
                conn.close()
            progress.update(phase="post_run_invariants", current_path=None, force=True)
            residual = build_artifact_naming_plan(os_root)
            if residual["move_count"] or residual["collisions"]:
                raise RuntimeError(
                    "artifact naming post-run invariant failed: "
                    f"moves={residual['move_count']} collisions={len(residual['collisions'])}"
                )
    except BaseException as error:
        rollback_status = "not_required"
        rollback_error: str | None = None
        if completed:
            rollback_status = "running"
            if progress:
                progress.event("rollback_started", completed_moves=len(completed))
                progress.update(phase="rollback", current_path=None, force=True)
            try:
                reverse_failures = _reverse_moves(completed)
                if reverse_failures:
                    raise RuntimeError("; ".join(reverse_failures))
                if archive and archive.is_file():
                    extract_migration_backup(archive, os_root)
                rollback_status = "completed"
                if progress:
                    progress.event("rollback_completed", completed_moves=len(completed))
            except BaseException as recovery_error:
                rollback_status = "failed"
                rollback_error = f"{type(recovery_error).__name__}: {recovery_error}"[
                    :2000
                ]
                if progress:
                    progress.event("rollback_failed", error=rollback_error)
        _terminal_receipt(
            terminal_path,
            run_id=run_id,
            status="rolled_back" if rollback_status == "completed" else "failed",
            plan=plan,
            progress=progress,
            error=error,
            completed_moves=len(completed),
            rollback_status=rollback_status,
            rollback_error=rollback_error,
            backup_dir=str(backup) if backup else None,
            backup_archive=str(archive) if archive else None,
            recovery_backup_archive=str(recovery_archive) if recovery_archive else None,
            preflight=preflight,
        )
        raise
    finally:
        if signal_guard_entered:
            signal_rollback.__exit__(None, None, None)
        if lock_acquired:
            lock.release()

    assert (
        plan is not None
        and preflight is not None
        and backup is not None
        and archive is not None
    )
    receipt = {
        **plan,
        "run_id": run_id,
        "applied_at": _utc_now(),
        "backup_dir": str(backup),
        "backup_archive": str(archive),
        "recovery_backup_archive": str(recovery_archive) if recovery_archive else None,
        "preflight": preflight,
        "changed_reference_files": changed_files,
        "sqlite_updates": sqlite_updates,
        "active_projection": projection,
        "post_run_invariants": {"move_count": 0, "collision_count": 0},
    }
    receipt_path = receipt_dir / "receipt.json"
    _atomic_json(receipt_path, receipt)
    _terminal_receipt(
        terminal_path,
        run_id=run_id,
        status="completed",
        plan=plan,
        progress=progress,
        completed_moves=len(completed),
        rollback_status="not_required",
        backup_dir=str(backup),
        backup_archive=str(archive),
        recovery_backup_archive=str(recovery_archive) if recovery_archive else None,
        receipt_path=str(receipt_path),
        preflight=preflight,
    )
    return {**receipt, "receipt_path": str(receipt_path)}


def restore_artifact_naming_migration(
    receipt_path: str | Path, *, apply: bool = False
) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).expanduser().read_text(encoding="utf-8"))
    plan = {
        key: receipt[key]
        for key in ("schema", "root", "moves", "plan_sha256")
        if key in receipt
    }
    if not apply:
        return {
            "apply": False,
            "restore_move_count": len(receipt.get("moves", [])),
            "plan": plan,
        }
    root = Path(receipt["root"])
    failures = _reverse_moves(receipt.get("moves", []))
    if failures:
        raise RuntimeError(
            "artifact naming restore could not reverse every move: "
            + "; ".join(failures)
        )
    archive = Path(receipt["backup_archive"])
    extract_migration_backup(archive, root)
    return {
        "apply": True,
        "restored": True,
        "root": str(root),
        "backup_archive": str(archive),
    }
