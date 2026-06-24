"""Filesystem-to-Notion sync planning with workspace guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path, shared_factory_path


MAPPING_PATH = ".notion-sync/mapping.yml"
BOOTSTRAP_MANIFEST_PATH = ".notion-control-plane/manifest.yml"
ACTIVE_WORK_SYNC_MANIFEST_PATH = ".notion-active-work-sync/last-run.yml"
GENOME_NOTION = "Genome's Notion"
BLOCKED_WORKSPACE_MARKERS = ("michael clark", "michaelwclark", "personal notion")

ACTIVE_WORK_REQUIRED_PROPERTIES: dict[str, str] = {
    "Name": "title",
    "Type": "select",
    "Status": "select",
    "Domain": "rich_text",
    "Project": "rich_text",
    "Active Link": "rich_text",
    "Source Path": "rich_text",
    "Last Synced": "date",
}


@dataclass(frozen=True)
class SyncObject:
    kind: str
    key: str
    title: str
    path: Path

    @property
    def fingerprint(self) -> str:
        if self.path.is_file():
            payload = self.path.read_bytes()
        else:
            payload = str(self.path).encode()
        return hashlib.sha256(payload).hexdigest()

    def record_key(self) -> str:
        return f"{self.kind}:{self.key}"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def target_workspace(root: Path) -> str:
    customer_profile = load_yaml(root / "customer.yml")
    if customer_profile:
        customer = customer_profile.get("customer") or {}
        workspace = customer.get("notion_workspace")
        if workspace:
            return str(workspace)
    return GENOME_NOTION


def load_mapping(root: Path) -> dict[str, Any]:
    mapping = load_yaml(root / MAPPING_PATH)
    mapping.setdefault("records", {})
    return mapping


def write_mapping(root: Path, mapping: dict[str, Any]) -> None:
    path = root / MAPPING_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")


def notion_id_for(record_key: str) -> str:
    digest = hashlib.sha256(record_key.encode()).hexdigest()[:16]
    return f"local-notion-{digest}"


def domain_dirs(root: Path) -> list[Path]:
    domains = [path for path in root.iterdir() if path.is_dir() and (path / "domain.yml").is_file()]
    shared = shared_factory_path(root)
    if (shared / "domain.yml").is_file():
        domains.append(shared)
    return sorted(domains)


def discover_sync_objects(root: str | Path) -> list[SyncObject]:
    os_root = expand_path(root)
    objects: list[SyncObject] = []
    for domain_root in domain_dirs(os_root):
        domain = domain_root.name
        objects.append(SyncObject("domain", domain, domain, domain_root / "domain.yml"))
        active_work = domain_root / "00-control-plane" / "active-work.md"
        if active_work.is_file():
            objects.append(SyncObject("active_work", domain, f"{domain} active work", active_work))
        approvals = domain_root / "00-control-plane" / "approval-rules.md"
        if approvals.is_file():
            objects.append(SyncObject("approvals", domain, f"{domain} approvals", approvals))
        decisions = domain_root / "00-control-plane" / "decisions.md"
        if decisions.is_file():
            objects.append(SyncObject("decisions", domain, f"{domain} decisions", decisions))
        state_index = domain_root / "00-control-plane" / "state-index.md"
        if state_index.is_file():
            objects.append(SyncObject("state_index", domain, f"{domain} state index", state_index))
        metrics = domain_root / "07-metrics" / "scorecards.md"
        if metrics.is_file():
            objects.append(SyncObject("metrics", domain, f"{domain} metrics", metrics))

        for project in sorted((domain_root / "02-projects").glob("*/project.yml")):
            key = f"{domain}/{project.parent.name}"
            objects.append(SyncObject("project", key, project.parent.name, project))
        for workflow in sorted((domain_root / "03-workflows").glob("*/*/workflow.md")):
            key = f"{domain}/{workflow.parent.parent.name}/{workflow.parent.name}"
            objects.append(SyncObject("workflow", key, workflow.parent.name, workflow))
        for automation in sorted((domain_root / "04-automations").glob("*/*/automation.md")):
            key = f"{domain}/{automation.parent.parent.name}/{automation.parent.name}"
            objects.append(SyncObject("automation", key, automation.parent.name, automation))
        for run_log in sorted((domain_root / "06-runs-and-logs" / "runs").glob("*/run-log.md")):
            key = f"{domain}/{run_log.parent.name}"
            objects.append(SyncObject("run", key, run_log.parent.name, run_log))
    return objects


def build_sync_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    mapping = load_mapping(os_root)
    records = mapping.get("records", {})
    actions = []
    for item in discover_sync_objects(os_root):
        existing = records.get(item.record_key())
        fingerprint = item.fingerprint
        if not existing:
            action = "create"
        elif existing.get("fingerprint") != fingerprint:
            action = "update"
        else:
            action = "no-op"
        actions.append(
            {
                "action": action,
                "kind": item.kind,
                "key": item.key,
                "title": item.title,
                "path": str(item.path),
                "record_key": item.record_key(),
                "notion_id": existing.get("notion_id") if existing else None,
                "fingerprint": fingerprint,
            }
        )
    return {
        "root": str(os_root),
        "workspace": target_workspace(os_root),
        "mapping_path": str(os_root / MAPPING_PATH),
        "actions": actions,
    }


def verify_workspace(root: Path, verified_workspace: str | None) -> str:
    expected = target_workspace(root)
    if not verified_workspace:
        raise ValueError(f"cannot apply Notion sync without verified workspace: expected {expected!r}")
    lowered = verified_workspace.lower()
    if any(marker in lowered for marker in BLOCKED_WORKSPACE_MARKERS):
        raise ValueError("refusing Notion write: verified workspace appears to be Michael Clark's personal Notion")
    if verified_workspace != expected:
        raise ValueError(f"verified workspace {verified_workspace!r} does not match expected workspace {expected!r}")
    return expected


def apply_sync_plan(root: str | Path, *, verified_workspace: str | None) -> dict[str, Any]:
    os_root = expand_path(root)
    workspace = verify_workspace(os_root, verified_workspace)
    plan = build_sync_plan(os_root)
    mapping = load_mapping(os_root)
    mapping["workspace"] = workspace
    mapping["updated_at"] = datetime.now(timezone.utc).isoformat()
    records = mapping.setdefault("records", {})
    applied = []
    for action in plan["actions"]:
        if action["action"] == "no-op":
            applied.append({**action, "applied": False})
            continue
        record_key = action["record_key"]
        existing = records.get(record_key, {})
        records[record_key] = {
            "kind": action["kind"],
            "key": action["key"],
            "title": action["title"],
            "path": action["path"],
            "notion_id": existing.get("notion_id") or notion_id_for(record_key),
            "fingerprint": action["fingerprint"],
        }
        applied.append({**action, "notion_id": records[record_key]["notion_id"], "applied": True})
    write_mapping(os_root, mapping)
    return {
        "root": str(os_root),
        "workspace": workspace,
        "mapping_path": str(os_root / MAPPING_PATH),
        "actions": applied,
    }


def format_sync_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


def _active_index_path(os_root: Path) -> Path:
    return os_root / "00-control-plane" / "active" / "index.yml"


def _load_active_index(os_root: Path) -> dict[str, Any]:
    path = _active_index_path(os_root)
    if not path.is_file():
        raise ValueError(f"active index is missing; run `agentic-os project work-item sync-active --root {os_root}` first")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"active index is not a mapping: {path}")
    return data


def _active_row_name(kind: str, entry: dict[str, Any]) -> str:
    if kind == "automation":
        return str(entry.get("id") or "")
    project = str(entry.get("project") or "")
    item_id = str(entry.get("id") or "")
    return f"{project} / {item_id}" if project else item_id


def build_active_work_sync_plan(root: str | Path, *, database_id: str | None = None) -> dict[str, Any]:
    """Build a deterministic row plan for the live ``OS Active Work`` database."""
    os_root = expand_path(root)
    index = _load_active_index(os_root)
    rows: list[dict[str, Any]] = []
    for kind, source_key, notion_type, status_default in (
        ("work_item", "work_items", "Work Item", None),
        ("worktree", "worktrees", "Worktree", "active"),
        ("automation", "automations", "Automation", None),
    ):
        for entry in index.get(source_key) or []:
            if not isinstance(entry, dict):
                continue
            source_path = entry.get("target") or entry.get("path") or ""
            rows.append(
                {
                    "kind": kind,
                    "name": _active_row_name(kind, entry),
                    "type": notion_type,
                    "status": str(entry.get("status") or status_default or ""),
                    "domain": str(entry.get("domain") or ""),
                    "project": str(entry.get("project") or ""),
                    "active_link": str(entry.get("link") or ""),
                    "source_path": str(source_path),
                }
            )
    rows.sort(key=lambda row: (row["type"], row["name"], row["active_link"]))
    return {
        "mode": "dry-run",
        "root": str(os_root),
        "workspace": target_workspace(os_root),
        "database_id": database_id,
        "active_index": str(_active_index_path(os_root)),
        "planned": len(rows),
        "rows": [{**row, "action": "planned"} for row in rows],
    }


def _title_prop(value: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def _rich_text_prop(value: str) -> dict[str, Any]:
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def _select_prop(value: str) -> dict[str, Any]:
    return {"select": {"name": value[:100]}} if value else {"select": None}


def _date_prop(value: str) -> dict[str, Any]:
    return {"date": {"start": value}}


def _active_work_properties(row: dict[str, Any], synced_date: str) -> dict[str, Any]:
    return {
        "Name": _title_prop(row["name"]),
        "Type": _select_prop(row["type"]),
        "Status": _select_prop(row["status"]),
        "Domain": _rich_text_prop(row["domain"]),
        "Project": _rich_text_prop(row["project"]),
        "Active Link": _rich_text_prop(row["active_link"]),
        "Source Path": _rich_text_prop(row["source_path"]),
        "Last Synced": _date_prop(synced_date),
    }


def _plain_text(items: list[dict[str, Any]]) -> str:
    return "".join(str(item.get("plain_text") or (item.get("text") or {}).get("content") or "") for item in items)


def _property_value(properties: dict[str, Any], name: str) -> str:
    prop = properties.get(name) or {}
    prop_type = prop.get("type")
    if prop_type == "title":
        return _plain_text(prop.get("title") or [])
    if prop_type == "rich_text":
        return _plain_text(prop.get("rich_text") or [])
    if prop_type == "select":
        return str(((prop.get("select") or {}).get("name")) or "")
    if prop_type == "date":
        return str(((prop.get("date") or {}).get("start")) or "")
    return ""


def _desired_values(row: dict[str, Any], synced_date: str) -> dict[str, str]:
    return {
        "Name": row["name"],
        "Type": row["type"],
        "Status": row["status"],
        "Domain": row["domain"],
        "Project": row["project"],
        "Active Link": row["active_link"],
        "Source Path": row["source_path"],
        "Last Synced": synced_date,
    }


def _missing_active_work_properties(property_types: dict[str, str]) -> list[str]:
    missing = []
    for name, expected_type in ACTIVE_WORK_REQUIRED_PROPERTIES.items():
        if property_types.get(name) != expected_type:
            missing.append(f"{name} ({expected_type})")
    return missing


def apply_active_work_sync(
    root: str | Path,
    *,
    database_id: str | None,
    verified_workspace: str | None,
    token_env: str = "GENOMES_NOTION_PAT",
    fetcher: Any | None = None,
) -> dict[str, Any]:
    """Upsert the filesystem active index into the live ``OS Active Work`` DB."""
    if not database_id:
        raise ValueError("cannot apply active-work Notion sync without --database-id")
    os_root = expand_path(root)
    workspace = verify_workspace(os_root, verified_workspace)
    plan = build_active_work_sync_plan(os_root, database_id=database_id)

    from .notion_api import (
        _default_fetcher,
        create_database_page,
        get_bot_workspace,
        get_database_property_types,
        query_database_by_rich_text_property,
        update_database_page,
    )

    active_fetcher = fetcher or _default_fetcher
    bot_workspace = get_bot_workspace(token_env, fetcher=active_fetcher)
    if bot_workspace != workspace:
        raise ValueError(
            f"live API workspace mismatch: bot reports {bot_workspace!r} "
            f"but verified_workspace expects {workspace!r}; refusing Notion write"
        )
    missing = _missing_active_work_properties(get_database_property_types(database_id, token_env, fetcher=active_fetcher))
    if missing:
        raise ValueError("OS Active Work database is missing required properties: " + ", ".join(missing))

    synced_date = datetime.now(timezone.utc).date().isoformat()
    rows: list[dict[str, Any]] = []
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for row in plan["rows"]:
        desired = _desired_values(row, synced_date)
        matches = query_database_by_rich_text_property(
            database_id,
            "Active Link",
            row["active_link"],
            token_env,
            fetcher=active_fetcher,
        )
        props = _active_work_properties(row, synced_date)
        if matches:
            page = matches[0]
            existing = {name: _property_value(page.get("properties") or {}, name) for name in desired}
            if existing == desired:
                action = "unchanged"
                counts["unchanged"] += 1
                notion_id = str(page.get("id") or "").replace("-", "")
            else:
                update_database_page(str(page["id"]), props, token_env, fetcher=active_fetcher)
                action = "updated"
                counts["updated"] += 1
                notion_id = str(page.get("id") or "").replace("-", "")
        else:
            notion_id = create_database_page(database_id, props, token_env, fetcher=active_fetcher)
            action = "created"
            counts["created"] += 1
        rows.append({**row, "action": action, "notion_id": notion_id})

    result = {
        "mode": "apply",
        "live": True,
        "root": str(os_root),
        "workspace": workspace,
        "database_id": database_id,
        "active_index": plan["active_index"],
        "manifest_path": str(os_root / ACTIVE_WORK_SYNC_MANIFEST_PATH),
        "planned": len(rows),
        "counts": counts,
        **counts,
        "rows": rows,
    }
    manifest = {key: value for key, value in result.items() if key != "rows"}
    manifest["rows"] = rows
    manifest_path = os_root / ACTIVE_WORK_SYNC_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return result


CONTROL_PLANE_DATABASES = (
    ("OS Inbox", "Capture requests, rough ideas, and kickoff records."),
    ("Work Items", "Active work queue across domains, projects, workflows, and automations."),
    ("Runs", "Execution history, validation evidence, artifacts, and final state."),
    ("Approvals", "Human approval queue for risky actions."),
    ("Domains", "Domain catalog with root paths, owners, and source systems."),
)


def bootstrap_id(name: str) -> str:
    digest = hashlib.sha256(name.encode()).hexdigest()[:16]
    return f"local-bootstrap-{digest}"


def build_bootstrap_plan(root: str | Path, *, parent_page_id: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    recent_runs = [str(path) for path in sorted(os_root.glob("*/06-runs-and-logs/runs/*/run-log.md"))[-5:]]
    databases = [
        {"name": name, "purpose": purpose, "action": "create-or-update", "local_id": bootstrap_id(name)}
        for name, purpose in CONTROL_PLANE_DATABASES
    ]
    return {
        "root": str(os_root),
        "workspace": target_workspace(os_root),
        "parent_page_id": parent_page_id,
        "home_page": {"name": "Agentic OS", "action": "create-or-update", "local_id": bootstrap_id("Agentic OS")},
        "databases": databases,
        "dashboard_views": [
            "Needs Approval",
            "Active Work",
            "Waiting On Me",
            "Running Or Failed Runs",
            "Recent Outputs",
            "Automation Health",
            "Inbox To Triage",
            "Decisions This Week",
        ],
        "seed_records": {"runs": recent_runs},
        "manifest_path": str(os_root / BOOTSTRAP_MANIFEST_PATH),
    }


def apply_bootstrap_plan(
    root: str | Path,
    *,
    verified_workspace: str | None,
    parent_page_id: str | None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    workspace = verify_workspace(os_root, verified_workspace)
    if not parent_page_id:
        raise ValueError("cannot bootstrap Notion control plane without an approved parent page id")
    plan = build_bootstrap_plan(os_root, parent_page_id=parent_page_id)
    manifest = {
        "workspace": workspace,
        "parent_page_id": parent_page_id,
        "home_page": plan["home_page"],
        "databases": plan["databases"],
        "dashboard_views": plan["dashboard_views"],
        "seed_records": plan["seed_records"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os_root / BOOTSTRAP_MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return {"root": str(os_root), "workspace": workspace, "manifest_path": str(path), "applied": True}
