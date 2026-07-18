"""CLI for the installed versioned Agentic OS object library."""

from __future__ import annotations

import argparse
import json

from ..library import (
    OBJECT_KINDS,
    apply_legacy_migration,
    create_object,
    get_object,
    init_library,
    library_doctor,
    query_objects,
    refresh_registry,
)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_init(args: argparse.Namespace) -> int:
    _print(init_library(args.root, dry_run=not args.apply, initialize_git=args.git))
    return 0


def handle_refresh(args: argparse.Namespace) -> int:
    _print(refresh_registry(args.root, dry_run=not args.apply))
    return 0


def handle_create(args: argparse.Namespace) -> int:
    _print(
        create_object(
            args.root,
            args.kind,
            args.object_id,
            level=args.level,
            domain=args.domain,
            project=args.project,
            title=args.title,
            description=args.description,
            entrypoint=args.entrypoint,
            dry_run=not args.apply,
        )
    )
    return 0


def handle_list(args: argparse.Namespace) -> int:
    objects = query_objects(
        args.root,
        kind=args.kind,
        level=args.level,
        domain=args.domain,
        project=args.project,
        status=args.status,
    )
    _print({"api_version": "agentic-os-library/v1", "count": len(objects), "objects": objects})
    return 0


def handle_show(args: argparse.Namespace) -> int:
    _print(get_object(args.root, args.object_id))
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    result = library_doctor(args.root)
    _print(result)
    return 0 if result["status"] in {"healthy", "warning"} else 1


def handle_migrate(args: argparse.Namespace) -> int:
    result = apply_legacy_migration(args.root, dry_run=not args.apply)
    _print(result)
    return 1 if result.get("status") == "blocked" else 0


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default="~/agentic_os", help="Installed Agentic OS root.")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "library",
        help="Operate the versioned installed object library and generated registries.",
    )
    commands = parser.add_subparsers(dest="library_command", required=True)

    init_parser = commands.add_parser("init", help="Plan or initialize the lib/ object repository.")
    _root_argument(init_parser)
    init_parser.add_argument("--apply", action="store_true", help="Create the library layout.")
    init_parser.add_argument("--git", action="store_true", help="Initialize lib/.git when applying.")
    init_parser.set_defaults(handler=handle_init)

    refresh_parser = commands.add_parser("refresh", help="Plan or rebuild generated library registries.")
    _root_argument(refresh_parser)
    refresh_parser.add_argument("--apply", action="store_true", help="Write generated registries.")
    refresh_parser.set_defaults(handler=handle_refresh)

    create_parser = commands.add_parser("create", help="Plan or create one manifest-backed object.")
    _root_argument(create_parser)
    create_parser.add_argument("kind", choices=OBJECT_KINDS)
    create_parser.add_argument("object_id")
    create_parser.add_argument("--level", choices=("root", "domain", "project"), default="root")
    create_parser.add_argument("--domain")
    create_parser.add_argument("--project")
    create_parser.add_argument("--title")
    create_parser.add_argument("--description", default="")
    create_parser.add_argument("--entrypoint")
    create_parser.add_argument("--apply", action="store_true", help="Create the object and refresh registries.")
    create_parser.set_defaults(handler=handle_create)

    list_parser = commands.add_parser("list", help="List objects from the compact canonical registry.")
    _root_argument(list_parser)
    list_parser.add_argument("--kind", choices=OBJECT_KINDS)
    list_parser.add_argument("--level", choices=("root", "domain", "project"))
    list_parser.add_argument("--domain")
    list_parser.add_argument("--project")
    list_parser.add_argument("--status")
    list_parser.set_defaults(handler=handle_list)

    show_parser = commands.add_parser("show", help="Show one canonical object.")
    _root_argument(show_parser)
    show_parser.add_argument("object_id")
    show_parser.set_defaults(handler=handle_show)

    doctor_parser = commands.add_parser("doctor", help="Validate manifests, registries, and Git presence.")
    _root_argument(doctor_parser)
    doctor_parser.set_defaults(handler=handle_doctor)

    migrate_parser = commands.add_parser(
        "migrate-legacy",
        help="Plan or copy legacy definitions into lib/ using the first-class registry.",
    )
    _root_argument(migrate_parser)
    migrate_parser.add_argument("--apply", action="store_true", help="Copy definitions and write manifests.")
    migrate_parser.set_defaults(handler=handle_migrate)
