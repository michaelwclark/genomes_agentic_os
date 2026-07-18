"""Canonical, local-first Agentic OS report definitions, runs, and artifacts.

The engine only executes bounded built-in projections.  It never evaluates a
definition as shell, Python, SQL, or an external API request.  Files remain the
source of truth and optional Notion projection is an explicitly guarded output.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from .artifact_naming import dated_name, load_artifact_naming_policy
from .report_registry import collect_reports
from .resource_actions import API_VERSION as ACTION_API_VERSION
from .scaffold import expand_path, repo_root, validate_name


DEFINITION_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
REPORT_QUERY_API_VERSION = "report-query/v1"
REPORT_REGISTRY_API_VERSION = "report-registry/v1"
REPORT_RUN_REGISTRY_API_VERSION = "report-run-registry/v1"
REPORT_ARTIFACT_REGISTRY_API_VERSION = "report-artifact-registry/v1"
REPORT_REGISTRY = "harness/registries/report-definitions.yml"
REPORT_CATALOG_REGISTRY = "harness/registries/reports.yml"
REPORT_RUN_REGISTRY = "harness/registries/report-runs.yml"
REPORT_ARTIFACT_REGISTRY = "harness/registries/report-artifacts.yml"
REPORT_LOG_ROOT = "harness/shared_factory/06-runs-and-logs/report-engine"
REPORT_RUN_ROOT = "harness/shared_factory/06-runs-and-logs/reports"
MAX_SOURCE_BYTES = 1024 * 1024
RICH_SECTION_TYPES = {"markdown", "table", "chart", "list", "timeline", "links", "evidence"}
NotionProjector = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return _sha_bytes(encoded)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_stamp()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_yaml(path: Path, value: Any) -> None:
    _atomic_write(path, yaml.safe_dump(value, sort_keys=False))


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def _load_yaml(path: Path, default: Any | None = None) -> Any:
    if not path.is_file():
        if default is not None:
            return deepcopy(default)
        raise ValueError(f"required file is missing: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    return value if value is not None else deepcopy(default)


def _empty_registries() -> dict[str, dict[str, Any]]:
    return {
        REPORT_REGISTRY: {"api_version": REPORT_REGISTRY_API_VERSION, "definitions": []},
        REPORT_RUN_REGISTRY: {"api_version": REPORT_RUN_REGISTRY_API_VERSION, "runs": []},
        REPORT_ARTIFACT_REGISTRY: {"api_version": REPORT_ARTIFACT_REGISTRY_API_VERSION, "artifacts": []},
    }


def ensure_report_registries(root: str | Path) -> list[str]:
    os_root = expand_path(root)
    created: list[str] = []
    for relative, payload in _empty_registries().items():
        path = os_root / relative
        if not path.exists():
            _atomic_yaml(path, payload)
            created.append(relative)
    return created


def _load_registry(root: Path, relative: str) -> dict[str, Any]:
    expected = _empty_registries()[relative]
    value = _load_yaml(root / relative, expected)
    if not isinstance(value, dict) or value.get("api_version") != expected["api_version"]:
        raise ValueError(f"invalid report registry contract: {relative}")
    collection = next(key for key in ("definitions", "runs", "artifacts") if key in expected)
    if not isinstance(value.get(collection), list):
        raise ValueError(f"{relative}.{collection} must be a list")
    return value


def _schema_path(root: Path, schema_name: str) -> Path:
    installed = root / "harness" / "schemas" / schema_name
    if installed.is_file():
        return installed
    source = repo_root() / "schemas" / schema_name
    if source.is_file():
        return source
    raise ValueError(f"report schema is unavailable: {schema_name}")


def _validate_schema(root: Path, value: Mapping[str, Any], schema_name: str) -> list[str]:
    schema = json.loads(_schema_path(root, schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(dict(value)), key=lambda item: tuple(str(part) for part in item.path))
    ]


def _definition_by_id(registry: Mapping[str, Any], report_id: str) -> dict[str, Any]:
    report_id = validate_name(report_id, "report_id")
    found = next(
        (item for item in registry.get("definitions", []) if isinstance(item, dict) and item.get("id") == report_id),
        None,
    )
    if found is None:
        raise ValueError(f"unknown report definition: {report_id}")
    return deepcopy(found)


def _definition_reference_findings(root: Path, definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    source_ids = [str(item.get("id")) for item in definition.get("sources", []) if isinstance(item, dict)]
    if len(source_ids) != len(set(source_ids)):
        findings.append({"code": "duplicate_source_id", "severity": "error"})
    for section in definition.get("sections", []):
        if not isinstance(section, dict):
            continue
        if section.get("source_id") not in source_ids:
            findings.append(
                {"code": "unknown_section_source", "severity": "error", "section_id": section.get("id")}
            )
        if section.get("type") == "chart" and not section.get("chart_type"):
            findings.append({"code": "chart_type_missing", "severity": "error", "section_id": section.get("id")})

    catalog_ref = definition.get("catalog_ref")
    if catalog_ref:
        catalog = _load_yaml(root / REPORT_CATALOG_REGISTRY, {"reports": []})
        catalog_rows = catalog.get("reports", []) if isinstance(catalog, dict) else []
        catalog_entry = next(
            (item for item in catalog_rows if isinstance(item, dict) and item.get("id") == catalog_ref),
            None,
        )
        if catalog_entry is None:
            findings.append({"code": "catalog_reference_stale", "severity": "error", "catalog_ref": catalog_ref})

    schedule_id = (definition.get("schedule") or {}).get("schedule_id")
    if schedule_id:
        runtime_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
        if not runtime_path.is_file():
            findings.append({"code": "schedule_registry_missing", "severity": "error", "schedule_id": schedule_id})
        else:
            runtime = _load_yaml(runtime_path, {})
            schedule = next(
                (
                    item
                    for item in (runtime.get("schedules") if isinstance(runtime, dict) else []) or []
                    if isinstance(item, dict) and item.get("id") == schedule_id
                ),
                None,
            )
            if schedule is None:
                findings.append({"code": "schedule_reference_stale", "severity": "error", "schedule_id": schedule_id})
            else:
                expected_fragment = f"report run-now {definition.get('id')}"
                if expected_fragment not in str(schedule.get("command") or ""):
                    findings.append(
                        {
                            "code": "schedule_command_mismatch",
                            "severity": "warning",
                            "schedule_id": schedule_id,
                            "expected_fragment": expected_fragment,
                        }
                    )
    return findings


def validate_report_definition(root: str | Path, definition: Mapping[str, Any]) -> dict[str, Any]:
    os_root = expand_path(root)
    errors = _validate_schema(os_root, definition, "report-definition.schema.json")
    findings = _definition_reference_findings(os_root, definition) if not errors else []
    errors.extend(item["code"] for item in findings if item.get("severity") == "error")
    return {
        "api_version": REPORT_QUERY_API_VERSION,
        "resource_kind": "report_definition",
        "resource_id": definition.get("id"),
        "ok": not errors,
        "errors": errors,
        "findings": findings,
    }


def load_definition_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"definition file is missing: {source}")
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
    else:
        value = _load_yaml(source, {})
    if not isinstance(value, dict):
        raise ValueError("report definition file must contain an object")
    return value


def _related(root: Path, definition_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs = [
        deepcopy(item)
        for item in _load_registry(root, REPORT_RUN_REGISTRY)["runs"]
        if isinstance(item, dict) and item.get("definition_id") == definition_id
    ]
    artifacts = [
        deepcopy(item)
        for item in _load_registry(root, REPORT_ARTIFACT_REGISTRY)["artifacts"]
        if isinstance(item, dict) and item.get("definition_id") == definition_id
    ]
    return runs, artifacts


def _catalog_entry(root: Path, catalog_ref: str | None) -> dict[str, Any] | None:
    if not catalog_ref:
        return None
    registry = _load_yaml(root / REPORT_CATALOG_REGISTRY, {"reports": []})
    rows = registry.get("reports", []) if isinstance(registry, dict) else []
    return deepcopy(
        next((item for item in rows if isinstance(item, dict) and item.get("id") == catalog_ref), None)
    )


def _health_projection(definition: Mapping[str, Any], runs: list[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    latest = max(runs, key=lambda item: str(item.get("completed_at") or ""), default=None)
    if definition.get("status") == "archived":
        return {"status": "archived", "latest_run": latest}
    if latest is None:
        return {"status": "never_run", "latest_run": None}
    completed = datetime.fromisoformat(str(latest["completed_at"]).replace("Z", "+00:00"))
    stale_after = int((definition.get("health_policy") or {}).get("max_stale_hours", 24))
    if completed < now - timedelta(hours=stale_after):
        return {"status": "stale", "latest_run": latest}
    return {"status": str(latest.get("status") or "unknown"), "latest_run": latest}


def report_resource_projection(root: str | Path, definition: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    runs, artifacts = _related(os_root, str(definition["id"]))
    health = _health_projection(definition, runs, now or _now())
    latest_artifact = max(artifacts, key=lambda item: str(item.get("created_at") or ""), default=None)
    catalog = _catalog_entry(os_root, definition.get("catalog_ref"))
    return {
        "id": definition["id"],
        "name": definition["name"],
        "summary": definition["summary"],
        "status": definition["status"],
        "scope": deepcopy(definition.get("scope") or {}),
        "domain": (definition.get("scope") or {}).get("domain"),
        "project": (definition.get("scope") or {}).get("project"),
        "source": {"kind": "registry", "path": REPORT_REGISTRY},
        "catalog_ref": definition.get("catalog_ref"),
        "catalog": catalog,
        "schedule_id": (definition.get("schedule") or {}).get("schedule_id"),
        "generator": definition.get("generator"),
        "source_count": len(definition.get("sources") or []),
        "run_count": len(runs),
        "artifact_count": len(artifacts),
        "health": health,
        "latest_run": health["latest_run"],
        "latest_artifact": latest_artifact,
        "definition": deepcopy(dict(definition)),
    }


def _indexed_projection(root: Path, resource_kind: str, item: Mapping[str, Any], definitions: Mapping[str, Any]) -> dict[str, Any]:
    projected = deepcopy(dict(item))
    definition = definitions.get(str(projected.get("definition_id")))
    projected["scope"] = deepcopy((definition or {}).get("scope") or {})
    projected["source"] = {
        "kind": "artifact" if resource_kind == "artifact" else "run",
        "path": projected.get("path"),
    }
    if definition:
        projected["definition_name"] = definition.get("name")
        projected["catalog_ref"] = definition.get("catalog_ref")
    return projected


def query_report_resources(
    root: str | Path,
    resource_kind: str,
    *,
    definition_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if limit < 1 or limit > 500:
        raise ValueError("report query limit must be between 1 and 500")
    definitions_by_id = {
        str(item.get("id")): item
        for item in _load_registry(os_root, REPORT_REGISTRY)["definitions"]
        if isinstance(item, dict) and item.get("id")
    }
    if resource_kind == "definition":
        items = [
            report_resource_projection(os_root, item)
            for item in definitions_by_id.values()
            if isinstance(item, dict) and (include_archived or item.get("status") != "archived")
        ]
    elif resource_kind == "run":
        items = [
            _indexed_projection(os_root, "run", item, definitions_by_id)
            for item in _load_registry(os_root, REPORT_RUN_REGISTRY)["runs"]
            if isinstance(item, dict)
        ]
    elif resource_kind == "artifact":
        items = [
            _indexed_projection(os_root, "artifact", item, definitions_by_id)
            for item in _load_registry(os_root, REPORT_ARTIFACT_REGISTRY)["artifacts"]
            if isinstance(item, dict)
        ]
    else:
        raise ValueError(f"unsupported report resource kind: {resource_kind}")
    if definition_id:
        definition_id = validate_name(definition_id, "definition_id")
        items = [item for item in items if item.get("definition_id", item.get("id")) == definition_id]
    if status:
        items = [item for item in items if item.get("status") == status or (item.get("health") or {}).get("status") == status]
    items.sort(key=lambda item: (str(item.get("completed_at") or item.get("updated_at") or ""), str(item.get("id"))), reverse=True)
    total_count = len(items)
    items = items[:limit]
    return {
        "api_version": REPORT_QUERY_API_VERSION,
        "resource_kind": resource_kind,
        "count": len(items),
        "total_count": total_count,
        "limit": limit,
        "truncated": total_count > len(items),
        "items": items,
    }


def get_report_resource(root: str | Path, resource_kind: str, resource_id: str) -> dict[str, Any]:
    if resource_kind == "definition":
        resource_id = validate_name(resource_id, "resource_id")
    elif not resource_id or not all(
        character.islower() or character.isdigit() or character in "-_" for character in resource_id
    ):
        raise ValueError(f"invalid report resource id: {resource_id!r}")
    os_root = expand_path(root)
    definitions = {
        str(item.get("id")): item
        for item in _load_registry(os_root, REPORT_REGISTRY)["definitions"]
        if isinstance(item, dict) and item.get("id")
    }
    if resource_kind == "definition":
        raw = definitions.get(resource_id)
        found = report_resource_projection(os_root, raw) if raw else None
    elif resource_kind in {"run", "artifact"}:
        relative = REPORT_RUN_REGISTRY if resource_kind == "run" else REPORT_ARTIFACT_REGISTRY
        collection = "runs" if resource_kind == "run" else "artifacts"
        raw = next(
            (
                item
                for item in _load_registry(os_root, relative)[collection]
                if isinstance(item, dict) and item.get("id") == resource_id
            ),
            None,
        )
        found = _indexed_projection(os_root, resource_kind, raw, definitions) if raw else None
    else:
        raise ValueError(f"unsupported report resource kind: {resource_kind}")
    if found is None:
        raise ValueError(f"unknown report {resource_kind}: {resource_id}")
    return {"api_version": REPORT_QUERY_API_VERSION, "resource_kind": resource_kind, "resource": found}


def _backup_file(root: Path, relative: str, occurred_at: datetime) -> Path:
    source = root / relative
    backup = root / REPORT_LOG_ROOT / "backups" / _stamp(occurred_at) / relative.replace("/", "__")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def _write_action_receipt(
    root: Path,
    *,
    action: str,
    resource_kind: str,
    resource_id: str,
    occurred_at: datetime,
    files: list[dict[str, Any]],
    readback: Mapping[str, Any],
    rollback_supported: bool,
) -> Path:
    receipt = root / REPORT_LOG_ROOT / "receipts" / f"{_stamp(occurred_at)}-{resource_kind}-{resource_id}-{action.rsplit('.', 1)[-1]}.yml"
    payload = {
        "api_version": ACTION_API_VERSION,
        "action": action,
        "resource": {"kind": resource_kind, "id": resource_id},
        "occurred_at": _iso(occurred_at),
        "files": files,
        "readback": deepcopy(dict(readback)),
        "rollback": {
            "supported": rollback_supported,
            "receipt": str(receipt.relative_to(root)),
            "guard": "current_sha256_must_match_after_sha256",
        },
        "external_effects": "none" if action != "report.run_now" else "filesystem only unless projection evidence says otherwise",
    }
    _atomic_yaml(receipt, payload)
    return receipt


def _lifecycle_action(
    root: str | Path,
    action: str,
    definition: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    os_root = expand_path(root)
    validation = validate_report_definition(os_root, definition)
    if action == "report.archive" and not validation["ok"]:
        schema_errors = _validate_schema(os_root, definition, "report-definition.schema.json")
        validation = {**validation, "ok": not schema_errors, "errors": schema_errors}
    if not validation["ok"]:
        raise ValueError("invalid report definition: " + "; ".join(validation["errors"]))
    registry = _load_registry(os_root, REPORT_REGISTRY)
    report_id = str(definition["id"])
    current = next((item for item in registry["definitions"] if isinstance(item, dict) and item.get("id") == report_id), None)
    if before is None and current is not None:
        raise ValueError(f"report definition already exists: {report_id}")
    if before is not None and current is None:
        raise ValueError(f"unknown report definition: {report_id}")
    planned = {
        "api_version": ACTION_API_VERSION,
        "action": action,
        "status": "planned" if dry_run else action.rsplit(".", 1)[-1] + "d",
        "dry_run": dry_run,
        "resource": {"kind": "report", "id": report_id, "before": deepcopy(before), "after": deepcopy(dict(definition))},
        "validation": validation,
        "backup": None,
        "receipt": None,
        "readback": {"ok": True, "definition": deepcopy(dict(definition))} if dry_run else None,
    }
    if dry_run:
        return planned
    occurred_at = _now()
    backup = _backup_file(os_root, REPORT_REGISTRY, occurred_at)
    registry["definitions"] = [item for item in registry["definitions"] if not isinstance(item, dict) or item.get("id") != report_id]
    registry["definitions"].append(deepcopy(dict(definition)))
    registry["definitions"].sort(key=lambda item: str(item.get("id") or ""))
    registry_path = os_root / REPORT_REGISTRY
    _atomic_yaml(registry_path, registry)
    readback = _definition_by_id(_load_registry(os_root, REPORT_REGISTRY), report_id)
    readback_ok = readback == dict(definition)
    file_evidence = {
        "path": REPORT_REGISTRY,
        "backup": str(backup.relative_to(os_root)),
        "before_sha256": _sha_json(_load_yaml(backup, {})),
        "after_sha256": _sha_json(_load_registry(os_root, REPORT_REGISTRY)),
    }
    receipt = _write_action_receipt(
        os_root,
        action=action,
        resource_kind="report",
        resource_id=report_id,
        occurred_at=occurred_at,
        files=[file_evidence],
        readback={"ok": readback_ok, "definition": readback},
        rollback_supported=True,
    )
    planned.update(
        {
            "backup": str(backup),
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "definition": readback},
        }
    )
    return planned


def create_report_definition(root: str | Path, definition: Mapping[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    normalized = deepcopy(dict(definition))
    report_id = validate_name(str(normalized.get("id") or ""), "report_id")
    timestamp = _iso()
    normalized.setdefault("schema_version", DEFINITION_SCHEMA_VERSION)
    normalized.setdefault("catalog_ref", None)
    normalized.setdefault("status", "active")
    normalized.setdefault("created_at", timestamp)
    normalized.setdefault("updated_at", normalized["created_at"])
    normalized.setdefault("archived_at", None)
    normalized["id"] = report_id
    validation = validate_report_definition(os_root, normalized)
    if not validation["ok"]:
        raise ValueError("invalid report definition: " + "; ".join(validation["errors"]))
    if not dry_run:
        ensure_report_registries(os_root)
    return _lifecycle_action(os_root, "report.create", normalized, before=None, dry_run=dry_run)


def update_report_definition(root: str | Path, report_id: str, definition: Mapping[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    before = _definition_by_id(_load_registry(os_root, REPORT_REGISTRY), report_id)
    normalized = {**deepcopy(before), **deepcopy(dict(definition))}
    if normalized.get("id") not in (None, report_id):
        raise ValueError("report update cannot change id")
    normalized["id"] = report_id
    normalized["schema_version"] = DEFINITION_SCHEMA_VERSION
    normalized["created_at"] = before["created_at"]
    normalized["updated_at"] = _iso()
    normalized.setdefault("archived_at", before.get("archived_at"))
    return _lifecycle_action(os_root, "report.update", normalized, before=before, dry_run=dry_run)


def set_report_archived(root: str | Path, report_id: str, *, archived: bool, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    before = _definition_by_id(_load_registry(os_root, REPORT_REGISTRY), report_id)
    expected = "archived" if archived else "active"
    if before["status"] == expected:
        return {
            "api_version": ACTION_API_VERSION,
            "action": "report.archive" if archived else "report.restore",
            "status": "unchanged",
            "dry_run": dry_run,
            "resource": {"kind": "report", "id": report_id, "before": before, "after": before},
            "backup": None,
            "receipt": None,
            "readback": {"ok": True, "definition": before},
        }
    after = deepcopy(before)
    after["status"] = expected
    after["archived_at"] = _iso() if archived else None
    after["updated_at"] = _iso()
    return _lifecycle_action(
        os_root,
        "report.archive" if archived else "report.restore",
        after,
        before=before,
        dry_run=dry_run,
    )


def _safe_source_path(root: Path, relative: str) -> Path:
    unresolved = root / relative
    try:
        unresolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source path escapes Agentic OS root: {relative}") from exc
    cursor = root
    for part in unresolved.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"source path may not traverse a symlink: {relative}")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"source path escapes Agentic OS root: {relative}") from exc
    return candidate


def _parse_source(path: Path, parser: str) -> Any:
    if not path.is_file():
        raise ValueError("file is missing")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError(f"file exceeds {MAX_SOURCE_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if parser == "json":
        return json.loads(text)
    if parser == "yaml":
        return yaml.safe_load(text)
    return text


def _record_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 1 if value not in (None, "") else 0


def _load_sources(root: Path, definition: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    values: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for source in definition.get("sources") or []:
        source_id = str(source["id"])
        required = bool(source["required"])
        observed_at = _iso()
        try:
            if source["kind"] == "filesystem":
                path = _safe_source_path(root, str(source.get("path") or ""))
                value = _parse_source(path, str(source.get("parser") or "text"))
                detail = str(path.relative_to(root))
            elif source["kind"] == "report_inventory":
                query = source.get("query") or {}
                rows = collect_reports(root, max_files=int(query.get("limit", 100)))
                for key in ("domain", "project", "status", "type"):
                    if query.get(key):
                        rows = [row for row in rows if row.get(key) == query[key]]
                value = rows
                detail = "bounded report inventory projection"
            else:
                raise ValueError(f"unsupported source kind: {source['kind']}")
            values[source_id] = value
            count = _record_count(value)
            source_status = "complete" if count else "partial"
            evidence.append(
                {
                    "source_id": source_id,
                    "required": required,
                    "status": source_status,
                    "detail": detail if count else f"{detail}; source returned no records",
                    "observed_at": observed_at,
                    "record_count": count,
                    "sha256": _sha_json(value),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
            level = "error" if required else "partial"
            detail = str(exc)
            evidence.append(
                {
                    "source_id": source_id,
                    "required": required,
                    "status": level,
                    "detail": detail,
                    "observed_at": observed_at,
                    "record_count": 0,
                    "sha256": None,
                }
            )
            errors.append({"source_id": source_id, "required": required, "code": "source_unavailable", "detail": detail})
    return values, evidence, errors


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"value": item} for item in value]
    if isinstance(value, dict):
        return [{"key": key, "value": item} for key, item in value.items()]
    return [{"value": value}] if value not in (None, "") else []


def _section_data(section: Mapping[str, Any], value: Any, source_evidence: Mapping[str, Any]) -> Any:
    kind = section["type"]
    if kind == "markdown":
        return value if isinstance(value, str) else yaml.safe_dump(value, sort_keys=False).strip()
    if kind == "table":
        return {"rows": _as_rows(value)}
    if kind == "chart":
        return {
            "chart_type": section.get("chart_type"),
            "x": section.get("x"),
            "y": section.get("y"),
            "series": _as_rows(value),
        }
    if kind in {"list", "timeline", "links"}:
        return {"items": _as_rows(value)}
    return deepcopy(dict(source_evidence))


def _build_sections(definition: Mapping[str, Any], values: Mapping[str, Any], evidence: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_source = {str(item["source_id"]): item for item in evidence}
    sections: list[dict[str, Any]] = []
    for spec in definition.get("sections") or []:
        source_id = str(spec["source_id"])
        source_evidence = by_source[source_id]
        sections.append(
            {
                "id": spec["id"],
                "type": spec["type"],
                "title": spec["title"],
                "status": source_evidence["status"],
                "data": _section_data(spec, values.get(source_id), source_evidence),
                "evidence": deepcopy(dict(source_evidence)),
            }
        )
    return sections


def _overall_status(evidence: Iterable[Mapping[str, Any]], errors: list[dict[str, Any]], partial_is_error: bool) -> str:
    rows = list(evidence)
    required_error = any(item.get("required") and item.get("status") == "error" for item in rows)
    any_partial = any(item.get("status") != "complete" for item in rows)
    if required_error or (partial_is_error and any_partial):
        return "error"
    if errors or any_partial:
        return "partial"
    return "success"


def _markdown_artifact(artifact: Mapping[str, Any], run: Mapping[str, Any]) -> str:
    lines = [
        f"# {artifact['title']}",
        "",
        str(artifact["summary"]),
        "",
        f"- Status: `{artifact['status']}`",
        f"- Definition: `{artifact['definition_id']}`",
        f"- Run: `{artifact['run_id']}`",
        f"- Source completeness: `{artifact['source_completeness']:.0%}`",
    ]
    for section in artifact["sections"]:
        lines.extend(["", f"## {section['title']}", "", f"Status: `{section['status']}`", ""])
        data = section["data"]
        if section["type"] == "markdown":
            lines.append(str(data))
        else:
            lines.extend(["```yaml", yaml.safe_dump(data, sort_keys=False).strip(), "```"])
    if run["errors"]:
        lines.extend(["", "## Errors and partial evidence", "", "```yaml", yaml.safe_dump(run["errors"], sort_keys=False).strip(), "```"])
    lines.extend(["", "## Projection evidence", "", "```yaml", yaml.safe_dump(run["projection_evidence"], sort_keys=False).strip(), "```", ""])
    return "\n".join(lines)


def _retention_plan(root: Path, definition: Mapping[str, Any], new_run: Mapping[str, Any]) -> dict[str, Any]:
    existing = [
        item
        for item in _load_registry(root, REPORT_RUN_REGISTRY)["runs"]
        if isinstance(item, dict) and item.get("definition_id") == definition["id"]
    ]
    if not any(item.get("id") == new_run.get("id") for item in existing):
        existing.append(dict(new_run))
    existing.sort(
        key=lambda item: (str(item.get("completed_at") or ""), str(item.get("id") or "")),
        reverse=True,
    )
    retention = definition["retention"]
    cutoff = _now() - timedelta(days=int(retention["max_age_days"]))
    candidates: list[dict[str, Any]] = []
    for index, run in enumerate(existing):
        completed = datetime.fromisoformat(str(run["completed_at"]).replace("Z", "+00:00"))
        reasons = []
        if index >= int(retention["max_runs"]):
            reasons.append("max_runs")
        if completed < cutoff:
            reasons.append("max_age_days")
        if reasons:
            candidates.append({"run_id": run["id"], "reasons": reasons})
    return {"policy": deepcopy(retention), "candidates": candidates, "action": "plan_only", "deleted": 0}


def run_report_now(
    root: str | Path,
    report_id: str,
    *,
    dry_run: bool = True,
    trigger: str = "manual",
    project_notion: bool = False,
    notion_workspace: str | None = None,
    notion_projector: NotionProjector | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    definition = _definition_by_id(_load_registry(os_root, REPORT_REGISTRY), report_id)
    validation = validate_report_definition(os_root, definition)
    if not validation["ok"]:
        raise ValueError("report definition is invalid or stale: " + "; ".join(validation["errors"]))
    if definition["status"] != "active":
        raise ValueError("archived report definitions cannot run")
    if not definition["permissions"]["run_now"]:
        raise ValueError("report definition forbids run-now")
    if project_notion and notion_workspace != "Genome's Notion":
        raise ValueError("Notion projection requires exact workspace verification: Genome's Notion")
    if dry_run:
        return {
            "api_version": ACTION_API_VERSION,
            "action": "report.run_now",
            "status": "planned",
            "dry_run": True,
            "resource": {"kind": "report", "id": report_id},
            "plan": {
                "sources": [item["id"] for item in definition["sources"]],
                "sections": [item["id"] for item in definition["sections"]],
                "destinations": deepcopy(definition["destinations"]),
                "notion_requested": project_notion,
            },
            "validation": validation,
            "readback": {"ok": True, "mutated": False},
        }

    started = _now()
    start_clock = time.monotonic()
    values, source_evidence, errors = _load_sources(os_root, definition)
    complete_count = sum(1 for item in source_evidence if item["status"] == "complete")
    completeness = complete_count / len(source_evidence) if source_evidence else 0.0
    status = _overall_status(source_evidence, errors, bool(definition["health_policy"]["partial_is_error"]))
    run_id = dated_name(
        f"{report_id}-{started.strftime('%H%M%S%fZ').lower()}",
        when=started,
        policy=load_artifact_naming_policy(os_root),
        scope="report_runs",
    )
    if not run_id or not all(character.islower() or character.isdigit() or character in "-_" for character in run_id):
        raise ValueError(f"invalid report run id: {run_id!r}")
    artifact_id = f"{run_id}_artifact"
    sections = _build_sections(definition, values, source_evidence)
    provisional = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "id": artifact_id,
        "definition_id": report_id,
        "run_id": run_id,
        "created_at": _iso(started),
        "status": status,
        "title": definition["name"],
        "summary": definition["summary"],
        "sections": sections,
        "source_completeness": completeness,
        "errors": deepcopy(errors),
    }
    projection_evidence: list[dict[str, Any]] = []
    for destination in definition["destinations"]:
        if not destination["enabled"]:
            projection_evidence.append({"kind": destination["kind"], "status": "disabled", "external_write": False})
            continue
        if destination["kind"] == "filesystem":
            projection_evidence.append({"kind": "filesystem", "status": "complete", "external_write": False})
            continue
        if not project_notion:
            projection_evidence.append(
                {"kind": "notion", "status": "skipped", "detail": "projection not requested", "external_write": False}
            )
            continue
        if not definition["permissions"]["notion_projection"]:
            projection_evidence.append(
                {"kind": "notion", "status": "error", "detail": "definition forbids Notion projection", "external_write": False}
            )
            errors.append({"code": "notion_permission_denied", "detail": "definition forbids Notion projection"})
            status = "partial" if status == "success" else status
            continue
        if destination.get("workspace") != "Genome's Notion":
            projection_evidence.append(
                {"kind": "notion", "status": "error", "detail": "destination workspace is not Genome's Notion", "external_write": False}
            )
            errors.append({"code": "notion_destination_mismatch", "detail": "workspace verification failed"})
            status = "partial" if status == "success" else status
            continue
        if notion_projector is None:
            projection_evidence.append(
                {"kind": "notion", "status": "error", "detail": "no approved Notion projector is configured", "external_write": False}
            )
            errors.append({"code": "notion_projector_unavailable", "detail": "no approved projector configured"})
            status = "partial" if status == "success" else status
            continue
        try:
            projected = dict(notion_projector(provisional, deepcopy(destination)))
            projection_evidence.append(
                {
                    "kind": "notion",
                    "status": "complete" if projected.get("ok") else "error",
                    "workspace": "Genome's Notion",
                    "external_write": bool(projected.get("ok")),
                    "receipt": projected.get("receipt"),
                }
            )
            if not projected.get("ok"):
                errors.append({"code": "notion_projection_failed", "detail": str(projected.get("error") or "unknown")})
                status = "partial" if status == "success" else status
        except Exception as exc:  # external adapter failures are evidence, not hidden crashes
            projection_evidence.append(
                {"kind": "notion", "status": "error", "detail": str(exc), "external_write": False}
            )
            errors.append({"code": "notion_projection_failed", "detail": str(exc)})
            status = "partial" if status == "success" else status

    completed = _now()
    artifact_without_hash = {**provisional, "status": status, "errors": deepcopy(errors)}
    artifact = {**artifact_without_hash, "content_sha256": _sha_json(artifact_without_hash)}
    run = {
        "schema_version": RUN_SCHEMA_VERSION,
        "id": run_id,
        "definition_id": report_id,
        "status": status,
        "started_at": _iso(started),
        "completed_at": _iso(completed),
        "duration_ms": max(0, round((time.monotonic() - start_clock) * 1000)),
        "source_completeness": completeness,
        "source_evidence": source_evidence,
        "errors": errors,
        "artifact_ids": [artifact_id],
        "projection_evidence": projection_evidence,
        "trigger": trigger,
    }
    run_errors = _validate_schema(os_root, run, "report-run.schema.json")
    artifact_errors = _validate_schema(os_root, artifact, "report-artifact.schema.json")
    if run_errors or artifact_errors:
        raise ValueError("generated report contract failed validation: " + "; ".join(run_errors + artifact_errors))

    occurred_at = _now()
    run_registry = _load_registry(os_root, REPORT_RUN_REGISTRY)
    artifact_registry = _load_registry(os_root, REPORT_ARTIFACT_REGISTRY)
    run_registry_backup = _backup_file(os_root, REPORT_RUN_REGISTRY, occurred_at)
    artifact_registry_backup = _backup_file(os_root, REPORT_ARTIFACT_REGISTRY, occurred_at)
    run_dir = os_root / REPORT_RUN_ROOT / report_id / run_id
    if run_dir.exists():
        raise ValueError(f"report run id collision: {run_id}")
    run_dir.mkdir(parents=True)
    run_path = run_dir / "run.yml"
    artifact_path = run_dir / "artifact.json"
    markdown_path = run_dir / "report.md"
    _atomic_yaml(run_path, run)
    _atomic_json(artifact_path, artifact)
    _atomic_write(markdown_path, _markdown_artifact(artifact, run))
    run_index = {**run, "path": str(run_path.relative_to(os_root))}
    artifact_index = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "id": artifact_id,
        "definition_id": report_id,
        "run_id": run_id,
        "status": status,
        "created_at": artifact["created_at"],
        "content_sha256": artifact["content_sha256"],
        "path": str(artifact_path.relative_to(os_root)),
        "markdown_path": str(markdown_path.relative_to(os_root)),
    }
    run_registry["runs"].append(run_index)
    artifact_registry["artifacts"].append(artifact_index)
    _atomic_yaml(os_root / REPORT_RUN_REGISTRY, run_registry)
    _atomic_yaml(os_root / REPORT_ARTIFACT_REGISTRY, artifact_registry)
    readback_run = get_report_resource(os_root, "run", run_id)["resource"]
    readback_artifact = get_report_resource(os_root, "artifact", artifact_id)["resource"]
    retention = _retention_plan(os_root, definition, run)
    files = [
        {
            "path": REPORT_RUN_REGISTRY,
            "backup": str(run_registry_backup.relative_to(os_root)),
            "before_sha256": _sha_json(_load_yaml(run_registry_backup, {})),
            "after_sha256": _sha_json(_load_registry(os_root, REPORT_RUN_REGISTRY)),
        },
        {
            "path": REPORT_ARTIFACT_REGISTRY,
            "backup": str(artifact_registry_backup.relative_to(os_root)),
            "before_sha256": _sha_json(_load_yaml(artifact_registry_backup, {})),
            "after_sha256": _sha_json(_load_registry(os_root, REPORT_ARTIFACT_REGISTRY)),
        },
        {"path": str(run_path.relative_to(os_root)), "backup": None, "before_sha256": None, "after_sha256": _sha_bytes(run_path.read_bytes())},
        {"path": str(artifact_path.relative_to(os_root)), "backup": None, "before_sha256": None, "after_sha256": _sha_bytes(artifact_path.read_bytes())},
        {"path": str(markdown_path.relative_to(os_root)), "backup": None, "before_sha256": None, "after_sha256": _sha_bytes(markdown_path.read_bytes())},
    ]
    receipt = _write_action_receipt(
        os_root,
        action="report.run_now",
        resource_kind="report_run",
        resource_id=run_id,
        occurred_at=occurred_at,
        files=files,
        readback={"ok": readback_run["id"] == run_id and readback_artifact["id"] == artifact_id},
        rollback_supported=False,
    )
    return {
        "api_version": ACTION_API_VERSION,
        "action": "report.run_now",
        "status": status,
        "dry_run": False,
        "resource": {"kind": "report_run", "id": run_id, "definition_id": report_id},
        "run": run,
        "artifact": artifact,
        "paths": {"run": str(run_path), "artifact": str(artifact_path), "markdown": str(markdown_path)},
        "retention": retention,
        "receipt": str(receipt),
        "readback": {"ok": True, "run": readback_run, "artifact": readback_artifact},
    }


def rollback_report_action(root: str | Path, receipt_ref: str, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    receipt_path = _safe_source_path(os_root, receipt_ref)
    receipt_root = (os_root / REPORT_LOG_ROOT / "receipts").resolve()
    try:
        receipt_path.relative_to(receipt_root)
    except ValueError as exc:
        raise ValueError("report rollback accepts only report-engine lifecycle receipts") from exc
    receipt = _load_yaml(receipt_path, {})
    if not isinstance(receipt, dict) or receipt.get("api_version") != ACTION_API_VERSION:
        raise ValueError("invalid resource action receipt")
    if not (receipt.get("rollback") or {}).get("supported"):
        raise ValueError("this report action is immutable and does not support rollback")
    files = receipt.get("files") or []
    guards: list[dict[str, Any]] = []
    for item in files:
        path = _safe_source_path(os_root, str(item["path"]))
        current = _sha_json(_load_yaml(path, {}))
        ok = current == item.get("after_sha256")
        guards.append({"path": item["path"], "ok": ok, "expected": item.get("after_sha256"), "actual": current})
    if not all(item["ok"] for item in guards):
        raise ValueError("rollback refused because report registry changed after the receipt")
    result = {
        "api_version": ACTION_API_VERSION,
        "action": "report.rollback",
        "status": "planned" if dry_run else "rolled_back",
        "dry_run": dry_run,
        "resource": deepcopy(receipt["resource"]),
        "guards": guards,
        "readback": {"ok": True, "restored": False if dry_run else True},
        "receipt": None,
    }
    if dry_run:
        return result
    occurred_at = _now()
    for item in files:
        backup = _safe_source_path(os_root, str(item["backup"]))
        try:
            backup.relative_to((os_root / REPORT_LOG_ROOT / "backups").resolve())
        except ValueError as exc:
            raise ValueError("report rollback backup is outside the governed backup root") from exc
        destination = _safe_source_path(os_root, str(item["path"]))
        _atomic_write(destination, backup.read_text(encoding="utf-8"))
    rollback_receipt = os_root / REPORT_LOG_ROOT / "receipts" / f"{_stamp(occurred_at)}-report-rollback.yml"
    _atomic_yaml(
        rollback_receipt,
        {
            "api_version": ACTION_API_VERSION,
            "action": "report.rollback",
            "occurred_at": _iso(occurred_at),
            "source_receipt": str(receipt_path.relative_to(os_root)),
            "resource": deepcopy(receipt["resource"]),
            "readback": {"ok": True},
        },
    )
    result["receipt"] = str(rollback_receipt)
    return result


def consolidation_plan(root: str | Path, *, stale_days: int = 30) -> dict[str, Any]:
    if stale_days < 1 or stale_days > 3650:
        raise ValueError("stale_days must be between 1 and 3650")
    os_root = expand_path(root)
    definitions = _load_registry(os_root, REPORT_REGISTRY)["definitions"]
    runs = _load_registry(os_root, REPORT_RUN_REGISTRY)["runs"]
    by_key: dict[str, list[str]] = {}
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        key = _sha_json(
            {
                "name": " ".join(str(definition.get("name") or "").lower().split()),
                "generator": definition.get("generator"),
                "sources": definition.get("sources"),
                "scope": definition.get("scope"),
            }
        )
        by_key.setdefault(key, []).append(str(definition["id"]))
    duplicates = [
        {"definition_ids": sorted(ids), "recommendation": "review_and_choose_canonical"}
        for ids in by_key.values()
        if len(ids) > 1
    ]
    latest_by_definition: dict[str, str] = {}
    for run in runs:
        if isinstance(run, dict):
            latest_by_definition[str(run.get("definition_id"))] = max(
                str(run.get("completed_at") or ""), latest_by_definition.get(str(run.get("definition_id")), "")
            )
    cutoff = _now() - timedelta(days=stale_days)
    stale: list[dict[str, Any]] = []
    for definition in definitions:
        if not isinstance(definition, dict) or definition.get("status") == "archived":
            continue
        latest = latest_by_definition.get(str(definition["id"]))
        if latest is None:
            stale.append({"definition_id": definition["id"], "reason": "never_run"})
        elif datetime.fromisoformat(latest.replace("Z", "+00:00")) < cutoff:
            stale.append({"definition_id": definition["id"], "reason": "last_run_before_cutoff", "latest_run": latest})
    canonical_paths = {
        str(item.get("path"))
        for item in _load_registry(os_root, REPORT_ARTIFACT_REGISTRY)["artifacts"]
        if isinstance(item, dict)
    }
    legacy = [
        {"source": row["source"], "title": row["title"], "recommendation": "map_or_leave_as_legacy"}
        for row in collect_reports(os_root, max_files=500)
        if row["source"] not in canonical_paths and REPORT_LOG_ROOT not in row["source"]
    ]
    catalog = _load_yaml(os_root / REPORT_CATALOG_REGISTRY, {"reports": []})
    catalog_rows = catalog.get("reports", []) if isinstance(catalog, dict) else []
    catalog_ids = {
        str(item.get("id")) for item in catalog_rows if isinstance(item, dict) and item.get("id")
    }
    definitions_by_catalog = {
        str(item.get("catalog_ref"))
        for item in definitions
        if isinstance(item, dict) and item.get("catalog_ref")
    }
    catalog_gaps = {
        "catalog_without_definition": sorted(catalog_ids - definitions_by_catalog),
        "definition_without_catalog": sorted(
            str(item.get("id"))
            for item in definitions
            if isinstance(item, dict) and not item.get("catalog_ref")
        ),
    }
    return {
        "api_version": REPORT_QUERY_API_VERSION,
        "action": "report.consolidation_plan",
        "generated_at": _iso(),
        "stale_days": stale_days,
        "duplicates": duplicates,
        "stale": stale,
        "legacy_artifacts": legacy,
        "catalog_gaps": catalog_gaps,
        "summary": {
            "duplicate_groups": len(duplicates),
            "stale_definitions": len(stale),
            "legacy_artifacts": len(legacy),
            "catalog_without_definition": len(catalog_gaps["catalog_without_definition"]),
            "definition_without_catalog": len(catalog_gaps["definition_without_catalog"]),
        },
        "mutation": {"performed": False, "deletions": 0, "automatic_archive": False},
    }


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "DEFINITION_SCHEMA_VERSION",
    "REPORT_ARTIFACT_REGISTRY",
    "REPORT_REGISTRY",
    "REPORT_RUN_REGISTRY",
    "RUN_SCHEMA_VERSION",
    "consolidation_plan",
    "create_report_definition",
    "ensure_report_registries",
    "get_report_resource",
    "load_definition_file",
    "query_report_resources",
    "report_resource_projection",
    "rollback_report_action",
    "run_report_now",
    "set_report_archived",
    "update_report_definition",
    "validate_report_definition",
]
