"""Materialized first-class Agentic OS resource registry.

Refreshes may inspect the installed tree. Normal reads never do: they load one
atomic JSON snapshot from ``harness/registries/first-class-resources.json``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable
from uuid import uuid4

import yaml

from .operator_resources import query_operator_resources
from .scaffold import expand_path

API_VERSION = "first-class-resource-registry/v1"
REGISTRY_PATH = Path("harness/registries/first-class-resources.json")
TAG_OVERLAY_API_VERSION = "first-class-resource-tags/v1"
TAG_MUTATION_API_VERSION = "first-class-resource-tag-mutation/v1"
TAG_OVERLAY_PATH = Path("harness/registries/first-class-resource-tags.json")
TAG_RECEIPT_ROOT = Path(
    "harness/shared_factory/06-runs-and-logs/resource-tag-mutations"
)
TAG_LOCK_PATH = Path("harness/registries/.first-class-resource-tags.lock")
_PROCESS_TAG_LOCK = threading.RLock()
RESOURCE_KINDS = (
    "automation",
    "automation_instance",
    "program",
    "program_instance",
    "workflow",
    "workflow_instance",
    "rule",
    "report",
    "skill",
    "command",
)

DIAGNOSTIC_REPAIRS = {
    "resource_read_failed": (
        "repair_resource_source",
        "Restore read access or repair the reported resource source.",
    ),
    "registry_unavailable": (
        "repair_registry_source",
        "Repair the registry source so it can be loaded deterministically.",
    ),
}
REGISTRY_SOURCES = (
    ("skill", "skills", "harness/registries/skills.yml"),
    ("command", "commands", "harness/registries/commands.yml"),
    ("rule", "rules", "harness/registries/rules.yml"),
    ("report", "reports", "harness/registries/reports.yml"),
    ("report", "definitions", "harness/registries/report-definitions.yml"),
)
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "worktrees",
    "worker-runs",
    "artifacts",
    "backups",
    "templates",
    "logs",
}
MAX_AUTOMATION_EVIDENCE_REFS = 12


def _iso(value: datetime | None = None) -> str:
    return (
        (value or datetime.now(UTC))
        .astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_resource_tag(value: str) -> str:
    """Return the canonical custom-tag spelling or reject unsafe input."""

    if not isinstance(value, str):
        raise ValueError("tag must be a string")
    normalized = re.sub(r"[\s_]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("tag must not be empty")
    if len(normalized) > 32:
        raise ValueError("tag must be 32 characters or fewer")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
        raise ValueError("tag may contain only letters, numbers, spaces, '_' or '-'")
    return normalized


def _validate_resource_id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 510:
        raise ValueError("resource id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValueError("resource id contains unsupported characters")
    if ":" not in value:
        raise ValueError("resource id must be a stable first-class resource identity")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _tag_mutation_lock(root: Path):
    lock_path = root / TAG_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_TAG_LOCK, lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _empty_tag_overlay() -> dict[str, Any]:
    return {
        "api_version": TAG_OVERLAY_API_VERSION,
        "updated_at": None,
        "resources": {},
    }


def _load_tag_overlay(root: Path) -> dict[str, Any]:
    path = root / TAG_OVERLAY_PATH
    if not path.is_file():
        return _empty_tag_overlay()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("api_version") != TAG_OVERLAY_API_VERSION or not isinstance(
        payload.get("resources"), dict
    ):
        raise ValueError("first-class resource tag overlay contract is invalid")
    normalized: dict[str, dict[str, Any]] = {}
    for resource_id, entry in payload["resources"].items():
        resource_id = _validate_resource_id(resource_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("tags"), list):
            raise ValueError(f"tag overlay entry is invalid: {resource_id}")
        tags = sorted({normalize_resource_tag(tag) for tag in entry["tags"]})
        if tags:
            normalized[resource_id] = {
                "tags": tags,
                "updated_at": entry.get("updated_at"),
            }
    return {
        "api_version": TAG_OVERLAY_API_VERSION,
        "updated_at": payload.get("updated_at"),
        "resources": normalized,
    }


def _stable_id(kind: str, identity: str) -> str:
    return f"{kind}:{re.sub(r'[^A-Za-z0-9._:-]+', ':', identity)}"[:510]


def _scope(relative_ref: str) -> tuple[str | None, str | None]:
    parts = Path(relative_ref).parts
    if not parts:
        return None, None
    if parts[0] == "harness":
        return "shared_factory", None
    domain = parts[0]
    if len(parts) >= 4 and parts[1] == "02-projects":
        return domain, parts[2]
    return domain, None


def _relative_source(root: Path, value: Any) -> str:
    candidate = Path(str(value or REGISTRY_PATH))
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return REGISTRY_PATH.as_posix()
    if ".." in candidate.parts:
        return REGISTRY_PATH.as_posix()
    return candidate.as_posix()


def _summary_from_markdown(path: Path, fallback: str) -> tuple[str, str]:
    body = path.read_text(encoding="utf-8", errors="replace")[:64_000]
    heading = re.search(
        r"^#\s+(?:OSProgram|InstanceOSProgram|Automation|Workflow)?\s*:?\s*(.+)$",
        body,
        re.M,
    )
    purpose = re.search(
        r"^##\s+(?:Purpose|Summary)\s*$\n+(.+?)(?=\n##\s|\Z)", body, re.M | re.S
    )
    title = (
        heading.group(1).strip()
        if heading
        else fallback.replace("_", " ").replace("-", " ").title()
    )
    summary = (
        " ".join(
            line.strip() for line in purpose.group(1).splitlines() if line.strip()
        )[:600]
        if purpose
        else ""
    )
    return title, summary


def _normalize_diagnostic(item: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("code") or "unknown_diagnostic")
    repair_kind, guidance = DIAGNOSTIC_REPAIRS.get(
        code,
        (
            str(item.get("repair_kind") or "inspect_source"),
            str(
                item.get("guidance")
                or "Inspect the reported source and resource evidence before changing canonical state."
            ),
        ),
    )
    if code.endswith("_registry_unavailable"):
        repair_kind, guidance = DIAGNOSTIC_REPAIRS["registry_unavailable"]
    return {
        **item,
        "resource_id": item.get("resource_id"),
        "path": item.get("path") or item.get("source"),
        "repair_kind": repair_kind,
        "guidance": guidance,
    }


def _diagnostic_summary(
    diagnostics: list[dict[str, Any]], *, returned: int
) -> dict[str, Any]:
    by_code = {
        code: sum(item.get("code") == code for item in diagnostics)
        for code in sorted({str(item.get("code")) for item in diagnostics})
    }
    errors = sum(item.get("severity") == "error" for item in diagnostics)
    warnings = sum(item.get("severity") == "warning" for item in diagnostics)
    info = sum(item.get("severity") == "info" for item in diagnostics)
    return {
        "returned": returned,
        "diagnostics": len(diagnostics),
        "info": info,
        "warnings": warnings,
        "errors": errors,
        "partial": bool(errors or warnings),
        "by_diagnostic_code": by_code,
    }


def _entry(
    *,
    kind: str,
    resource_id: str,
    native_id: str,
    title: str,
    summary: str,
    source: str,
    generated_at: str,
    domain: str | None = None,
    project: str | None = None,
    subtype: str | None = None,
    health_state: str = "not_applicable",
    health_summary: str = "Runtime health does not apply to this static resource.",
    health_evidence_basis: str = "static_registration",
    health_liveness_observed: bool = False,
    health_observed_at: str | None = None,
    tags: Iterable[str | None] = (),
    source_updated_at: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "id": resource_id,
        "native_id": native_id,
        "kind": kind,
        "title": title,
        "summary": summary or f"{kind.replace('_', ' ')} registered in Agentic OS.",
        "scope": {"domain": domain, "project": project},
        "source": source,
        "observed_at": generated_at,
        "source_updated_at": source_updated_at,
        "subtype": subtype,
        "health": {
            "state": health_state,
            "summary": health_summary,
            "evidence_basis": health_evidence_basis,
            "liveness_observed": health_liveness_observed,
            "observed_at": health_observed_at,
        },
        "tags": sorted({tag for tag in tags if tag}),
    }
    if evidence is not None:
        entry["evidence"] = evidence
    return entry


def _safe_evidence_ref(
    root: Path,
    value: Any,
    *,
    label: str,
    source: str,
    observed_at: str | None = None,
) -> dict[str, Any] | None:
    """Project one existing path without granting absolute or escaped authority."""

    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    if not (resolved.is_file() or resolved.is_dir()):
        return None
    return {
        "path": relative.as_posix(),
        "kind": "directory" if resolved.is_dir() else "file",
        "label": label,
        "source": source,
        "observed_at": observed_at,
    }


def _evidence_group(
    refs: Iterable[dict[str, Any] | None],
    *,
    available_reason: str,
    unavailable_reason: str,
    unavailable_code: str,
) -> dict[str, Any]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        if ref is not None:
            unique.setdefault((ref["path"], ref["kind"]), ref)
    bounded = list(unique.values())[:MAX_AUTOMATION_EVIDENCE_REFS]
    return {
        "available": bool(bounded),
        "reason": available_reason.format(count=len(bounded))
        if bounded
        else unavailable_reason,
        "unavailable_code": None if bounded else unavailable_code,
        "references": bounded,
    }


def _automation_evidence(root: Path, resource: dict[str, Any]) -> dict[str, Any]:
    identity = (
        resource.get("definition")
        or resource.get("instance")
        or resource.get("tracking")
        or {}
    )
    if not isinstance(identity, dict):
        identity = {}
    owner = identity.get("path") or identity.get("cwd")
    log_refs: list[dict[str, Any] | None] = []
    run_refs: list[dict[str, Any] | None] = []
    recent_refs: list[dict[str, Any] | None] = []

    if isinstance(owner, str) and owner:
        log_refs.append(
            _safe_evidence_ref(
                root,
                (Path(owner) / "logs").as_posix(),
                label="Logs folder",
                source="automation_definition",
            )
        )
        run_refs.append(
            _safe_evidence_ref(
                root,
                (Path(owner) / "runs").as_posix(),
                label="Runs folder",
                source="automation_definition",
            )
        )

    for run in resource.get("runs") or []:
        if not isinstance(run, dict):
            continue
        observed_at = next(
            (
                run.get(field)
                for field in ("finished_at", "updated_at", "started_at", "created_at")
                if isinstance(run.get(field), str)
            ),
            None,
        )
        log_refs.append(
            _safe_evidence_ref(
                root,
                run.get("log"),
                label="Run log",
                source="run_receipt",
                observed_at=observed_at,
            )
        )
        run_refs.append(
            _safe_evidence_ref(
                root,
                run.get("source_path"),
                label="Run queue receipts",
                source="run_receipt",
                observed_at=observed_at,
            )
        )

    for item in resource.get("recent_evidence") or []:
        if not isinstance(item, dict):
            continue
        recent_refs.append(
            _safe_evidence_ref(
                root,
                item.get("path"),
                label="Recent evidence",
                source=str(item.get("source") or "filesystem_receipt"),
                observed_at=item.get("observed_at")
                if isinstance(item.get("observed_at"), str)
                else None,
            )
        )

    return {
        "logs": _evidence_group(
            log_refs,
            available_reason="{count} canonical log reference(s) available.",
            unavailable_reason="No canonical root-relative log evidence is available.",
            unavailable_code="no_log_evidence",
        ),
        "runs": _evidence_group(
            run_refs,
            available_reason="{count} canonical run reference(s) available.",
            unavailable_reason="No canonical root-relative run evidence is available.",
            unavailable_code="no_run_evidence",
        ),
        "recent": _evidence_group(
            recent_refs,
            available_reason="{count} recent evidence reference(s) available.",
            unavailable_reason="No recent root-relative evidence file is available.",
            unavailable_code="no_recent_evidence",
        ),
    }


def _operator_entries(
    root: Path, kind: str, generated_at: str, diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        envelope = query_operator_resources(root, kind)
    except (
        Exception
    ) as exc:  # malformed resources remain visible as a refresh diagnostic
        diagnostics.append(
            {
                "severity": "error",
                "code": f"{kind}_projection_failed",
                "source": "operator-resource-query/v1",
                "message": f"{type(exc).__name__}: {exc}",
                "kind": kind,
                "resource_id": None,
                "path": None,
                "repair_kind": "repair_projection",
                "guidance": f"Repair the {kind} operator projection before refreshing the registry.",
            }
        )
        return []
    diagnostics.extend(
        {**item, "kind": kind} for item in (envelope.get("diagnostics") or [])
    )
    result: list[dict[str, Any]] = []
    for resource in envelope.get("resources") or []:
        resource_type = str(resource.get("resource_type") or "definition")
        mapped_kind = kind if resource_type == "definition" else f"{kind}_instance"
        identity = (
            resource.get("definition")
            or resource.get("instance")
            or resource.get("tracking")
            or {}
        )
        if not isinstance(identity, dict):
            identity = {}
        source = _relative_source(
            root, identity.get("path") or identity.get("cwd") or REGISTRY_PATH
        )
        domain = (
            identity.get("domain") if isinstance(identity.get("domain"), str) else None
        )
        project = (
            identity.get("project")
            if isinstance(identity.get("project"), str)
            else None
        )
        health = (
            resource.get("health") if isinstance(resource.get("health"), dict) else {}
        )
        status = str(health.get("status") or "unobserved").lower()
        health_state = (
            status
            if status
            in {
                "not_applicable",
                "unobserved",
                "disabled",
                "healthy",
                "degraded",
                "unhealthy",
            }
            else (
                "unhealthy"
                if status in {"failed", "failure", "error"}
                else (
                    "degraded"
                    if status in {"stale", "partial"}
                    else (
                        "healthy"
                        if status in {"success", "active", "done", "queued"}
                        else "unobserved"
                    )
                )
            )
        )
        evidence_basis = str(
            health.get("evidence_basis") or health.get("source") or "unobserved"
        )
        liveness_observed = health.get("liveness_observed") is True
        health_summary = str(
            health.get("reason")
            or (
                "Runtime health does not apply to this static resource."
                if health_state == "not_applicable"
                else f"Evidence-backed status: {health_state}."
            )
        )
        result.append(
            _entry(
                kind=mapped_kind,
                resource_id=str(resource["id"]),
                native_id=str(resource["id"]),
                title=str(
                    identity.get("display_name")
                    or identity.get("name")
                    or resource["id"]
                ),
                summary=str(
                    identity.get("summary")
                    or f"{mapped_kind.replace('_', ' ')} projected by Agentic OS."
                ),
                source=source,
                generated_at=generated_at,
                domain=domain,
                project=project,
                subtype=resource_type,
                health_state=health_state,
                health_summary=health_summary,
                health_evidence_basis=evidence_basis,
                health_liveness_observed=liveness_observed,
                health_observed_at=(
                    health.get("observed_at")
                    if isinstance(health.get("observed_at"), str)
                    else None
                ),
                tags=(mapped_kind, resource_type, status),
                source_updated_at=health.get("observed_at")
                if isinstance(health.get("observed_at"), str)
                else None,
                evidence=_automation_evidence(root, resource)
                if kind == "automation"
                else None,
            )
        )
    return result


def _document_entries(
    root: Path, generated_at: str, diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    patterns = {"workflow.md": "workflow_instance", "RULES.md": "rule"}
    result: list[dict[str, Any]] = []
    for current, directories, filenames in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name not in SKIP_PARTS and not name.startswith(".")
        ]
        for filename in sorted(set(filenames).intersection(patterns)):
            base_kind = patterns[filename]
            path = Path(current) / filename
            relative = path.relative_to(root)
            relative_ref = relative.as_posix()
            kind = base_kind
            if base_kind == "workflow_instance" and relative_ref.startswith(
                "harness/shared_factory/"
            ):
                kind = "workflow"
            try:
                native_id = (
                    path.parent.name
                    if kind != "rule"
                    else ":".join(relative.parts[:-1]) or "root"
                )
                title, summary = _summary_from_markdown(path, native_id)
                domain, project = _scope(relative_ref)
                result.append(
                    _entry(
                        kind=kind,
                        resource_id=_stable_id(kind, relative_ref),
                        native_id=native_id,
                        title=title,
                        summary=summary,
                        source=relative_ref,
                        generated_at=generated_at,
                        domain=domain,
                        project=project,
                        subtype=(
                            "rule_document"
                            if kind == "rule"
                            else ("definition" if kind == "workflow" else "instance")
                        ),
                        health_summary="Runtime health does not apply to this canonical filesystem document.",
                        health_evidence_basis="static_filesystem_presence",
                        tags=(kind, domain, project),
                        source_updated_at=_iso(
                            datetime.fromtimestamp(path.stat().st_mtime, UTC)
                        ),
                    )
                )
            except OSError as exc:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "resource_read_failed",
                        "source": relative_ref,
                        "message": str(exc),
                        "kind": base_kind,
                    }
                )
    return result


def _registry_entries(
    root: Path, generated_at: str, diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sources = list(REGISTRY_SOURCES)
    for path in root.glob("*/02-projects/*/config/resource-registries/*.yml"):
        key = path.stem
        kind = key[:-1] if key.endswith("s") else key
        if kind in RESOURCE_KINDS:
            sources.append((kind, key, path.relative_to(root).as_posix()))
    result: list[dict[str, Any]] = []
    for kind, key, relative_ref in sources:
        path = root / relative_ref
        if not path.is_file():
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            records = payload.get(key) or []
            if not isinstance(records, list):
                raise ValueError(f"{key} must be a list")
            for record in records:
                if not isinstance(record, dict) or not record.get("id"):
                    continue
                native_id = str(record["id"])
                scope = (
                    record.get("scope") if isinstance(record.get("scope"), dict) else {}
                )
                domain, project = _scope(relative_ref)
                domain = (
                    record.get("domain")
                    if isinstance(record.get("domain"), str)
                    else (
                        scope.get("domain")
                        if isinstance(scope.get("domain"), str)
                        else domain
                    )
                )
                project = (
                    record.get("project")
                    if isinstance(record.get("project"), str)
                    else (
                        scope.get("project")
                        if isinstance(scope.get("project"), str)
                        else project
                    )
                )
                declared_source = _relative_source(
                    root, record.get("source") or relative_ref
                )
                source = (
                    declared_source
                    if (root / declared_source).exists()
                    else relative_ref
                )
                title = str(
                    record.get("name")
                    or record.get("command")
                    or native_id.replace("-", " ").title()
                )
                identity = (
                    f"typed:definition:{native_id}"
                    if relative_ref == "harness/registries/report-definitions.yml"
                    else f"{relative_ref}:{native_id}"
                )
                result.append(
                    _entry(
                        kind=kind,
                        resource_id=_stable_id(kind, identity),
                        native_id=native_id,
                        title=title,
                        summary=str(
                            record.get("description") or record.get("summary") or ""
                        ),
                        source=source,
                        generated_at=generated_at,
                        domain=domain,
                        project=project,
                        subtype="registry_entry" if kind != "report" else "definition",
                        health_state="not_applicable",
                        health_summary="Runtime health does not apply to this canonical registry definition.",
                        health_evidence_basis="static_registry_presence",
                        tags=(kind, domain, project),
                        source_updated_at=_iso(
                            datetime.fromtimestamp(path.stat().st_mtime, UTC)
                        ),
                    )
                )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": f"{kind}_registry_unavailable",
                    "source": relative_ref,
                    "message": f"{type(exc).__name__}: {exc}",
                    "kind": kind,
                }
            )
    return result


def _merge_custom_tags(
    root: Path,
    resources: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> None:
    try:
        overlay = _load_tag_overlay(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        diagnostics.append(
            {
                "severity": "error",
                "code": "resource_tag_overlay_invalid",
                "source": TAG_OVERLAY_PATH.as_posix(),
                "message": f"{type(exc).__name__}: {exc}",
                "kind": None,
                "resource_id": None,
                "path": TAG_OVERLAY_PATH.as_posix(),
                "repair_kind": "repair_resource_tag_overlay",
                "guidance": "Repair or restore the custom-tag overlay before changing tags.",
            }
        )
        overlay = _empty_tag_overlay()
    entries = overlay["resources"]
    known_ids = {resource["id"] for resource in resources}
    for resource in resources:
        derived = sorted(set(resource.get("tags") or []))
        custom = list((entries.get(resource["id"]) or {}).get("tags") or [])
        resource["tags"] = sorted(set((*derived, *custom)))
        resource["tag_provenance"] = {
            "derived": derived,
            "custom": custom,
        }
    for resource_id in sorted(set(entries).difference(known_ids)):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "resource_tag_target_missing",
                "source": TAG_OVERLAY_PATH.as_posix(),
                "message": f"custom tags reference an unknown resource: {resource_id}",
                "kind": None,
                "resource_id": resource_id,
                "path": TAG_OVERLAY_PATH.as_posix(),
                "repair_kind": "remove_or_restore_resource_tag_target",
                "guidance": "Restore the resource or remove its custom tags with the governed tag command.",
            }
        )


def _refresh_first_class_registry_unlocked(
    root: str | Path, *, now: datetime | None = None
) -> dict[str, Any]:
    os_root = expand_path(root)
    generated_at = _iso(now)
    diagnostics: list[dict[str, Any]] = []
    resources = [
        *_operator_entries(os_root, "program", generated_at, diagnostics),
        *_operator_entries(os_root, "automation", generated_at, diagnostics),
        *_document_entries(os_root, generated_at, diagnostics),
        *_registry_entries(os_root, generated_at, diagnostics),
    ]
    unique: dict[str, dict[str, Any]] = {}
    for resource in sorted(
        resources, key=lambda item: (item["kind"], item["id"], item["source"])
    ):
        unique.setdefault(resource["id"], resource)
    resources = list(unique.values())
    _merge_custom_tags(os_root, resources, diagnostics)
    diagnostics = [_normalize_diagnostic(item) for item in diagnostics]
    fingerprint_resources = [
        {key: value for key, value in resource.items() if key != "observed_at"}
        for resource in resources
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_resources, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    payload = {
        "api_version": API_VERSION,
        "generated_at": generated_at,
        "root": str(os_root),
        "registry_path": str(REGISTRY_PATH),
        "fingerprint": fingerprint,
        "resources": resources,
        "diagnostics": diagnostics,
        "summary": {
            **_diagnostic_summary(diagnostics, returned=len(resources)),
            "by_kind": {
                kind: sum(item["kind"] == kind for item in resources)
                for kind in RESOURCE_KINDS
            },
        },
    }
    target = os_root / REGISTRY_PATH
    _write_json_atomic(target, payload)
    return payload


def refresh_first_class_registry(
    root: str | Path, *, now: datetime | None = None
) -> dict[str, Any]:
    os_root = expand_path(root)
    with _tag_mutation_lock(os_root):
        return _refresh_first_class_registry_unlocked(os_root, now=now)


def list_resource_tags(root: str | Path, resource_id: str) -> dict[str, Any]:
    os_root = expand_path(root)
    resource_id = _validate_resource_id(resource_id)
    with _tag_mutation_lock(os_root):
        snapshot_path = os_root / REGISTRY_PATH
        snapshot = (
            json.loads(snapshot_path.read_text(encoding="utf-8"))
            if snapshot_path.is_file()
            else _refresh_first_class_registry_unlocked(os_root)
        )
        resource = next(
            (
                item
                for item in snapshot.get("resources") or []
                if item.get("id") == resource_id
            ),
            None,
        )
        if resource is None or not isinstance(resource.get("tag_provenance"), dict):
            snapshot = _refresh_first_class_registry_unlocked(os_root)
            resource = next(
                (
                    item
                    for item in snapshot["resources"]
                    if item.get("id") == resource_id
                ),
                None,
            )
        if resource is None:
            raise ValueError(f"unknown first-class resource id: {resource_id}")
        provenance = resource.get("tag_provenance") or {}
        return {
            "api_version": TAG_OVERLAY_API_VERSION,
            "resource_id": resource_id,
            "tags": list(resource.get("tags") or []),
            "derived_tags": list(provenance.get("derived") or []),
            "custom_tags": list(provenance.get("custom") or []),
            "registry_fingerprint": snapshot.get("fingerprint"),
        }


def mutate_resource_tag(
    root: str | Path,
    *,
    operation: str,
    resource_id: str,
    tag: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add or remove one custom tag and atomically refresh the materialized view."""

    if operation not in {"add", "remove"}:
        raise ValueError("tag operation must be add or remove")
    os_root = expand_path(root)
    resource_id = _validate_resource_id(resource_id)
    tag = normalize_resource_tag(tag)
    occurred_at = _iso(now)
    with _tag_mutation_lock(os_root):
        snapshot_path = os_root / REGISTRY_PATH
        snapshot = (
            json.loads(snapshot_path.read_text(encoding="utf-8"))
            if snapshot_path.is_file()
            else _refresh_first_class_registry_unlocked(os_root, now=now)
        )
        if not any(
            item.get("id") == resource_id for item in snapshot.get("resources") or []
        ):
            snapshot = _refresh_first_class_registry_unlocked(os_root, now=now)
        if not any(
            item.get("id") == resource_id for item in snapshot.get("resources") or []
        ):
            raise ValueError(f"unknown first-class resource id: {resource_id}")

        overlay = _load_tag_overlay(os_root)
        entries = overlay["resources"]
        current = set((entries.get(resource_id) or {}).get("tags") or [])
        changed = tag not in current if operation == "add" else tag in current
        if operation == "add":
            current.add(tag)
        else:
            current.discard(tag)
        if current:
            entries[resource_id] = {
                "tags": sorted(current),
                "updated_at": occurred_at,
            }
        else:
            entries.pop(resource_id, None)
        overlay["updated_at"] = occurred_at
        _write_json_atomic(os_root / TAG_OVERLAY_PATH, overlay)
        refreshed = _refresh_first_class_registry_unlocked(os_root, now=now)
        resource = next(
            item for item in refreshed["resources"] if item["id"] == resource_id
        )
        receipt = {
            "api_version": TAG_MUTATION_API_VERSION,
            "operation": operation,
            "resource_id": resource_id,
            "tag": tag,
            "changed": changed,
            "custom_tags": resource["tag_provenance"]["custom"],
            "tags": resource["tags"],
            "occurred_at": occurred_at,
            "overlay_path": TAG_OVERLAY_PATH.as_posix(),
            "registry_path": REGISTRY_PATH.as_posix(),
            "registry_fingerprint": refreshed["fingerprint"],
        }
        receipt_name = (
            f"{occurred_at.replace(':', '').replace('-', '')}-{uuid4().hex[:12]}.json"
        )
        receipt_path = TAG_RECEIPT_ROOT / receipt_name
        receipt["receipt_path"] = receipt_path.as_posix()
        _write_json_atomic(os_root / receipt_path, receipt)
        return receipt


def query_first_class_registry(
    root: str | Path,
    *,
    kind: str | None = None,
    domain: str | None = None,
    project: str | None = None,
    query: str | None = None,
    ensure: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    path = os_root / REGISTRY_PATH
    if ensure and not path.is_file():
        refresh_first_class_registry(os_root)
    if not path.is_file():
        raise ValueError(
            f"first-class resource registry is missing; run refresh: {path}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("api_version") != API_VERSION or not isinstance(
        payload.get("resources"), list
    ):
        raise ValueError("first-class resource registry contract is invalid")
    needle = (query or "").strip().lower()
    resources = [
        item
        for item in payload["resources"]
        if (not kind or item.get("kind") == kind)
        and (not domain or (item.get("scope") or {}).get("domain") == domain)
        and (not project or (item.get("scope") or {}).get("project") == project)
        and (
            not needle
            or any(
                needle in str(item.get(field) or "").lower()
                for field in ("title", "summary", "native_id", "kind")
            )
        )
    ]
    diagnostics = [
        item
        for item in payload.get("diagnostics") or []
        if not kind
        or item.get("kind") == kind
        or (
            kind.endswith("_instance")
            and item.get("kind") == kind.removesuffix("_instance")
        )
    ]
    return {
        **payload,
        "query": {"kind": kind, "domain": domain, "project": project, "text": query},
        "resources": resources,
        "diagnostics": diagnostics,
        "summary": {
            **payload["summary"],
            **_diagnostic_summary(diagnostics, returned=len(resources)),
        },
    }
