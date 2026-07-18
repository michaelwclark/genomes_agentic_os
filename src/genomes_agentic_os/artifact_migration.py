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
    ArtifactNamingPolicy,
    dated_name,
    filesystem_timestamp,
    has_date_prefix,
    legacy_date_from_name,
    load_artifact_naming_policy,
    parse_timestamp,
    strip_legacy_date,
)
from .scaffold import expand_path
from .state import work_items as state_work_items
from .state.db import connect, default_db_path


MIGRATION_SCHEMA = "artifact-date-prefix-migration/v1"
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".toml", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}


def _project_roots(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("domains/*/projects/*", "domains/*/02-projects/*", "*/02-projects/*"):
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
            return parse_timestamp(data["created_at"], fallback=filesystem_timestamp(path))
    return filesystem_timestamp(path)


def _move(kind: str, source: Path, destination: Path, when: datetime, *, method: str = "rename") -> dict[str, str]:
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
        return candidate.resolve() if candidate.is_absolute() else (path / candidate).resolve()

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
        if current_path != path and ".git" in files and (current_path / ".git").is_file():
            result.append(current_path.relative_to(path))
    return sorted(set(result))


def _final_path(path: Path, parent_moves: Iterable[dict[str, str]]) -> Path:
    value = str(path)
    for move in sorted(parent_moves, key=lambda item: len(item["source"]), reverse=True):
        source = move["source"]
        if value == source or value.startswith(source + os.sep):
            return Path(move["destination"] + value[len(source) :])
    return path


def _named_artifact_roots(root: Path, name: str) -> list[Path]:
    result: list[Path] = []
    for current, dirs, _files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [entry for entry in dirs if entry not in SKIP_DIRS and entry not in {"lib", "worktrees"}]
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
                if item.name.startswith(".") or item.name == "README.md" or has_date_prefix(item.name, policy):
                    continue
                when = _metadata_created_at(item)
                destination = item.with_name(
                    dated_name(item.name, when=when, policy=policy, scope="work_items", force=True)
                )
                moves.append(_move("work_item", item, destination, when))

        worktree_root = project / "worktrees"
        if worktree_root.is_dir():
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
                if checkout.name in {"README.md", "index.yml", "closed.yml"} or checkout.name.startswith("."):
                    continue
                if has_date_prefix(checkout.name, policy):
                    continue
                entry = registered.get(checkout.name, {})
                when = parse_timestamp(entry.get("created_at"), fallback=filesystem_timestamp(checkout))
                destination = checkout.with_name(
                    dated_name(checkout.name, when=when, policy=policy, scope="worktrees", force=True)
                )
                if _is_linked_git_worktree(checkout):
                    method = "git_worktree_repair" if _initialized_submodule_paths(checkout) else "git_worktree"
                else:
                    method = "rename"
                moves.append(_move("worktree", checkout, destination, when, method=method))

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

    for conversation_root in sorted(conversation_roots) if policy.enabled_for("conversation_logs") else []:
        for source_before_parent_move in sorted(conversation_root.iterdir()):
            if not source_before_parent_move.is_file() or has_date_prefix(source_before_parent_move.name, policy):
                continue
            when = legacy_date_from_name(source_before_parent_move.name) or filesystem_timestamp(source_before_parent_move)
            new_name = dated_name(
                strip_legacy_date(source_before_parent_move.name),
                when=when,
                policy=policy,
                scope="conversation_logs",
                force=True,
            )
            source = _final_path(source_before_parent_move, parent_moves)
            moves.append(_move("conversation_log", source, source.with_name(new_name), when))

    for project in _project_roots(os_root) if policy.enabled_for("thread_closeouts") else []:
        work_items = project / "work-items"
        if not work_items.is_dir():
            continue
        for closeout_root in sorted(work_items.glob("*/*/artifacts/thread-closeouts")):
            if not closeout_root.is_dir():
                continue
            for closeout_before_parent_move in sorted(path for path in closeout_root.iterdir() if path.is_dir()):
                if has_date_prefix(closeout_before_parent_move.name, policy):
                    continue
                when = legacy_date_from_name(closeout_before_parent_move.name) or filesystem_timestamp(
                    closeout_before_parent_move
                )
                source = _final_path(closeout_before_parent_move, parent_moves)
                new_name = dated_name(
                    strip_legacy_date(closeout_before_parent_move.name),
                    when=when,
                    policy=policy,
                    scope="thread_closeouts",
                    force=True,
                )
                moves.append(_move("thread_closeout", source, source.with_name(new_name), when))

    for async_root in _named_artifact_roots(os_root, "async-runs") if policy.enabled_for("async_runs") else []:
        for run_before_parent_move in sorted(path for path in async_root.iterdir() if path.is_dir()):
            if has_date_prefix(run_before_parent_move.name, policy):
                continue
            when = legacy_date_from_name(run_before_parent_move.name) or filesystem_timestamp(run_before_parent_move)
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
            if not run.is_dir() or run.name.startswith(".") or has_date_prefix(run.name, policy):
                continue
            when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
            new_name = dated_name(
                strip_legacy_date(run.name), when=when, policy=policy, scope="run_logs", force=True
            )
            moves.append(_move("run_log", run, run.with_name(new_name), when))

    reports_root = os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "reports"
    if reports_root.is_dir() and policy.enabled_for("report_runs"):
        for report_root in sorted(path for path in reports_root.iterdir() if path.is_dir()):
            for run in sorted(path for path in report_root.iterdir() if path.is_dir()):
                if has_date_prefix(run.name, policy):
                    continue
                when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
                new_name = dated_name(
                    strip_legacy_date(run.name), when=when, policy=policy, scope="report_runs", force=True
                )
                moves.append(_move("report_run", run, run.with_name(new_name), when))

    for project in _project_roots(os_root) if policy.enabled_for("development_runs") else []:
        development_root = project / "state" / "development-runs"
        if not development_root.is_dir():
            continue
        for run in sorted(path for path in development_root.iterdir() if path.is_dir()):
            if has_date_prefix(run.name, policy):
                continue
            when = legacy_date_from_name(run.name) or filesystem_timestamp(run)
            new_name = dated_name(
                strip_legacy_date(run.name), when=when, policy=policy, scope="development_runs", force=True
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
                {**move, "collision_reason": "duplicate_planned_destination", "destination": destination}
                for move in candidates
            )
    counts: dict[str, int] = {}
    for move in moves:
        counts[move["kind"]] = counts.get(move["kind"], 0) + 1
    payload = {
        "schema": MIGRATION_SCHEMA,
        "root": str(os_root),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
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
    hash_payload = {key: value for key, value in payload.items() if key != "generated_at"}
    payload["plan_sha256"] = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()
    return payload


def _backup_paths(root: Path) -> list[Path]:
    paths = [root / "harness" / "config", root / "harness" / "registries", root / "harness" / "logs"]
    control = root / "harness" / "shared_factory" / "00-control-plane"
    paths.extend(path for path in (control / "state.db", control / "active-now.json") if path.exists())
    shared_runs = root / "harness" / "shared_factory" / "06-runs-and-logs"
    if shared_runs.exists():
        paths.append(shared_runs)
    for project in _project_roots(root):
        for relative in ("work-items", "state", "logs"):
            candidate = project / relative
            if candidate.exists():
                paths.append(candidate)
        for candidate in (
            project / "worktrees" / "index.yml",
            project / "worktrees" / "closed.yml",
            project / "config" / "worktrees.yml",
        ):
            if candidate.exists():
                paths.append(candidate)
    for domain in _domain_roots(root):
        candidate = domain / "06-runs-and-logs"
        if candidate.exists():
            paths.append(candidate)
    return sorted(set(paths))


def create_migration_backup(root: Path, backup_dir: Path, plan: dict[str, Any]) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest = backup_dir / "migration-plan.json"
    manifest.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = backup_dir / "mutable-state.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as tar:
        for path in _backup_paths(root):
            if path.exists() or path.is_symlink():
                tar.add(path, arcname=str(path.relative_to(root)), recursive=True)
        # Reference rewriting spans rules, context, project status, and other
        # small text surfaces outside the state directories above. Preserve
        # each eligible file so restore reverses both names and references.
        for path in _iter_reference_files(root):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return archive


def extract_migration_backup(archive: Path, root: Path) -> None:
    """Restore a trusted migration archive over operator-owned read-only files."""
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"unsafe backup member path: {member.name}")
            destination = root / member_path
            if destination.exists() and destination.is_file() and not destination.is_symlink():
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
                ["git", "-C", str(repository), "worktree", "move", str(source), str(destination)],
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


def _repair_moved_worktree(repository: Path, worktree: Path, submodules: list[Path]) -> None:
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "repair", str(worktree)],
        capture_output=True,
        text=True,
        check=True,
    )
    worktree_git_file = worktree / ".git"
    worktree_match = re.match(r"gitdir:\s*(.+)", worktree_git_file.read_text(encoding="utf-8").strip())
    if not worktree_match:
        raise ValueError(f"invalid worktree gitdir file: {worktree_git_file}")
    worktree_git_dir = Path(worktree_match.group(1))
    if not worktree_git_dir.is_absolute():
        worktree_git_dir = (worktree / worktree_git_dir).resolve()
    for relative in submodules:
        submodule_root = worktree / relative
        git_file = submodule_root / ".git"
        match = re.match(r"gitdir:\s*(.+)", git_file.read_text(encoding="utf-8").strip())
        if not match:
            raise ValueError(f"invalid submodule gitdir file: {git_file}")
        git_dir = Path(match.group(1))
        if not git_dir.is_absolute():
            git_dir = (submodule_root / git_dir).resolve()
        if not git_dir.is_dir():
            normalized = match.group(1).replace("\\", "/")
            marker = f"/.git/worktrees/{worktree_git_dir.name}/"
            if marker not in normalized:
                raise FileNotFoundError(f"cannot recover stale submodule gitdir: {git_file}")
            git_dir = worktree_git_dir / normalized.split(marker, 1)[1]
        if not git_dir.is_dir():
            raise FileNotFoundError(f"submodule gitdir is missing: {git_dir}")
        git_file.write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
        subprocess.run(
            ["git", "config", "--file", str(git_dir / "config"), "core.worktree", str(submodule_root.resolve())],
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


def _reference_replacements(root: Path, moves: list[dict[str, str]]) -> list[tuple[str, str]]:
    replacements: dict[str, str] = {}
    for move in moves:
        source = Path(move["source"])
        destination = Path(move["destination"])
        replacements[str(source)] = str(destination)
        try:
            replacements[str(source.relative_to(root))] = str(destination.relative_to(root))
        except ValueError:
            pass
    return sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)


def _project_for_path(root: Path, path: Path) -> tuple[str, str, Path] | None:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if len(parts) >= 4 and parts[0] == "domains" and parts[2] in {"projects", "02-projects"}:
        return parts[1], parts[3], root.joinpath(*parts[:4])
    if len(parts) >= 5 and parts[:3] == ("harness", "shared_factory", "02-projects"):
        return "shared_factory", parts[3], root.joinpath(*parts[:4])
    if len(parts) >= 3 and parts[1] == "02-projects":
        return parts[0], parts[2], root.joinpath(*parts[:3])
    return None


def _targeted_reference_scopes(root: Path, moves: list[dict[str, str]]) -> dict[Path, dict[str, str]]:
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
            scope = current.parent if current.name == "06-runs-and-logs" else destination.parent
        elif kind == "report_run":
            scope = root / "harness"
        elif kind == "conversation_log":
            scope = destination.parent
        elif kind == "async_run":
            scope = destination.parent
        if scope is not None:
            scopes.setdefault(scope, {})[source.name] = destination.name
    return scopes


def _iter_reference_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and name != "lib"]
        if "worktrees" in current_path.parts:
            # Registry files sit at the worktrees root; checkout contents are source code.
            dirs[:] = []
        for filename in files:
            path = current_path / filename
            if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 10 * 1024 * 1024:
                yield path


def _replacement_engine(
    replacements: list[tuple[str, str]],
) -> tuple[re.Pattern[str] | None, Any]:
    mapping = dict(replacements)
    protected_destinations = set(mapping.values()) - set(mapping)
    tokens = sorted(set(mapping) | protected_destinations, key=len, reverse=True)
    if not tokens:
        return None, lambda value: value
    pattern = re.compile("|".join(re.escape(token) for token in tokens))

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        return mapping.get(value, value)

    return pattern, lambda value: pattern.sub(replace, value)


def _rewrite_text_references(root: Path, replacements: list[tuple[str, str]]) -> list[str]:
    pattern, replace = _replacement_engine(replacements)
    if pattern is None:
        return []

    changed: list[str] = []
    for path in _iter_reference_files(root):
        before = path.read_text(encoding="utf-8", errors="replace")
        after = replace(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(str(path))
    return changed


def _rewrite_targeted_references(root: Path, moves: list[dict[str, str]]) -> list[str]:
    changed: list[str] = []
    for scope, mapping in _targeted_reference_scopes(root, moves).items():
        replacements = sorted(mapping.items(), key=lambda pair: len(pair[0]), reverse=True)
        changed.extend(_rewrite_text_references(scope, replacements))
    return sorted(set(changed))


def _replace_exact_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_values(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact_values(item, replacements) for key, item in value.items()}
    return value


def _rewrite_worktree_registry_ids(root: Path, moves: list[dict[str, str]]) -> list[str]:
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
                path.write_text(yaml.safe_dump(after, sort_keys=False), encoding="utf-8")
                changed.append(str(path))
    return changed


def _sqlite_reference_replacements(root: Path, moves: list[dict[str, str]]) -> list[tuple[str, str]]:
    replacements = dict(_reference_replacements(root, moves))
    for move in moves:
        if move["kind"] != "work_item":
            continue
        source = Path(move["source"])
        destination = Path(move["destination"])
        project = _project_for_path(root, destination)
        if project:
            domain, project_name, _ = project
            replacements[f"{domain}:{project_name}:{source.name}"] = f"{domain}:{project_name}:{destination.name}"
    return sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)


def _rewrite_sqlite_references(db_path: Path, replacements: list[tuple[str, str]]) -> int:
    if not db_path.is_file():
        return 0
    pattern, replace = _replacement_engine(replacements)
    if pattern is None:
        return 0
    changed = 0
    conn = sqlite3.connect(db_path)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("sqlite_")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")') if str(row[2]).upper() in {"", "TEXT"}]
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


def _reverse_moves(moves: Iterable[dict[str, str]]) -> None:
    for move in reversed(list(moves)):
        destination = Path(move["destination"])
        source = Path(move["source"])
        if not destination.exists() and not destination.is_symlink():
            continue
        reverse = {**move, "source": str(destination), "destination": str(source)}
        try:
            _perform_move(reverse)
        except Exception:
            # The backup remains the authoritative recovery surface if git or
            # filesystem state changed again during rollback.
            pass


def apply_artifact_naming_plan(
    root: str | Path,
    *,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    plan = build_artifact_naming_plan(os_root)
    if plan["collisions"]:
        raise ValueError(f"artifact naming migration has {len(plan['collisions'])} destination collision(s)")
    now = datetime.now(timezone.utc)
    policy = load_artifact_naming_policy(os_root)
    backup_name = dated_name(
        f"{now.strftime('%H%M%SZ')}-artifact-date-prefix-backup",
        when=now,
        policy=policy,
        scope="run_logs",
    )
    backup = expand_path(backup_dir) if backup_dir else Path("~/backups/agentic_os").expanduser() / backup_name
    archive = create_migration_backup(os_root, backup, plan)
    completed: list[dict[str, str]] = []
    try:
        for move in plan["moves"]:
            _perform_move(move)
            completed.append(move)
        replacements = _reference_replacements(os_root, plan["moves"])
        changed_files = _rewrite_text_references(os_root, replacements)
        changed_files.extend(_rewrite_targeted_references(os_root, plan["moves"]))
        changed_files.extend(_rewrite_worktree_registry_ids(os_root, plan["moves"]))
        changed_files = sorted(set(changed_files))
        sqlite_updates = _rewrite_sqlite_references(
            default_db_path(os_root),
            _sqlite_reference_replacements(os_root, plan["moves"]),
        )
        conn = connect(default_db_path(os_root))
        try:
            projection = state_work_items.write_active_projection(conn, os_root)
        finally:
            conn.close()
    except Exception:
        _reverse_moves(completed)
        extract_migration_backup(archive, os_root)
        raise

    receipt_time = datetime.now(timezone.utc)
    receipt_name = dated_name(
        f"{receipt_time.strftime('%H%M%SZ')}-artifact-date-prefix-migration",
        when=receipt_time,
        policy=policy,
        scope="run_logs",
    )
    receipt_dir = os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "migrations" / receipt_name
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        **plan,
        "applied_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backup_dir": str(backup),
        "backup_archive": str(archive),
        "changed_reference_files": changed_files,
        "sqlite_updates": sqlite_updates,
        "active_projection": projection,
    }
    receipt_path = receipt_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**receipt, "receipt_path": str(receipt_path)}


def restore_artifact_naming_migration(receipt_path: str | Path, *, apply: bool = False) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).expanduser().read_text(encoding="utf-8"))
    plan = {key: receipt[key] for key in ("schema", "root", "moves", "plan_sha256") if key in receipt}
    if not apply:
        return {"apply": False, "restore_move_count": len(receipt.get("moves", [])), "plan": plan}
    root = Path(receipt["root"])
    _reverse_moves(receipt.get("moves", []))
    archive = Path(receipt["backup_archive"])
    extract_migration_backup(archive, root)
    return {"apply": True, "restored": True, "root": str(root), "backup_archive": str(archive)}
