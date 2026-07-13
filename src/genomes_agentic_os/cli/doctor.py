"""CLI commands for OS health checks and explicit migrations."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..cli_help import AosHelpFormatter, env_epilog
from ..doctor import doctor, doctor_all, format_doctor_result
from ..migrations import format_migration_result, migrate_apply, migrate_plan

from ._shared import DEFAULT_ROOT


def handle_doctor(args: argparse.Namespace) -> int:
    if getattr(args, "all_systems", False):
        result = doctor_all(args.root)
    else:
        result = doctor(args.root, fix_missing=args.fix_missing)
    if getattr(args, "check_remotes", False):
        from ..hosts import load_hosts  # noqa: PLC0415
        from ..validate import validate_project_remotes_connectivity  # noqa: PLC0415

        root_path = Path(args.root).expanduser()
        try:
            hosts = load_hosts(root_path)
        except ValueError:
            hosts = {}
        # Unreachable hosts are a warning state by spec — never flip doctor ok.
        connectivity_warnings = validate_project_remotes_connectivity(root_path, hosts)
        if isinstance(result.get("warnings"), list):
            result["warnings"].extend(connectivity_warnings)
        else:
            result["warnings"] = connectivity_warnings
    print(format_doctor_result(result))
    return 0 if result["ok"] else 1


def handle_migrate_plan(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_plan(args.root)))
    return 0


def handle_migrate_apply(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_apply(args.root, args.migration_id)))
    return 0


def register(subparsers) -> None:
    """Register the doctor / migrate command group."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run installed OS health checks.",
        description=(
            "Run OS health checks against the installed root. Checks required files, registry contracts, "
            "config.toml conventions, and optional remote host reachability. "
            "Use --all to aggregate all subsystem doctors (runtime, event-graph, config) in one pass. "
            "Use --fix-missing to create only missing managed files without overwriting local edits."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/", "Registry files checked for contract compliance."),
                ("config/hosts.yml", "SSH host registry probed when --check-remotes is set."),
            ],
            examples=[
                ("agentic-os doctor", "Run structural health checks on the default OS root."),
                ("agentic-os doctor --all", "Run all subsystem doctors in one report."),
                ("agentic-os doctor --fix-missing", "Create missing managed files only."),
                ("agentic-os doctor --check-remotes", "Also probe registered SSH hosts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    doctor_parser.add_argument("--fix-missing", action="store_true", help="Create missing managed files only.")
    doctor_parser.add_argument(
        "--all",
        action="store_true",
        dest="all_systems",
        help="Aggregate all subsystem doctors (runtime, event-graph, config) into one report.",
    )
    doctor_parser.add_argument(
        "--check-remotes",
        action="store_true",
        help="Probe each registered host with ssh -o BatchMode=yes <alias> true and report unreachable hosts as warnings.",
    )
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
