"""Governed, versioned workflow authoring and queue-only run requests.

Workflow definitions remain local filesystem objects.  The public API accepts a
canonical domain/lane/id identity and never accepts a target path, shell
command, provider query, or execution destination.  Definitions, immutable
versions, installed instances, and workflow runs are deliberately separate
resource kinds.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from .runtime_ops import append_run_queue_item
from .scaffold import (
    create_workflow,
    domain_path,
    expand_path,
    installed_domain_names,
    normalize_domain,
    repo_root,
    shared_factory_path,
    validate_name,
)
from .workflow_ops import check_workflow


API_VERSION = "workflow-engine/v1"
DEFINITION_SCHEMA_VERSION = 1
DEFINITION_FILE = ".agentic-workflow.yml"
INSTANCE_FILE = ".agentic-workflow-instance.yml"
VERSION_ROOT = Path("harness/shared_factory/00-control-plane/workflow-engine/versions")
EVIDENCE_ROOT = Path("harness/shared_factory/06-runs-and-logs/workflow-engine")
MAX_DEFINITION_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_QUERY_LIMIT = 500
DRIFT_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9:_-]{1,180}$")
RECEIPT_ID_PATTERN = re.compile(r"^\d{8}T\d{12}Z-[a-z_]+-[a-f0-9]{8}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_stamp()}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _atomic_yaml(path: Path, value: Any) -> None:
    _atomic_bytes(path, yaml.safe_dump(value, sort_keys=False).encode("utf-8"))


def _load_yaml(path: Path, *, default: Any | None = None) -> Any:
    if not path.is_file():
        if default is not None:
            return deepcopy(default)
        raise ValueError(f"required file is missing: {path}")
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError(f"workflow file exceeds {MAX_RECORD_BYTES} bytes: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    return deepcopy(default) if value is None and default is not None else value


def load_workflow_definition_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"definition file is missing: {source}")
    if source.stat().st_size > MAX_DEFINITION_BYTES:
        raise ValueError(f"definition file exceeds {MAX_DEFINITION_BYTES} bytes")
    if source.suffix.lower() == ".json":
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON definition: {exc}") from exc
    else:
        value = _load_yaml(source, default={})
    if not isinstance(value, dict):
        raise ValueError("workflow definition file must contain an object")
    return value


def _schema_path(root: Path) -> Path:
    installed = root / "harness/schemas/workflow-definition.schema.json"
    if installed.is_file():
        return installed
    source = repo_root() / "schemas/workflow-definition.schema.json"
    if source.is_file():
        return source
    raise ValueError("workflow definition schema is unavailable")


def _json_path(parts: list[Any]) -> str:
    path = "$"
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _finding(code: str, message: str, *, path: str = "$", severity: str = "error", step_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": severity, "path": path, "message": message}
    if step_id:
        result["step_id"] = step_id
    return result


def validate_workflow_definition(root: str | Path, definition: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a definition with field- and step-addressable findings."""

    os_root = expand_path(root)
    findings: list[dict[str, Any]] = []
    schema = json.loads(_schema_path(os_root).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(dict(definition)), key=lambda item: tuple(str(part) for part in item.path)):
        path = _json_path(list(error.absolute_path))
        step_id = None
        parts = list(error.absolute_path)
        if len(parts) >= 2 and parts[0] == "steps" and isinstance(parts[1], int):
            steps = definition.get("steps")
            if isinstance(steps, list) and parts[1] < len(steps) and isinstance(steps[parts[1]], dict):
                step_id = str(steps[parts[1]].get("id") or "") or None
        findings.append(_finding("schema_error", error.message, path=path, step_id=step_id))

    steps = definition.get("steps")
    if isinstance(steps, list):
        ids: list[str] = []
        orders: list[int] = []
        by_id: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(steps):
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("id") or "")
            if step_id in ids:
                findings.append(_finding("duplicate_step_id", f"duplicate step id: {step_id}", path=f"$.steps[{index}].id", step_id=step_id))
            ids.append(step_id)
            by_id[step_id] = raw
            order = raw.get("order")
            if isinstance(order, int) and not isinstance(order, bool):
                if order in orders:
                    findings.append(_finding("duplicate_step_order", f"duplicate step order: {order}", path=f"$.steps[{index}].order", step_id=step_id))
                orders.append(order)
                if order != index + 1:
                    findings.append(
                        _finding(
                            "invalid_step_order",
                            f"step list position {index + 1} must use order {index + 1}, not {order}",
                            path=f"$.steps[{index}].order",
                            step_id=step_id,
                        )
                    )
        position = {step_id: index for index, step_id in enumerate(ids)}
        graph: dict[str, list[str]] = {}
        for index, raw in enumerate(steps):
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("id") or "")
            dependencies = raw.get("depends_on")
            if not isinstance(dependencies, list):
                continue
            graph[step_id] = []
            for dependency in dependencies:
                dependency = str(dependency)
                if dependency not in by_id:
                    findings.append(
                        _finding(
                            "unknown_step_dependency",
                            f"unknown dependency: {dependency}",
                            path=f"$.steps[{index}].depends_on",
                            step_id=step_id,
                        )
                    )
                    continue
                graph[step_id].append(dependency)
                if position.get(dependency, index) >= index:
                    findings.append(
                        _finding(
                            "dependency_not_prior",
                            f"dependency must reference an earlier step: {dependency}",
                            path=f"$.steps[{index}].depends_on",
                            step_id=step_id,
                        )
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return True
            if step_id in visited:
                return False
            visiting.add(step_id)
            cyclic = any(visit(dependency) for dependency in graph.get(step_id, []))
            visiting.remove(step_id)
            visited.add(step_id)
            return cyclic

        for step_id in graph:
            if visit(step_id):
                findings.append(_finding("step_dependency_cycle", "step dependency graph contains a cycle", path="$.steps", step_id=step_id))
                break

    findings.sort(key=lambda item: (item["path"], item["code"], item.get("step_id") or ""))
    errors = [item for item in findings if item["severity"] == "error"]
    return {
        "api_version": API_VERSION,
        "resource_kind": "workflow_definition",
        "resource_id": definition.get("id"),
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len([item for item in findings if item["severity"] == "warning"]),
        "findings": findings,
    }


def _domains(root: Path) -> list[str]:
    names = installed_domain_names(root)
    if shared_factory_path(root).is_dir():
        names.append("shared_factory")
    return sorted(set(names))


def _ensure_contained(root: Path, target: Path) -> Path:
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"derived workflow target escaped the installed root: {target}")
    return target


def _target(root: Path, workflow_id: str, domain: str, lane: str) -> dict[str, Any]:
    workflow_id = validate_name(workflow_id, "workflow")
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    base = domain_path(root, domain)
    if not base.is_dir():
        raise ValueError(f"unknown installed domain: {domain}")
    path = base / "03-workflows" / lane / workflow_id
    definition = path / DEFINITION_FILE
    instance = path / INSTANCE_FILE
    version_root = root / VERSION_ROOT / domain / lane / workflow_id
    for item in (path, definition, instance, version_root):
        _ensure_contained(root, item)
    return {
        "id": workflow_id,
        "domain": domain,
        "lane": lane,
        "path": path,
        "definition": definition,
        "instance": instance,
        "version_root": version_root,
        "definition_id": f"workflow_definition:{domain}:{lane}:{workflow_id}",
        "instance_id": f"workflow_instance:{domain}:{lane}:{workflow_id}",
        "identity": f"workflow:{domain}:{lane}:{workflow_id}",
    }


def _iter_targets(root: Path, *, domain: str | None = None, lane: str | None = None) -> list[dict[str, Any]]:
    domains = [normalize_domain(domain)] if domain else _domains(root)
    found: list[dict[str, Any]] = []
    for domain_name in domains:
        collection = domain_path(root, domain_name) / "03-workflows"
        if not collection.is_dir():
            continue
        lanes = [validate_name(lane, "lane")] if lane else sorted(path.name for path in collection.iterdir() if path.is_dir())
        for lane_name in lanes:
            lane_root = collection / lane_name
            if not lane_root.is_dir():
                continue
            for child in sorted(lane_root.iterdir()):
                if child.is_dir() and re.fullmatch(r"[a-z0-9_]+", child.name):
                    found.append(_target(root, child.name, domain_name, lane_name))
    return found


def _relative(root: Path, path: Path) -> str:
    _ensure_contained(root, path)
    return str(path.relative_to(root))


def _state_hash(root: Path, targets: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(str(targets["identity"]).encode("utf-8") + b"\0")
    target = Path(targets["path"])
    if target.is_dir():
        for path in sorted(item for item in target.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise ValueError(f"workflow contract file cannot be a symlink: {path}")
            digest.update(str(path.relative_to(target)).encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    else:
        digest.update(b"<workflow-absent>\0")
    version_root = Path(targets["version_root"])
    if version_root.is_dir():
        for path in sorted(item for item in version_root.glob("*.yml") if item.is_file()):
            if path.is_symlink():
                raise ValueError(f"workflow version cannot be a symlink: {path}")
            digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _summary_from_markdown(path: Path, workflow_id: str) -> tuple[str, str]:
    name = workflow_id.replace("_", " ").title()
    summary = f"Legacy workflow {name}."
    if not path.is_file():
        return name, summary
    content = path.read_text(encoding="utf-8", errors="replace")
    for line in content.splitlines():
        if line.startswith("# "):
            name = line[2:].strip().split(":", 1)[-1].strip() or name
            break
    for block in re.split(r"\n\s*\n", content):
        text = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if text and not text.startswith(("#", "|", "- Status:")):
            summary = text[:1000]
            break
    return name, summary


def _legacy_projection(root: Path, targets: Mapping[str, Any]) -> dict[str, Any]:
    name, summary = _summary_from_markdown(Path(targets["path"]) / "workflow.md", str(targets["id"]))
    readiness = check_workflow(root, str(targets["domain"]), str(targets["lane"]), str(targets["id"]))
    severities = {item.severity for item in readiness}
    health = "blocked" if "blocker" in severities else "degraded" if "fix-soon" in severities else "healthy"
    return {
        "resource_kind": "workflow_definition",
        "definition_id": targets["definition_id"],
        "id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "name": name,
        "summary": summary,
        "owner": None,
        "availability": "active",
        "health": health,
        "version": None,
        "steps": [],
        "linked_capabilities": [],
        "managed": False,
        "editable": False,
        "source_state": "partial",
        "partial_sources": [DEFINITION_FILE],
        "source": {"kind": "filesystem", "path": _relative(root, Path(targets["path"]) / "workflow.md")},
        "drift_hash": _state_hash(root, targets),
        "validation": {"ok": False, "findings": [_finding("managed_definition_missing", "managed workflow definition is missing", path=f"$.{DEFINITION_FILE}", severity="warning")]},
    }


def _managed_definition(root: Path, targets: Mapping[str, Any]) -> dict[str, Any]:
    value = _load_yaml(Path(targets["definition"]), default={})
    if not isinstance(value, dict):
        raise ValueError(f"workflow definition must contain an object: {targets['definition']}")
    return value


def _definition_projection(root: Path, targets: Mapping[str, Any]) -> dict[str, Any]:
    if not Path(targets["definition"]).is_file():
        return _legacy_projection(root, targets)
    try:
        definition = _managed_definition(root, targets)
    except ValueError as exc:
        name, summary = _summary_from_markdown(Path(targets["path"]) / "workflow.md", str(targets["id"]))
        return {
            "resource_kind": "workflow_definition",
            "definition_id": targets["definition_id"],
            "id": targets["id"],
            "domain": targets["domain"],
            "lane": targets["lane"],
            "name": name,
            "summary": summary,
            "owner": None,
            "availability": "active",
            "health": "blocked",
            "version": None,
            "steps": [],
            "linked_capabilities": [],
            "managed": True,
            "editable": False,
            "source_state": "invalid",
            "partial_sources": [DEFINITION_FILE],
            "source": {"kind": "filesystem", "path": _relative(root, Path(targets["definition"]))},
            "drift_hash": _state_hash(root, targets),
            "validation": {
                "ok": False,
                "findings": [_finding("definition_parse_error", str(exc), path=f"$.{DEFINITION_FILE}")],
            },
        }
    validation = validate_workflow_definition(root, definition)
    instance = _load_yaml(Path(targets["instance"]), default=None) if Path(targets["instance"]).is_file() else None
    versions = sorted(Path(targets["version_root"]).glob("*.yml")) if Path(targets["version_root"]).is_dir() else []
    return {
        **deepcopy(definition),
        "resource_kind": "workflow_definition",
        "definition_id": targets["definition_id"],
        "id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "managed": True,
        "editable": True,
        "source_state": "complete" if validation["ok"] else "invalid",
        "partial_sources": [],
        "source": {"kind": "filesystem", "path": _relative(root, Path(targets["definition"]))},
        "drift_hash": _state_hash(root, targets),
        "validation": validation,
        "relationships": {
            "instance_id": instance.get("id") if isinstance(instance, dict) else None,
            "active_version_id": instance.get("version_id") if isinstance(instance, dict) else None,
            "version_count": len(versions),
        },
    }


def _version_records(root: Path, targets: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    base = Path(targets["version_root"]) if targets else root / VERSION_ROOT
    if not base.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.yml")):
        if path.is_symlink() or not path.resolve().is_relative_to((root / VERSION_ROOT).resolve()):
            continue
        value = _load_yaml(path, default={})
        if isinstance(value, dict) and value.get("api_version") == API_VERSION and value.get("resource_kind") == "workflow_version":
            records.append({**value, "source": {"kind": "immutable_version", "path": _relative(root, path)}})
    return records


def _instance_records(root: Path, targets: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    choices = [targets] if targets else _iter_targets(root)
    records: list[dict[str, Any]] = []
    for choice in choices:
        if choice is None or not Path(choice["instance"]).is_file():
            continue
        value = _load_yaml(Path(choice["instance"]), default={})
        if isinstance(value, dict) and value.get("resource_kind") == "workflow_instance":
            records.append({**value, "source": {"kind": "instance_pointer", "path": _relative(root, Path(choice["instance"]))}, "drift_hash": _state_hash(root, choice)})
    return records


def _run_records(root: Path) -> list[dict[str, Any]]:
    run_root = root / EVIDENCE_ROOT / "run-requests"
    if not run_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(run_root.glob("*.yml")):
        value = _load_yaml(path, default={})
        if isinstance(value, dict) and value.get("resource_kind") == "workflow_run":
            records.append({**value, "source": {"kind": "run_request", "path": _relative(root, path)}})
    return records


def _matches_filters(
    item: Mapping[str, Any],
    *,
    domain: str | None,
    lane: str | None,
    workflow: str | None,
    availability: str | None,
    health: str | None,
    owner: str | None,
    linked_capability: str | None,
    query: str | None,
    include_archived: bool,
) -> bool:
    if domain and item.get("domain") != domain:
        return False
    if lane and item.get("lane") != lane:
        return False
    if workflow and item.get("workflow_id", item.get("id")) != workflow:
        return False
    if not include_archived and item.get("availability") == "archived":
        return False
    if availability and item.get("availability") != availability:
        return False
    if health and item.get("health") != health:
        return False
    if owner and str(item.get("owner") or "").casefold() != owner.casefold():
        return False
    if linked_capability:
        linked = json.dumps(item.get("linked_capabilities") or [], sort_keys=True).casefold()
        if linked_capability.casefold() not in linked:
            return False
    if query:
        haystack = " ".join(str(item.get(key) or "") for key in ("id", "name", "summary", "owner", "domain", "lane"))
        haystack += " " + json.dumps(item.get("steps") or [], sort_keys=True, default=str)
        if query.casefold() not in haystack.casefold():
            return False
    return True


def query_workflow_resources(
    root: str | Path,
    resource_kind: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
    workflow: str | None = None,
    availability: str | None = None,
    health: str | None = None,
    owner: str | None = None,
    linked_capability: str | None = None,
    query: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if limit < 1 or limit > MAX_QUERY_LIMIT:
        raise ValueError(f"workflow query limit must be between 1 and {MAX_QUERY_LIMIT}")
    domain = normalize_domain(domain) if domain else None
    lane = validate_name(lane, "lane") if lane else None
    workflow = validate_name(workflow, "workflow") if workflow else None
    if resource_kind == "definition":
        items = [_definition_projection(os_root, item) for item in _iter_targets(os_root, domain=domain, lane=lane)]
    elif resource_kind == "version":
        items = _version_records(os_root)
    elif resource_kind == "instance":
        items = _instance_records(os_root)
    elif resource_kind == "run":
        items = _run_records(os_root)
    else:
        raise ValueError(f"unsupported workflow resource kind: {resource_kind}")
    items = [
        item
        for item in items
        if _matches_filters(
            item,
            domain=domain,
            lane=lane,
            workflow=workflow,
            availability=availability,
            health=health,
            owner=owner,
            linked_capability=linked_capability,
            query=query,
            include_archived=include_archived,
        )
    ]
    items.sort(key=lambda item: (str(item.get("updated_at") or item.get("published_at") or item.get("created_at") or ""), str(item.get("id") or "")), reverse=True)
    partial_count = len([item for item in items if item.get("source_state") == "partial"])
    invalid_count = len([item for item in items if item.get("source_state") == "invalid"])
    total_count = len(items)
    items = items[:limit]
    return {
        "api_version": API_VERSION,
        "resource_kind": resource_kind,
        "count": len(items),
        "total_count": total_count,
        "limit": limit,
        "truncated": len(items) < total_count,
        "items": items,
        "source_health": {
            "status": "invalid" if invalid_count else "partial" if partial_count else "complete",
            "partial_count": partial_count,
            "invalid_count": invalid_count,
        },
    }


def get_workflow_resource(
    root: str | Path,
    resource_kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if resource_kind in {"definition", "instance"}:
        if not domain or not lane:
            raise ValueError(f"--domain and --lane are required for workflow {resource_kind} get")
        targets = _target(os_root, resource_id, domain, lane)
        if not Path(targets["path"]).is_dir():
            raise ValueError(f"unknown workflow: {resource_id}")
        if resource_kind == "definition":
            found = _definition_projection(os_root, targets)
        else:
            records = _instance_records(os_root, targets)
            found = records[0] if records else None
    elif resource_kind == "version":
        found = next((item for item in _version_records(os_root) if item.get("id") == resource_id), None)
    elif resource_kind == "run":
        found = next((item for item in _run_records(os_root) if item.get("id") == resource_id), None)
    else:
        raise ValueError(f"unsupported workflow resource kind: {resource_kind}")
    if found is None:
        raise ValueError(f"unknown workflow {resource_kind}: {resource_id}")
    return {"api_version": API_VERSION, "resource_kind": resource_kind, "resource": found}


def _normalize_definition(definition: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    normalized = deepcopy(dict(definition))
    occurred_at = _iso(now)
    normalized.setdefault("schema_version", DEFINITION_SCHEMA_VERSION)
    normalized.setdefault("resource_kind", "workflow_definition")
    normalized.setdefault("availability", "draft")
    normalized.setdefault("health", "unknown")
    normalized.setdefault("owner", "OS Owner")
    normalized.setdefault("inputs", {})
    normalized.setdefault("outputs", {})
    normalized.setdefault("approvals", [])
    normalized.setdefault("retry", {"max_attempts": 1, "backoff_seconds": 0})
    normalized.setdefault("failure_policy", "stop")
    normalized.setdefault("prompts", [])
    normalized.setdefault("agents", [])
    normalized.setdefault("models", [])
    normalized.setdefault("linked_capabilities", [])
    normalized.setdefault("publish", {"allowed": True})
    normalized.setdefault("created_at", occurred_at)
    normalized.setdefault("updated_at", normalized["created_at"])
    for index, step in enumerate(normalized.get("steps") or []):
        if not isinstance(step, dict):
            continue
        step.setdefault("summary", str(step.get("name") or step.get("id") or "Workflow step"))
        step.setdefault("order", index + 1)
        step.setdefault("kind", "manual")
        step.setdefault("depends_on", [])
        step.setdefault("inputs", {})
        step.setdefault("outputs", {})
        step.setdefault("approvals", [])
        step.setdefault("retry", {"max_attempts": 1, "backoff_seconds": 0})
        step.setdefault("failure_policy", "stop")
    return normalized


def _validate_identity(definition: Mapping[str, Any], targets: Mapping[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_definition(definition)
    workflow_id = validate_name(str(normalized.get("id") or ""), "workflow")
    domain = normalize_domain(str(normalized.get("domain") or ""))
    lane = validate_name(str(normalized.get("lane") or ""), "lane")
    normalized.update({"id": workflow_id, "domain": domain, "lane": lane})
    if targets:
        for field in ("id", "domain", "lane"):
            if normalized[field] != targets[field]:
                raise ValueError(f"workflow update cannot change {field}")
    return normalized


def _confirm(expected: str | None, actual: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    if expected is None:
        raise ValueError("--expected-drift-hash is required with --apply; run the dry-run plan first")
    if not DRIFT_HASH_PATTERN.fullmatch(expected):
        raise ValueError(f"invalid expected drift hash: {expected!r}")
    if expected != actual:
        raise ValueError(f"stale workflow plan: expected drift hash {expected}, current drift hash {actual}")


def _file_state(root: Path, path: Path) -> dict[str, Any]:
    _ensure_contained(root, path)
    data = path.read_bytes() if path.is_file() else None
    return {
        "path": _relative(root, path),
        "existed": data is not None,
        "sha256": _sha(data) if data is not None else None,
        "bytes_base64": base64.b64encode(data).decode("ascii") if data is not None else None,
    }


def _backup(root: Path, targets: Mapping[str, Any], *, action: str, files: list[Path]) -> tuple[str, Path, dict[str, Any]]:
    occurred_at = _now()
    backup_id = f"{_stamp(occurred_at)}-{action.rsplit('.', 1)[-1].replace('-', '_')}-{_sha(str(targets['identity']) + _stamp(occurred_at))[:8]}"
    path = root / EVIDENCE_ROOT / "backups" / f"{backup_id}.yml"
    payload = {
        "api_version": API_VERSION,
        "backup_id": backup_id,
        "action": action,
        "created_at": _iso(occurred_at),
        "identity": {key: targets[key] for key in ("id", "domain", "lane", "identity")},
        "target": _relative(root, Path(targets["path"])),
        "target_existed": Path(targets["path"]).is_dir(),
        "before_drift_hash": _state_hash(root, targets),
        "files": [_file_state(root, item) for item in files],
    }
    _atomic_yaml(path, payload)
    return backup_id, path, payload


def _restore_backup(root: Path, targets: Mapping[str, Any], backup: Mapping[str, Any]) -> None:
    if backup.get("target") != _relative(root, Path(targets["path"])):
        raise ValueError("workflow backup target does not match canonical identity")
    for state in backup.get("files") or []:
        destination = root / str(state["path"])
        _ensure_contained(root, destination)
        if state.get("existed"):
            _atomic_bytes(destination, base64.b64decode(str(state.get("bytes_base64") or "")))
        elif destination.is_file():
            destination.unlink()
    if not backup.get("target_existed") and Path(targets["path"]).is_dir():
        shutil.rmtree(Path(targets["path"]))


def _receipt(
    root: Path,
    targets: Mapping[str, Any],
    *,
    action: str,
    backup_id: str | None,
    backup_path: Path | None,
    before_hash: str,
    after_hash: str,
    readback: Mapping[str, Any],
    rollback_supported: bool,
) -> tuple[str, Path]:
    occurred_at = _now()
    receipt_id = f"{_stamp(occurred_at)}-{action.rsplit('.', 1)[-1].replace('-', '_')}-{_sha(str(targets['identity']) + _stamp(occurred_at))[:8]}"
    path = root / EVIDENCE_ROOT / "receipts" / f"{receipt_id}.yml"
    payload = {
        "api_version": API_VERSION,
        "receipt_id": receipt_id,
        "action": action,
        "occurred_at": _iso(occurred_at),
        "identity": {key: targets[key] for key in ("id", "domain", "lane", "identity")},
        "before_drift_hash": before_hash,
        "after_drift_hash": after_hash,
        "backup_id": backup_id,
        "backup": _relative(root, backup_path) if backup_path else None,
        "readback": deepcopy(dict(readback)),
        "rollback": {"supported": rollback_supported, "guard": "current_drift_hash_must_match_after_drift_hash"},
        "external_effects": "local filesystem only" if action != "workflow.run-now" else "local queue request only; no dispatch performed",
    }
    _atomic_yaml(path, payload)
    return receipt_id, path


def _base(action: str, root: Path, targets: Mapping[str, Any], *, dry_run: bool, before_hash: str) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "action": action,
        "status": "planned" if dry_run else "applied",
        "dry_run": dry_run,
        "root": str(root),
        "resource": {
            "kind": "workflow",
            "id": targets["id"],
            "domain": targets["domain"],
            "lane": targets["lane"],
            "definition_id": targets["definition_id"],
            "instance_id": targets["instance_id"],
            "path": str(targets["path"]),
        },
        "drift": {"before": before_hash, "after": None},
        "backup_id": None,
        "receipt_id": None,
        "receipt": None,
    }


def create_workflow_definition(
    root: str | Path,
    definition: Mapping[str, Any],
    *,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    normalized = _validate_identity(definition)
    targets = _target(os_root, normalized["id"], normalized["domain"], normalized["lane"])
    if Path(targets["definition"]).exists():
        raise ValueError(f"managed workflow definition already exists: {normalized['id']}")
    validation = validate_workflow_definition(os_root, normalized)
    if not validation["ok"]:
        raise ValueError("invalid workflow definition: " + "; ".join(item["message"] for item in validation["findings"][:8]))
    before_hash = _state_hash(os_root, targets)
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run)
    result = _base("workflow.create", os_root, targets, dry_run=dry_run, before_hash=before_hash)
    result.update({"definition": normalized, "validation": validation, "readback": {"ok": True, "definition": normalized} if dry_run else None})
    if dry_run:
        return result
    backup_id, backup_path, backup = _backup(os_root, targets, action="workflow.create", files=[Path(targets["definition"]), Path(targets["instance"])])
    try:
        if not Path(targets["path"]).is_dir():
            create_workflow(os_root, normalized["domain"], normalized["lane"], normalized["id"])
        _atomic_yaml(Path(targets["definition"]), normalized)
        readback = _managed_definition(os_root, targets)
        if readback != normalized:
            raise ValueError("canonical workflow definition readback mismatch")
    except Exception as exc:
        _restore_backup(os_root, targets, backup)
        raise ValueError(f"workflow create failed; exact prior state restored: {exc}") from exc
    after_hash = _state_hash(os_root, targets)
    receipt_id, receipt_path = _receipt(
        os_root,
        targets,
        action="workflow.create",
        backup_id=backup_id,
        backup_path=backup_path,
        before_hash=before_hash,
        after_hash=after_hash,
        readback={"ok": True, "definition": readback},
        rollback_supported=True,
    )
    result.update({"drift": {"before": before_hash, "after": after_hash}, "backup_id": backup_id, "receipt_id": receipt_id, "receipt": str(receipt_path), "readback": {"ok": True, "definition": readback}})
    return result


def _merge_mapping(before: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(dict(before))
    for key, value in changes.items():
        if key == "steps" and isinstance(value, list) and isinstance(merged.get("steps"), list):
            old_by_id = {str(item.get("id")): item for item in merged["steps"] if isinstance(item, dict) and item.get("id")}
            incoming_ids = {str(item.get("id")) for item in value if isinstance(item, dict) and item.get("id")}
            removed = sorted(set(old_by_id) - incoming_ids)
            if removed:
                raise ValueError("workflow update would destructively remove steps: " + ", ".join(removed))
            merged_steps: list[Any] = []
            for item in value:
                if isinstance(item, dict) and str(item.get("id") or "") in old_by_id:
                    merged_steps.append(_merge_mapping(old_by_id[str(item["id"])], item))
                else:
                    merged_steps.append(deepcopy(item))
            merged[key] = merged_steps
        elif isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_mapping(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def update_workflow_definition(
    root: str | Path,
    workflow_id: str,
    definition: Mapping[str, Any],
    *,
    domain: str,
    lane: str,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _target(os_root, workflow_id, domain, lane)
    if not Path(targets["definition"]).is_file():
        raise ValueError(f"managed workflow definition is missing: {workflow_id}")
    before = _managed_definition(os_root, targets)
    incoming = deepcopy(dict(definition))
    for field in ("id", "domain", "lane"):
        if field in incoming and incoming[field] not in (None, targets[field]):
            raise ValueError(f"workflow update cannot change {field}")
    merged = _merge_mapping(before, incoming)
    merged.update({"id": targets["id"], "domain": targets["domain"], "lane": targets["lane"], "schema_version": DEFINITION_SCHEMA_VERSION, "resource_kind": "workflow_definition", "created_at": before.get("created_at", _iso()), "updated_at": _iso()})
    normalized = _validate_identity(merged, targets)
    validation = validate_workflow_definition(os_root, normalized)
    if not validation["ok"]:
        raise ValueError("invalid workflow definition: " + "; ".join(item["message"] for item in validation["findings"][:8]))
    before_hash = _state_hash(os_root, targets)
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run)
    result = _base("workflow.update", os_root, targets, dry_run=dry_run, before_hash=before_hash)
    result.update({"definition": normalized, "validation": validation, "preserved_unknown_fields": True, "readback": {"ok": True, "definition": normalized} if dry_run else None})
    if dry_run:
        return result
    backup_id, backup_path, backup = _backup(os_root, targets, action="workflow.update", files=[Path(targets["definition"])])
    try:
        _atomic_yaml(Path(targets["definition"]), normalized)
        readback = _managed_definition(os_root, targets)
        if readback != normalized:
            raise ValueError("canonical workflow definition readback mismatch")
    except Exception as exc:
        _restore_backup(os_root, targets, backup)
        raise ValueError(f"workflow update failed; exact prior bytes restored: {exc}") from exc
    after_hash = _state_hash(os_root, targets)
    receipt_id, receipt_path = _receipt(os_root, targets, action="workflow.update", backup_id=backup_id, backup_path=backup_path, before_hash=before_hash, after_hash=after_hash, readback={"ok": True, "definition": readback}, rollback_supported=True)
    result.update({"drift": {"before": before_hash, "after": after_hash}, "backup_id": backup_id, "receipt_id": receipt_id, "receipt": str(receipt_path), "readback": {"ok": True, "definition": readback}})
    return result


def _version_record(targets: Mapping[str, Any], definition: Mapping[str, Any], *, occurred_at: datetime) -> tuple[dict[str, Any], Path]:
    definition_sha = _sha_json(definition)
    version = str(definition["version"])
    version_id = f"workflow_version:{targets['domain']}:{targets['lane']}:{targets['id']}:{version}:{definition_sha[:12]}"
    filename = f"{version.replace('.', '_').replace('-', '_')}-{definition_sha[:12]}.yml"
    path = Path(targets["version_root"]) / filename
    record = {
        "api_version": API_VERSION,
        "resource_kind": "workflow_version",
        "id": version_id,
        "definition_id": targets["definition_id"],
        "workflow_id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "version": version,
        "definition_sha256": definition_sha,
        "published_at": _iso(occurred_at),
        "owner": definition.get("owner"),
        "availability": definition.get("availability"),
        "health": definition.get("health"),
        "linked_capabilities": deepcopy(definition.get("linked_capabilities") or []),
        "definition": deepcopy(dict(definition)),
    }
    return record, path


def publish_workflow(
    root: str | Path,
    workflow_id: str,
    *,
    domain: str,
    lane: str,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _target(os_root, workflow_id, domain, lane)
    definition = _managed_definition(os_root, targets)
    validation = validate_workflow_definition(os_root, definition)
    if not validation["ok"]:
        raise ValueError("workflow publish blocked by validation errors")
    if definition.get("availability") != "active":
        raise ValueError("workflow publish requires availability=active")
    if (definition.get("publish") or {}).get("allowed") is not True:
        raise ValueError("workflow publish is denied by definition policy")
    occurred_at = _now()
    version_record, version_path = _version_record(targets, definition, occurred_at=occurred_at)
    for existing in _version_records(os_root, targets):
        if existing.get("version") == definition.get("version") and existing.get("definition_sha256") != version_record["definition_sha256"]:
            raise ValueError(f"workflow version is immutable and already published with different content: {definition['version']}")
        if existing.get("version") == definition.get("version") and existing.get("definition_sha256") == version_record["definition_sha256"]:
            version_record = {key: deepcopy(value) for key, value in existing.items() if key != "source"}
            version_path = os_root / str((existing.get("source") or {}).get("path"))
    instance = {
        "api_version": API_VERSION,
        "resource_kind": "workflow_instance",
        "id": targets["instance_id"],
        "definition_id": targets["definition_id"],
        "version_id": version_record["id"],
        "workflow_id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "version": definition["version"],
        "status": "active",
        "availability": definition["availability"],
        "health": definition["health"],
        "owner": definition["owner"],
        "linked_capabilities": deepcopy(definition.get("linked_capabilities") or []),
        "updated_at": _iso(occurred_at),
    }
    before_hash = _state_hash(os_root, targets)
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run)
    result = _base("workflow.publish", os_root, targets, dry_run=dry_run, before_hash=before_hash)
    result.update({"version": version_record, "instance": instance, "validation": validation, "readback": {"ok": True, "version": version_record, "instance": instance} if dry_run else None})
    if dry_run:
        return result
    backup_id, backup_path, backup = _backup(os_root, targets, action="workflow.publish", files=[Path(targets["instance"]), version_path])
    try:
        if version_path.is_file():
            existing = _load_yaml(version_path, default={})
            if existing != version_record:
                raise ValueError("immutable workflow version readback conflict")
            version_created = False
        else:
            _atomic_yaml(version_path, version_record)
            version_created = True
        _atomic_yaml(Path(targets["instance"]), instance)
        version_readback = _load_yaml(version_path, default={})
        instance_readback = _load_yaml(Path(targets["instance"]), default={})
        if version_readback != version_record or instance_readback != instance:
            raise ValueError("workflow publish canonical readback mismatch")
    except Exception as exc:
        _restore_backup(os_root, targets, backup)
        raise ValueError(f"workflow publish failed; exact prior pointer/version restored: {exc}") from exc
    after_hash = _state_hash(os_root, targets)
    receipt_id, receipt_path = _receipt(os_root, targets, action="workflow.publish", backup_id=backup_id, backup_path=backup_path, before_hash=before_hash, after_hash=after_hash, readback={"ok": True, "version": version_readback, "instance": instance_readback}, rollback_supported=True)
    result.update({"drift": {"before": before_hash, "after": after_hash}, "backup_id": backup_id, "receipt_id": receipt_id, "receipt": str(receipt_path), "version_created": version_created, "readback": {"ok": True, "version": version_readback, "instance": instance_readback}})
    return result


def workflow_run_now(
    root: str | Path,
    workflow_id: str,
    *,
    domain: str,
    lane: str,
    idempotency_key: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _target(os_root, workflow_id, domain, lane)
    definition = _managed_definition(os_root, targets)
    validation = validate_workflow_definition(os_root, definition)
    if not validation["ok"]:
        raise ValueError("workflow run request blocked by validation errors")
    if definition.get("availability") != "active":
        raise ValueError("workflow must be active before queueing a run")
    if not Path(targets["instance"]).is_file():
        raise ValueError("workflow must be published before queueing a run")
    instance = _load_yaml(Path(targets["instance"]), default={})
    before_hash = _state_hash(os_root, targets)
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run)
    if idempotency_key is None:
        idempotency_key = f"workflow:{targets['domain']}:{targets['lane']}:{targets['id']}:{_stamp()}"
    if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("idempotency key may contain letters, numbers, colon, underscore, and hyphen only")
    harness = str((definition.get("execution") or {}).get("harness") or "agentic_os")
    execution_targets = {
        "agentic_os": "agentic_os_harness",
        "codex": "codex_harness",
        "claude": "claude_harness",
    }
    if harness not in execution_targets:
        raise ValueError("workflow execution harness must be agentic_os, codex, or claude")
    occurred_at = _now()
    queue_id = f"queue_{_sha(idempotency_key)[:12]}"
    run_id = f"workflow_run:{_sha(idempotency_key)[:12]}"
    approval_required = bool(definition.get("approvals"))
    status = "dry-run" if dry_run else "approval-needed" if approval_required else "queued"
    queue_item = {
        "id": queue_id,
        "kind": "workflow",
        "ref": targets["identity"],
        "status": status,
        "approval_state": "required" if approval_required and not dry_run else "not_required",
        "approval_required": approval_required,
        "created_at": _iso(occurred_at),
        "due_at": _iso(occurred_at),
        "dry_run": dry_run,
        "idempotency_key": idempotency_key,
        "execution_target": execution_targets[harness],
        "dispatch_performed": False,
        "execution_contract": "harness_worker_required",
        "workflow_definition_id": targets["definition_id"],
        "workflow_version_id": instance.get("version_id"),
        "workflow_instance_id": targets["instance_id"],
        "resource_drift_hash": before_hash,
    }
    run = {
        "api_version": API_VERSION,
        "resource_kind": "workflow_run",
        "id": run_id,
        "queue_item_id": queue_id,
        "definition_id": targets["definition_id"],
        "version_id": instance.get("version_id"),
        "instance_id": targets["instance_id"],
        "workflow_id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "status": status,
        "execution_target": execution_targets[harness],
        "execution_status": "not_started",
        "dispatch_performed": False,
        "execution_contract": "harness_worker_required",
        "idempotency_key": idempotency_key,
        "created_at": _iso(occurred_at),
    }
    result = _base("workflow.run-now", os_root, targets, dry_run=dry_run, before_hash=before_hash)
    result.update({"status": "planned" if dry_run else status, "run": run, "queue_item": queue_item, "dispatch_performed": False, "external_effects": "local queue request only; no dispatch performed", "readback": {"ok": True, "run": None, "queue_item": None} if dry_run else None})
    if dry_run:
        return result
    queued = append_run_queue_item(os_root, queue_item)
    run.update(
        {
            "status": queued["queue_item"].get("status"),
            "queue_created": queued["created"],
            "created_at": queued["queue_item"].get("created_at", run["created_at"]),
            "updated_at": queued["queue_item"].get("updated_at"),
        }
    )
    run_path = os_root / EVIDENCE_ROOT / "run-requests" / f"{_sha(idempotency_key)[:12]}.yml"
    _atomic_yaml(run_path, run)
    run_readback = _load_yaml(run_path, default={})
    readback_ok = run_readback == run and queued["queue_item"].get("id") == queue_id
    receipt_id, receipt_path = _receipt(os_root, targets, action="workflow.run-now", backup_id=None, backup_path=None, before_hash=before_hash, after_hash=before_hash, readback={"ok": readback_ok, "run": run_readback, "queue_item": queued["queue_item"]}, rollback_supported=False)
    result.update({"status": str(run["status"]), "queue_created": queued["created"], "receipt_id": receipt_id, "receipt": str(receipt_path), "readback": {"ok": readback_ok, "run": run_readback, "queue_item": queued["queue_item"]}})
    return result


def rollback_workflow_action(
    root: str | Path,
    receipt_id: str,
    *,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
        raise ValueError("workflow rollback accepts only a fixed workflow-engine receipt id")
    receipt_path = os_root / EVIDENCE_ROOT / "receipts" / f"{receipt_id}.yml"
    receipt = _load_yaml(receipt_path, default={})
    if not isinstance(receipt, dict) or receipt.get("api_version") != API_VERSION:
        raise ValueError("invalid workflow-engine receipt")
    if not (receipt.get("rollback") or {}).get("supported"):
        raise ValueError("this workflow action is immutable and does not support rollback")
    identity = receipt.get("identity") or {}
    targets = _target(os_root, str(identity.get("id") or ""), str(identity.get("domain") or ""), str(identity.get("lane") or ""))
    current_hash = _state_hash(os_root, targets)
    _confirm(expected_drift_hash, current_hash, dry_run=dry_run)
    if current_hash != receipt.get("after_drift_hash"):
        raise ValueError("rollback refused because workflow state changed after the source receipt")
    backup_ref = str(receipt.get("backup") or "")
    backup_path = os_root / backup_ref
    backup_root = (os_root / EVIDENCE_ROOT / "backups").resolve()
    if not backup_path.resolve().is_relative_to(backup_root):
        raise ValueError("workflow rollback backup is outside the governed backup root")
    backup = _load_yaml(backup_path, default={})
    if backup.get("backup_id") != receipt.get("backup_id"):
        raise ValueError("workflow rollback backup identity mismatch")
    result = _base("workflow.rollback", os_root, targets, dry_run=dry_run, before_hash=current_hash)
    result.update({"source_receipt_id": receipt_id, "restore_drift_hash": backup.get("before_drift_hash"), "readback": {"ok": True, "restored": False} if dry_run else None})
    if dry_run:
        return result
    _restore_backup(os_root, targets, backup)
    restored_hash = _state_hash(os_root, targets)
    if restored_hash != backup.get("before_drift_hash"):
        raise ValueError("workflow rollback readback did not restore the exact prior state")
    rollback_id, rollback_path = _receipt(os_root, targets, action="workflow.rollback", backup_id=None, backup_path=None, before_hash=current_hash, after_hash=restored_hash, readback={"ok": True, "restored": True, "source_receipt_id": receipt_id}, rollback_supported=False)
    result.update({"status": "rolled_back", "drift": {"before": current_hash, "after": restored_hash}, "receipt_id": rollback_id, "receipt": str(rollback_path), "readback": {"ok": True, "restored": True}})
    return result
