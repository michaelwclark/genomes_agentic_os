"""CLI commands that scaffold the OS tree: init, domain, profile, room."""

from __future__ import annotations

import argparse
import sys

from ..room_profile import format_profile_result, install_profile_os, load_os_profile, write_profile_template
from ..scaffold import DEFAULT_PROJECTS_SOURCE, create_domain, init_os

from ._shared import DEFAULT_ROOT, print_result


def handle_init(args: argparse.Namespace) -> int:
    if args.profile:
        result = install_profile_os(
            args.target,
            args.profile,
            projects_source=args.projects_source,
            include_legacy_agent=args.include_legacy_agent,
        )
        print(
            format_profile_result(
                result
            )
        )
        return 0
    domains = None
    if getattr(args, "domains", None):
        domains = tuple(part.strip() for part in str(args.domains).split(",") if part.strip())
        if not domains:
            print("--domains requires at least one domain slug", file=sys.stderr)
            return 2
    result = init_os(
        args.target,
        projects_source=args.projects_source,
        include_legacy_agent=args.include_legacy_agent,
        domains=domains,
    )
    print_result(result)
    return 0


def handle_domain_create(args: argparse.Namespace) -> int:
    print_result(create_domain(args.root, args.name, include_legacy_agent=args.include_legacy_agent))
    return 0


def handle_profile_create(args: argparse.Namespace) -> int:
    print(format_profile_result(write_profile_template(args.target)))
    return 0


def handle_profile_validate(args: argparse.Namespace) -> int:
    profile = load_os_profile(args.profile)
    print(format_profile_result({"profile": args.profile, "rooms": [room["slug"] for room in profile["rooms"]], "ok": True}))
    return 0


def handle_room_create(args: argparse.Namespace) -> int:
    print_result(create_domain(args.root, args.room_slug))
    return 0


def handle_room_update(args: argparse.Namespace) -> int:
    profile = load_os_profile(args.from_profile)
    room = next((room for room in profile["rooms"] if room["slug"] == args.room_slug), None)
    if room is None:
        raise ValueError(f"room not found in profile: {args.room_slug}")
    result = install_profile_os(args.root, args.from_profile)
    print(format_profile_result(result))
    return 0


def register(subparsers) -> None:
    """Register the init / domain / profile / room command group."""
    init_parser = subparsers.add_parser("init", help="Create the base installed OS tree.")
    init_parser.add_argument("--target", default=DEFAULT_ROOT, help="Installed OS target path.")
    init_parser.add_argument("--profile", help="Room-first OS profile YAML.")
    init_parser.add_argument(
        "--domains",
        help="Comma-separated domain slugs to create instead of the built-in defaults (e.g. personal,work,archive).",
    )
    init_parser.add_argument(
        "--projects-source",
        default=DEFAULT_PROJECTS_SOURCE,
        help="Deprecated compatibility flag; project repo links now live under domain 02-projects entries.",
    )
    init_parser.add_argument(
        "--include-legacy-agent",
        action="store_true",
        help="Also create AGENT.md compatibility adapters for harnesses that require that exact filename.",
    )
    init_parser.set_defaults(handler=handle_init)

    domain_parser = subparsers.add_parser("domain", help="Manage domains.")
    domain_subparsers = domain_parser.add_subparsers(dest="domain_command", required=True)
    domain_create = domain_subparsers.add_parser("create", help="Create a domain scaffold.")
    domain_create.add_argument("name")
    domain_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    domain_create.add_argument(
        "--include-legacy-agent",
        action="store_true",
        help="Also create AGENT.md compatibility adapters for harnesses that require that exact filename.",
    )
    domain_create.set_defaults(handler=handle_domain_create)

    profile_parser = subparsers.add_parser("profile", help="Manage room-first OS profiles.")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_create = profile_subparsers.add_parser("create", help="Create an editable profile template.")
    profile_create.add_argument("--target", required=True)
    profile_create.set_defaults(handler=handle_profile_create)
    profile_validate = profile_subparsers.add_parser("validate", help="Validate a room-first profile.")
    profile_validate.add_argument("profile")
    profile_validate.set_defaults(handler=handle_profile_validate)

    room_parser = subparsers.add_parser("room", help="Manage rooms.")
    room_subparsers = room_parser.add_subparsers(dest="room_command", required=True)
    room_create = room_subparsers.add_parser("create", help="Create a room scaffold.")
    room_create.add_argument("room_slug")
    room_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    room_create.set_defaults(handler=handle_room_create)
    room_update = room_subparsers.add_parser("update", help="Update a room from a profile.")
    room_update.add_argument("room_slug")
    room_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    room_update.add_argument("--from-profile", required=True)
    room_update.set_defaults(handler=handle_room_update)
