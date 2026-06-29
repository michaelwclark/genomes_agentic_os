"""Configurable document-routing planner for Agentic OS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import shutil

import yaml

from .scaffold import expand_path


CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/doc-config.yml")
TEMPLATE_RELATIVE_PATH = Path("templates/runtime/doc-config.yml")


@dataclass(frozen=True)
class DocConfigBucket:
    id: str
    title: str
    create_policy: str
    aliases: list[str]
    purpose: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def doc_config_path(root: str | Path) -> Path:
    return expand_path(root) / CONFIG_RELATIVE_PATH


def doc_config_template_path() -> Path:
    return _repo_root() / TEMPLATE_RELATIVE_PATH


def load_doc_config(root: str | Path) -> tuple[Path, dict[str, Any]]:
    path = doc_config_path(root)
    config = _load_yaml(path)
    if config:
        return path, config
    template = doc_config_template_path()
    return path, _load_yaml(template)


def init_doc_config(root: str | Path, *, domain: str | None = None, project: str | None = None) -> dict[str, Any]:
    path = doc_config_path(root)
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
    request_l = request.lower()
    for area in areas:
        terms = []
        for key in ("aliases", "keywords"):
            values = area.get(key, [])
            if isinstance(values, list):
                terms.extend(str(value).lower() for value in values)
        if any(term and term in request_l for term in terms):
            return area
    return areas[0] if areas else None


def build_doc_config_plan(
    root: str | Path,
    *,
    request: str,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    questions_present: bool = False,
) -> dict[str, Any]:
    path, config = load_doc_config(root)
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    area = _infer_area(config, request, domain, project)
    destination_domain = domain or (area or {}).get("domain")
    destination_project = project or (area or {}).get("project")
    namespace = str(routing.get("feature_namespace") or "Specs")
    request_hash = hashlib.sha256(request.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(expand_path(root)),
        "config_path": str(path),
        "request_hash": request_hash,
        "request": request,
        "source_of_truth": routing.get("source_of_truth", config.get("source_of_truth", "filesystem")),
        "destination": {
            "domain": destination_domain,
            "project": destination_project,
            "work_item": work_item,
            "filesystem_bucket": "work-items" if destination_project else "01-inbox",
            "notion_path": (area or {}).get("notion_path"),
            "notion_namespace": namespace,
            "compatibility_namespaces": routing.get("compatibility_namespaces", ["Features"]),
        },
        "buckets": _plan_buckets(config, questions_present=questions_present),
        "search_methods": _enabled_search_methods(config),
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
    }


def format_doc_config_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
