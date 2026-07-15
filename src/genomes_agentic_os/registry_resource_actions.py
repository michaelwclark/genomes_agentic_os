"""Governed authoring for registry-backed rules, reports, skills, and commands.

Only deterministic registry and prompt-document targets are supported. This
module cannot accept a source path, executable path, or shell command.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from .capability_registry import REGISTRY_FILES
from .scaffold import domain_path, expand_path, normalize_domain, validate_name


API_VERSION = "resource-actions/v1"
AUTHORING_MANAGER = "agentic-os resource authoring"
REGISTRY_RESOURCE_KINDS = ("rule", "report", "skill", "command")
REGISTRY_SCOPES = ("system", "domain", "project")
COLLECTIONS = {kind: f"{kind}s" for kind in REGISTRY_RESOURCE_KINDS}
EVIDENCE_ROOT = Path("harness/shared_factory/06-runs-and-logs/resource-actions/registry-authoring")
BACKUP_ID_PATTERN = re.compile(r"^\d{8}T\d{12}Z-[a-f0-9]{8}$")
RESOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"required file is missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"expected mapping: {path}")
    return loaded


def _load_yaml(path: Path, collection: str) -> dict[str, Any]:
    if not path.exists():
        return {collection: []}
    loaded = _load_mapping(path)
    entries = loaded.get(collection)
    if entries is None:
        loaded[collection] = []
    elif not isinstance(entries, list):
        raise ValueError(f"expected {collection} list in registry: {path}")
    return loaded


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_stamp()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, yaml.safe_dump(payload, sort_keys=False))


def _kind(value: str) -> str:
    if value not in REGISTRY_RESOURCE_KINDS:
        raise ValueError(f"registry authoring does not support resource kind: {value}")
    return value


def _scope(value: str) -> str:
    if value not in REGISTRY_SCOPES:
        raise ValueError(f"scope must be one of {', '.join(REGISTRY_SCOPES)}: {value!r}")
    return value


def _text(value: str, label: str, *, maximum: int, multiline: bool = False) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{label} must be non-empty and at most {maximum} characters")
    if not multiline and ("\n" in normalized or "\r" in normalized):
        raise ValueError(f"{label} must be a single line")
    return normalized


def _scope_root(
    root: Path,
    scope: str,
    *,
    domain: str | None,
    project: str | None,
) -> tuple[Path, str | None, str | None]:
    scope = _scope(scope)
    if scope == "system":
        if domain or project:
            raise ValueError("system scope does not accept --domain or --project")
        return root / "harness", None, None
    if not domain:
        raise ValueError(f"--domain is required for {scope} scope")
    normalized_domain = normalize_domain(domain)
    domain_root = domain_path(root, normalized_domain)
    if not domain_root.is_dir():
        raise ValueError(f"unknown installed domain: {normalized_domain}")
    if scope == "domain":
        if project:
            raise ValueError("domain scope does not accept --project")
        return domain_root, normalized_domain, None
    if not project:
        raise ValueError("--project is required for project scope")
    normalized_project = validate_name(project, "project")
    project_root = domain_root / "02-projects" / normalized_project
    if not project_root.is_dir():
        raise ValueError(f"unknown installed project: {normalized_domain}/{normalized_project}")
    return project_root, normalized_domain, normalized_project


def _targets(
    root: Path,
    kind: str,
    resource_id: str,
    scope: str,
    *,
    domain: str | None,
    project: str | None,
) -> dict[str, Any]:
    kind = _kind(kind)
    # Existing built-in registries predate the snake_case authoring contract
    # and contain safe hyphenated IDs. They remain readable and validatable;
    # create_registry_resource() applies the stricter canonical-name check.
    if not RESOURCE_ID_PATTERN.fullmatch(resource_id):
        raise ValueError(
            f"{kind} must use lowercase letters, numbers, hyphens, and underscores only: {resource_id!r}"
        )
    base, domain, project = _scope_root(root, scope, domain=domain, project=project)
    collection = COLLECTIONS[kind]
    if scope == "system":
        registry = root / REGISTRY_FILES[collection]
        sources = {
            "rule": root / "harness/rules" / f"{resource_id}.md",
            "report": root / "harness/reports" / f"{resource_id}.md",
            "skill": root / "harness/skills" / resource_id / "SKILL.md",
            "command": root / "harness/commands" / f"os-{resource_id}.md",
        }
    elif scope == "domain":
        registry = base / "00-control-plane/resource-registries" / f"{collection}.yml"
        sources = {kind: base / "00-control-plane/registry-resources" / kind / f"{resource_id}.md"}
    else:
        registry = base / "config/resource-registries" / f"{collection}.yml"
        sources = {kind: base / "config/registry-resources" / kind / f"{resource_id}.md"}
    capability_registry = root / REGISTRY_FILES["capabilities"]
    scope_key = ":".join(part for part in (scope, domain, project) if part)
    capability_id = f"{kind}:{scope_key}:{resource_id}"
    targets = {
        "kind": kind,
        "collection": collection,
        "id": resource_id,
        "scope": scope,
        "domain": domain,
        "project": project,
        "registry": registry,
        "source": sources[kind],
        "capability_registry": capability_registry,
        "capability_id": capability_id,
    }
    for target_name in ("registry", "source", "capability_registry"):
        _ensure_contained(root, targets[target_name])
    return targets


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError as exc:
        raise ValueError(f"derived resource target escaped the installed root: {path}") from exc


def _ensure_contained(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"derived resource target escaped the installed root: {path}")
    return path


def _entry(registry: dict[str, Any], collection: str, resource_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in registry.get(collection) or []
            if isinstance(item, dict) and item.get("id") == resource_id
        ),
        None,
    )


def _capability_entry(registry: dict[str, Any], capability_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in registry.get("capabilities") or []
            if isinstance(item, dict) and item.get("id") == capability_id
        ),
        None,
    )


def _mutable(entry: dict[str, Any]) -> bool:
    return entry.get("managed_by") == AUTHORING_MANAGER


def _render_prompt(kind: str, entry: dict[str, Any], prompt: str) -> str:
    title = entry["name"]
    description = entry["description"]
    scope = entry["scope"]
    if kind == "skill":
        frontmatter = yaml.safe_dump(
            {"name": entry["id"], "description": description},
            sort_keys=False,
        ).strip()
        return f"---\n{frontmatter}\n---\n\n# {title}\n\n## Scope\n\n`{scope}`\n\n## Prompt\n\n{prompt}\n"
    if kind == "command":
        return (
            f"# Command: /{entry['id']}\n\n## Description\n\n{description}\n\n"
            f"## Scope\n\n`{scope}`\n\n## Execution Contract\n\n{prompt}\n"
        )
    heading = "Rule" if kind == "rule" else "Report Definition"
    prompt_heading = "Rule Prompt" if kind == "rule" else "Generation Prompt"
    return (
        f"# {heading}: {title}\n\n## Description\n\n{description}\n\n"
        f"## Scope\n\n`{scope}`\n\n## {prompt_heading}\n\n{prompt}\n"
    )


def _capability_for(targets: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": targets["capability_id"],
        "type": targets["kind"],
        "ref": targets["id"],
        "name": entry["name"],
        "description": entry["description"],
        "status": entry["status"],
        "scope": targets["scope"],
        "domain": targets["domain"],
        "project": targets["project"],
        "managed_by": AUTHORING_MANAGER,
    }


def _base(action: str, targets: dict[str, Any], root: Path, *, dry_run: bool, status: str) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "action": action,
        "status": status,
        "dry_run": dry_run,
        "root": str(root),
        "resource": {
            "kind": targets["kind"],
            "id": targets["id"],
            "scope": targets["scope"],
            "domain": targets["domain"],
            "project": targets["project"],
            "registry": str(targets["registry"]),
            "source": str(targets["source"]),
        },
        "backup_id": None,
        "receipt": None,
    }


def _backup(
    root: Path,
    targets: dict[str, Any],
    *,
    action: str,
    before_entry: dict[str, Any] | None,
    before_capability: dict[str, Any] | None,
    before_source: str | None,
) -> tuple[str, Path]:
    occurred_at = _now()
    identity = f"{action}:{targets['capability_id']}:{_stamp(occurred_at)}"
    backup_id = f"{_stamp(occurred_at)}-{_sha(identity)[:8]}"
    backup_path = root / EVIDENCE_ROOT / "backups" / f"{backup_id}.yml"
    _ensure_contained(root, backup_path)
    bundle = {
        "api_version": API_VERSION,
        "backup_id": backup_id,
        "created_at": _iso(occurred_at),
        "action": action,
        "identity": {
            "kind": targets["kind"],
            "id": targets["id"],
            "scope": targets["scope"],
            "domain": targets["domain"],
            "project": targets["project"],
            "capability_id": targets["capability_id"],
        },
        "targets": {
            "registry": _relative(root, targets["registry"]),
            "source": _relative(root, targets["source"]),
            "capability_registry": _relative(root, targets["capability_registry"]),
        },
        "before": {
            "entry": before_entry,
            "capability": before_capability,
            "source": before_source,
        },
    }
    _write_yaml(backup_path, bundle)
    return backup_id, backup_path


def _receipt(
    root: Path,
    targets: dict[str, Any],
    *,
    action: str,
    backup_id: str,
    before_entry: dict[str, Any] | None,
    after_entry: dict[str, Any] | None,
    readback_ok: bool,
) -> Path:
    occurred_at = _now()
    receipt_path = root / EVIDENCE_ROOT / "receipts" / (
        f"{_stamp(occurred_at)}-{targets['kind']}-{targets['id']}-{action.rsplit('.', 1)[-1]}.yml"
    )
    _ensure_contained(root, receipt_path)
    payload = {
        "api_version": API_VERSION,
        "action": action,
        "occurred_at": _iso(occurred_at),
        "identity": {
            "kind": targets["kind"],
            "id": targets["id"],
            "scope": targets["scope"],
            "domain": targets["domain"],
            "project": targets["project"],
        },
        "backup_id": backup_id,
        "before_sha256": _sha(yaml.safe_dump(before_entry, sort_keys=True)) if before_entry else None,
        "after_sha256": _sha(yaml.safe_dump(after_entry, sort_keys=True)) if after_entry else None,
        "readback_ok": readback_ok,
        "external_effects": "none",
    }
    _write_yaml(receipt_path, payload)
    return receipt_path


def _write_state(
    root: Path,
    targets: dict[str, Any],
    *,
    entry: dict[str, Any] | None,
    source: str | None,
    capability: dict[str, Any] | None,
) -> None:
    registry = _load_yaml(targets["registry"], targets["collection"])
    registry[targets["collection"]] = [
        item
        for item in registry[targets["collection"]]
        if not (isinstance(item, dict) and item.get("id") == targets["id"])
    ]
    if entry is not None:
        registry[targets["collection"]].append(entry)
        registry[targets["collection"]].sort(key=lambda item: str(item.get("id") or ""))
    _write_yaml(targets["registry"], registry)

    capability_registry = _load_yaml(targets["capability_registry"], "capabilities")
    capability_registry["capabilities"] = [
        item
        for item in capability_registry["capabilities"]
        if not (isinstance(item, dict) and item.get("id") == targets["capability_id"])
    ]
    if capability is not None:
        capability_registry["capabilities"].append(capability)
        capability_registry["capabilities"].sort(key=lambda item: str(item.get("id") or ""))
    _write_yaml(targets["capability_registry"], capability_registry)

    if source is None:
        if targets["source"].is_file():
            targets["source"].unlink()
    else:
        _atomic_write(targets["source"], source)


def _readback(root: Path, targets: dict[str, Any]) -> dict[str, Any]:
    registry = _load_yaml(targets["registry"], targets["collection"])
    capability_registry = _load_yaml(targets["capability_registry"], "capabilities")
    entry = deepcopy(_entry(registry, targets["collection"], targets["id"]))
    capability = deepcopy(_capability_entry(capability_registry, targets["capability_id"]))
    source = targets["source"].read_text(encoding="utf-8") if targets["source"].is_file() else None
    return {"entry": entry, "capability": capability, "source": source}


def registry_resource_list(
    root: str | Path,
    kind: str,
    *,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    probe = _targets(os_root, kind, "probe", scope, domain=domain, project=project)
    registry = _load_yaml(probe["registry"], probe["collection"])
    resources = []
    for raw in registry[probe["collection"]]:
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        item["mutable"] = _mutable(item)
        resources.append(item)
    resources.sort(key=lambda item: str(item.get("id") or ""))
    return {
        "api_version": API_VERSION,
        "action": "resource.list",
        "status": "ok",
        "root": str(os_root),
        "kind": kind,
        "scope": scope,
        "domain": probe["domain"],
        "project": probe["project"],
        "count": len(resources),
        "resources": resources,
    }


def registry_resource_get(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    state = _readback(os_root, targets)
    if state["entry"] is None:
        raise ValueError(f"unknown {kind}: {resource_id}")
    return {
        "api_version": API_VERSION,
        "action": "resource.get",
        "status": "ok",
        "root": str(os_root),
        "resource": {
            **state["entry"],
            "scope": scope,
            "domain": targets["domain"],
            "project": targets["project"],
            "mutable": _mutable(state["entry"]),
            "source_content": state["source"],
        },
    }


def validate_registry_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    state = _readback(os_root, targets)
    findings: list[dict[str, str]] = []
    entry = state["entry"]
    if entry is None:
        findings.append({"severity": "blocker", "message": "registry entry is missing"})
    else:
        for field in ("id", "description", "source"):
            if not entry.get(field):
                findings.append({"severity": "blocker", "message": f"required field is missing: {field}"})
        if _mutable(entry):
            if entry.get("source") != _relative(os_root, targets["source"]):
                findings.append({"severity": "blocker", "message": "source does not match canonical target"})
            if state["source"] is None:
                findings.append({"severity": "blocker", "message": "canonical prompt source is missing"})
            elif entry.get("prompt_sha256") != _sha(state["source"]):
                findings.append({"severity": "blocker", "message": "prompt source checksum does not match registry"})
            if state["capability"] is None:
                findings.append({"severity": "blocker", "message": "capability projection is missing"})
            elif state["capability"] != _capability_for(targets, entry):
                findings.append({"severity": "blocker", "message": "capability projection does not match registry resource"})
    ok = not any(finding["severity"] == "blocker" for finding in findings)
    if ok:
        findings.append({"severity": "observation", "message": "registry resource is structurally valid"})
    return {
        "api_version": API_VERSION,
        "action": "resource.validate",
        "status": "valid" if ok else "invalid",
        "ok": ok,
        "root": str(os_root),
        "resource": {
            "kind": kind,
            "id": resource_id,
            "scope": scope,
            "domain": targets["domain"],
            "project": targets["project"],
            "mutable": bool(entry and _mutable(entry)),
        },
        "findings": findings,
    }


def create_registry_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    name: str,
    description: str,
    prompt: str,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    validate_name(resource_id, kind)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    name = _text(name, "name", maximum=120)
    description = _text(description, "description", maximum=500)
    prompt = _text(prompt, "prompt", maximum=50000, multiline=True)
    state = _readback(os_root, targets)
    if state["entry"] is not None:
        raise ValueError(f"{kind} already exists: {resource_id}")
    now = _iso()
    entry: dict[str, Any] = {
        "id": resource_id,
        "name": name,
        "description": description,
        "status": "draft",
        "scope": scope,
        "domain": targets["domain"],
        "project": targets["project"],
        "source": _relative(os_root, targets["source"]),
        "managed_by": AUTHORING_MANAGER,
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
    }
    if kind == "command":
        entry["command"] = f"/{resource_id}"
    source = _render_prompt(kind, entry, prompt)
    entry["prompt_sha256"] = _sha(source)
    capability = _capability_for(targets, entry)
    result = _base("resource.create", targets, os_root, dry_run=dry_run, status="planned" if dry_run else "created")
    result["resource"]["after"] = entry
    if dry_run:
        result["readback"] = {"ok": True, "entry": None}
        return result
    backup_id, _ = _backup(
        os_root,
        targets,
        action="resource.create",
        before_entry=None,
        before_capability=None,
        before_source=None,
    )
    _write_state(os_root, targets, entry=entry, source=source, capability=capability)
    readback = _readback(os_root, targets)
    readback_ok = readback == {"entry": entry, "source": source, "capability": capability}
    receipt = _receipt(
        os_root,
        targets,
        action="resource.create",
        backup_id=backup_id,
        before_entry=None,
        after_entry=entry,
        readback_ok=readback_ok,
    )
    result.update(
        {
            "backup_id": backup_id,
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "entry": readback["entry"]},
        }
    )
    return result


def update_registry_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if name is None and description is None and prompt is None:
        raise ValueError("at least one of --name, --description, or --prompt is required")
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    before = _readback(os_root, targets)
    if before["entry"] is None:
        raise ValueError(f"unknown {kind}: {resource_id}")
    if not _mutable(before["entry"]):
        raise ValueError(f"built-in or unmanaged {kind} is read-only: {resource_id}")
    entry = deepcopy(before["entry"])
    if entry.get("status") == "archived":
        raise ValueError(f"restore archived {kind} before updating: {resource_id}")
    if name is not None:
        entry["name"] = _text(name, "name", maximum=120)
    if description is not None:
        entry["description"] = _text(description, "description", maximum=500)
    if prompt is None:
        source = before["source"]
        if source is None:
            raise ValueError("canonical prompt source is missing; supply --prompt to repair")
        prompt_value = _extract_prompt(source)
    else:
        prompt_value = _text(prompt, "prompt", maximum=50000, multiline=True)
    source = _render_prompt(kind, entry, prompt_value)
    entry["prompt_sha256"] = _sha(source)
    entry["updated_at"] = _iso()
    capability = _capability_for(targets, entry)
    result = _base("resource.update", targets, os_root, dry_run=dry_run, status="planned" if dry_run else "updated")
    result["resource"].update({"before": before["entry"], "after": entry})
    if dry_run:
        result["readback"] = {"ok": True, "entry": before["entry"]}
        return result
    backup_id, _ = _backup(
        os_root,
        targets,
        action="resource.update",
        before_entry=before["entry"],
        before_capability=before["capability"],
        before_source=before["source"],
    )
    _write_state(os_root, targets, entry=entry, source=source, capability=capability)
    readback = _readback(os_root, targets)
    readback_ok = readback == {"entry": entry, "source": source, "capability": capability}
    receipt = _receipt(
        os_root,
        targets,
        action="resource.update",
        backup_id=backup_id,
        before_entry=before["entry"],
        after_entry=entry,
        readback_ok=readback_ok,
    )
    result.update({"backup_id": backup_id, "receipt": str(receipt), "readback": {"ok": readback_ok, "entry": readback["entry"]}})
    return result


def _extract_prompt(source: str) -> str:
    for heading in ("## Prompt", "## Execution Contract", "## Rule Prompt", "## Generation Prompt"):
        marker = f"{heading}\n\n"
        if marker in source:
            return source.split(marker, 1)[1].strip()
    raise ValueError("canonical prompt section is missing; supply --prompt to repair")


def set_registry_resource_archive(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    archived: bool,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    before = _readback(os_root, targets)
    if before["entry"] is None:
        raise ValueError(f"unknown {kind}: {resource_id}")
    if not _mutable(before["entry"]):
        raise ValueError(f"built-in or unmanaged {kind} is read-only: {resource_id}")
    entry = deepcopy(before["entry"])
    if archived:
        if entry.get("status") == "archived":
            status = "unchanged"
        else:
            entry["status_before_archive"] = entry.get("status") or "draft"
            entry["status"] = "archived"
            entry["archived_at"] = _iso()
            status = "planned" if dry_run else "archived"
        action = "resource.archive"
    else:
        if entry.get("status") != "archived":
            status = "unchanged"
        else:
            entry["status"] = entry.pop("status_before_archive", "draft")
            entry["archived_at"] = None
            status = "planned" if dry_run else "restored"
        action = "resource.restore"
    entry["updated_at"] = _iso()
    capability = _capability_for(targets, entry)
    result = _base(action, targets, os_root, dry_run=dry_run, status=status)
    result["resource"].update({"before": before["entry"], "after": entry})
    if dry_run or status == "unchanged":
        result["readback"] = {"ok": True, "entry": before["entry"]}
        return result
    backup_id, _ = _backup(
        os_root,
        targets,
        action=action,
        before_entry=before["entry"],
        before_capability=before["capability"],
        before_source=before["source"],
    )
    _write_state(os_root, targets, entry=entry, source=before["source"], capability=capability)
    readback = _readback(os_root, targets)
    readback_ok = readback == {"entry": entry, "source": before["source"], "capability": capability}
    receipt = _receipt(
        os_root,
        targets,
        action=action,
        backup_id=backup_id,
        before_entry=before["entry"],
        after_entry=entry,
        readback_ok=readback_ok,
    )
    result.update({"backup_id": backup_id, "receipt": str(receipt), "readback": {"ok": readback_ok, "entry": readback["entry"]}})
    return result


def rollback_registry_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    backup_id: str,
    scope: str = "system",
    domain: str | None = None,
    project: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise ValueError(f"invalid backup_id: {backup_id!r}")
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, scope, domain=domain, project=project)
    backup_path = os_root / EVIDENCE_ROOT / "backups" / f"{backup_id}.yml"
    _ensure_contained(os_root, backup_path)
    bundle = _load_mapping(backup_path)
    identity = bundle.get("identity") or {}
    expected_identity = {
        "kind": kind,
        "id": resource_id,
        "scope": scope,
        "domain": targets["domain"],
        "project": targets["project"],
        "capability_id": targets["capability_id"],
    }
    if identity != expected_identity:
        raise ValueError("backup identity does not match the requested resource")
    expected_targets = {
        "registry": _relative(os_root, targets["registry"]),
        "source": _relative(os_root, targets["source"]),
        "capability_registry": _relative(os_root, targets["capability_registry"]),
    }
    if bundle.get("targets") != expected_targets:
        raise ValueError("backup targets do not match canonical resource targets")
    before = bundle.get("before") or {}
    current = _readback(os_root, targets)
    result = _base("resource.rollback", targets, os_root, dry_run=dry_run, status="planned" if dry_run else "rolled_back")
    result["backup_id"] = backup_id
    result["resource"].update({"before": current["entry"], "after": before.get("entry")})
    if dry_run:
        result["readback"] = {"ok": True, "entry": current["entry"]}
        return result
    rollback_backup_id, _ = _backup(
        os_root,
        targets,
        action="resource.rollback",
        before_entry=current["entry"],
        before_capability=current["capability"],
        before_source=current["source"],
    )
    _write_state(
        os_root,
        targets,
        entry=before.get("entry"),
        source=before.get("source"),
        capability=before.get("capability"),
    )
    readback = _readback(os_root, targets)
    expected = {
        "entry": before.get("entry"),
        "source": before.get("source"),
        "capability": before.get("capability"),
    }
    readback_ok = readback == expected
    receipt = _receipt(
        os_root,
        targets,
        action="resource.rollback",
        backup_id=rollback_backup_id,
        before_entry=current["entry"],
        after_entry=before.get("entry"),
        readback_ok=readback_ok,
    )
    result.update(
        {
            "rollback_backup_id": rollback_backup_id,
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "entry": readback["entry"]},
        }
    )
    return result
