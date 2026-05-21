"""Customer Agentic OS factory operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .scaffold import (
    AUTOMATION_FILES,
    WORKFLOW_FILES,
    automation_logs_readme,
    automation_scaffold_content,
    create_domain_structure,
    ensure_dir,
    expand_path,
    template_source_dir,
    validate_name,
    write_file_once,
    workflow_examples_readme,
    workflow_runs_readme,
    workflow_scaffold_content,
)
from .validate import ValidationResult, validate_domain


PRIVATE_TERMS = ("genome", "clark", "clarks_consulting", "los", "lenders")
CUSTOMER_ROOT_FILES = ("README.md", "ROUTER.md", "AGENTS.md", "CLAUDE.md", "AGENT.md", "customer.yml")


@dataclass
class CustomerResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)

    def extend(self, other: Any) -> None:
        self.created.extend(getattr(other, "created", []))
        self.skipped.extend(getattr(other, "skipped", []))
        self.updated.extend(getattr(other, "updated", []))

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "skipped": [str(path) for path in self.skipped],
        }


def load_profile(profile_path: str | Path) -> dict[str, Any]:
    path = expand_path(profile_path)
    if not path.is_file():
        raise ValueError(f"profile file is missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("customer profile must be a YAML mapping")
    customer = data.get("customer")
    if not isinstance(customer, dict):
        raise ValueError("customer profile must include a customer mapping")
    return data


def profile_customer(data: dict[str, Any]) -> dict[str, Any]:
    customer = data.get("customer") or {}
    if not isinstance(customer, dict):
        raise ValueError("customer profile must include a customer mapping")
    return customer


def profile_value(data: dict[str, Any], key: str, default: Any = None) -> Any:
    customer = profile_customer(data)
    if key in customer:
        return customer[key]
    return data.get(key, default)


def normalize_profile(customer_slug: str, data: dict[str, Any]) -> dict[str, Any]:
    slug = validate_name(customer_slug, "customer_slug")
    customer = profile_customer(data)
    profile_slug = customer.get("slug")
    if profile_slug and not str(profile_slug).startswith("<"):
        profile_slug = validate_name(str(profile_slug), "customer.slug")
        if profile_slug != slug:
            raise ValueError(f"profile customer.slug {profile_slug!r} does not match {slug!r}")
    customer["slug"] = slug
    customer.setdefault("display_name", slug.replace("_", " ").title())
    customer.setdefault("owner", "Customer Owner")
    customer.setdefault("notion_workspace", "")

    approved_domains = profile_value(data, "approved_domains")
    if not approved_domains:
        approved_domains = [room["id"] for room in data.get("rooms", []) if isinstance(room, dict) and room.get("id")]
    if not approved_domains:
        approved_domains = ["operations"]
    customer["approved_domains"] = [validate_customer_name(str(domain), "approved domain") for domain in approved_domains]

    for list_key in ("source_systems", "default_workflows", "default_automations"):
        customer[list_key] = profile_value(data, list_key, []) or []
    customer["approval_policy"] = profile_value(data, "approval_policy", {}) or {}
    data["customer"] = customer
    data["content_boundary"] = {
        "public_customer_install": True,
        "source_owner_domains_excluded": True,
    }
    return data


def validate_customer_name(value: str, label: str) -> str:
    value = validate_name(value, label)
    lowered = value.lower()
    if lowered in PRIVATE_TERMS:
        raise ValueError(f"{label} uses a private Genome source name: {value!r}")
    return value


def render_customer_readme(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    return f"""# {customer['display_name']} Agentic OS

This install contains the customer-approved operating domains, templates, workflows, automations, run logs, and update contract.

## Customer

| Field | Value |
| --- | --- |
| Slug | `{customer['slug']}` |
| Owner | {customer.get('owner', '')} |
| Notion Workspace | {customer.get('notion_workspace', '')} |

## Approved Domains

{chr(10).join(f'- `{domain}`' for domain in customer['approved_domains'])}

## Update Contract

Updates are additive and non-destructive. Local customer edits are preserved unless an operator explicitly replaces them.
"""


def render_customer_router(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    rows = "\n".join(f"| `{domain}` | `{domain}/ROUTER.md` |" for domain in customer["approved_domains"])
    return f"""# Customer Router

Read this file first, then load only the domain router and context files needed for the request.

## Routing Table

| Domain | Router |
| --- | --- |
{rows}

## Operating Rules

- Use only customer-approved domains and source systems.
- Stop before external writes, customer-visible output, production changes, destructive actions, billing, legal, or credential changes unless approval is explicit.
- Record material runs in the domain run log.
"""


def render_agent_router() -> str:
    return """# Agent Router

Source of truth: `ROUTER.md`.

Load `ROUTER.md`, then follow the relevant domain router and context file before acting.
"""


def render_customer_asset(template_name: str, profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    template = (template_source_dir() / "customer" / template_name).read_text(encoding="utf-8")
    return (
        template.replace("<customer_or_project>", customer["display_name"])
        .replace("<workflow_or_outcome>", f"{customer['display_name']} automation candidate")
        .replace("<input>", "customer-approved input")
        .replace("<output>", "customer-approved output")
        .replace("<criterion>", "Pilot output is reviewed and approved before external use.")
    )


def write_customer_assets(root: Path, profile: dict[str, Any], result: CustomerResult) -> None:
    customer_dir = root / "customer"
    write_file_once(customer_dir / "README.md", "# Customer Operating Package\n", result)
    write_file_once(customer_dir / "handoff-checklist.md", render_customer_asset("customer-handoff-checklist.md", profile), result)
    write_file_once(customer_dir / "automation-fit-matrix.md", render_customer_asset("automation-fit-matrix.md", profile), result)
    write_file_once(customer_dir / "client-automation-brief.md", render_customer_asset("client-automation-brief.md", profile), result)
    write_file_once(
        customer_dir / "update-contract.md",
        """# Customer Update Contract

Updates add missing standards, templates, domains, workflows, and automations. They do not overwrite local edits.

## Operator Review

- Review generated diffs before sharing customer-visible material.
- Keep secrets out of customer docs and run logs.
- Re-run customer validation after updates.
""",
        result,
    )
    shared = root / "shared_factory" / "05-knowledge" / "templates"
    write_file_once(
        shared / "profile" / "customer-os-profile.yml",
        (template_source_dir() / "profile" / "customer-os-profile.yml").read_text(encoding="utf-8"),
        result,
    )
    for filename in ("client-automation-brief.md", "automation-fit-matrix.md", "customer-handoff-checklist.md"):
        write_file_once(shared / "customer" / filename, (template_source_dir() / "customer" / filename).read_text(encoding="utf-8"), result)


def parse_bundle_item(item: Any, default_domain: str) -> tuple[str, str, str]:
    if isinstance(item, str):
        parts = item.split("/")
        if len(parts) == 3:
            domain, lane, name = parts
        elif len(parts) == 2:
            domain = default_domain
            lane, name = parts
        else:
            raise ValueError(f"bundle item must be domain/lane/name or lane/name: {item!r}")
    elif isinstance(item, dict):
        domain = str(item.get("domain") or default_domain)
        lane = str(item.get("lane") or "operations")
        name = str(item.get("name") or item.get("id") or "")
    else:
        raise ValueError(f"unsupported bundle item: {item!r}")
    return (
        validate_customer_name(domain, "bundle domain"),
        validate_name(lane, "bundle lane"),
        validate_name(name, "bundle name"),
    )


def create_customer_domain(root: Path, domain: str) -> CustomerResult:
    result = CustomerResult()
    create_domain_structure(root, domain, result)
    return result


def create_customer_workflow(root: Path, domain: str, lane: str, name: str) -> CustomerResult:
    result = create_customer_domain(root, domain)
    workflow_root = root / domain / "03-workflows" / lane / name
    ensure_dir(workflow_root, result)
    ensure_dir(workflow_root / "examples", result)
    ensure_dir(workflow_root / "runs", result)
    write_file_once(workflow_root / "examples" / "README.md", workflow_examples_readme(domain, lane, name), result)
    write_file_once(workflow_root / "runs" / "README.md", workflow_runs_readme(domain, lane, name), result)
    for filename in WORKFLOW_FILES:
        write_file_once(workflow_root / filename, workflow_scaffold_content(domain, lane, name, filename), result)
    return result


def create_customer_automation(root: Path, domain: str, lane: str, name: str) -> CustomerResult:
    result = create_customer_domain(root, domain)
    automation_root = root / domain / "04-automations" / lane / name
    ensure_dir(automation_root, result)
    ensure_dir(automation_root / "logs", result)
    write_file_once(automation_root / "logs" / "README.md", automation_logs_readme(domain, lane, name), result)
    for filename in AUTOMATION_FILES:
        write_file_once(automation_root / filename, automation_scaffold_content(domain, lane, name, filename), result)
    return result


def apply_customer_profile(root: Path, profile: dict[str, Any], result: CustomerResult) -> None:
    customer = profile_customer(profile)
    for domain in customer["approved_domains"]:
        result.extend(create_customer_domain(root, domain))
    default_domain = customer["approved_domains"][0]
    for item in customer.get("default_workflows", []):
        domain, lane, name = parse_bundle_item(item, default_domain)
        result.extend(create_customer_workflow(root, domain, lane, name))
    for item in customer.get("default_automations", []):
        domain, lane, name = parse_bundle_item(item, default_domain)
        result.extend(create_customer_automation(root, domain, lane, name))


def customer_init(customer_slug: str, profile_path: str | Path, target: str | Path) -> dict[str, Any]:
    profile = normalize_profile(customer_slug, load_profile(profile_path))
    root = expand_path(target)
    result = CustomerResult()
    root.mkdir(parents=True, exist_ok=True)
    write_file_once(root / "README.md", render_customer_readme(profile), result)
    write_file_once(root / "ROUTER.md", render_customer_router(profile), result)
    for filename in ("AGENTS.md", "CLAUDE.md", "AGENT.md"):
        write_file_once(root / filename, render_agent_router(), result)
    write_file_once(root / "customer.yml", yaml.safe_dump(profile, sort_keys=False), result)
    write_customer_assets(root, profile, result)
    apply_customer_profile(root, profile, result)
    return {"root": str(root), "customer": profile_customer(profile)["slug"], **result.as_dict()}


def customer_update(customer_slug: str, root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    profile_path = os_root / "customer.yml"
    if not profile_path.is_file():
        raise ValueError(f"customer.yml is missing: {profile_path}")
    profile = normalize_profile(customer_slug, yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {})
    result = CustomerResult()
    write_customer_assets(os_root, profile, result)
    apply_customer_profile(os_root, profile, result)
    return {"root": str(os_root), "customer": profile_customer(profile)["slug"], **result.as_dict()}


def private_term_warnings(root: Path) -> list[str]:
    warnings = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".yml", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for term in PRIVATE_TERMS:
            if re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text):
                warnings.append(f"private source term {term!r} appears in {path}")
                break
    return warnings


def customer_validate(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    core_errors: list[str] = []
    profile_warnings: list[str] = []
    if not os_root.is_dir():
        return {"root": str(os_root), "ok": False, "core_errors": [f"missing root: {os_root}"], "profile_warnings": []}
    for filename in CUSTOMER_ROOT_FILES:
        if not (os_root / filename).is_file():
            core_errors.append(f"missing customer root file: {os_root / filename}")
    profile_path = os_root / "customer.yml"
    profile: dict[str, Any] = {}
    if profile_path.is_file():
        try:
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            profile = normalize_profile(str(profile_customer(profile).get("slug", "")), profile)
        except (ValueError, yaml.YAMLError) as exc:
            core_errors.append(f"invalid customer profile: {exc}")
    if profile:
        customer = profile_customer(profile)
        if not customer.get("notion_workspace"):
            profile_warnings.append("customer.notion_workspace is empty")
        if not customer.get("source_systems"):
            profile_warnings.append("customer.source_systems is empty")
        if not customer.get("default_workflows"):
            profile_warnings.append("customer.default_workflows is empty")
        if not customer.get("default_automations"):
            profile_warnings.append("customer.default_automations is empty")
        domain_result = ValidationResult(root=os_root)
        for domain in customer["approved_domains"]:
            validate_domain(os_root / domain, domain_result)
        core_errors.extend(domain_result.errors)
        profile_warnings.extend(domain_result.warnings)
    profile_warnings.extend(private_term_warnings(os_root))
    return {"root": str(os_root), "ok": not core_errors, "core_errors": core_errors, "profile_warnings": profile_warnings}


def format_customer_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
