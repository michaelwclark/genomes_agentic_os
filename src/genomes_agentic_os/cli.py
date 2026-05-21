"""Command-line interface for Genome's Agentic OS."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

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

    automation_parser = subparsers.add_parser("automation", help="Manage automations.")
    automation_subparsers = automation_parser.add_subparsers(dest="automation_command", required=True)
    automation_create = automation_subparsers.add_parser("create", help="Create an automation scaffold.")
    automation_create.add_argument("domain")
    automation_create.add_argument("lane")
    automation_create.add_argument("name")
    automation_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_create.set_defaults(handler=handle_automation_create)

    run_log_parser = subparsers.add_parser("run-log", help="Manage run logs.")
    run_log_subparsers = run_log_parser.add_subparsers(dest="run_log_command", required=True)
    run_log_create = run_log_subparsers.add_parser("create", help="Create a timestamped run log.")
    run_log_create.add_argument("domain")
    run_log_create.add_argument("workflow_or_automation")
    run_log_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_create.set_defaults(handler=handle_run_log_create)

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


def handle_automation_create(args: argparse.Namespace) -> int:
    print_result(create_automation(args.root, args.domain, args.lane, args.name))
    return 0


def handle_run_log_create(args: argparse.Namespace) -> int:
    print_result(create_run_log(args.root, args.domain, args.workflow_or_automation))
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
