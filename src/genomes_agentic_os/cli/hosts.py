"""CLI commands for the installed SSH host registry."""

from __future__ import annotations

import argparse
import json

import yaml

from ..hosts import format_host_routing_status, host_routing_status, list_hosts, upsert_host
from ..host_doctor import (
    apply_safe_repairs,
    build_host_report,
    default_config_root,
    host_projection,
    load_host_policies,
    project_host_report,
    project_losmon_report,
    project_losmon_drop,
    write_host_report,
)

from ._shared import DEFAULT_ROOT


def handle_host_add(args: argparse.Namespace) -> int:
    result = upsert_host(
        args.root,
        args.alias,
        ssh_alias=getattr(args, "ssh_alias", None),
        user=getattr(args, "user", None),
        home=getattr(args, "home", None),
        description=getattr(args, "description", None),
    )
    print(f"{result['action']}: {result['alias']} → {result['path']}")
    return 0


def handle_host_list(args: argparse.Namespace) -> int:
    hosts = list_hosts(args.root)
    if getattr(args, "json", False):
        import json

        print(json.dumps({"api_version": "host-list/v1", "hosts": hosts}, indent=2, sort_keys=True))
        return 0
    if not hosts:
        print("No hosts registered. Use: agentic-os host add <alias>")
        return 0
    for entry in hosts:
        alias = entry.get("alias", "")
        ssh_alias = entry.get("ssh_alias", alias)
        home = entry.get("home", "")
        desc = entry.get("description", "")
        home_part = f"  home: {home}" if home else ""
        print(f"  {alias}  (ssh_alias: {ssh_alias}){home_part}  {desc}")
    return 0


def handle_host_routing(args: argparse.Namespace) -> int:
    result = host_routing_status(args.root, recent_runs=getattr(args, "recent_runs", 8))
    if getattr(args, "json", False):
        import json

        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_host_routing_status(result))
    return 0


def handle_host_health_report(args: argparse.Namespace) -> int:
    report = build_host_report(
        args.root,
        host_alias=args.host,
        config_root=args.config_root,
    )
    config_root = args.config_root or default_config_root(args.root)
    policies = load_host_policies(config_root, report["host"])
    report["repairs"] = apply_safe_repairs(report, policies, apply=args.apply_safe_repairs)
    if args.apply_safe_repairs and any(item.get("applied") for item in report["repairs"]):
        verification = build_host_report(
            args.root,
            host_alias=report["host"],
            config_root=config_root,
        )
        report["verification"] = {
            "status": verification["status"],
            "checked_at": verification["checked_at"],
            "findings": verification["findings"],
        }
        report["status"] = verification["status"]
    paths = write_host_report(args.root, report)
    notion = {"applied": False}
    if args.apply_notion:
        projection = host_projection(policies)
        page_id = args.notion_page_id or projection.get("page_id")
        if not page_id:
            raise ValueError("no Notion page id configured; set notion_page_id in the host identity policy or pass --notion-page-id")
        notion = project_host_report(
            report,
            page_id,
            verified_workspace=projection.get("workspace") or args.verified_workspace,
            token_env=args.token_env,
        )
    losmon = {"applied": False}
    if args.apply_losmon:
        identity = next((policy for policy in reversed(policies) if policy.get("losmon_ingest_url")), {})
        url = args.losmon_url or identity.get("losmon_ingest_url")
        if not url:
            raise ValueError("no LOSMON ingestion URL configured; set losmon_ingest_url or pass --losmon-url")
        losmon = project_losmon_report(
            report,
            str(url),
            token_env=str(identity.get("losmon_token_env") or args.losmon_token_env),
        )
    if args.apply_losmon_drop:
        identity = next((policy for policy in reversed(policies) if policy.get("losmon_drop_target")), {})
        target = identity.get("losmon_drop_target")
        if not target:
            raise ValueError("no losmon_drop_target configured in the host identity policy")
        losmon = project_losmon_drop(paths["latest_json"], str(target))
    result = {"report": report, "paths": paths, "notion": notion, "losmon": losmon}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else yaml.safe_dump(result, sort_keys=False))
    return 1 if args.fail_on_unhealthy and report["status"] != "healthy" else 0


def register(subparsers) -> None:
    """Register the host command group."""
    host_parser = subparsers.add_parser("host", help="Manage the installed SSH host registry.")
    host_subparsers = host_parser.add_subparsers(dest="host_command", required=True)
    host_add = host_subparsers.add_parser("add", help="Add or update a host alias in the registry.")
    host_add.add_argument("alias", help="Host alias (identifier used in project remotes).")
    host_add.add_argument("--ssh-alias", help="SSH alias that resolves via ~/.ssh/config.")
    host_add.add_argument("--user", help="Remote username (informational).")
    host_add.add_argument("--home", help="Absolute home/path-domain root on this host.")
    host_add.add_argument("--description", help="Human-readable description of this host.")
    host_add.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_add.set_defaults(handler=handle_host_add)
    host_list = host_subparsers.add_parser("list", help="List registered hosts.")
    host_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    host_list.set_defaults(handler=handle_host_list)
    host_routing = host_subparsers.add_parser(
        "routing",
        help="Show cross-host routing policy and recent harness host receipts.",
    )
    host_routing.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_routing.add_argument("--recent-runs", type=int, default=8, help="Recent harness receipts to show.")
    host_routing.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    host_routing.set_defaults(handler=handle_host_routing)
    host_health = host_subparsers.add_parser(
        "health-report",
        help="Run the policy-composed Auto-Doctor host report and optional safe repair pass.",
    )
    host_health.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_health.add_argument("--host", help="Host policy alias; defaults to the local hostname.")
    host_health.add_argument("--config-root", help="Auto-Doctor Markdown policy root.")
    host_health.add_argument("--apply-safe-repairs", action="store_true", help="Apply allowlisted reconstructable repairs and recheck.")
    host_health.add_argument("--apply-notion", action="store_true", help="Replace the verified host page with the latest report.")
    host_health.add_argument("--notion-page-id", help="Override the Genome's Notion host page id from policy.")
    host_health.add_argument("--verified-workspace", default="Genome's Notion", help="Expected Notion workspace name.")
    host_health.add_argument("--token-env", default="GENOMES_NOTION_PAT", help="Notion token environment variable name.")
    host_health.add_argument("--apply-losmon", action="store_true", help="Ingest the report into the configured LOSMON fleet endpoint.")
    host_health.add_argument("--losmon-url", help="Override the LOSMON report ingestion URL from policy.")
    host_health.add_argument("--losmon-token-env", default="LOSMON_HOST_HEALTH_TOKEN", help="LOSMON ingestion token environment variable name.")
    host_health.add_argument("--apply-losmon-drop", action="store_true", help="Copy latest.json to the policy's SSH-backed LOSMON drop path.")
    host_health.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    host_health.add_argument("--fail-on-unhealthy", action="store_true", help="Return exit 1 for degraded or critical health (interactive/CI use).")
    host_health.set_defaults(handler=handle_host_health_report)
