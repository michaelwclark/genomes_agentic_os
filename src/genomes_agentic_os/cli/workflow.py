"""CLI commands for workflows and shared/instance OS programs."""

from __future__ import annotations

import argparse

from ..scaffold import create_instance_program, create_program, create_workflow
from ..workflow_ops import check_workflow, format_findings

from ._shared import DEFAULT_ROOT, print_result


def handle_workflow_create(args: argparse.Namespace) -> int:
    print_result(create_workflow(args.root, args.domain, args.lane, args.name))
    return 0


def handle_workflow_check(args: argparse.Namespace) -> int:
    print(format_findings(check_workflow(args.root, args.domain, args.lane, args.workflow)))
    return 0


def handle_program_create(args: argparse.Namespace) -> int:
    print_result(create_program(args.root, args.name))
    return 0


def handle_instance_program_create(args: argparse.Namespace) -> int:
    print_result(create_instance_program(args.root, args.domain, args.name))
    return 0


def register(subparsers) -> None:
    """Register the workflow / program / instance-program command group."""
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
