"""CLI for configurable durable artifact naming and migration."""

from __future__ import annotations

import argparse
import json

from ..artifact_migration import (
    apply_artifact_naming_plan,
    build_artifact_naming_plan,
    restore_artifact_naming_migration,
)
from ..artifact_naming import CONFIG_RELATIVE_PATH, load_artifact_naming_policy
from ._shared import DEFAULT_ROOT


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def handle_show(args: argparse.Namespace) -> int:
    policy = load_artifact_naming_policy(args.root)
    _print(
        {
            "config": str(CONFIG_RELATIVE_PATH),
            "enabled": policy.enabled,
            "date_format": policy.date_format,
            "separator": policy.separator,
            "scopes": dict(policy.scopes),
        }
    )
    return 0


def handle_migrate(args: argparse.Namespace) -> int:
    result = (
        apply_artifact_naming_plan(args.root, backup_dir=args.backup_dir)
        if args.apply
        else build_artifact_naming_plan(args.root)
    )
    _print(result)
    return 0


def handle_restore(args: argparse.Namespace) -> int:
    _print(restore_artifact_naming_migration(args.receipt, apply=args.apply))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("naming", help="Inspect and migrate durable artifact naming policy.")
    commands = parser.add_subparsers(dest="naming_command", required=True)
    show = commands.add_parser("show", help="Show the effective artifact naming policy.")
    show.add_argument("--root", default=DEFAULT_ROOT)
    show.set_defaults(handler=handle_show)
    migrate = commands.add_parser("migrate", help="Plan or apply the date-prefix migration.")
    migrate.add_argument("--root", default=DEFAULT_ROOT)
    migrate.add_argument("--backup-dir")
    migrate.add_argument("--apply", action="store_true")
    migrate.set_defaults(handler=handle_migrate)
    restore = commands.add_parser("restore", help="Plan or restore a migration receipt and backup.")
    restore.add_argument("receipt")
    restore.add_argument("--apply", action="store_true")
    restore.set_defaults(handler=handle_restore)
