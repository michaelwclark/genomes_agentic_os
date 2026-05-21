"""Command-line interface for Genome's Agentic OS."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .automation_ops import (
    AUTOMATION_MATURITY_LEVELS,
    attach_automation,
    check_automation,
    format_automation_check,
    set_automation_maturity,
)
from .customer import customer_init, customer_update, customer_validate, format_customer_result
from .doctor import doctor, format_doctor_result
from .losmon import format_losmon_result, losmon_validate
from .migrations import format_migration_result, migrate_apply, migrate_plan
from .notion_sync import apply_sync_plan, build_sync_plan, format_sync_result
from .routing import build_context, context_from_here, format_packet, route_request
from .scaffold import (
    create_automation,
    create_domain,
    create_project,
    create_run_log,
    create_workflow,
    install_docs,
    init_os,
)
from .validate import validate_root
from .workflow_ops import check_workflow, close_run_log, format_findings


DEFAULT_ROOT = "~/agentic_os"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-os", description="Scaffold and validate an Agentic OS root.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create the base installed OS tree.")
    init_parser.add_argument("--target", default=DEFAULT_ROOT, help="Installed OS target path.")
    init_parser.set_defaults(handler=handle_init)

    domain_parser = subparsers.add_parser("domain", help="Manage domains.")
    domain_subparsers = domain_parser.add_subparsers(dest="domain_command", required=True)
    domain_create = domain_subparsers.add_parser("create", help="Create a domain scaffold.")
    domain_create.add_argument("name")
    domain_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    domain_create.set_defaults(handler=handle_domain_create)

    project_parser = subparsers.add_parser("project", help="Manage projects.")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_create = project_subparsers.add_parser("create", help="Create a project scaffold.")
    project_create.add_argument("domain")
    project_create.add_argument("project")
    project_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_create.add_argument("--repo", help="Repository path or URL.")
    project_create.add_argument("--notion", help="Notion page, database, or URL.")
    project_create.add_argument("--jira", help="Jira project, issue, or URL.")
    project_create.add_argument("--status", default="active", choices=("active", "waiting", "blocked", "done"))
    project_create.add_argument("--lane", help="Primary operating lane for this project.")
    project_create.set_defaults(handler=handle_project_create)

    workflow_parser = subparsers.add_parser("workflow", help="Manage workflows.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_create = workflow_subparsers.add_parser("create", help="Create a workflow scaffold.")
    workflow_create.add_argument("domain")
    workflow_create.add_argument("lane")
    workflow_create.add_argument("name")
    workflow_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    workflow_create.set_defaults(handler=handle_workflow_create)
    workflow_check = workflow_subparsers.add_parser("check", help="Check workflow readiness.")
    workflow_check.add_argument("domain")
    workflow_check.add_argument("lane")
    workflow_check.add_argument("workflow")
    workflow_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    workflow_check.set_defaults(handler=handle_workflow_check)

    automation_parser = subparsers.add_parser("automation", help="Manage automations.")
    automation_subparsers = automation_parser.add_subparsers(dest="automation_command", required=True)
    automation_create = automation_subparsers.add_parser("create", help="Create an automation scaffold.")
    automation_create.add_argument("domain")
    automation_create.add_argument("lane")
    automation_create.add_argument("name")
    automation_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_create.set_defaults(handler=handle_automation_create)
    automation_check = automation_subparsers.add_parser("check", help="Check automation maturity readiness.")
    automation_check.add_argument("domain")
    automation_check.add_argument("lane")
    automation_check.add_argument("automation")
    automation_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_check.set_defaults(handler=handle_automation_check)
    automation_attach = automation_subparsers.add_parser("attach", help="Attach an automation to a project.")
    automation_attach.add_argument("domain")
    automation_attach.add_argument("lane")
    automation_attach.add_argument("automation")
    automation_attach.add_argument("--project", required=True)
    automation_attach.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_attach.set_defaults(handler=handle_automation_attach)
    automation_maturity = automation_subparsers.add_parser(
        "set-maturity",
        help="Set the automation maturity level after evidence checks.",
    )
    automation_maturity.add_argument("domain")
    automation_maturity.add_argument("lane")
    automation_maturity.add_argument("automation")
    automation_maturity.add_argument("level", choices=AUTOMATION_MATURITY_LEVELS)
    automation_maturity.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_maturity.set_defaults(handler=handle_automation_set_maturity)

    run_log_parser = subparsers.add_parser("run-log", help="Manage run logs.")
    run_log_subparsers = run_log_parser.add_subparsers(dest="run_log_command", required=True)
    run_log_create = run_log_subparsers.add_parser("create", help="Create a timestamped run log.")
    run_log_create.add_argument("domain")
    run_log_create.add_argument("workflow_or_automation")
    run_log_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_create.set_defaults(handler=handle_run_log_create)
    run_log_close = run_log_subparsers.add_parser("close", help="Close a run log with audit evidence.")
    run_log_close.add_argument("domain")
    run_log_close.add_argument("run_id")
    run_log_close.add_argument("--status", required=True, choices=("done", "waiting", "failed", "needs_approval"))
    run_log_close.add_argument("--summary", default="")
    run_log_close.add_argument("--validation", action="append", default=[])
    run_log_close.add_argument("--artifact", action="append", default=[])
    run_log_close.add_argument("--approval", action="append", default=[])
    run_log_close.add_argument("--next-action", default="")
    run_log_close.add_argument("--owner", default="OS Owner")
    run_log_close.add_argument("--learning", default="")
    run_log_close.add_argument("--project")
    run_log_close.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_close.set_defaults(handler=handle_run_log_close)

    route_parser = subparsers.add_parser("route", help="Route a request to a domain, project, or workflow.")
    route_parser.add_argument("request")
    route_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    route_parser.set_defaults(handler=handle_route)

    context_parser = subparsers.add_parser("context", help="Build deterministic context packets.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build = context_subparsers.add_parser("build", help="Build a context packet.")
    context_build.add_argument("--domain", required=True)
    context_build.add_argument("--project")
    context_build.add_argument("--workflow")
    context_build.add_argument("--lane")
    context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_build.set_defaults(handler=handle_context_build)

    here_parser = subparsers.add_parser("here", help="Route from the current working directory.")
    here_subparsers = here_parser.add_subparsers(dest="here_command", required=True)
    here_route = here_subparsers.add_parser("route", help="Route a request from the current directory.")
    here_route.add_argument("request")
    here_route.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_route.set_defaults(handler=handle_here_route)
    here_context = here_subparsers.add_parser("context", help="Build context from the current directory.")
    here_context_subparsers = here_context.add_subparsers(dest="here_context_command", required=True)
    here_context_build = here_context_subparsers.add_parser("build", help="Build context from the current directory.")
    here_context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_context_build.set_defaults(handler=handle_here_context_build)

    customer_parser = subparsers.add_parser("customer", help="Manage customer Agentic OS installs.")
    customer_subparsers = customer_parser.add_subparsers(dest="customer_command", required=True)
    customer_init_parser = customer_subparsers.add_parser("init", help="Create a customer OS from a profile.")
    customer_init_parser.add_argument("customer_slug")
    customer_init_parser.add_argument("--profile", required=True)
    customer_init_parser.add_argument("--target", required=True)
    customer_init_parser.set_defaults(handler=handle_customer_init)
    customer_update_parser = customer_subparsers.add_parser("update", help="Add missing customer OS assets.")
    customer_update_parser.add_argument("customer_slug")
    customer_update_parser.add_argument("--root", required=True)
    customer_update_parser.set_defaults(handler=handle_customer_update)
    customer_validate_parser = customer_subparsers.add_parser("validate", help="Validate a customer OS root.")
    customer_validate_parser.add_argument("--root", required=True)
    customer_validate_parser.set_defaults(handler=handle_customer_validate)

    notion_parser = subparsers.add_parser("notion", help="Plan and apply filesystem-to-Notion sync.")
    notion_subparsers = notion_parser.add_subparsers(dest="notion_command", required=True)
    notion_plan = notion_subparsers.add_parser("plan-sync", help="Build a reviewable Notion sync plan.")
    notion_plan.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_plan.set_defaults(handler=handle_notion_plan_sync)
    notion_sync = notion_subparsers.add_parser("sync", help="Run a guarded Notion sync.")
    notion_sync.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_sync_mode = notion_sync.add_mutually_exclusive_group(required=True)
    notion_sync_mode.add_argument("--dry-run", action="store_true")
    notion_sync_mode.add_argument("--apply", action="store_true")
    notion_sync.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_sync.set_defaults(handler=handle_notion_sync)

    doctor_parser = subparsers.add_parser("doctor", help="Run installed OS health checks.")
    doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    doctor_parser.add_argument("--fix-missing", action="store_true", help="Create missing managed files only.")
    doctor_parser.set_defaults(handler=handle_doctor)

    migrate_parser = subparsers.add_parser("migrate", help="Plan and apply explicit migrations.")
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_plan_parser = migrate_subparsers.add_parser("plan", help="Create a reviewable migration plan.")
    migrate_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    migrate_plan_parser.set_defaults(handler=handle_migrate_plan)
    migrate_apply_parser = migrate_subparsers.add_parser("apply", help="Apply an approved migration by ID.")
    migrate_apply_parser.add_argument("migration_id")
    migrate_apply_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    migrate_apply_parser.set_defaults(handler=handle_migrate_apply)

    losmon_parser = subparsers.add_parser("losmon", help="Validate Agentic OS against LOSMon replacement needs.")
    losmon_subparsers = losmon_parser.add_subparsers(dest="losmon_command", required=True)
    losmon_validate_parser = losmon_subparsers.add_parser("validate", help="Create LOSMon replacement validation objects.")
    losmon_validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    losmon_validate_parser.add_argument("--repo", help="LOS or losmon repository path.")
    losmon_validate_parser.set_defaults(handler=handle_losmon_validate)

    validate_parser = subparsers.add_parser("validate", help="Validate an installed OS root.")
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    validate_parser.set_defaults(handler=handle_validate)

    docs_parser = subparsers.add_parser("docs", help="Install or update runtime OS documentation.")
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_install = docs_subparsers.add_parser(
        "install",
        help="Install runtime templates, manual, commands, skills, and plans.",
    )
    docs_install.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_install.set_defaults(handler=handle_docs_install)
    docs_update = docs_subparsers.add_parser(
        "update",
        help="Add missing runtime template, manual, command, skill, and plan assets without overwriting local edits.",
    )
    docs_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_update.set_defaults(handler=handle_docs_update)

    return parser


def print_result(result) -> None:
    messages = result.messages()
    if not messages:
        print("no changes")
        return
    for message in messages:
        print(message)


def handle_init(args: argparse.Namespace) -> int:
    print_result(init_os(args.target))
    return 0


def handle_domain_create(args: argparse.Namespace) -> int:
    print_result(create_domain(args.root, args.name))
    return 0


def handle_project_create(args: argparse.Namespace) -> int:
    print_result(
        create_project(
            args.root,
            args.domain,
            args.project,
            repo=args.repo,
            notion=args.notion,
            jira=args.jira,
            status=args.status,
            lane=args.lane,
        )
    )
    return 0


def handle_workflow_create(args: argparse.Namespace) -> int:
    print_result(create_workflow(args.root, args.domain, args.lane, args.name))
    return 0


def handle_workflow_check(args: argparse.Namespace) -> int:
    print(format_findings(check_workflow(args.root, args.domain, args.lane, args.workflow)))
    return 0


def handle_automation_create(args: argparse.Namespace) -> int:
    print_result(create_automation(args.root, args.domain, args.lane, args.name))
    return 0


def handle_automation_check(args: argparse.Namespace) -> int:
    print(format_automation_check(check_automation(args.root, args.domain, args.lane, args.automation)))
    return 0


def handle_automation_attach(args: argparse.Namespace) -> int:
    result = attach_automation(args.root, args.domain, args.lane, args.automation, args.project)
    print(yaml_dump(result))
    return 0


def handle_automation_set_maturity(args: argparse.Namespace) -> int:
    result = set_automation_maturity(args.root, args.domain, args.lane, args.automation, args.level)
    print(yaml_dump(result))
    return 0


def handle_run_log_create(args: argparse.Namespace) -> int:
    print_result(create_run_log(args.root, args.domain, args.workflow_or_automation))
    return 0


def handle_run_log_close(args: argparse.Namespace) -> int:
    result = close_run_log(
        args.root,
        args.domain,
        args.run_id,
        status=args.status,
        summary=args.summary,
        validation=args.validation,
        artifacts=args.artifact,
        approvals=args.approval,
        next_action=args.next_action,
        owner=args.owner,
        learning=args.learning,
        project=args.project,
    )
    print(yaml_dump(result))
    return 0


def yaml_dump(value) -> str:
    import yaml

    return yaml.safe_dump(value, sort_keys=False).strip()


def handle_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request)))
    return 0


def handle_context_build(args: argparse.Namespace) -> int:
    print(
        format_packet(
            build_context(
                args.root,
                domain=args.domain,
                project=args.project,
                workflow=args.workflow,
                lane=args.lane,
            )
        )
    )
    return 0


def handle_here_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request, cwd=Path.cwd())))
    return 0


def handle_here_context_build(args: argparse.Namespace) -> int:
    print(format_packet(context_from_here(args.root, cwd=Path.cwd())))
    return 0


def handle_customer_init(args: argparse.Namespace) -> int:
    print(format_customer_result(customer_init(args.customer_slug, args.profile, args.target)))
    return 0


def handle_customer_update(args: argparse.Namespace) -> int:
    print(format_customer_result(customer_update(args.customer_slug, args.root)))
    return 0


def handle_customer_validate(args: argparse.Namespace) -> int:
    result = customer_validate(args.root)
    print(format_customer_result(result))
    return 0 if result["ok"] else 1


def handle_notion_plan_sync(args: argparse.Namespace) -> int:
    print(format_sync_result(build_sync_plan(args.root)))
    return 0


def handle_notion_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_sync_plan(args.root)))
    else:
        print(format_sync_result(apply_sync_plan(args.root, verified_workspace=args.verified_workspace)))
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    result = doctor(args.root, fix_missing=args.fix_missing)
    print(format_doctor_result(result))
    return 0 if result["ok"] else 1


def handle_migrate_plan(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_plan(args.root)))
    return 0


def handle_migrate_apply(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_apply(args.root, args.migration_id)))
    return 0


def handle_losmon_validate(args: argparse.Namespace) -> int:
    print(format_losmon_result(losmon_validate(args.root, repo=args.repo)))
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    result = validate_root(args.root)
    if result.ok:
        print(f"valid: {Path(args.root).expanduser()}")
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 1


def handle_docs_install(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_update(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
