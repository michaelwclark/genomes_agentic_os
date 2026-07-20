"""Configurable document-routing planner for Agentic OS."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import re
import shutil

import yaml

from .scaffold import domain_path, expand_path, repo_root, titleize_name, validate_name


CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/doc-config.yml")
TEMPLATE_RELATIVE_PATH = Path("templates/runtime/doc-config.yml")


@dataclass(frozen=True)
class DocConfigBucket:
    id: str
    title: str
    create_policy: str
    aliases: list[str]
    purpose: str


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def doc_config_path(root: str | Path) -> Path:
    return expand_path(root) / CONFIG_RELATIVE_PATH


def project_doc_config_path(root: str | Path, domain: str, project: str) -> Path:
    domain = validate_name(domain, "domain")
    project = validate_name(project, "project")
    return domain_path(expand_path(root), domain) / "02-projects" / project / "config" / "doc-config.yml"


def doc_config_template_path() -> Path:
    return repo_root() / TEMPLATE_RELATIVE_PATH


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_doc_config(root: str | Path, *, domain: str | None = None, project: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = doc_config_path(root)
    config = _deep_merge(_load_yaml(doc_config_template_path()), _load_yaml(path))
    if domain and project:
        project_path = project_doc_config_path(root, domain, project)
        if project_path.is_file():
            config = _deep_merge(config, _load_yaml(project_path))
            path = project_path
    return path, config


def init_doc_config(root: str | Path, *, domain: str | None = None, project: str | None = None) -> dict[str, Any]:
    path = project_doc_config_path(root, domain, project) if domain and project else doc_config_path(root)
    template = doc_config_template_path()
    if not template.is_file():
        raise ValueError(f"doc-config template not found: {template}")
    if path.exists():
        action = "exists"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, path)
        action = "created"
    return {
        "ok": True,
        "action": action,
        "path": str(path),
        "domain": domain,
        "project": project,
    }


def _enabled_search_methods(config: dict[str, Any]) -> list[dict[str, Any]]:
    methods = config.get("search_methods") if isinstance(config.get("search_methods"), dict) else {}
    rows = []
    for method_id, method in methods.items():
        if not isinstance(method, dict) or not method.get("enabled", False):
            continue
        rows.append(
            {
                "id": str(method_id),
                "priority": int(method.get("priority", 999)),
                "applies_to": method.get("applies_to", []),
                "workspace_verification_required": bool(method.get("workspace_verification_required", False)),
                "description": method.get("description", ""),
            }
        )
    return sorted(rows, key=lambda row: (row["priority"], row["id"]))


def _disabled_search_methods(config: dict[str, Any]) -> list[str]:
    methods = config.get("search_methods") if isinstance(config.get("search_methods"), dict) else {}
    return sorted(
        str(method_id)
        for method_id, method in methods.items()
        if isinstance(method, dict) and not method.get("enabled", False)
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_]+", value.lower()) if token}


def _bucket_from_mapping(mapping: dict[str, Any]) -> DocConfigBucket:
    return DocConfigBucket(
        id=str(mapping.get("id", "")),
        title=str(mapping.get("title", "")),
        create_policy=str(mapping.get("create_policy", "")),
        aliases=[str(alias) for alias in mapping.get("aliases", []) or []],
        purpose=str(mapping.get("purpose", "")),
    )


def _plan_buckets(config: dict[str, Any], *, questions_present: bool) -> list[dict[str, Any]]:
    buckets_config = config.get("buckets") if isinstance(config.get("buckets"), dict) else {}
    rows: list[DocConfigBucket] = []
    for item in buckets_config.get("default", []) or []:
        if isinstance(item, dict):
            rows.append(_bucket_from_mapping(item))
    questions = buckets_config.get("questions")
    if questions_present and isinstance(questions, dict) and questions.get("enabled", True):
        rows.append(_bucket_from_mapping(questions))
    return [
        {
            "id": bucket.id,
            "title": bucket.title,
            "aliases": bucket.aliases,
            "create_policy": bucket.create_policy,
            "purpose": bucket.purpose,
        }
        for bucket in rows
        if bucket.id and bucket.title
    ]


def _work_areas(config: dict[str, Any]) -> list[dict[str, Any]]:
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    areas = routing.get("work_areas", [])
    return [area for area in areas if isinstance(area, dict)]


def _infer_area(config: dict[str, Any], request: str, domain: str | None, project: str | None) -> dict[str, Any] | None:
    areas = _work_areas(config)
    if domain or project:
        for area in areas:
            if domain and area.get("domain") != domain:
                continue
            if project and area.get("project") != project:
                continue
            return area
    request_tokens = _tokens(request)
    best_area = None
    best_score = 0
    for area in areas:
        terms = [
            str(area.get("id") or ""),
            str(area.get("title") or ""),
            str(area.get("domain") or ""),
            str(area.get("project") or ""),
        ]
        for key in ("aliases", "keywords"):
            values = area.get(key, [])
            if isinstance(values, list):
                terms.extend(str(value) for value in values)
        area_tokens: set[str] = set()
        for term in terms:
            area_tokens.update(_tokens(term))
        score = len(request_tokens & area_tokens)
        if score > best_score:
            best_area = area
            best_score = score
    return best_area


def _notion_path(base: str | None, namespace: str, work_item: str | None, *, include_namespace: bool = True) -> str | None:
    if not base:
        return None
    parts = [base]
    if include_namespace:
        parts.append(namespace)
    if work_item:
        parts.append(work_item)
    return " -> ".join(part for part in parts if part)


def build_doc_config_plan(
    root: str | Path,
    *,
    request: str,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    questions_present: bool = False,
) -> dict[str, Any]:
    path, config = load_doc_config(root, domain=domain, project=project)
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    area = _infer_area(config, request, domain, project)
    destination_domain = domain or (area or {}).get("domain")
    destination_project = project or (area or {}).get("project")
    namespace = str(routing.get("feature_namespace") or "Specs")
    filesystem_destination = None
    if destination_domain and destination_project:
        project_root = domain_path(expand_path(root), validate_name(str(destination_domain), "domain")) / "02-projects" / validate_name(str(destination_project), "project")
        filesystem_destination = str(project_root / "work-items" / "02-active" / work_item) if work_item else str(project_root / "work-items" / "02-active")
    base_notion_path = (area or {}).get("notion_path")
    if not base_notion_path and destination_project:
        base_notion_path = f"Projects -> {titleize_name(str(destination_project))}"
    request_hash = hashlib.sha256(request.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(expand_path(root)),
        "config_path": str(path),
        "request_hash": request_hash,
        "request": request,
        "source_of_truth": routing.get("source_of_truth", config.get("source_of_truth", "filesystem")),
        "target_kind": "spec",
        "destination": {
            "work_area": (area or {}).get("id"),
            "work_area_confidence": "high" if area else "none",
            "domain": destination_domain,
            "project": destination_project,
            "work_item": work_item,
            "filesystem": filesystem_destination,
            "filesystem_bucket": "work-items" if destination_project else "01-inbox",
            "notion_path": _notion_path(base_notion_path, namespace, work_item),
            "notion_namespace": namespace,
            "compatibility_namespaces": routing.get("compatibility_namespaces", ["Features"]),
        },
        "filesystem_mirror": config.get("filesystem_mirror") or {},
        "buckets": _plan_buckets(config, questions_present=questions_present),
        "search_methods": {
            "enabled": _enabled_search_methods(config),
            "disabled": _disabled_search_methods(config),
        },
        "notion": config.get("notion") or {},
        "notion_workspace": ((config.get("notion") or {}).get("workspace") or {}).get("expected"),
        "workspace_verification_required": bool(routing.get("external_writes_require_workspace_verification", True)),
        "next_actions": [
            "Search existing filesystem and verified Notion destinations before creating anything.",
            "Keep filesystem/work-item files canonical; use Notion as the operator projection.",
        ],
    }


def doc_config_doctor(root: str | Path) -> dict[str, Any]:
    path, config = load_doc_config(root)
    findings: list[dict[str, str]] = []
    if not path.is_file():
        findings.append({"severity": "blocker", "path": str(path), "message": "installed doc-config.yml is missing"})
    for key in ("schema_version", "routing", "buckets", "search_methods"):
        if key not in config:
            findings.append({"severity": "blocker", "path": str(path), "message": f"missing required key: {key}"})
    methods = _enabled_search_methods(config)
    if not methods:
        findings.append({"severity": "blocker", "path": str(path), "message": "at least one search method must be enabled"})
    method_ids = {method["id"] for method in methods}
    required_methods = {"config", "markdown", "ripgrep", "filesystem", "notion", "context_mode", "memory"}
    for method_id in sorted(required_methods - method_ids):
        findings.append({"severity": "blocker", "path": str(path), "message": f"search method disabled or missing: {method_id}"})
    plan = build_doc_config_plan(root, request="doctor questions check", questions_present=True)
    if "QUESTIONS" not in {bucket["title"] for bucket in plan["buckets"]}:
        findings.append({"severity": "blocker", "path": str(path), "message": "QUESTIONS bucket missing when questions are present"})
    if "PLAN" not in {bucket["title"] for bucket in plan["buckets"]}:
        findings.append({"severity": "blocker", "path": str(path), "message": "PLAN bucket missing"})
    plan_bucket = next((bucket for bucket in plan["buckets"] if bucket["title"] == "PLAN"), None)
    if plan_bucket and "PLANS" not in set(plan_bucket.get("aliases") or []):
        findings.append({"severity": "blocker", "path": str(path), "message": "PLAN bucket must include PLANS alias"})
    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "root": str(expand_path(root)),
        "config_path": str(path),
        "findings": findings,
        "enabled_search_methods": [method["id"] for method in methods],
        "disabled_search_methods": _disabled_search_methods(config),
    }


def format_doc_config_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
