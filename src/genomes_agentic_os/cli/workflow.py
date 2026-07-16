"""CLI commands for workflows and shared/instance OS programs."""

from __future__ import annotations

import argparse
import json

from ..scaffold import create_instance_program, create_program, create_workflow
from ..workflow_engine import (
    create_workflow_definition,
    get_workflow_resource,
    load_workflow_definition_file,
    publish_workflow,
    query_workflow_resources,
    rollback_workflow_action,
    update_workflow_definition,
    validate_workflow_definition,
    workflow_run_now,
)
from ..workflow_ops import check_workflow, format_findings

from ._shared import DEFAULT_ROOT, print_result, yaml_dump


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, sort_keys=True) if json_output else yaml_dump(value))


def _safe_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default).")
    mode.add_argument("--apply", action="store_true", help="Persist the governed action and its receipt.")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed Agentic OS root path.")
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def handle_workflow_create(args: argparse.Namespace) -> int:
    if args.definition_file:
        if any((args.domain, args.lane, args.name)):
            raise ValueError("managed workflow create accepts identity from --definition-file, not positional targets")
        result = create_workflow_definition(
            args.root,
            load_workflow_definition_file(args.definition_file),
            expected_drift_hash=args.expected_drift_hash,
            dry_run=not args.apply,
        )
        _print(result, json_output=args.json)
        return 0 if result.get("readback", {}).get("ok") else 1
    if not all((args.domain, args.lane, args.name)):
        raise ValueError("legacy scaffold create requires domain, lane, and name, or use --definition-file")
    print_result(create_workflow(args.root, args.domain, args.lane, args.name))
    return 0


def handle_workflow_check(args: argparse.Namespace) -> int:
    print(format_findings(check_workflow(args.root, args.domain, args.lane, args.workflow)))
    return 0


def handle_workflow_query(args: argparse.Namespace) -> int:
    result = query_workflow_resources(
        args.root,
        args.resource_kind,
        domain=args.domain,
        lane=args.lane,
        workflow=args.workflow,
        availability=args.availability,
        health=args.health,
        owner=args.owner,
        linked_capability=args.linked_capability,
        query=args.query,
        include_archived=args.include_archived,
        limit=args.limit,
    )
    _print(result, json_output=args.json)
    return 0


def handle_workflow_get(args: argparse.Namespace) -> int:
    result = get_workflow_resource(
        args.root,
        args.resource_kind,
        args.resource_id,
        domain=args.domain,
        lane=args.lane,
    )
    _print(result, json_output=args.json)
    return 0


def handle_workflow_validate(args: argparse.Namespace) -> int:
    result = validate_workflow_definition(args.root, load_workflow_definition_file(args.definition_file))
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def handle_workflow_update(args: argparse.Namespace) -> int:
    result = update_workflow_definition(
        args.root,
        args.workflow_id,
        load_workflow_definition_file(args.definition_file),
        domain=args.domain,
        lane=args.lane,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_workflow_publish(args: argparse.Namespace) -> int:
    result = publish_workflow(
        args.root,
        args.workflow_id,
        domain=args.domain,
        lane=args.lane,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_workflow_run_now(args: argparse.Namespace) -> int:
    result = workflow_run_now(
        args.root,
        args.workflow_id,
        domain=args.domain,
        lane=args.lane,
        idempotency_key=args.idempotency_key,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_workflow_rollback(args: argparse.Namespace) -> int:
    result = rollback_workflow_action(
        args.root,
        args.receipt_id,
        expected_drift_hash=args.expected_drift_hash,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_program_create(args: argparse.Namespace) -> int:
    print_result(create_program(args.root, args.name))
    return 0


def handle_instance_program_create(args: argparse.Namespace) -> int:
    print_result(create_instance_program(args.root, args.domain, args.name))
    return 0


def register(subparsers) -> None:
    """Register the workflow / program / instance-program command group."""
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Manage governed workflow definitions, versions, instances, and queued runs.",
        description=(
            "Scaffold legacy workflow folders or operate the workflow-engine/v1 contract. "
            "Governed mutations are dry-run by default and run-now only queues work."
        ),
    )
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_create = workflow_subparsers.add_parser(
        "create",
        help="Create a legacy scaffold or plan/apply a managed workflow definition.",
    )
    workflow_create.add_argument("domain", nargs="?")
    workflow_create.add_argument("lane", nargs="?")
    workflow_create.add_argument("name", nargs="?")
    workflow_create.add_argument("--definition-file", help="YAML/JSON WorkflowDefinition; its identity fixes the target.")
    workflow_create.add_argument("--expected-drift-hash", help="Required on managed --apply after dry-run readback.")
    _common(workflow_create)
    _safe_mode(workflow_create)
    workflow_create.set_defaults(handler=handle_workflow_create)
    workflow_check = workflow_subparsers.add_parser("check", help="Check workflow readiness.")
    workflow_check.add_argument("domain")
    workflow_check.add_argument("lane")
    workflow_check.add_argument("workflow")
    workflow_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    workflow_check.set_defaults(handler=handle_workflow_check)

    workflow_query = workflow_subparsers.add_parser("query", help="Query definitions, versions, instances, or runs.")
    workflow_query.add_argument("resource_kind", choices=("definition", "version", "instance", "run"))
    workflow_query.add_argument("--domain")
    workflow_query.add_argument("--lane")
    workflow_query.add_argument("--workflow")
    workflow_query.add_argument("--availability", choices=("draft", "active", "paused", "archived"))
    workflow_query.add_argument("--health", choices=("healthy", "degraded", "blocked", "unknown"))
    workflow_query.add_argument("--owner")
    workflow_query.add_argument("--linked-capability")
    workflow_query.add_argument("--query")
    workflow_query.add_argument("--include-archived", action="store_true")
    workflow_query.add_argument("--limit", type=int, default=200, help="Maximum 1-500 resources (default: 200).")
    _common(workflow_query)
    workflow_query.set_defaults(handler=handle_workflow_query)

    workflow_get = workflow_subparsers.add_parser("get", help="Read one definition, version, instance, or run.")
    workflow_get.add_argument("resource_kind", choices=("definition", "version", "instance", "run"))
    workflow_get.add_argument("resource_id")
    workflow_get.add_argument("--domain")
    workflow_get.add_argument("--lane")
    _common(workflow_get)
    workflow_get.set_defaults(handler=handle_workflow_get)

    workflow_validate = workflow_subparsers.add_parser("validate", help="Validate one WorkflowDefinition file.")
    workflow_validate.add_argument("--definition-file", required=True)
    _common(workflow_validate)
    workflow_validate.set_defaults(handler=handle_workflow_validate)

    workflow_update = workflow_subparsers.add_parser("update", help="Plan or update a managed definition without changing identity.")
    workflow_update.add_argument("workflow_id")
    workflow_update.add_argument("--domain", required=True)
    workflow_update.add_argument("--lane", required=True)
    workflow_update.add_argument("--definition-file", required=True)
    workflow_update.add_argument("--expected-drift-hash", help="Required on --apply after dry-run readback.")
    _common(workflow_update)
    _safe_mode(workflow_update)
    workflow_update.set_defaults(handler=handle_workflow_update)

    workflow_publish = workflow_subparsers.add_parser("publish", help="Plan or publish an immutable version and instance pointer.")
    workflow_publish.add_argument("workflow_id")
    workflow_publish.add_argument("--domain", required=True)
    workflow_publish.add_argument("--lane", required=True)
    workflow_publish.add_argument("--expected-drift-hash", help="Required on --apply after dry-run readback.")
    _common(workflow_publish)
    _safe_mode(workflow_publish)
    workflow_publish.set_defaults(handler=handle_workflow_publish)

    workflow_run_now = workflow_subparsers.add_parser(
        "run-now",
        help="Plan or append a governed queue request; this command never executes the workflow.",
    )
    workflow_run_now.add_argument("workflow_id")
    workflow_run_now.add_argument("--domain", required=True)
    workflow_run_now.add_argument("--lane", required=True)
    workflow_run_now.add_argument("--idempotency-key")
    workflow_run_now.add_argument("--expected-drift-hash", help="Required on --apply after dry-run readback.")
    _common(workflow_run_now)
    _safe_mode(workflow_run_now)
    workflow_run_now.set_defaults(handler=handle_workflow_run_now)

    workflow_rollback = workflow_subparsers.add_parser("rollback", help="Plan or restore exact bytes from a governed receipt.")
    workflow_rollback.add_argument("receipt_id", help="Fixed workflow-engine receipt id, not a caller path.")
    workflow_rollback.add_argument("--expected-drift-hash", help="Required on --apply after dry-run readback.")
    _common(workflow_rollback)
    _safe_mode(workflow_rollback)
    workflow_rollback.set_defaults(handler=handle_workflow_rollback)

    program_parser = subparsers.add_parser("program", help="Manage shared OS programs.")
    program_subparsers = program_parser.add_subparsers(dest="program_command", required=True)
    program_create = program_subparsers.add_parser("create", help="Create a shared OSProgram scaffold.")
    program_create.add_argument("name")
    program_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    program_create.set_defaults(handler=handle_program_create)

    instance_program_parser = subparsers.add_parser("instance-program", help="Manage domain-local OS programs.")
    instance_program_subparsers = instance_program_parser.add_subparsers(dest="instance_program_command", required=True)
    instance_program_create = instance_program_subparsers.add_parser(
        "create",
        help="Create a domain-local InstanceOSProgram scaffold.",
    )
    instance_program_create.add_argument("domain")
    instance_program_create.add_argument("name")
    instance_program_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    instance_program_create.set_defaults(handler=handle_instance_program_create)
