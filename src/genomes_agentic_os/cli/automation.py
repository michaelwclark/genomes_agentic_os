"""CLI commands for automations and the automation control plane."""

from __future__ import annotations

import argparse

from ..automation_ops import (
    AUTOMATION_MATURITY_LEVELS,
    attach_automation,
    check_automation,
    format_automation_check,
    set_automation_maturity,
)
from ..automation_control import (
    automation_control_doctor,
    format_automation_control_result,
    list_automation_control,
    run_automation_control,
)
from ..scaffold import create_automation

from ._shared import DEFAULT_ROOT, print_result, yaml_dump


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


def handle_automation_control_list(args: argparse.Namespace) -> int:
    print(format_automation_control_result(list_automation_control(args.root)))
    return 0


def handle_automation_control_doctor(args: argparse.Namespace) -> int:
    result = automation_control_doctor(args.root)
    print(format_automation_control_result(result))
    return 0 if result.get("ok") else 1


def handle_automation_control_run(args: argparse.Namespace) -> int:
    print(format_automation_control_result(run_automation_control(args.root, dry_run=not args.apply)))
    return 0


def register(subparsers) -> None:
    """Register the automation / automation-control command group."""
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

    automation_control_parser = subparsers.add_parser(
        "automation-control",
        help="Gate expensive automations behind cheap source-readiness probes.",
    )
    automation_control_subparsers = automation_control_parser.add_subparsers(
        dest="automation_control_command",
        required=True,
    )
    automation_control_list = automation_control_subparsers.add_parser("list", help="List managed automation gates.")
    automation_control_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_list.set_defaults(handler=handle_automation_control_list)
    automation_control_doctor_parser = automation_control_subparsers.add_parser(
        "doctor",
        help="Validate managed automation-control config.",
    )
    automation_control_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_doctor_parser.set_defaults(handler=handle_automation_control_doctor)
    automation_control_run = automation_control_subparsers.add_parser(
        "run",
        help="Evaluate configured automation gates and enqueue ready work.",
    )
    automation_control_run.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_run_mode = automation_control_run.add_mutually_exclusive_group()
    automation_control_run_mode.add_argument("--dry-run", action="store_true", default=True)
    automation_control_run_mode.add_argument("--apply", action="store_true")
    automation_control_run.set_defaults(handler=handle_automation_control_run)
