"""CLI commands for customer Agentic OS installs."""

from __future__ import annotations

import argparse

from ..customer import (
    customer_init,
    customer_update,
    customer_validate,
    format_customer_result,
    scaffold_customer_brief,
)


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


def handle_customer_brief(args: argparse.Namespace) -> int:
    import json

    result = scaffold_customer_brief(args.root, args.domain, args.name)
    print(json.dumps(result, indent=2))
    return 0


def register(subparsers) -> None:
    """Register the customer command group."""
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
    customer_brief_parser = customer_subparsers.add_parser(
        "brief",
        help="Scaffold a client-automation-brief instance into a customer install domain.",
    )
    customer_brief_parser.add_argument("--root", required=True, help="Customer OS root path.")
    customer_brief_parser.add_argument("--domain", required=True, help="Domain (room) to place the brief in.")
    customer_brief_parser.add_argument("--name", required=True, help="Brief slug (snake_case). Becomes <name>-brief.md in domain/01-intake/.")
    customer_brief_parser.set_defaults(handler=handle_customer_brief)
