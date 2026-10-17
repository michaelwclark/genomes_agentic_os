"""Explicit, bounded schema ownership and active consumer migration transactions.

Scaffolding preserves unknown overrides. This owner does not run automatically:
an operator freezes a plan, acknowledges its exact bytes, and applies or rolls
back only that plan. Package smoke and selected validation are separate claims.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence
import uuid

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable
import yaml

from .auto_dev_orchestration import AutoDevStateError, plan_legacy_consumer_migration
from .scaffold import repo_root
from .state.db import default_db_path
from .state import work_items

# Limits bound the complete selection, reads, diagnostics, and transaction size.
MAX_CONSUMERS = 50
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTICS = 100
DEFAULT_SCHEMA = "auto-dev-work-item.schema.json"
TRANSACTION_RELATIVE = Path("harness/shared_factory/00-control-plane/schema-adoption")
PLAN_SCHEMA = "schema-adoption-plan/v1"
JOURNAL_SCHEMA = "schema-adoption-journal/v1"


class SchemaAdoptionError(ValueError):
    """Sanitized permanent refusal of an unsafe schema transaction."""
    retryable = False

    def __init__(self, code: str, message: str):
        self.error_code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _digest(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _identity(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _path(root: Path, raw: str | Path) -> Path:
    """Resolve an in-root path while refusing symlinks, including ancestors."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if ".." in candidate.parts:
        raise SchemaAdoptionError("path_escape", "parent path traversal is unsupported")
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise SchemaAdoptionError("path_escape", "selected path must remain inside the installed root") from exc
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise SchemaAdoptionError("path_escape", "symlink paths are unsupported")
    return candidate


def _root(raw: str | Path) -> Path:
    value = Path(raw).expanduser().absolute()
    if value.is_symlink() or value.resolve() != value:
        raise SchemaAdoptionError("path_escape", "root must be a canonical directory without symlink ancestors")
    if not value.is_dir():
        raise SchemaAdoptionError("root_missing", "installed root must exist")
    return value


def _read(path: Path, *, optional: bool = False) -> bytes | None:
    if optional and not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise SchemaAdoptionError("read_bound", "selected file is missing, nonregular, or exceeds the byte limit")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise SchemaAdoptionError("read_bound", "selected file exceeds the byte limit")
    return data


def _object(data: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object member")
            result[key] = value
        return result

    def finite(_: str) -> None:
        raise ValueError("nonfinite JSON")

    try:
        value = json.loads(data, object_pairs_hook=unique, parse_constant=finite)
    except (ValueError, UnicodeError) as exc:
        raise SchemaAdoptionError("invalid_json", f"{label} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise SchemaAdoptionError("invalid_json", f"{label} must be a JSON object")
    return value


def _schema(data: bytes) -> dict[str, Any]:
    value = _object(data, "schema")
    # Frozen local validation never fetches references or reads arbitrary files.
    def local_refs(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(child, str) or not child.startswith("#")):
                    raise SchemaAdoptionError("external_reference", "schema validation permits local references only")
                local_refs(child)
        elif isinstance(item, list):
            for child in item:
                local_refs(child)
    local_refs(value)
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise SchemaAdoptionError("invalid_schema", "schema is not a supported JSON Schema") from exc
    return value


def _validation(schema: dict[str, Any] | None, value: Mapping[str, Any]) -> dict[str, Any]:
    if schema is None:
        return {"available": False, "valid": None, "diagnostics": [], "truncated": False}
    diagnostics = []
    truncated = False
    try:
        for error in Draft202012Validator(schema).iter_errors(value):
            if len(diagnostics) == MAX_DIAGNOSTICS:
                truncated = True
                break
            # Do not serialize error.message: it may contain consumer values.
            diagnostics.append({"keyword": error.validator,
                                "instance_path": list(error.absolute_path),
                                "schema_path": list(error.absolute_schema_path)})
    except (Unresolvable, RecursionError) as exc:
        raise SchemaAdoptionError("validation_reference", "selected schema references cannot be safely evaluated") from exc
    return {"available": True, "valid": not diagnostics and not truncated,
            "diagnostics": diagnostics, "truncated": truncated}


def _manifest(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"schema_version": 1, "managed_by": "genomes-agentic-os package", "entries": []}
    try:
        value = yaml.safe_load(data)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise SchemaAdoptionError("invalid_manifest", "schema manifest is malformed") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("managed_by") != "genomes-agentic-os package"
            or not isinstance(value.get("entries"), list)):
        raise SchemaAdoptionError("invalid_manifest", "schema manifest ownership contract is unsupported")
    destinations = []
    for entry in value["entries"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("destination"), str):
            raise SchemaAdoptionError("invalid_manifest", "schema manifest entries are malformed")
        destinations.append(entry["destination"])
    if len(destinations) != len(set(destinations)):
        raise SchemaAdoptionError("invalid_manifest", "schema manifest destinations must be unique")
    return value


def _manifest_checksum(raw: Any) -> str | None:
    """Read scaffold's sha256: convention, accepting older bare SHA256 values."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", raw):
        raise SchemaAdoptionError("invalid_manifest", "selected manifest checksum convention is unsupported")
    return raw.removeprefix("sha256:")


def _adopted_manifest(manifest: dict[str, Any], path: str, schema_name: str, checksum: str) -> bytes:
    entry = next((item for item in manifest["entries"] if item["destination"] == path), None)
    if entry is None:
        entry = {"destination": path}
        manifest["entries"].append(entry)
    # Match scaffold.file_sha256 so the next package upgrade keeps ownership.
    qualified = f"sha256:{checksum}"
    entry.update(source=f"schemas/{schema_name}", source_checksum=qualified,
                 managed_checksum=qualified, observed_checksum=qualified, status="current")
    return yaml.safe_dump(manifest, sort_keys=False).encode("utf-8")


def _canonical(root: Path, projection_path: Path, projection: Mapping[str, Any], *, active: bool) -> dict[str, Any]:
    canonical_id = projection.get("canonical_work_id")
    db_path = _path(root, default_db_path(root))
    if not isinstance(canonical_id, str) or not db_path.is_file():
        raise SchemaAdoptionError("canonical_identity", "consumer requires an existing canonical work registry identity")
    try:
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            row = work_items.get(connection, canonical_id)
    except sqlite3.Error as exc:
        raise SchemaAdoptionError("canonical_identity", "canonical work registry cannot be read") from exc
    if not row:
        raise SchemaAdoptionError("canonical_identity", "selected consumer is not registered canonical work")
    packet = _path(root, str(row.get("packet_path") or ""))
    terminal = row.get("lifecycle") in work_items.TERMINAL_STATES
    if packet != projection_path.parent or terminal == active:
        raise SchemaAdoptionError("canonical_identity", "consumer location or active/historical lifecycle does not match the registry")
    if row.get("domain") != projection.get("domain") or row.get("project") != projection.get("project"):
        raise SchemaAdoptionError("canonical_identity", "consumer domain/project differs from canonical work")
    return {"id": canonical_id, "lifecycle": row.get("lifecycle"), "record_sha256": _identity(row)}


def _consumers(root: Path, active: Sequence[str | Path], historical: Sequence[str | Path], old_schema: dict[str, Any] | None,
               new_schema: dict[str, Any], *, migrate: bool) -> list[dict[str, Any]]:
    if len(active) + len(historical) > MAX_CONSUMERS:
        raise SchemaAdoptionError("selection_bound", "consumer selection exceeds the maximum")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, selection in (("active", active), ("historical", historical)):
        for raw in selection:
            path = _path(root, raw)
            if path.name != "autodev.json" or str(path) in seen:
                raise SchemaAdoptionError("consumer_selection", "select distinct exact autodev.json consumers")
            seen.add(str(path))
            data = _read(path)
            value = _object(data, "consumer")
            canonical = _canonical(root, path, value, active=kind == "active")
            row = {"path": path.relative_to(root).as_posix(), "kind": kind,
                   "sha256": _digest(data), "canonical": canonical,
                   "old_validation": _validation(old_schema, value), "new_validation": _validation(new_schema, value)}
            if migrate and kind == "active":
                delivery = value.get("delivery")
                if not isinstance(delivery, dict):
                    raise SchemaAdoptionError("consumer_identity", "consumer delivery binding is missing")
                if (value.get("work_item_id") != path.parent.name
                        or not isinstance(delivery.get("task_state_ref"), str) or not delivery["task_state_ref"].strip()
                        or ("portfolio_ref" in delivery and (not isinstance(delivery["portfolio_ref"], str) or not delivery["portfolio_ref"].strip()))):
                    raise SchemaAdoptionError("consumer_identity", "consumer packet and explicit delivery references must match canonical authority")
                task_path = _path(root, delivery["task_state_ref"])
                run_root = path.parents[2] / "state/development-runs"
                try:
                    task_relative = task_path.relative_to(run_root)
                except ValueError as exc:
                    raise SchemaAdoptionError("consumer_identity", "task must belong to the selected project's canonical delivery run") from exc
                if (len(task_relative.parts) != 4 or task_relative.parts[1] != "tasks" or task_relative.parts[3] != "state.json"
                        or "portfolio_ref" in delivery and _path(root, delivery["portfolio_ref"]) != task_path.parents[2] / "portfolio.json"):
                    raise SchemaAdoptionError("consumer_identity", "task and portfolio references must match canonical delivery layout")
                task_data = _read(task_path)
                task = _object(task_data, "task")
                if (task.get("canonical_work_id") != canonical["id"]
                        or not isinstance(task.get("work_item"), str) or not task["work_item"].strip()
                        or ("autodev_path" in task and (not isinstance(task["autodev_path"], str) or not task["autodev_path"].strip()))
                        or any(name in task and task[name] != value.get(name) for name in ("domain", "project"))
                        or "run_id" in task and task["run_id"] != task_relative.parts[0]
                        or _path(root, task["work_item"]) != path.parent
                        or _path(root, task.get("autodev_path", path)) != path):
                    raise SchemaAdoptionError("consumer_identity", "task is not bound to the selected canonical consumer")
                try:
                    migration = plan_legacy_consumer_migration(value, task)
                except (AutoDevStateError, TypeError, AttributeError) as exc:
                    raise SchemaAdoptionError("unsupported_consumer", "consumer contract cannot be safely migrated") from exc
                row.update(task_path=task_path.relative_to(root).as_posix(), task_sha256=_digest(task_data), migration=migration,
                           migrated_validation=_validation(new_schema, migration["projection"]))
            rows.append(row)
    return rows


def plan_schema_adoption(root: str | Path, *, schema_name: str = DEFAULT_SCHEMA,
                         consumers: Sequence[str | Path] = (), historical: Sequence[str | Path] = (),
                         migrate_consumers: bool = False) -> dict[str, Any]:
    """Freeze exact identities and validation for one schema and selected consumers."""
    target = _root(root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*\.schema\.json", schema_name):
        raise SchemaAdoptionError("schema_selection", "select one bundled schema filename")
    if migrate_consumers and (schema_name != DEFAULT_SCHEMA or not consumers):
        raise SchemaAdoptionError("consumer_selection", "migration requires selected active Auto-Dev consumers")
    installed_path = _path(target, Path("harness/schemas") / schema_name)
    manifest_path = _path(target, "harness/schemas/package-manifest.yml")
    installed = _read(installed_path, optional=True)
    manifest_bytes = _read(manifest_path, optional=True)
    bundled_path = repo_root() / "schemas" / schema_name
    bundled = _read(bundled_path)
    installed_schema = _schema(installed) if installed is not None else None
    bundled_schema = _schema(bundled)
    manifest = _manifest(manifest_bytes)
    relative = installed_path.relative_to(target).as_posix()
    prior = next((entry for entry in manifest["entries"] if entry["destination"] == relative), None)
    installed_hash, bundled_hash = _digest(installed), _digest(bundled)
    if prior and _manifest_checksum(prior.get("observed_checksum")) != installed_hash:
        raise SchemaAdoptionError("manifest_divergence", "selected schema differs from its manifest readback; refresh or investigate before planning")
    if installed is None:
        ownership = "absent"
    elif installed_hash == bundled_hash:
        ownership = "current_managed" if prior and _manifest_checksum(prior.get("managed_checksum")) == installed_hash else "current_unowned"
    elif prior and _manifest_checksum(prior.get("managed_checksum")) == installed_hash:
        ownership = "managed_upgrade"
    else:
        ownership = "unowned_or_custom_override"
    rows = _consumers(target, consumers, historical, installed_schema, bundled_schema, migrate=migrate_consumers)
    plan = {"schema": PLAN_SCHEMA, "kind": "consumer_migration" if migrate_consumers else "schema_adoption",
            "root": str(target), "schema_name": schema_name,
            "installed": {"path": relative, "sha256": installed_hash, "ownership": ownership},
            "bundled": {"sha256": bundled_hash, "schema_id": bundled_schema.get("$id"),
                        "distribution_version": version("genomes-agentic-os"), "module": str(Path(__file__).resolve())},
            "manifest": {"path": manifest_path.relative_to(target).as_posix(), "sha256": _digest(manifest_bytes)},
            "consumers": rows, "coverage": "exact selected consumers only; not whole-root health",
            "limits": {"max_consumers": MAX_CONSUMERS, "max_file_bytes": MAX_FILE_BYTES, "max_diagnostics": MAX_DIAGNOSTICS},
            "execution_receipts_created": False}
    plan["plan_sha256"] = _identity(plan)
    if len(_json_bytes(plan)) > MAX_FILE_BYTES:
        raise SchemaAdoptionError("plan_bound", "complete frozen plan exceeds the byte limit; reduce the selection")
    return plan


def _verify_plan(plan: Mapping[str, Any], expected: str) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("kind") not in {"schema_adoption", "consumer_migration"}:
        raise SchemaAdoptionError("invalid_plan", "unsupported adoption plan")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if not expected or expected != plan.get("plan_sha256") or expected != _identity(payload):
        raise SchemaAdoptionError("plan_hash", "explicit plan hash does not match frozen content")
    if (not isinstance(plan.get("root"), str) or not isinstance(plan.get("consumers"), list)
            or len(plan["consumers"]) > MAX_CONSUMERS
            or any(not isinstance(row, dict) or row.get("kind") not in {"active", "historical"}
                   or not isinstance(row.get("path"), str) for row in plan["consumers"])):
        raise SchemaAdoptionError("invalid_plan", "plan root or consumer selection is malformed")
    for label in ("installed", "bundled", "manifest"):
        descriptor = plan.get(label)
        if not isinstance(descriptor, dict) or "sha256" not in descriptor:
            raise SchemaAdoptionError("invalid_plan", "plan schema or manifest identities are malformed")
        checksum = descriptor["sha256"]
        if not (checksum is None and label != "bundled") and not (isinstance(checksum, str) and re.fullmatch(r"[a-f0-9]{64}", checksum)):
            raise SchemaAdoptionError("invalid_plan", "plan identity checksum is malformed")
        if label != "bundled" and not isinstance(descriptor.get("path"), str):
            raise SchemaAdoptionError("invalid_plan", "plan target path is malformed")
    if not isinstance(plan.get("schema_name"), str):
        raise SchemaAdoptionError("invalid_plan", "plan schema selection is malformed")
    for row in plan["consumers"]:
        if not isinstance(row.get("canonical"), dict) or not isinstance(row.get("sha256"), str):
            raise SchemaAdoptionError("invalid_plan", "plan consumer identity is malformed")
        if plan["kind"] == "consumer_migration" and row["kind"] == "active":
            migration = row.get("migration")
            if (not isinstance(migration, dict) or not isinstance(migration.get("projection"), dict)
                    or not isinstance(migration.get("task"), dict) or not isinstance(migration.get("changed"), bool)
                    or not isinstance(row.get("task_path"), str) or not isinstance(row.get("task_sha256"), str)):
                raise SchemaAdoptionError("invalid_plan", "plan migration binding is malformed")
    return dict(plan)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_handle = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_handle)
        finally:
            os.close(directory_handle)
    finally:
        if temp.exists():
            temp.unlink()


def _writes(root: Path, plan: Mapping[str, Any]) -> list[tuple[Path, bytes]]:
    if plan["kind"] == "consumer_migration":
        writes = []
        for row in plan["consumers"]:
            if row["kind"] == "active" and row["migration"]["changed"]:
                writes.extend([(_path(root, row["task_path"]), _json_bytes(row["migration"]["task"])),
                               (_path(root, row["path"]), _json_bytes(row["migration"]["projection"]))])
        return writes
    schema_path = _path(root, plan["installed"]["path"])
    manifest_path = _path(root, plan["manifest"]["path"])
    bundled = _read(repo_root() / "schemas" / plan["schema_name"])
    manifest = _manifest(_read(manifest_path, optional=True))
    after_manifest = _adopted_manifest(manifest, plan["installed"]["path"], plan["schema_name"], _digest(bundled))
    return [(schema_path, bundled), (manifest_path, after_manifest)]


def _transaction_lock_paths(root: Path, plan: Mapping[str, Any]) -> list[Path]:
    portfolios: set[Path] = set()
    tasks: set[Path] = set()
    projections: set[Path] = set()
    for row in plan["consumers"]:
        projections.add(_path(root, row["path"]))
        if row["kind"] == "active" and "migration" in row:
            task = _path(root, row["task_path"])
            portfolios.add(_path(root, task.parents[2] / "portfolio.json"))
            tasks.add(task)
    # Match delivery's portfolio -> task -> projection order. The adoption lock
    # is an outer owner lock, never acquired by delivery or projection writers.
    return [path.with_suffix(path.suffix + ".lock") for group in (portfolios, tasks, projections) for path in sorted(group)]


def _journal(root: Path, path: Path, value: Mapping[str, Any]) -> None:
    _atomic(_path(root, path), _json_bytes(value))


def _pending_transactions(root: Path, owner_dir: Path) -> None:
    """A crashed transaction requires explicit recovery before another apply."""
    if not owner_dir.exists():
        return
    count = 0
    for child in owner_dir.iterdir():
        count += 1
        if count > 1000:
            raise SchemaAdoptionError("journal_bound", "transaction inventory exceeds the bounded recovery limit")
        _path(root, child)
        if child.is_dir() and (child / "journal.json").exists():
            journal = _object(_read(_path(root, child / "journal.json")), "journal")
            if journal.get("status") not in {"applied", "rolled_back"}:
                raise SchemaAdoptionError("recovery_required", "an interrupted transaction requires explicit rollback before another apply")


def _validate_journal_writes(root: Path, directory: Path, journal: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    """Bind rollback target authority to the frozen plan rather than journal data."""
    expected: list[tuple[str, str | None, str | None]] = []
    if plan["kind"] == "consumer_migration":
        for row in plan["consumers"]:
            if row["kind"] == "active" and row["migration"]["changed"]:
                expected.extend([(row["task_path"], row["task_sha256"], _digest(_json_bytes(row["migration"]["task"]))),
                                 (row["path"], row["sha256"], _digest(_json_bytes(row["migration"]["projection"])))])
    else:
        expected = [(plan["installed"]["path"], plan["installed"]["sha256"], plan["bundled"]["sha256"]),
                    (plan["manifest"]["path"], plan["manifest"]["sha256"], None)]
    rows = journal.get("writes")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise SchemaAdoptionError("journal_identity", "journal write selection differs from its frozen plan")
    for index, (row, (path, before, after)) in enumerate(zip(rows, expected)):
        if (not isinstance(row, dict) or row.get("path") != path or row.get("before_sha256") != before
                or row.get("backup") != f"backup-{index}.bin"
                or (after is not None and row.get("after_sha256") != after)):
            raise SchemaAdoptionError("journal_identity", "journal target identities differ from their frozen plan")
        _path(root, path)
        _path(root, directory / row["backup"])
    if plan["kind"] == "schema_adoption":
        before_manifest = _read(directory / "backup-1.bin") if plan["manifest"]["sha256"] else None
        manifest = _manifest(before_manifest)
        after_manifest = _adopted_manifest(manifest, plan["installed"]["path"], plan["schema_name"], plan["bundled"]["sha256"])
        if rows[1]["after_sha256"] != _digest(after_manifest):
            raise SchemaAdoptionError("journal_identity", "journal manifest result differs from the frozen ownership operation")


def _restore(root: Path, directory: Path, journal: dict[str, Any], *, strict: bool = True,
             plan: Mapping[str, Any] | None = None) -> None:
    """Restore only own resulting bytes; public rollback prevalidates all rows."""
    for row in journal["writes"]:
        current = _digest(_read(_path(root, row["path"]), optional=True))
        if strict and current not in {row["before_sha256"], row["after_sha256"]}:
            raise SchemaAdoptionError("rollback_divergence", "rollback refuses a concurrent or unknown target change")
        if row["before_sha256"] is not None:
            backup = _read(_path(root, directory / row["backup"]))
            if _digest(backup) != row["before_sha256"]:
                raise SchemaAdoptionError("backup_divergence", "rollback backup identity differs")
    unresolved: list[dict[str, str]] = []
    try:
        for row in reversed(journal["writes"]):
            if plan is not None:
                _migration_dependencies(root, plan, "rollback_dependency_divergence")
            path = _path(root, row["path"])
            current = _digest(_read(path, optional=True))
            if current == row["before_sha256"]:
                continue
            if current != row["after_sha256"]:
                if strict:
                    raise SchemaAdoptionError("rollback_divergence", "rollback refuses a late unknown target change")
                unresolved.append({"path": row["path"], "reason": "unknown_target_bytes_preserved"})
                continue
            if row["before_sha256"] is None:
                path.unlink()
            else:
                backup = _read(_path(root, directory / row["backup"]))
                if _digest(backup) != row["before_sha256"]:
                    raise SchemaAdoptionError("backup_divergence", "rollback backup changed immediately before restoration")
                _atomic(path, backup)
        if plan is not None:
            _migration_dependencies(root, plan, "rollback_dependency_divergence")
            _rollback_consumers(root, plan)
        for row in journal["writes"]:
            if _digest(_read(_path(root, row["path"]), optional=True)) != row["before_sha256"]:
                if not any(item["path"] == row["path"] for item in unresolved):
                    unresolved.append({"path": row["path"], "reason": "restoration_readback_differs"})
        if unresolved:
            raise SchemaAdoptionError("rollback_readback", "known writes restored where safe; unknown target changes require manual recovery")
    except (SchemaAdoptionError, OSError):
        journal.update(status="recovery_required", readback_verified=False,
                       recovery_diagnostics=unresolved or [{"reason": "restoration_interrupted_or_diverged"}])
        _journal(root, directory / "journal.json", journal)
        raise
    journal.update(status="rolled_back", restored_at=_now(), readback_verified=True)
    _journal(root, directory / "journal.json", journal)


def _migration_dependencies(root: Path, plan: Mapping[str, Any], error_code: str) -> None:
    """Read-only compatibility prerequisites bind every migration boundary."""
    if plan["kind"] == "consumer_migration":
        for dependency in ("installed", "manifest"):
            descriptor = plan[dependency]
            if _digest(_read(_path(root, descriptor["path"]), optional=True)) != descriptor["sha256"]:
                raise SchemaAdoptionError(error_code, "transaction refuses a changed schema or manifest prerequisite")


def _rollback_consumers(root: Path, plan: Mapping[str, Any]) -> None:
    """Freeze diagnostic-only bytes and canonical authority across restoration."""
    for row in plan["consumers"]:
        path = _path(root, row["path"])
        if (row["kind"] == "historical" or plan["kind"] == "schema_adoption") and _digest(_read(path)) != row["sha256"]:
            raise SchemaAdoptionError("consumer_divergence", "rollback refuses a changed diagnostic-only selected consumer")
        value = _object(_read(path), "consumer rollback identity")
        if _canonical(root, path, value, active=row["kind"] == "active") != row["canonical"]:
            raise SchemaAdoptionError("canonical_divergence", "rollback refuses changed canonical consumer authority")


def apply_schema_plan(plan: Mapping[str, Any], *, expected_plan_sha256: str,
                      acknowledge_installed_sha256: str) -> dict[str, Any]:
    """Apply acknowledged exact bytes with prevalidation, journal, and recovery."""
    frozen = _verify_plan(plan, expected_plan_sha256)
    root = _root(frozen["root"])
    acknowledged = frozen["installed"]["sha256"] or "absent"
    if acknowledge_installed_sha256 != acknowledged:
        raise SchemaAdoptionError("operator_acknowledgement", "explicit installed schema hash acknowledgement is required")
    if frozen["kind"] == "consumer_migration" and frozen["installed"]["sha256"] != frozen["bundled"]["sha256"]:
        raise SchemaAdoptionError("schema_not_adopted", "adopt the exact bundled schema before consumer migration")
    owner_dir = _path(root, TRANSACTION_RELATIVE)
    with ExitStack() as locks:
        locks.enter_context(_lock(_path(root, owner_dir / "mutation.lock")))
        _pending_transactions(root, owner_dir)
        for path in _transaction_lock_paths(root, frozen):
            locks.enter_context(_lock(_path(root, path)))
        active = [row["path"] for row in frozen["consumers"] if row["kind"] == "active"]
        historical = [row["path"] for row in frozen["consumers"] if row["kind"] == "historical"]
        current = plan_schema_adoption(root, schema_name=frozen["schema_name"], consumers=active, historical=historical,
                                       migrate_consumers=frozen["kind"] == "consumer_migration")
        if current["plan_sha256"] != expected_plan_sha256:
            raise SchemaAdoptionError("stale_plan", "installed, bundled, manifest, or selected consumer identity changed")
        writes = _writes(root, frozen)
        expected_before = {frozen["installed"]["path"]: frozen["installed"]["sha256"],
                           frozen["manifest"]["path"]: frozen["manifest"]["sha256"]}
        for row in frozen["consumers"]:
            if row["kind"] == "active" and "migration" in row:
                expected_before.update({row["task_path"]: row["task_sha256"], row["path"]: row["sha256"]})
        prepared = [(path, data, _read(path, optional=True)) for path, data in writes]
        if any(_digest(before) != expected_before[path.relative_to(root).as_posix()] for path, _, before in prepared):
            raise SchemaAdoptionError("stale_plan", "target identity changed before its exact backup")
        _migration_dependencies(root, frozen, "stale_plan")
        directory = _path(root, owner_dir / uuid.uuid4().hex)
        directory.mkdir(parents=True)
        journal: dict[str, Any] = {"schema": JOURNAL_SCHEMA, "root": str(root), "kind": frozen["kind"],
                                  "plan_sha256": expected_plan_sha256, "status": "prepared", "created_at": _now(),
                                  "writes": [], "lock_paths": [str(path.relative_to(root)) for path in _transaction_lock_paths(root, frozen)]}
        for index, (path, after, before) in enumerate(prepared):
            backup = f"backup-{index}.bin"
            if before is not None:
                _atomic(directory / backup, before)
            journal["writes"].append({"path": path.relative_to(root).as_posix(), "backup": backup,
                                      "before_sha256": _digest(before), "after_sha256": _digest(after)})
        _atomic(directory / "plan.json", _json_bytes(frozen))
        _journal(root, directory / "journal.json", journal)
        try:
            _validate_journal_writes(root, directory, journal, frozen)
            journal["status"] = "applying"
            _journal(root, directory / "journal.json", journal)
            # Durable preparation is itself a time boundary. Read all original
            # target hashes again before any target mutation, then immediately
            # before each write. Cooperative writers hold the same locks;
            # these checkpoints also detect measured noncooperating changes.
            if any(_digest(_read(_path(root, row["path"]), optional=True)) != row["before_sha256"] for row in journal["writes"]):
                raise SchemaAdoptionError("stale_plan", "target identity changed after durable preparation")
            for (path, data), row in zip(writes, journal["writes"]):
                _migration_dependencies(root, frozen, "apply_dependency_divergence")
                if _digest(_read(path, optional=True)) != row["before_sha256"]:
                    raise SchemaAdoptionError("stale_plan", "target identity changed immediately before its write")
                _atomic(path, data)
                if _digest(_read(path)) != row["after_sha256"]:
                    raise SchemaAdoptionError("apply_readback", "target identity changed immediately after its write")
            for row in frozen["consumers"]:
                path = _path(root, row["path"])
                value = _object(_read(path), "consumer readback")
                if _canonical(root, path, value, active=row["kind"] == "active") != row["canonical"]:
                    raise SchemaAdoptionError("canonical_divergence", "canonical consumer identity changed during apply")
                if row["kind"] == "historical" or frozen["kind"] == "schema_adoption":
                    if _digest(_read(path)) != row["sha256"]:
                        raise SchemaAdoptionError("consumer_divergence", "diagnostic-only consumer changed during apply")
            _migration_dependencies(root, frozen, "apply_dependency_divergence")
            if any(_digest(_read(path)) != _digest(data) for path, data in writes):
                raise SchemaAdoptionError("apply_readback", "written target identity differs")
            journal.update(status="applied", finished_at=_now(), readback_verified=True)
            _journal(root, directory / "journal.json", journal)
        except BaseException:
            try:
                _restore(root, directory, journal, strict=False)
            except (SchemaAdoptionError, OSError) as recovery_error:
                journal.update(status="recovery_required", readback_verified=False,
                               recovery_failure=getattr(recovery_error, "error_code", "restoration_io_failure"))
                _journal(root, directory / "journal.json", journal)
            raise
    validation_readback = []
    for row in frozen["consumers"]:
        validation = row.get("migrated_validation") if frozen["kind"] == "consumer_migration" and row["kind"] == "active" else row["new_validation"]
        validation_readback.append({"path": row["path"], "kind": row["kind"], "valid": validation["valid"],
                                    "diagnostics_count": len(validation["diagnostics"]), "truncated": validation["truncated"],
                                    "new_pending_stages": row.get("migration", {}).get("new_pending_stages", [])})
    return {"schema": "schema-adoption-receipt/v1", "status": journal["status"], "kind": frozen["kind"],
            "plan_sha256": expected_plan_sha256, "journal": str(directory / "journal.json"),
            "readback_verified": journal["readback_verified"], "writes": journal["writes"],
            "selected_validation_readback": validation_readback,
            "whole_root_health_claimed": False, "execution_receipts_created": False}


def rollback_schema_transaction(root: str | Path, journal_path: str | Path, *, expected_plan_sha256: str) -> dict[str, Any]:
    """Restore exact backed-up schema, manifest, or consumers after stale checks."""
    target = _root(root)
    path = _path(target, journal_path)
    owner_dir = _path(target, TRANSACTION_RELATIVE)
    if path.name != "journal.json" or path.parent.parent != owner_dir:
        raise SchemaAdoptionError("journal_selection", "select an exact adoption owner transaction journal")
    with ExitStack() as locks:
        locks.enter_context(_lock(_path(target, owner_dir / "mutation.lock")))
        journal = _object(_read(path), "journal")
        plan = _verify_plan(_object(_read(path.parent / "plan.json"), "plan"), expected_plan_sha256)
        if (journal.get("schema") != JOURNAL_SCHEMA or journal.get("root") != str(target)
                or journal.get("plan_sha256") != expected_plan_sha256 or plan["root"] != str(target)):
            raise SchemaAdoptionError("journal_identity", "journal does not match the selected root and frozen plan")
        for lock_path in _transaction_lock_paths(target, plan):
            locks.enter_context(_lock(_path(target, lock_path)))
        _validate_journal_writes(target, path.parent, journal, plan)
        _migration_dependencies(target, plan, "rollback_dependency_divergence")
        for row in journal["writes"]:
            if _digest(_read(_path(target, row["path"]), optional=True)) not in {row["before_sha256"], row["after_sha256"]}:
                raise SchemaAdoptionError("rollback_divergence", "rollback refuses a concurrent or unknown target change")
        _rollback_consumers(target, plan)
        _restore(target, path.parent, journal, plan=plan)
    return {"schema": "schema-adoption-receipt/v1", "status": "rolled_back", "journal": str(path),
            "plan_sha256": expected_plan_sha256, "readback_verified": True, "whole_root_health_claimed": False}
