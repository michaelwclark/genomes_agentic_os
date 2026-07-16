"""Materialized first-class Agentic OS resource registry.

Refreshes may inspect the installed tree. Normal reads never do: they load one
atomic JSON snapshot from ``harness/registries/first-class-resources.json``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .operator_resources import query_operator_resources
from .scaffold import expand_path


API_VERSION = "first-class-resource-registry/v1"
REGISTRY_PATH = Path("harness/registries/first-class-resources.json")
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


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    heading = re.search(r"^#\s+(?:OSProgram|InstanceOSProgram|Automation|Workflow)?\s*:?\s*(.+)$", body, re.M)
    purpose = re.search(r"^##\s+(?:Purpose|Summary)\s*$\n+(.+?)(?=\n##\s|\Z)", body, re.M | re.S)
    title = heading.group(1).strip() if heading else fallback.replace("_", " ").replace("-", " ").title()
    summary = " ".join(line.strip() for line in purpose.group(1).splitlines() if line.strip())[:600] if purpose else ""
    return title, summary


def _entry(
    *, kind: str, resource_id: str, native_id: str, title: str, summary: str,
    source: str, generated_at: str, domain: str | None = None,
    project: str | None = None, subtype: str | None = None,
    health_state: str = "unknown", health_summary: str = "No runtime health assertion is available.",
    tags: Iterable[str | None] = (), source_updated_at: str | None = None,
) -> dict[str, Any]:
    return {
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
        "health": {"state": health_state, "summary": health_summary},
        "tags": sorted({tag for tag in tags if tag}),
    }


def _operator_entries(root: Path, kind: str, generated_at: str, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        envelope = query_operator_resources(root, kind)
    except Exception as exc:  # malformed resources remain visible as a refresh diagnostic
        diagnostics.append({"severity": "error", "code": f"{kind}_projection_failed", "source": "operator-resource-query/v1", "message": f"{type(exc).__name__}: {exc}", "kind": kind})
        return []
    diagnostics.extend({**item, "kind": kind} for item in (envelope.get("diagnostics") or []))
    result: list[dict[str, Any]] = []
    for resource in envelope.get("resources") or []:
        resource_type = str(resource.get("resource_type") or "definition")
        mapped_kind = kind if resource_type == "definition" else f"{kind}_instance"
        identity = resource.get("definition") or resource.get("instance") or resource.get("tracking") or {}
        if not isinstance(identity, dict):
            identity = {}
        source = _relative_source(root, identity.get("path") or identity.get("cwd") or REGISTRY_PATH)
        domain = identity.get("domain") if isinstance(identity.get("domain"), str) else None
        project = identity.get("project") if isinstance(identity.get("project"), str) else None
        health = resource.get("health") if isinstance(resource.get("health"), dict) else {}
        status = str(health.get("status") or "unknown").lower()
        health_state = "unhealthy" if status in {"failed", "failure", "error", "unhealthy"} else "degraded" if status in {"stale", "partial", "degraded"} else "healthy" if status in {"healthy", "success", "active", "done", "queued"} else "unknown"
        result.append(_entry(
            kind=mapped_kind,
            resource_id=str(resource["id"]),
            native_id=str(resource["id"]),
            title=str(identity.get("display_name") or identity.get("name") or resource["id"]),
            summary=str(identity.get("summary") or f"{mapped_kind.replace('_', ' ')} projected by Agentic OS."),
            source=source,
            generated_at=generated_at,
            domain=domain,
            project=project,
            subtype=resource_type,
            health_state=health_state,
            health_summary=f"Evidence-backed status: {status}. Process and host liveness were not observed.",
            tags=(mapped_kind, resource_type, status),
            source_updated_at=health.get("observed_at") if isinstance(health.get("observed_at"), str) else None,
        ))
    return result


def _document_entries(root: Path, generated_at: str, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = {"workflow.md": "workflow_instance", "RULES.md": "rule"}
    result: list[dict[str, Any]] = []
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in SKIP_PARTS and not name.startswith(".")]
        for filename in sorted(set(filenames).intersection(patterns)):
            base_kind = patterns[filename]
            path = Path(current) / filename
            relative = path.relative_to(root)
            relative_ref = relative.as_posix()
            kind = base_kind
            if base_kind == "workflow_instance" and relative_ref.startswith("harness/shared_factory/"):
                kind = "workflow"
            try:
                native_id = path.parent.name if kind != "rule" else ":".join(relative.parts[:-1]) or "root"
                title, summary = _summary_from_markdown(path, native_id)
                domain, project = _scope(relative_ref)
                result.append(_entry(
                    kind=kind,
                    resource_id=_stable_id(kind, relative_ref),
                    native_id=native_id,
                    title=title,
                    summary=summary,
                    source=relative_ref,
                    generated_at=generated_at,
                    domain=domain,
                    project=project,
                    subtype="rule_document" if kind == "rule" else ("definition" if kind == "workflow" else "instance"),
                    health_summary="Present in the canonical Agentic OS filesystem.",
                    tags=(kind, domain, project),
                    source_updated_at=_iso(datetime.fromtimestamp(path.stat().st_mtime, UTC)),
                ))
            except OSError as exc:
                diagnostics.append({"severity": "warning", "code": "resource_read_failed", "source": relative_ref, "message": str(exc), "kind": base_kind})
    return result


def _registry_entries(root: Path, generated_at: str, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
                domain, project = _scope(relative_ref)
                domain = record.get("domain") if isinstance(record.get("domain"), str) else scope.get("domain") if isinstance(scope.get("domain"), str) else domain
                project = record.get("project") if isinstance(record.get("project"), str) else scope.get("project") if isinstance(scope.get("project"), str) else project
                declared_source = _relative_source(root, record.get("source") or relative_ref)
                source = declared_source if (root / declared_source).exists() else relative_ref
                title = str(record.get("name") or record.get("command") or native_id.replace("-", " ").title())
                identity = f"typed:definition:{native_id}" if relative_ref == "harness/registries/report-definitions.yml" else f"{relative_ref}:{native_id}"
                result.append(_entry(
                    kind=kind,
                    resource_id=_stable_id(kind, identity),
                    native_id=native_id,
                    title=title,
                    summary=str(record.get("description") or record.get("summary") or ""),
                    source=source,
                    generated_at=generated_at,
                    domain=domain,
                    project=project,
                    subtype="registry_entry" if kind != "report" else "definition",
                    health_state="healthy",
                    health_summary="Present in the canonical Agentic OS registry.",
                    tags=(kind, domain, project),
                    source_updated_at=_iso(datetime.fromtimestamp(path.stat().st_mtime, UTC)),
                ))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            diagnostics.append({"severity": "warning", "code": f"{kind}_registry_unavailable", "source": relative_ref, "message": f"{type(exc).__name__}: {exc}", "kind": kind})
    return result


def refresh_first_class_registry(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
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
    for resource in sorted(resources, key=lambda item: (item["kind"], item["id"], item["source"])):
        unique.setdefault(resource["id"], resource)
    resources = list(unique.values())
    fingerprint = hashlib.sha256(json.dumps(resources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {
        "api_version": API_VERSION,
        "generated_at": generated_at,
        "root": str(os_root),
        "registry_path": str(REGISTRY_PATH),
        "fingerprint": fingerprint,
        "resources": resources,
        "diagnostics": diagnostics,
        "summary": {
            "returned": len(resources),
            "by_kind": {kind: sum(item["kind"] == kind for item in resources) for kind in RESOURCE_KINDS},
            "errors": sum(item.get("severity") == "error" for item in diagnostics),
            "warnings": sum(item.get("severity") == "warning" for item in diagnostics),
        },
    }
    target = os_root / REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


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
        raise ValueError(f"first-class resource registry is missing; run refresh: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("api_version") != API_VERSION or not isinstance(payload.get("resources"), list):
        raise ValueError("first-class resource registry contract is invalid")
    needle = (query or "").strip().lower()
    resources = [
        item for item in payload["resources"]
        if (not kind or item.get("kind") == kind)
        and (not domain or (item.get("scope") or {}).get("domain") == domain)
        and (not project or (item.get("scope") or {}).get("project") == project)
        and (not needle or any(needle in str(item.get(field) or "").lower() for field in ("title", "summary", "native_id", "kind")))
    ]
    diagnostics = [
        item for item in payload.get("diagnostics") or []
        if not kind or item.get("kind") == kind or (kind.endswith("_instance") and item.get("kind") == kind.removesuffix("_instance"))
    ]
    return {
        **payload,
        "query": {"kind": kind, "domain": domain, "project": project, "text": query},
        "resources": resources,
        "diagnostics": diagnostics,
        "summary": {
            **payload["summary"],
            "returned": len(resources),
            "errors": sum(item.get("severity") == "error" for item in diagnostics),
            "warnings": sum(item.get("severity") == "warning" for item in diagnostics),
        },
    }
