"""Document routing configuration for Agentic OS."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

import yaml

from .scaffold import (
    ScaffoldResult,
    domain_path,
    expand_path,
    template_source_dir,
    titleize_name,
    validate_name,
    write_file_once,
)
from .work_lifecycle import find_work_item_root


DOC_CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/doc-config.yml")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def default_doc_config() -> dict[str, Any]:
    return _load_yaml(template_source_dir() / "runtime" / "doc-config.yml")


def global_doc_config_path(root: str | Path) -> Path:
    return expand_path(root) / DOC_CONFIG_RELATIVE_PATH


def project_doc_config_path(root: str | Path, domain: str, project: str) -> Path:
    domain = validate_name(domain, "domain")
    project = validate_name(project, "project")
    return domain_path(expand_path(root), domain) / "02-projects" / project / "config" / "doc-config.yml"


def ensure_doc_config(root: str | Path, *, domain: str | None = None, project: str | None = None) -> ScaffoldResult:
    result = ScaffoldResult()
    source = template_source_dir() / "runtime" / "doc-config.yml"
    if domain and project:
        destination = project_doc_config_path(root, domain, project)
    else:
        destination = global_doc_config_path(root)
    write_file_once(destination, source.read_text(encoding="utf-8"), result)
    return result


def load_doc_config(root: str | Path, *, domain: str | None = None, project: str | None = None) -> dict[str, Any]:
    config = default_doc_config()
    config = _deep_merge(config, _load_yaml(global_doc_config_path(root)))
    if domain and project:
        config = _deep_merge(config, _load_yaml(project_doc_config_path(root, domain, project)))
    return config


def enabled_search_methods(config: dict[str, Any]) -> list[dict[str, Any]]:
    methods = config.get("search_methods") or {}
    rows = []
    for method_id, method in methods.items():
        if not isinstance(method, dict) or not method.get("enabled", False):
            continue
        rows.append({"id": method_id, **method})
    return sorted(rows, key=lambda item: (int(item.get("priority") or 100), str(item.get("id") or "")))


def disabled_search_methods(config: dict[str, Any]) -> list[str]:
    methods = config.get("search_methods") or {}
    return sorted(
        str(method_id)
        for method_id, method in methods.items()
        if isinstance(method, dict) and not method.get("enabled", False)
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_]+", value.lower()) if token}


def infer_work_area(config: dict[str, Any], request: str) -> tuple[dict[str, Any] | None, int]:
    work_areas = ((config.get("routing") or {}).get("work_areas") or [])
    request_tokens = _tokens(request)
    best: tuple[dict[str, Any] | None, int] = (None, 0)
    for area in work_areas:
        if not isinstance(area, dict):
            continue
        values = [
            str(area.get("id") or ""),
            str(area.get("title") or ""),
            str(area.get("domain") or ""),
            str(area.get("project") or ""),
            *[str(alias) for alias in area.get("aliases") or []],
            *[str(keyword) for keyword in area.get("keywords") or []],
        ]
        area_tokens: set[str] = set()
        for value in values:
            area_tokens.update(_tokens(value))
        score = len(request_tokens & area_tokens)
        if score > best[1]:
            best = (area, score)
    return best


def bucket_plan(config: dict[str, Any], *, questions_present: bool = False) -> list[dict[str, Any]]:
    buckets = config.get("buckets") or {}
    rows = []
    for bucket in buckets.get("default") or []:
        if isinstance(bucket, dict):
            rows.append({**bucket, "reason": "default"})
    questions = buckets.get("questions") or {}
    if isinstance(questions, dict) and questions.get("enabled", True) and questions_present:
        rows.append({**questions, "reason": "questions_present"})
    for bucket in buckets.get("optional") or []:
        if isinstance(bucket, dict) and bucket.get("enabled", False):
            rows.append({**bucket, "reason": "optional_enabled"})
    return rows


def doc_config_doctor(root: str | Path, *, domain: str | None = None, project: str | None = None) -> dict[str, Any]:
    config = load_doc_config(root, domain=domain, project=project)
    findings = []
    paths = [str(global_doc_config_path(root))]
    if domain and project:
        paths.append(str(project_doc_config_path(root, domain, project)))

    if int(config.get("schema_version") or 0) != 1:
        findings.append({"severity": "blocker", "message": "doc-config.yml must use schema_version: 1"})

    methods = config.get("search_methods")
    if not isinstance(methods, dict) or not enabled_search_methods(config):
        findings.append({"severity": "blocker", "message": "at least one search method must be enabled"})

    seen_titles: set[str] = set()
    for bucket in bucket_plan(config, questions_present=True):
        title = str(bucket.get("title") or "")
        if not title:
            findings.append({"severity": "warning", "message": "bucket is missing a title"})
            continue
        if title in seen_titles:
            findings.append({"severity": "warning", "message": f"duplicate bucket title: {title}"})
        seen_titles.add(title)

    workspace = ((config.get("notion") or {}).get("workspace") or {}).get("expected")
    if workspace != "Genome's Notion":
        findings.append({"severity": "warning", "message": "default Notion workspace should be Genome's Notion unless explicitly overridden"})

    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "paths": paths,
        "enabled_search_methods": [item["id"] for item in enabled_search_methods(config)],
        "disabled_search_methods": disabled_search_methods(config),
        "findings": findings,
    }


def build_doc_route_plan(
    root: str | Path,
    *,
    request: str,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    target_kind: str = "spec",
    questions_present: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    config = load_doc_config(os_root, domain=domain, project=project)
    routing = config.get("routing") or {}
    namespace = routing.get("feature_namespace") or "Specs"
    spec_like_target = target_kind in {"feature", "spec"}
    inferred_area, inferred_score = infer_work_area(config, request)
    if not domain and inferred_area and inferred_area.get("domain"):
        domain = str(inferred_area["domain"])
    if not project and inferred_area and inferred_area.get("project"):
        inferred_project = str(inferred_area["project"])
        project = inferred_project or None
    project_label = titleize_name(project) if project else None
    filesystem_destination = None
    notion_path = None

    if domain and project:
        project_root = domain_path(os_root, validate_name(domain, "domain")) / "02-projects" / validate_name(project, "project")
        if work_item:
            found = find_work_item_root(project_root, work_item)
            filesystem_destination = str(found or project_root / "work-items" / "02-active" / work_item)
        elif spec_like_target:
            filesystem_destination = str(project_root / "work-items" / "02-active")
        else:
            filesystem_destination = str(project_root)
        notion_path = " -> ".join(
            part
            for part in (
                inferred_area.get("notion_path") if inferred_area and inferred_area.get("notion_path") else "Projects",
                None if inferred_area and inferred_area.get("notion_path") else project_label,
                namespace if spec_like_target else None,
                work_item,
            )
            if part
        )

    return {
        "root": str(os_root),
        "request": request,
        "source_of_truth": routing.get("source_of_truth") or "filesystem",
        "target_kind": target_kind,
        "destination": {
            "work_area": inferred_area.get("id") if inferred_area else None,
            "work_area_confidence": "high" if inferred_score >= 2 else "low" if inferred_area else "none",
            "domain": domain,
            "project": project,
            "work_item": work_item,
            "filesystem": filesystem_destination,
            "notion_path": notion_path,
        },
        "routing_precedence": routing.get("precedence") or [],
        "filesystem_mirror": config.get("filesystem_mirror") or {},
        "buckets": bucket_plan(config, questions_present=questions_present),
        "search_methods": {
            "enabled": enabled_search_methods(config),
            "disabled": disabled_search_methods(config),
        },
        "analytics": config.get("analytics") or {},
        "notion": config.get("notion") or {},
        "next_actions": [
            "Load the routed Agentic OS layer before writing.",
            "Use filesystem/work-item files as source of truth.",
            "Verify Genome's Notion before Notion writes.",
            "Search for existing destinations before creating duplicates when search_existing is enabled.",
        ],
    }
