"""CLI surface for governed Agentic OS resource creation and validation."""

from __future__ import annotations

import argparse
import json

from ..filesystem_resource_actions import (
    AUTOMATION_LEVELS,
    HARNESS_VALUES,
    STATUSES,
    automation_run_now,
    automation_schedule_get,
    configure_automation_schedule,
    create_filesystem_resource,
    disable_filesystem_resource,
    filesystem_resource_get,
    filesystem_resource_list,
    repair_filesystem_resource,
    rollback_filesystem_resource,
    set_filesystem_resource_archive,
    update_filesystem_resource,
    validate_filesystem_resource,
)
from ..registry_resource_actions import (
    REGISTRY_RESOURCE_KINDS,
    REGISTRY_SCOPES,
    create_registry_resource,
    registry_resource_get,
    registry_resource_list,
    rollback_registry_resource,
    set_registry_resource_archive,
    update_registry_resource,
    validate_registry_resource,
)
from ..resource_actions import SUPPORTED_RESOURCE_KINDS

from ._shared import DEFAULT_ROOT, yaml_dump


ALL_RESOURCE_KINDS = (*SUPPORTED_RESOURCE_KINDS, *REGISTRY_RESOURCE_KINDS)


def _print(result: dict, *, json_output: bool) -> None:
    print(json.dumps(result, sort_keys=True) if json_output else yaml_dump(result))


def handle_resource_validate(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if args.lane:
            raise ValueError("registry resources do not accept --lane")
        result = validate_registry_resource(
            args.root,
            args.kind,
            args.name,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        result = validate_filesystem_resource(
            args.root,
            args.kind,
            args.name,
            domain=args.domain,
            lane=args.lane,
        )
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def handle_resource_create(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if not args.display_name or not args.description or not args.prompt:
            raise ValueError("--display-name, --description, and --prompt are required for registry resources")
        result = create_registry_resource(
            args.root,
            args.kind,
            args.name,
            name=args.display_name,
            description=args.description,
            prompt=args.prompt,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
            dry_run=not args.apply,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        if any(value is not None for value in (args.display_name, args.description, args.prompt)):
            raise ValueError("filesystem resource creation does not accept registry metadata or prompt fields")
        result = create_filesystem_resource(
            args.root,
            args.kind,
            args.name,
            domain=args.domain,
            lane=args.lane,
            dry_run=not args.apply,
        )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_list(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if args.lane:
            raise ValueError("registry resources do not accept --lane")
        result = registry_resource_list(
            args.root,
            args.kind,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        result = filesystem_resource_list(args.root, args.kind, domain=args.domain, lane=args.lane)
    _print(result, json_output=args.json)
    return 0


def handle_resource_get(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if args.lane:
            raise ValueError("registry resources do not accept --lane")
        result = registry_resource_get(
            args.root,
            args.kind,
            args.name,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        result = filesystem_resource_get(args.root, args.kind, args.name, domain=args.domain, lane=args.lane)
    _print(result, json_output=args.json)
    return 0


def handle_resource_update(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if any(
            value is not None
            for value in (
                args.summary,
                args.status,
                args.harness,
                args.model,
                args.complexity,
                args.notes,
                args.enabled,
                args.level,
                args.definition_id,
                args.expected_drift_hash,
                args.lane,
            )
        ):
            raise ValueError("registry resource update received filesystem-only fields")
        result = update_registry_resource(
            args.root,
            args.kind,
            args.name,
            name=args.display_name,
            description=args.description,
            prompt=args.prompt,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
            dry_run=not args.apply,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        if args.description is not None or args.prompt is not None:
            raise ValueError("filesystem resource update does not accept registry description or prompt fields")
        changes = {
            key: value
            for key, value in {
                "display_name": args.display_name,
                "summary": args.summary,
                "status": args.status,
                "harness": args.harness,
                "model": args.model,
                "complexity": args.complexity,
                "notes": args.notes,
                "enabled": args.enabled,
                "level": args.level,
                "definition_id": args.definition_id,
            }.items()
            if value is not None
        }
        result = update_filesystem_resource(
            args.root,
            args.kind,
            args.name,
            changes=changes,
            domain=args.domain,
            lane=args.lane,
            expected_drift_hash=args.expected_drift_hash,
            dry_run=not args.apply,
        )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_archive(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if args.lane or args.expected_drift_hash:
            raise ValueError("registry resource archive/restore received filesystem-only fields")
        result = set_registry_resource_archive(
            args.root,
            args.kind,
            args.name,
            archived=args.archive_value,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
            dry_run=not args.apply,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        result = set_filesystem_resource_archive(
            args.root,
            args.kind,
            args.name,
            archived=args.archive_value,
            domain=args.domain,
            lane=args.lane,
            expected_drift_hash=args.expected_drift_hash,
            dry_run=not args.apply,
        )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_rollback(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if args.lane or args.expected_drift_hash:
            raise ValueError("registry resource rollback received filesystem-only fields")
        result = rollback_registry_resource(
            args.root,
            args.kind,
            args.name,
            backup_id=args.backup_id,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
            dry_run=not args.apply,
        )
    else:
        if args.scope != "system" or args.project:
            raise ValueError("filesystem resources do not accept --scope or --project")
        result = rollback_filesystem_resource(
            args.root,
            args.kind,
            args.name,
            backup_id=args.backup_id,
            domain=args.domain,
            lane=args.lane,
            expected_drift_hash=args.expected_drift_hash,
            dry_run=not args.apply,
        )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_disable(args: argparse.Namespace) -> int:
    result = disable_filesystem_resource(
        args.root,
        args.kind,
        args.name,
        domain=args.domain,
        lane=args.lane,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_repair(args: argparse.Namespace) -> int:
    result = repair_filesystem_resource(
        args.root,
        args.kind,
        args.name,
        domain=args.domain,
        lane=args.lane,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_run_now(args: argparse.Namespace) -> int:
    result = automation_run_now(
        args.root,
        args.name,
        domain=args.domain,
        lane=args.lane,
        idempotency_key=args.idempotency_key,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_schedule_get(args: argparse.Namespace) -> int:
    result = automation_schedule_get(args.root, args.name, domain=args.domain, lane=args.lane)
    _print(result, json_output=args.json)
    return 0


def handle_resource_schedule_configure(args: argparse.Namespace) -> int:
    result = configure_automation_schedule(
        args.root,
        args.name,
        domain=args.domain,
        lane=args.lane,
        cadence=args.cadence,
        timezone_name=args.timezone,
        local_time=args.local_time,
        enabled=args.enabled,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", choices=REGISTRY_SCOPES, default="system")
    parser.add_argument("--domain")
    parser.add_argument("--project")


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _add_mutation_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")


def _add_filesystem_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lane")


def _add_drift_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-drift-hash", help="Drift hash returned by the immediately preceding dry-run plan.")


def _add_enabled_args(parser: argparse.ArgumentParser, *, default: bool | None = None) -> None:
    enabled = parser.add_mutually_exclusive_group()
    enabled.add_argument("--enabled", action="store_true", dest="enabled")
    enabled.add_argument("--disabled", action="store_false", dest="enabled")
    parser.set_defaults(enabled=default)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "resource",
        help="Plan, create, and validate governed Agentic OS resources.",
        description=(
            "Operate filesystem-backed automations, workflows, and programs, plus registry-backed "
            "rules, reports, skills, and commands, without executing them. Mutations are dry-runs "
            "unless --apply is passed."
        ),
    )
    commands = parser.add_subparsers(dest="resource_command", required=True)

    validate_parser = commands.add_parser("validate", help="Validate a resource contract without changing it.")
    validate_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    validate_parser.add_argument("name")
    _add_scope_args(validate_parser)
    validate_parser.add_argument("--lane")
    _add_output_args(validate_parser)
    validate_parser.set_defaults(handler=handle_resource_validate)

    create_parser = commands.add_parser("create", help="Plan or create a resource scaffold; never run it.")
    create_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    create_parser.add_argument("name")
    _add_scope_args(create_parser)
    create_parser.add_argument("--lane")
    create_parser.add_argument("--display-name")
    create_parser.add_argument("--description")
    create_parser.add_argument("--prompt")
    _add_mutation_mode(create_parser)
    _add_output_args(create_parser)
    create_parser.set_defaults(handler=handle_resource_create)

    list_parser = commands.add_parser("list", help="List resources from canonical scopes and filesystem locations.")
    list_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    _add_scope_args(list_parser)
    _add_filesystem_identity_args(list_parser)
    _add_output_args(list_parser)
    list_parser.set_defaults(handler=handle_resource_list)

    get_parser = commands.add_parser("get", help="Read one canonical resource and its operator metadata.")
    get_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    get_parser.add_argument("name")
    _add_scope_args(get_parser)
    _add_filesystem_identity_args(get_parser)
    _add_output_args(get_parser)
    get_parser.set_defaults(handler=handle_resource_get)

    update_parser = commands.add_parser("update", help="Update allowlisted metadata for a canonical resource.")
    update_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    update_parser.add_argument("name")
    update_parser.add_argument("--display-name")
    update_parser.add_argument("--description")
    update_parser.add_argument("--prompt")
    update_parser.add_argument("--summary")
    update_parser.add_argument("--status", choices=sorted(STATUSES))
    update_parser.add_argument("--harness", choices=sorted(HARNESS_VALUES))
    update_parser.add_argument("--model")
    update_parser.add_argument("--complexity")
    update_parser.add_argument("--notes")
    update_parser.add_argument("--level", choices=sorted(AUTOMATION_LEVELS))
    update_parser.add_argument("--definition-id")
    _add_enabled_args(update_parser)
    _add_scope_args(update_parser)
    _add_filesystem_identity_args(update_parser)
    _add_drift_arg(update_parser)
    _add_mutation_mode(update_parser)
    _add_output_args(update_parser)
    update_parser.set_defaults(handler=handle_resource_update)

    for command_name, archive_value in (("archive", True), ("restore", False)):
        archive_parser = commands.add_parser(command_name, help=f"{command_name.title()} a managed resource reversibly.")
        archive_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
        archive_parser.add_argument("name")
        _add_scope_args(archive_parser)
        _add_filesystem_identity_args(archive_parser)
        _add_drift_arg(archive_parser)
        _add_mutation_mode(archive_parser)
        _add_output_args(archive_parser)
        archive_parser.set_defaults(handler=handle_resource_archive, archive_value=archive_value)

    rollback_parser = commands.add_parser("rollback", help="Restore a managed resource from an identity-bound backup ID.")
    rollback_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    rollback_parser.add_argument("name")
    rollback_parser.add_argument("--backup-id", required=True)
    _add_scope_args(rollback_parser)
    _add_filesystem_identity_args(rollback_parser)
    _add_drift_arg(rollback_parser)
    _add_mutation_mode(rollback_parser)
    _add_output_args(rollback_parser)
    rollback_parser.set_defaults(handler=handle_resource_rollback)

    disable_parser = commands.add_parser("disable", help="Pause a filesystem resource without deleting it.")
    disable_parser.add_argument("kind", choices=SUPPORTED_RESOURCE_KINDS)
    disable_parser.add_argument("name")
    disable_parser.add_argument("--domain")
    _add_filesystem_identity_args(disable_parser)
    _add_drift_arg(disable_parser)
    _add_mutation_mode(disable_parser)
    _add_output_args(disable_parser)
    disable_parser.set_defaults(handler=handle_resource_disable)

    repair_parser = commands.add_parser("repair", help="Repair a filesystem resource lifecycle overlay safely.")
    repair_parser.add_argument("kind", choices=SUPPORTED_RESOURCE_KINDS)
    repair_parser.add_argument("name")
    repair_parser.add_argument("--domain")
    _add_filesystem_identity_args(repair_parser)
    _add_drift_arg(repair_parser)
    _add_mutation_mode(repair_parser)
    _add_output_args(repair_parser)
    repair_parser.set_defaults(handler=handle_resource_repair)

    run_now_parser = commands.add_parser("run-now", help="Queue an automation run request without dispatching it.")
    run_now_parser.add_argument("kind", choices=("automation",))
    run_now_parser.add_argument("name")
    run_now_parser.add_argument("--domain", required=True)
    run_now_parser.add_argument("--lane", required=True)
    run_now_parser.add_argument("--idempotency-key")
    _add_drift_arg(run_now_parser)
    _add_mutation_mode(run_now_parser)
    _add_output_args(run_now_parser)
    run_now_parser.set_defaults(handler=handle_resource_run_now)

    schedule_get_parser = commands.add_parser("schedule-get", help="Read the canonical schedule bound to an automation.")
    schedule_get_parser.add_argument("kind", choices=("automation",))
    schedule_get_parser.add_argument("name")
    schedule_get_parser.add_argument("--domain", required=True)
    schedule_get_parser.add_argument("--lane", required=True)
    _add_output_args(schedule_get_parser)
    schedule_get_parser.set_defaults(handler=handle_resource_schedule_get)

    schedule_configure_parser = commands.add_parser(
        "schedule-configure",
        help="Create or update an automation schedule using a canonical derived invocation.",
    )
    schedule_configure_parser.add_argument("kind", choices=("automation",))
    schedule_configure_parser.add_argument("name")
    schedule_configure_parser.add_argument("--domain", required=True)
    schedule_configure_parser.add_argument("--lane", required=True)
    schedule_configure_parser.add_argument("--cadence", required=True)
    schedule_configure_parser.add_argument("--timezone", default="America/Chicago")
    schedule_configure_parser.add_argument("--local-time")
    _add_enabled_args(schedule_configure_parser)
    _add_drift_arg(schedule_configure_parser)
    _add_mutation_mode(schedule_configure_parser)
    _add_output_args(schedule_configure_parser)
    schedule_configure_parser.set_defaults(handler=handle_resource_schedule_configure)
