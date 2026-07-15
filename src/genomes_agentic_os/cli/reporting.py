"""CLI surface for canonical report definitions, runs, and artifacts."""

from __future__ import annotations

import argparse
import json

from ..report_engine import (
    consolidation_plan,
    create_report_definition,
    ensure_report_registries,
    get_report_resource,
    load_definition_file,
    query_report_resources,
    rollback_report_action,
    run_report_now,
    set_report_archived,
    update_report_definition,
    validate_report_definition,
)
from ._shared import DEFAULT_ROOT, yaml_dump


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, sort_keys=True) if json_output else yaml_dump(value))


def _safe_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default).")
    mode.add_argument("--apply", action="store_true", help="Persist the governed action and its receipt.")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed Agentic OS root path.")
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def handle_init(args: argparse.Namespace) -> int:
    created = ensure_report_registries(args.root)
    _print({"api_version": "report-registry/v1", "created": created, "count": len(created)}, json_output=args.json)
    return 0


def handle_query(args: argparse.Namespace) -> int:
    result = query_report_resources(
        args.root,
        args.resource_kind,
        definition_id=args.definition_id,
        status=args.status,
        include_archived=args.include_archived,
    )
    _print(result, json_output=args.json)
    return 0


def handle_get(args: argparse.Namespace) -> int:
    _print(get_report_resource(args.root, args.resource_kind, args.resource_id), json_output=args.json)
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    definition = load_definition_file(args.definition_file)
    result = validate_report_definition(args.root, definition)
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def handle_create(args: argparse.Namespace) -> int:
    result = create_report_definition(args.root, load_definition_file(args.definition_file), dry_run=not args.apply)
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_update(args: argparse.Namespace) -> int:
    result = update_report_definition(
        args.root,
        args.report_id,
        load_definition_file(args.definition_file),
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_archive(args: argparse.Namespace) -> int:
    result = set_report_archived(args.root, args.report_id, archived=True, dry_run=not args.apply)
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_restore(args: argparse.Namespace) -> int:
    result = set_report_archived(args.root, args.report_id, archived=False, dry_run=not args.apply)
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_run_now(args: argparse.Namespace) -> int:
    result = run_report_now(
        args.root,
        args.report_id,
        dry_run=not args.apply,
        trigger=args.trigger,
        project_notion=args.project_notion,
        notion_workspace=args.notion_workspace,
    )
    _print(result, json_output=args.json)
    return 0 if result["status"] in {"planned", "success"} else 1


def handle_rollback(args: argparse.Namespace) -> int:
    result = rollback_report_action(args.root, args.receipt, dry_run=not args.apply)
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_consolidate(args: argparse.Namespace) -> int:
    _print(consolidation_plan(args.root, stale_days=args.stale_days), json_output=args.json)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "report",
        help="Define, query, run, and govern first-class Agentic OS reports.",
        description=(
            "Operate canonical ReportDefinition, ReportRun, and ReportArtifact resources. "
            "Lifecycle and run actions are dry-run by default."
        ),
    )
    commands = parser.add_subparsers(dest="report_command", required=True)

    init_parser = commands.add_parser("init", help="Create missing report registries additively.")
    _common(init_parser)
    init_parser.set_defaults(handler=handle_init)

    query_parser = commands.add_parser("query", help="Query a typed report resource projection.")
    query_parser.add_argument("resource_kind", choices=("definition", "run", "artifact"))
    query_parser.add_argument("--definition-id")
    query_parser.add_argument("--status")
    query_parser.add_argument("--include-archived", action="store_true")
    _common(query_parser)
    query_parser.set_defaults(handler=handle_query)

    get_parser = commands.add_parser("get", help="Read one definition, run, or artifact by id.")
    get_parser.add_argument("resource_kind", choices=("definition", "run", "artifact"))
    get_parser.add_argument("resource_id")
    _common(get_parser)
    get_parser.set_defaults(handler=handle_get)

    validate_parser = commands.add_parser("validate", help="Validate a report definition and its local references.")
    validate_parser.add_argument("--definition-file", required=True)
    _common(validate_parser)
    validate_parser.set_defaults(handler=handle_validate)

    create_parser = commands.add_parser("create", help="Plan or create a report definition.")
    create_parser.add_argument("--definition-file", required=True)
    _common(create_parser)
    _safe_mode(create_parser)
    create_parser.set_defaults(handler=handle_create)

    update_parser = commands.add_parser("update", help="Plan or replace a report definition without changing its identity.")
    update_parser.add_argument("report_id")
    update_parser.add_argument("--definition-file", required=True)
    _common(update_parser)
    _safe_mode(update_parser)
    update_parser.set_defaults(handler=handle_update)

    for name, handler, help_text in (
        ("archive", handle_archive, "Plan or archive an active report definition."),
        ("restore", handle_restore, "Plan or restore an archived report definition."),
    ):
        action_parser = commands.add_parser(name, help=help_text)
        action_parser.add_argument("report_id")
        _common(action_parser)
        _safe_mode(action_parser)
        action_parser.set_defaults(handler=handler)

    run_parser = commands.add_parser("run-now", help="Plan or run one report with explicit source and projection evidence.")
    run_parser.add_argument("report_id")
    run_parser.add_argument("--trigger", choices=("manual", "schedule", "workflow", "automation"), default="manual")
    run_parser.add_argument("--project-notion", action="store_true", help="Request the configured Notion projection.")
    run_parser.add_argument(
        "--notion-workspace",
        help="Exact verified workspace name; projection accepts only Genome's Notion.",
    )
    _common(run_parser)
    _safe_mode(run_parser)
    run_parser.set_defaults(handler=handle_run_now)

    rollback_parser = commands.add_parser("rollback", help="Plan or apply an optimistic rollback for a lifecycle receipt.")
    rollback_parser.add_argument("receipt", help="Receipt path relative to the Agentic OS root.")
    _common(rollback_parser)
    _safe_mode(rollback_parser)
    rollback_parser.set_defaults(handler=handle_rollback)

    consolidate_parser = commands.add_parser(
        "consolidate-plan",
        help="Find duplicate, stale, and legacy report candidates without deleting or archiving anything.",
    )
    consolidate_parser.add_argument("--stale-days", type=int, default=30)
    _common(consolidate_parser)
    consolidate_parser.set_defaults(handler=handle_consolidate)
