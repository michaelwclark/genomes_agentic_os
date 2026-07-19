"""CLI for configurable durable artifact naming and migration."""

from __future__ import annotations

import argparse
import json

from ..artifact_migration import (
    apply_artifact_naming_plan,
    build_artifact_migration_preflight,
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
    if args.apply:
        result = apply_artifact_naming_plan(
            args.root,
            backup_dir=args.backup_dir,
            allow_high_risk=args.allow_high_risk,
            recovery_backup_archive=args.recovery_backup_archive,
        )
    else:
        result = build_artifact_naming_plan(args.root)
        if args.preflight:
            result["preflight"] = build_artifact_migration_preflight(
                args.root,
                result,
                include_move_sources_in_backup=not bool(args.recovery_backup_archive),
                recovery_backup_archive=args.recovery_backup_archive,
            )
    _print(result)
    return 0


def handle_restore(args: argparse.Namespace) -> int:
    _print(restore_artifact_naming_migration(args.receipt, apply=args.apply))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "naming", help="Inspect and migrate durable artifact naming policy."
    )
    commands = parser.add_subparsers(dest="naming_command", required=True)
    show = commands.add_parser(
        "show", help="Show the effective artifact naming policy."
    )
    show.add_argument("--root", default=DEFAULT_ROOT)
    show.set_defaults(handler=handle_show)
    migrate = commands.add_parser(
        "migrate", help="Plan or apply the date-prefix migration."
    )
    migrate.add_argument("--root", default=DEFAULT_ROOT)
    migrate.add_argument("--backup-dir")
    migrate.add_argument(
        "--recovery-backup-archive",
        help="Existing full recovery archive; when supplied, the transaction backs up only mutable references.",
    )
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument(
        "--preflight",
        action="store_true",
        help="Inventory bounded rewrite and backup costs.",
    )
    migrate.add_argument(
        "--allow-high-risk",
        action="store_true",
        help="Acknowledge and override explicit preflight budgets for an apply.",
    )
    migrate.set_defaults(handler=handle_migrate)
    restore = commands.add_parser(
        "restore", help="Plan or restore a migration receipt and backup."
    )
    restore.add_argument("receipt")
    restore.add_argument("--apply", action="store_true")
    restore.set_defaults(handler=handle_restore)
