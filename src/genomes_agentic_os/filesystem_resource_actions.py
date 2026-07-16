"""Governed lifecycle actions for filesystem-backed Agentic OS resources.

The public surface accepts only canonical resource identity.  Paths, shell
commands, provider queries, and execution destinations are deliberately not
parameters.  Mutations are overlay based so existing resource contracts and
unknown metadata survive round trips unchanged.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
from typing import Any, Callable

import yaml

from .runtime_ops import append_run_queue_item
from .scaffold import (
    create_automation,
    create_instance_program,
    create_program,
    create_workflow,
    domain_path,
    expand_path,
    installed_domain_names,
    normalize_domain,
    shared_factory_path,
    validate_name,
)


API_VERSION = "resource-actions/v1"
AUTHORING_MANAGER = "agentic-os resource lifecycle"
SUPPORTED_RESOURCE_KINDS = ("automation", "workflow", "program", "instance-program")
OVERLAY_NAME = ".agentic-resource.yml"
EVIDENCE_ROOT = Path("harness/shared_factory/06-runs-and-logs/resource-actions/filesystem-lifecycle")
BACKUP_ID_PATTERN = re.compile(r"^\d{8}T\d{12}Z-[a-f0-9]{8}$")
DRIFT_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_-]{1,180}$")
STATUSES = {"draft", "active", "paused", "archived"}
AUTOMATION_LEVELS = {"observe", "prepare", "propose", "execute_approved", "execute_guarded"}
HARNESS_VALUES = {"agentic_os", "codex", "claude"}
HARNESS_TARGETS = {"agentic_os": "codex_harness", "codex": "codex_harness", "claude": "claude_harness"}
COMMON_MUTABLE_FIELDS = {"display_name", "summary", "status", "harness", "model", "complexity", "notes"}
MUTABLE_FIELDS = {
    "automation": COMMON_MUTABLE_FIELDS | {"enabled", "level"},
    "workflow": COMMON_MUTABLE_FIELDS,
    "program": COMMON_MUTABLE_FIELDS,
    "instance-program": COMMON_MUTABLE_FIELDS | {"definition_id"},
}
PRIMARY_FILES = {
    "automation": "automation.md",
    "workflow": "workflow.md",
    "program": "program.md",
    "instance-program": "program.md",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _kind(value: str) -> str:
    if value not in SUPPORTED_RESOURCE_KINDS:
        raise ValueError(f"filesystem lifecycle does not support resource kind: {value}")
    return value


def _ensure_contained(root: Path, target: Path) -> Path:
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"derived resource target escaped the installed root: {target}")
    return target


def _relative(root: Path, target: Path) -> str:
    _ensure_contained(root, target)
    return str(target.relative_to(root))


def _domains(root: Path) -> list[str]:
    names = installed_domain_names(root)
    if shared_factory_path(root).is_dir():
        names.append("shared_factory")
    return sorted(set(names))


def _targets(
    root: Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None,
    lane: str | None,
) -> dict[str, Any]:
    kind = _kind(kind)
    resource_id = validate_name(resource_id, kind)
    if kind in {"automation", "workflow"}:
        if not domain or not lane:
            raise ValueError(f"--domain and --lane are required for {kind}")
        domain = normalize_domain(domain)
        lane = validate_name(lane, "lane")
        base = domain_path(root, domain)
        if not base.is_dir():
            raise ValueError(f"unknown installed domain: {domain}")
        collection = "04-automations" if kind == "automation" else "03-workflows"
        target = base / collection / lane / resource_id
    elif kind == "program":
        if domain or lane:
            raise ValueError("program identity does not accept --domain or --lane")
        target = shared_factory_path(root, "00-programs", resource_id)
    else:
        if not domain:
            raise ValueError("--domain is required for instance-program")
        if lane:
            raise ValueError("instance-program identity does not accept --lane")
        domain = normalize_domain(domain)
        if domain == "shared_factory":
            raise ValueError("shared_factory definitions are programs, not instance-programs")
        base = domain_path(root, domain)
        if not base.is_dir():
            raise ValueError(f"unknown installed domain: {domain}")
        target = base / "00-programs" / resource_id
    overlay = target / OVERLAY_NAME
    _ensure_contained(root, target)
    _ensure_contained(root, overlay)
    return {
        "kind": kind,
        "id": resource_id,
        "domain": domain,
        "lane": lane,
        "path": target,
        "overlay": overlay,
        "primary": target / PRIMARY_FILES[kind],
        "identity": ":".join(part for part in (kind, domain, lane, resource_id) if part),
    }


def _summary(primary: Path, resource_id: str) -> str:
    if not primary.is_file():
        return resource_id.replace("_", " ").title()
    for block in re.split(r"\n\s*\n", primary.read_text(encoding="utf-8", errors="replace")):
        text = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if text and not text.startswith(("#", "- Status:", "|")):
            return text[:500]
    return resource_id.replace("_", " ").title()


def _implicit_metadata(targets: dict[str, Any]) -> dict[str, Any]:
    kind = targets["kind"]
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "kind": kind,
        "id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "display_name": targets["id"].replace("_", " ").title(),
        "summary": _summary(targets["primary"], targets["id"]),
        "status": "active",
        "managed_by": AUTHORING_MANAGER,
    }
    if kind == "automation":
        metadata.update({"enabled": True, "level": "observe"})
    if kind == "instance-program":
        metadata["definition_id"] = targets["id"]
    return metadata


def _load_overlay(targets: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not targets["overlay"].is_file():
        return _implicit_metadata(targets), False
    loaded = yaml.safe_load(targets["overlay"].read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"expected mapping: {targets['overlay']}")
    return loaded, True


def _overlay_bytes(metadata: dict[str, Any]) -> bytes:
    return yaml.safe_dump(metadata, sort_keys=False).encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_stamp()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _tree_hash(targets: dict[str, Any], *, overlay: bytes | None | object = ...) -> str:
    digest = hashlib.sha256()
    target = targets["path"]
    if target.is_dir():
        for path in sorted(item for item in target.iterdir() if item.is_file() and item.name != OVERLAY_NAME):
            if path.is_symlink():
                raise ValueError(f"managed resource contract file cannot be a symlink: {path}")
            digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    if overlay is ...:
        overlay_data = targets["overlay"].read_bytes() if targets["overlay"].is_file() else None
    else:
        overlay_data = overlay
    digest.update(b"overlay\0")
    digest.update(overlay_data if isinstance(overlay_data, bytes) else b"<absent>")
    digest.update(b"\0identity\0" + targets["identity"].encode("utf-8"))
    return digest.hexdigest()


def _validate_metadata(targets: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for field in ("kind", "id", "domain", "lane"):
        if metadata.get(field) != targets.get(field):
            findings.append({"severity": "blocker", "message": f"immutable identity mismatch: {field}"})
    if metadata.get("status") not in STATUSES:
        findings.append({"severity": "blocker", "message": f"unsupported lifecycle status: {metadata.get('status')}"})
    if targets["kind"] == "automation":
        if not isinstance(metadata.get("enabled"), bool):
            findings.append({"severity": "blocker", "message": "automation enabled must be boolean"})
        if metadata.get("level") not in AUTOMATION_LEVELS:
            findings.append({"severity": "blocker", "message": f"unsupported automation level: {metadata.get('level')}"})
    return findings


def _validate_existing(root: Path, targets: dict[str, Any]) -> dict[str, Any]:
    from .resource_actions import validate_resource

    result = validate_resource(
        root,
        targets["kind"],
        targets["id"],
        domain=targets["domain"],
        lane=targets["lane"],
    )
    metadata, _ = _load_overlay(targets)
    metadata_findings = _validate_metadata(targets, metadata)
    result["findings"].extend(metadata_findings)
    result["ok"] = result["ok"] and not any(item["severity"] == "blocker" for item in metadata_findings)
    result["status"] = "valid" if result["ok"] else "invalid"
    result["resource"].update({"metadata": metadata, "drift_hash": _tree_hash(targets)})
    return result


def _resource_view(root: Path, targets: dict[str, Any]) -> dict[str, Any]:
    if not targets["path"].is_dir():
        raise ValueError(f"unknown {targets['kind']}: {targets['id']}")
    metadata, explicit = _load_overlay(targets)
    return {
        **deepcopy(metadata),
        "kind": targets["kind"],
        "id": targets["id"],
        "domain": targets["domain"],
        "lane": targets["lane"],
        "path": str(targets["path"]),
        "primary_file": str(targets["primary"]),
        "metadata_explicit": explicit,
        "drift_hash": _tree_hash(targets),
    }


def filesystem_resource_get(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    return {
        "api_version": API_VERSION,
        "action": "resource.get",
        "status": "ok",
        "root": str(os_root),
        "resource": _resource_view(os_root, targets),
    }


def _iter_targets(root: Path, kind: str, domain: str | None, lane: str | None) -> list[dict[str, Any]]:
    kind = _kind(kind)
    found: list[dict[str, Any]] = []
    if kind == "program":
        if domain or lane:
            raise ValueError("program list does not accept --domain or --lane")
        roots = [(None, None, shared_factory_path(root, "00-programs"))]
    elif kind == "instance-program":
        if lane:
            raise ValueError("instance-program list does not accept --lane")
        domain_names = [normalize_domain(domain)] if domain else [item for item in _domains(root) if item != "shared_factory"]
        roots = [(item, None, domain_path(root, item) / "00-programs") for item in domain_names]
    else:
        domain_names = [normalize_domain(domain)] if domain else _domains(root)
        collection = "04-automations" if kind == "automation" else "03-workflows"
        roots = []
        for domain_name in domain_names:
            collection_root = domain_path(root, domain_name) / collection
            if lane:
                lane_names = [validate_name(lane, "lane")]
            elif collection_root.is_dir():
                lane_names = [path.name for path in collection_root.iterdir() if path.is_dir()]
            else:
                lane_names = []
            roots.extend((domain_name, lane_name, collection_root / lane_name) for lane_name in lane_names)
    for domain_name, lane_name, collection_root in roots:
        if not collection_root.is_dir():
            continue
        for child in sorted(collection_root.iterdir()):
            if child.is_dir() and re.fullmatch(r"[a-z0-9_]+", child.name):
                found.append(_targets(root, kind, child.name, domain=domain_name, lane=lane_name))
    return found


def filesystem_resource_list(
    root: str | Path,
    kind: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    resources = [_resource_view(os_root, targets) for targets in _iter_targets(os_root, kind, domain, lane)]
    resources.sort(key=lambda item: (str(item.get("domain") or ""), str(item.get("lane") or ""), item["id"]))
    return {
        "api_version": API_VERSION,
        "action": "resource.list",
        "status": "ok",
        "root": str(os_root),
        "kind": kind,
        "count": len(resources),
        "resources": resources,
    }


def validate_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    return _validate_existing(os_root, targets)


def _base(action: str, root: Path, targets: dict[str, Any], *, dry_run: bool, status: str) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "action": action,
        "status": status,
        "dry_run": dry_run,
        "root": str(root),
        "resource": {
            "kind": targets["kind"],
            "id": targets["id"],
            "domain": targets["domain"],
            "lane": targets["lane"],
            "path": str(targets["path"]),
        },
        "backup_id": None,
        "receipt": None,
    }


def _confirm(expected: str | None, actual: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    if expected is None:
        raise ValueError("--expected-drift-hash is required with --apply; run the dry-run plan first")
    if not DRIFT_HASH_PATTERN.fullmatch(expected):
        raise ValueError(f"invalid expected drift hash: {expected!r}")
    if expected != actual:
        raise ValueError(f"stale resource plan: expected drift hash {expected}, current drift hash {actual}")


def _backup(root: Path, targets: dict[str, Any], *, action: str) -> tuple[str, Path]:
    occurred_at = _now()
    identity = f"{action}:{targets['identity']}:{_stamp(occurred_at)}"
    backup_id = f"{_stamp(occurred_at)}-{_sha(identity)[:8]}"
    path = root / EVIDENCE_ROOT / "backups" / f"{backup_id}.yml"
    _ensure_contained(root, path)
    overlay_bytes = targets["overlay"].read_bytes() if targets["overlay"].is_file() else None
    payload = {
        "api_version": API_VERSION,
        "backup_id": backup_id,
        "created_at": _iso(occurred_at),
        "action": action,
        "identity": {
            "kind": targets["kind"],
            "id": targets["id"],
            "domain": targets["domain"],
            "lane": targets["lane"],
            "canonical": targets["identity"],
        },
        "target": _relative(root, targets["path"]),
        "before": {
            "exists": targets["path"].is_dir(),
            "drift_hash": _tree_hash(targets) if targets["path"].is_dir() else None,
            "overlay_exists": overlay_bytes is not None,
            "overlay_base64": base64.b64encode(overlay_bytes).decode("ascii") if overlay_bytes is not None else None,
        },
    }
    _atomic_write(path, yaml.safe_dump(payload, sort_keys=False).encode("utf-8"))
    return backup_id, path


def _restore_overlay(targets: dict[str, Any], before: dict[str, Any]) -> None:
    if before.get("overlay_exists"):
        _atomic_write(targets["overlay"], base64.b64decode(str(before.get("overlay_base64") or "")))
    elif targets["overlay"].is_file():
        targets["overlay"].unlink()


def _receipt(
    root: Path,
    targets: dict[str, Any],
    *,
    action: str,
    backup_id: str,
    before_hash: str | None,
    after_hash: str | None,
    readback_ok: bool,
) -> Path:
    occurred_at = _now()
    path = root / EVIDENCE_ROOT / "receipts" / (
        f"{_stamp(occurred_at)}-{targets['kind']}-{targets['id']}-{action.rsplit('.', 1)[-1]}.yml"
    )
    _ensure_contained(root, path)
    payload = {
        "api_version": API_VERSION,
        "action": action,
        "occurred_at": _iso(occurred_at),
        "identity": targets["identity"],
        "backup_id": backup_id,
        "before_drift_hash": before_hash,
        "after_drift_hash": after_hash,
        "readback_ok": readback_ok,
        "external_effects": "none",
    }
    _atomic_write(path, yaml.safe_dump(payload, sort_keys=False).encode("utf-8"))
    return path


def _diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"field": key, "before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


def _normalize_changes(kind: str, changes: dict[str, Any], *, internal_fields: set[str] | None = None) -> dict[str, Any]:
    unknown = sorted(set(changes) - MUTABLE_FIELDS[kind] - (internal_fields or set()))
    if unknown:
        raise ValueError(f"unsupported {kind} fields: {', '.join(unknown)}")
    if not changes:
        raise ValueError("at least one mutable field is required")
    normalized = deepcopy(changes)
    for field in ("display_name", "summary", "harness", "model", "complexity", "notes", "definition_id"):
        if field in normalized:
            value = str(normalized[field]).strip()
            if not value or len(value) > (2000 if field in {"summary", "notes"} else 200) or "\x00" in value:
                raise ValueError(f"{field} must be non-empty and within its size limit")
            normalized[field] = value
    if "status" in normalized and normalized["status"] not in STATUSES:
        raise ValueError(f"unsupported lifecycle status: {normalized['status']}")
    if "enabled" in normalized and not isinstance(normalized["enabled"], bool):
        raise ValueError("enabled must be boolean")
    if "level" in normalized and normalized["level"] not in AUTOMATION_LEVELS:
        raise ValueError(f"unsupported automation level: {normalized['level']}")
    if "harness" in normalized:
        normalized["harness"] = str(normalized["harness"]).lower()
        if normalized["harness"] not in HARNESS_VALUES:
            raise ValueError(f"harness must be one of {', '.join(sorted(HARNESS_VALUES))}")
    if "definition_id" in normalized:
        normalized["definition_id"] = validate_name(str(normalized["definition_id"]), "definition_id")
    return normalized


def update_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    changes: dict[str, Any],
    domain: str | None = None,
    lane: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
    action: str = "resource.update",
    _internal_fields: set[str] | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    if not targets["path"].is_dir():
        raise ValueError(f"unknown {kind}: {resource_id}")
    before, _ = _load_overlay(targets)
    changes = _normalize_changes(kind, changes, internal_fields=_internal_fields)
    if "definition_id" in changes and not shared_factory_path(os_root, "00-programs", changes["definition_id"]).is_dir():
        raise ValueError(f"unknown program definition: {changes['definition_id']}")
    if before.get("status") == "archived" and action == "resource.update":
        raise ValueError(f"restore archived {kind} before updating: {resource_id}")
    after = deepcopy(before)
    after.update(changes)
    after.update({"kind": kind, "id": resource_id, "domain": targets["domain"], "lane": targets["lane"]})
    after["schema_version"] = int(after.get("schema_version") or 1)
    after["managed_by"] = AUTHORING_MANAGER
    if after != before:
        after["updated_at"] = _iso()
    findings = _validate_metadata(targets, after)
    if findings:
        raise ValueError("; ".join(item["message"] for item in findings))
    before_hash = _tree_hash(targets)
    after_bytes = _overlay_bytes(after)
    after_hash = _tree_hash(targets, overlay=after_bytes)
    changed = before_hash != after_hash
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run or not changed)
    status = "unchanged" if not changed else ("planned" if dry_run else "updated")
    result = _base(action, os_root, targets, dry_run=dry_run, status=status)
    result["resource"].update({"before": before, "after": after, "diff": _diff(before, after)})
    result["drift"] = {"before": before_hash, "after": after_hash}
    if dry_run or not changed:
        result["readback"] = {"ok": True, "metadata": before}
        return result
    backup_id, backup_path = _backup(os_root, targets, action=action)
    backup = yaml.safe_load(backup_path.read_text(encoding="utf-8"))
    _atomic_write(targets["overlay"], after_bytes)
    try:
        readback, _ = _load_overlay(targets)
        validation = _validate_existing(os_root, targets)
        overlay_findings = _validate_metadata(targets, readback)
        readback_ok = (
            readback == after
            and _tree_hash(targets) == after_hash
            and not any(item["severity"] == "blocker" for item in overlay_findings)
        )
        if not readback_ok:
            raise ValueError("resource validation or readback failed")
    except Exception as exc:
        _restore_overlay(targets, backup["before"])
        raise ValueError(f"{exc}; exact prior overlay bytes restored") from exc
    receipt = _receipt(
        os_root,
        targets,
        action=action,
        backup_id=backup_id,
        before_hash=before_hash,
        after_hash=after_hash,
        readback_ok=True,
    )
    terminal_status = {
        "resource.update": "updated",
        "resource.archive": "archived",
        "resource.restore": "restored",
        "resource.disable": "disabled",
    }.get(action, action.rsplit(".", 1)[-1])
    result.update(
        {
            "status": terminal_status,
            "backup_id": backup_id,
            "receipt": str(receipt),
            "validation": validation,
            "readback": {"ok": True, "metadata": readback},
        }
    )
    return result


def set_filesystem_resource_archive(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    archived: bool,
    domain: str | None = None,
    lane: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    before, _ = _load_overlay(targets)
    if archived:
        if before.get("status") == "archived":
            changes = {"status": "archived"}
        else:
            changes = {"status_before_archive": before.get("status") or "active", "status": "archived"}
        action = "resource.archive"
    else:
        changes = {
            "status": before.get("status_before_archive", "active")
            if before.get("status") == "archived"
            else before.get("status", "active")
        }
        action = "resource.restore"
    return update_filesystem_resource(
        os_root,
        kind,
        resource_id,
        changes=changes,
        domain=domain,
        lane=lane,
        expected_drift_hash=expected_drift_hash,
        dry_run=dry_run,
        action=action,
        _internal_fields={"status_before_archive"},
    )


def disable_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    changes: dict[str, Any] = {"status": "paused"}
    if kind == "automation":
        changes["enabled"] = False
    return update_filesystem_resource(
        root,
        kind,
        resource_id,
        changes=changes,
        domain=domain,
        lane=lane,
        expected_drift_hash=expected_drift_hash,
        dry_run=dry_run,
        action="resource.disable",
    )


def repair_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Repair only the lifecycle overlay; contract findings remain visible."""

    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    if not targets["path"].is_dir():
        raise ValueError(f"unknown {kind}: {resource_id}")
    explicit = targets["overlay"].is_file()
    before: dict[str, Any]
    if explicit:
        try:
            loaded = yaml.safe_load(targets["overlay"].read_text(encoding="utf-8")) or {}
            before = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            before = {}
    else:
        before = _implicit_metadata(targets)
    defaults = _implicit_metadata(targets)
    after = deepcopy(before)
    for field in ("display_name", "summary", "status"):
        if not after.get(field):
            after[field] = defaults[field]
    after.update(
        {
            "schema_version": int(after.get("schema_version") or 1),
            "kind": kind,
            "id": resource_id,
            "domain": targets["domain"],
            "lane": targets["lane"],
            "managed_by": AUTHORING_MANAGER,
        }
    )
    if after.get("status") not in STATUSES:
        after["status"] = "paused" if kind == "automation" else "draft"
    if kind == "automation":
        if not isinstance(after.get("enabled"), bool):
            after["enabled"] = False
        if after.get("level") not in AUTOMATION_LEVELS:
            after["level"] = defaults["level"]
    if kind == "instance-program" and not after.get("definition_id"):
        after["definition_id"] = defaults["definition_id"]
    if after != before or not explicit:
        after["updated_at"] = _iso()
    findings = _validate_metadata(targets, after)
    if findings:
        raise ValueError("; ".join(item["message"] for item in findings))
    before_hash = _tree_hash(targets)
    after_bytes = _overlay_bytes(after)
    after_hash = _tree_hash(targets, overlay=after_bytes)
    changed = not explicit or targets["overlay"].read_bytes() != after_bytes
    _confirm(expected_drift_hash, before_hash, dry_run=dry_run or not changed)
    result = _base(
        "resource.repair",
        os_root,
        targets,
        dry_run=dry_run,
        status="unchanged" if not changed else ("planned" if dry_run else "repaired"),
    )
    result["resource"].update({"before": before, "after": after, "diff": _diff(before, after)})
    result["drift"] = {"before": before_hash, "after": after_hash}
    if dry_run or not changed:
        result["readback"] = {"ok": True, "metadata": before}
        return result
    backup_id, backup_path = _backup(os_root, targets, action="resource.repair")
    backup = yaml.safe_load(backup_path.read_text(encoding="utf-8"))
    _atomic_write(targets["overlay"], after_bytes)
    try:
        readback, _ = _load_overlay(targets)
        readback_ok = (
            readback == after
            and _tree_hash(targets) == after_hash
            and not _validate_metadata(targets, readback)
        )
        if not readback_ok:
            raise ValueError("resource lifecycle repair readback failed")
    except Exception as exc:
        _restore_overlay(targets, backup["before"])
        raise ValueError(f"{exc}; exact prior overlay bytes restored") from exc
    validation = _validate_existing(os_root, targets)
    receipt = _receipt(
        os_root,
        targets,
        action="resource.repair",
        backup_id=backup_id,
        before_hash=before_hash,
        after_hash=after_hash,
        readback_ok=True,
    )
    result.update(
        {
            "backup_id": backup_id,
            "receipt": str(receipt),
            "validation": validation,
            "readback": {"ok": True, "metadata": readback},
        }
    )
    return result


def create_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    exists = targets["path"].exists()
    result = _base(
        "resource.create",
        os_root,
        targets,
        dry_run=dry_run,
        status="exists" if exists else ("planned" if dry_run else "created"),
    )
    result["drift"] = {"before": _tree_hash(targets) if exists else _sha(f"absent:{targets['identity']}")}
    if exists:
        result["readback"] = {"ok": True, "exists": True}
        result["validation"] = _validate_existing(os_root, targets)
        return result
    if dry_run:
        result["readback"] = {"ok": True, "exists": False}
        return result
    backup_id, _ = _backup(os_root, targets, action="resource.create")
    creators: dict[str, tuple[Callable[..., Any], tuple[Any, ...]]] = {
        "automation": (create_automation, (os_root, domain, lane, resource_id)),
        "workflow": (create_workflow, (os_root, domain, lane, resource_id)),
        "program": (create_program, (os_root, resource_id)),
        "instance-program": (create_instance_program, (os_root, domain, resource_id)),
    }
    creator, args = creators[kind]
    scaffold = creator(*args)
    metadata = _implicit_metadata(targets)
    metadata["status"] = "draft"
    metadata["created_at"] = metadata["updated_at"] = _iso()
    if kind == "automation":
        metadata["enabled"] = False
    _atomic_write(targets["overlay"], _overlay_bytes(metadata))
    validation = _validate_existing(os_root, targets)
    if not targets["path"].is_dir() or _validate_metadata(targets, metadata):
        shutil.rmtree(targets["path"])
        raise ValueError("created resource failed lifecycle validation; created canonical resource folder was rolled back")
    after_hash = _tree_hash(targets)
    receipt = _receipt(
        os_root,
        targets,
        action="resource.create",
        backup_id=backup_id,
        before_hash=None,
        after_hash=after_hash,
        readback_ok=True,
    )
    result.update(
        {
            "backup_id": backup_id,
            "receipt": str(receipt),
            "changes": {
                "created": [str(path) for path in scaffold.created],
                "updated": [str(path) for path in scaffold.updated],
                "skipped": [str(path) for path in scaffold.skipped],
            },
            "drift": {"before": result["drift"]["before"], "after": after_hash},
            "validation": validation,
            "readback": {"ok": True, "exists": True, "metadata": metadata},
        }
    )
    return result


def rollback_filesystem_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    backup_id: str,
    domain: str | None = None,
    lane: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise ValueError(f"invalid backup_id: {backup_id!r}")
    os_root = expand_path(root)
    targets = _targets(os_root, kind, resource_id, domain=domain, lane=lane)
    backup_path = os_root / EVIDENCE_ROOT / "backups" / f"{backup_id}.yml"
    _ensure_contained(os_root, backup_path)
    if not backup_path.is_file():
        raise ValueError(f"unknown backup_id: {backup_id}")
    bundle = yaml.safe_load(backup_path.read_text(encoding="utf-8")) or {}
    expected_identity = {
        "kind": kind,
        "id": resource_id,
        "domain": targets["domain"],
        "lane": targets["lane"],
        "canonical": targets["identity"],
    }
    if bundle.get("identity") != expected_identity:
        raise ValueError("backup identity does not match the requested resource")
    if bundle.get("target") != _relative(os_root, targets["path"]):
        raise ValueError("backup target does not match the canonical resource target")
    before = bundle.get("before") or {}
    current_hash = _tree_hash(targets) if targets["path"].is_dir() else _sha(f"absent:{targets['identity']}")
    _confirm(expected_drift_hash, current_hash, dry_run=dry_run)
    result = _base("resource.rollback", os_root, targets, dry_run=dry_run, status="planned" if dry_run else "rolled_back")
    result["backup_id"] = backup_id
    result["drift"] = {"before": current_hash, "after": before.get("drift_hash")}
    if dry_run:
        result["readback"] = {"ok": True, "current_drift_hash": current_hash}
        return result
    rollback_backup_id, rollback_backup_path = _backup(os_root, targets, action="resource.rollback")
    if not before.get("exists"):
        if targets["path"].is_dir():
            shutil.rmtree(targets["path"])
        readback_ok = not targets["path"].exists()
        after_hash = None
    else:
        if not targets["path"].is_dir():
            raise ValueError("cannot restore overlay because canonical resource folder is missing")
        _restore_overlay(targets, before)
        after_hash = _tree_hash(targets)
        readback_ok = after_hash == before.get("drift_hash")
    if not readback_ok:
        rollback_bundle = yaml.safe_load(rollback_backup_path.read_text(encoding="utf-8")) or {}
        if targets["path"].is_dir():
            _restore_overlay(targets, rollback_bundle.get("before") or {})
        raise ValueError("rollback readback mismatch; exact pre-rollback overlay bytes restored")
    receipt = _receipt(
        os_root,
        targets,
        action="resource.rollback",
        backup_id=rollback_backup_id,
        before_hash=current_hash,
        after_hash=after_hash,
        readback_ok=True,
    )
    result.update({"rollback_backup_id": rollback_backup_id, "receipt": str(receipt), "readback": {"ok": True, "drift_hash": after_hash}})
    return result


def automation_schedule_id(domain: str, lane: str, resource_id: str) -> str:
    identity = (
        f"automation__{normalize_domain(domain)}__{validate_name(lane, 'lane')}__"
        f"{validate_name(resource_id, 'automation')}"
    )
    return validate_name(identity, "schedule_id")


def _automation_invocation(resource_id: str, domain: str, lane: str) -> str:
    # Every token is derived from validated canonical identity.  No caller shell
    # fragment is accepted by the public schedule API.
    return (
        f"agentic-os resource run-now automation {resource_id} --domain {domain} "
        f"--lane {lane} --root <root> --apply"
    )


def automation_schedule_get(root: str | Path, resource_id: str, *, domain: str, lane: str) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, "automation", resource_id, domain=domain, lane=lane)
    if not targets["path"].is_dir():
        raise ValueError(f"unknown automation: {resource_id}")
    from .resource_actions import schedule_get

    return schedule_get(os_root, automation_schedule_id(domain, lane, resource_id))


def configure_automation_schedule(
    root: str | Path,
    resource_id: str,
    *,
    domain: str,
    lane: str,
    cadence: str,
    timezone_name: str = "America/Chicago",
    local_time: str | None = None,
    enabled: bool | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, "automation", resource_id, domain=domain, lane=lane)
    if not targets["path"].is_dir():
        raise ValueError(f"unknown automation: {resource_id}")
    from .resource_actions import _load_yaml, _registry_path, schedule_create_governed, schedule_update

    registry = _load_yaml(_registry_path(os_root))
    schedule_id = automation_schedule_id(domain, lane, resource_id)
    existing = next((item for item in registry.get("schedules") or [] if item.get("id") == schedule_id), None)
    drift_hash = _sha(yaml.safe_dump({"resource": _tree_hash(targets), "schedule": existing}, sort_keys=True))
    _confirm(expected_drift_hash, drift_hash, dry_run=dry_run)
    command = _automation_invocation(resource_id, targets["domain"], targets["lane"])
    if existing is None:
        result = schedule_create_governed(
            os_root,
            schedule_id,
            cadence=cadence,
            timezone_name=timezone_name,
            local_time=local_time,
            command=command,
            enabled=bool(enabled),
            dry_run=dry_run,
        )
    else:
        changes: dict[str, Any] = {
            "cadence": cadence,
            "timezone": timezone_name,
            "local_time": local_time,
            "execution_target": "script",
            "command": command,
        }
        if enabled is not None:
            changes["enabled"] = enabled
        result = schedule_update(
            os_root,
            schedule_id,
            changes=changes,
            dry_run=dry_run,
            action="resource.schedule.configure",
        )
    result["action"] = "resource.schedule.configure"
    result["automation"] = {"kind": "automation", "id": resource_id, "domain": domain, "lane": lane}
    result["drift_hash"] = drift_hash
    result["dispatch_performed"] = False
    return result


def automation_run_now(
    root: str | Path,
    resource_id: str,
    *,
    domain: str,
    lane: str,
    idempotency_key: str | None = None,
    expected_drift_hash: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    targets = _targets(os_root, "automation", resource_id, domain=domain, lane=lane)
    view = _resource_view(os_root, targets)
    if not view.get("enabled") or view.get("status") in {"paused", "archived"}:
        raise ValueError(f"automation must be enabled and active before queueing: {resource_id}")
    drift_hash = view["drift_hash"]
    # Queue-only run-now records the current drift hash in the item. A GUI may
    # confirm a preceding plan, while a derived schedule safely queues against
    # current state without embedding a stale hash in its fixed command.
    if expected_drift_hash is not None:
        _confirm(expected_drift_hash, drift_hash, dry_run=dry_run)
    if idempotency_key is None:
        idempotency_key = f"automation:{targets['identity']}:{_stamp()}"
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("idempotency key may contain letters, numbers, colon, underscore, and hyphen only")
    occurred_at = _now()
    queue_item = {
        "id": f"queue_{_sha(idempotency_key)[:12]}",
        "kind": "automation",
        "ref": targets["identity"],
        "status": "dry-run" if dry_run else "queued",
        "approval_state": "not_required",
        "created_at": _iso(occurred_at),
        "due_at": _iso(occurred_at),
        "dry_run": dry_run,
        "idempotency_key": idempotency_key,
        "execution_target": HARNESS_TARGETS.get(str(view.get("harness") or "agentic_os"), "codex_harness"),
        "dispatch_performed": False,
        "resource_drift_hash": drift_hash,
    }
    result = _base("resource.run-now", os_root, targets, dry_run=dry_run, status="planned" if dry_run else "queued")
    result["queue_item"] = queue_item
    result["external_effects"] = "local queue item only; no dispatch performed"
    if dry_run:
        result["readback"] = {"ok": True, "queue_item": None}
        return result
    queued = append_run_queue_item(os_root, queue_item)
    result.update(
        {
            "status": "queued" if queued["created"] else "unchanged",
            "queue_created": queued["created"],
            "receipt": queued["run_queue"],
            "readback": {"ok": True, "queue_item": queued["queue_item"]},
        }
    )
    return result
