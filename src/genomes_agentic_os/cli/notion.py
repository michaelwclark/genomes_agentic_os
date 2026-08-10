"""CLI commands for Notion sync and Notion organization checks."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..notion_sync import (
    apply_active_work_sync,
    apply_bootstrap_plan,
    apply_sync_plan,
    build_active_work_sync_plan,
    build_bootstrap_plan,
    build_sync_plan,
    format_sync_result,
)
from ..notion_org import doctor_notion_org, format_notion_org_result

from ._shared import DEFAULT_ROOT


def handle_notion_plan_sync(args: argparse.Namespace) -> int:
    print(format_sync_result(build_sync_plan(args.root)))
    return 0


def handle_notion_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_sync_plan(args.root)))
    else:
        print(format_sync_result(apply_sync_plan(args.root, verified_workspace=args.verified_workspace)))
    return 0


def handle_notion_bootstrap(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_bootstrap_plan(args.root, parent_page_id=args.parent_page_id)))
    else:
        print(
            format_sync_result(
                apply_bootstrap_plan(
                    args.root,
                    verified_workspace=args.verified_workspace,
                    parent_page_id=args.parent_page_id,
                )
            )
        )
    return 0


def handle_notion_active_work_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_active_work_sync_plan(args.root, database_id=args.database_id)))
    else:
        print(
            format_sync_result(
                apply_active_work_sync(
                    args.root,
                    database_id=args.database_id,
                    verified_workspace=args.verified_workspace,
                    approved_parent_page_id=args.parent_page_id,
                    token_env=args.token_env,
                )
            )
        )
    return 0


def handle_notion_org_doctor(args: argparse.Namespace) -> int:
    result = doctor_notion_org(args.root, backup_dir=args.backup_dir)
    print(format_notion_org_result(result))
    return 0 if result["ok"] else 1


def register(subparsers) -> None:
    """Register the notion / notion-org command group."""
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
    notion_bootstrap = notion_subparsers.add_parser("bootstrap", help="Plan or apply the Notion control-plane bootstrap.")
    notion_bootstrap.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_bootstrap_mode = notion_bootstrap.add_mutually_exclusive_group(required=True)
    notion_bootstrap_mode.add_argument("--dry-run", action="store_true")
    notion_bootstrap_mode.add_argument("--apply", action="store_true")
    notion_bootstrap.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_bootstrap.add_argument("--parent-page-id", help="Approved parent page id in the verified workspace.")
    notion_bootstrap.set_defaults(handler=handle_notion_bootstrap)
    notion_active_work = notion_subparsers.add_parser(
        "active-work-sync",
        help="Plan or apply guarded Notion sync for the generated OS Active Work database.",
    )
    notion_active_work.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_active_work_mode = notion_active_work.add_mutually_exclusive_group(required=True)
    notion_active_work_mode.add_argument("--dry-run", action="store_true")
    notion_active_work_mode.add_argument("--apply", action="store_true")
    notion_active_work.add_argument("--database-id", help="Existing OS Active Work Notion database id.")
    notion_active_work.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_active_work.add_argument("--parent-page-id", help="Explicitly approved parent page containing the OS Active Work database.")
    notion_active_work.add_argument("--token-env", default="GENOMES_NOTION_PAT", help="Environment variable containing the Notion token.")
    notion_active_work.set_defaults(handler=handle_notion_active_work_sync)

    notion_org_parser = subparsers.add_parser(
        "notion-org",
        help="Check Notion IA organization before page moves.",
        description=(
            "Validate Notion information-architecture organization and backup readiness "
            "before performing page moves or structural changes. "
            "Currently supports 'doctor' to check config and verify a local backup exists."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
                ("GENOMES_NOTION_PAT", "Notion API token for read access."),
                ("GENOMES_NOTION_CONNECTOR", "Alternative Notion token (checked second)."),
            ],
            config_files=[
                ("harness/registries/notion-surfaces.yml", "Notion page/database ID registry."),
            ],
            examples=[
                ("agentic-os notion-org doctor", "Check Notion org config and backup readiness."),
                ("agentic-os notion-org doctor --backup-dir ~/notion-backup", "Also verify a local backup directory."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    notion_org_subparsers = notion_org_parser.add_subparsers(dest="notion_org_command", required=True)
    notion_org_doctor_parser = notion_org_subparsers.add_parser("doctor", help="Check Notion organization config and backup readiness.")
    notion_org_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_org_doctor_parser.add_argument("--backup-dir", help="Local Notion backup directory to verify before moves.")
    notion_org_doctor_parser.set_defaults(handler=handle_notion_org_doctor)
