"""CLI commands for runtime registries, heartbeats, schedules, queues, integrations."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..runtime_ops import (
    format_runtime_result,
    heartbeat_list,
    heartbeat_run,
    integration_doctor,
    integration_list,
    integration_setup,
    run_queue_prune,
    runtime_doctor,
    runtime_init,
    runtime_run_next,
    schedule_create,
    schedule_run_due,
)
from ..supervisor import format_supervise_result, supervise_tick

from ._shared import DEFAULT_ROOT


def _add_run_queue_prune_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    parser.add_argument(
        "--active-max-age-hours",
        type=int,
        default=24,
        help="Prune queued/running/approval-needed items older than this many hours.",
    )
    parser.add_argument("--terminal-max-age-days", type=int, default=2, help="Prune done items older than this many days.")
    parser.add_argument("--failed-max-age-days", type=int, default=7, help="Prune failed/blocked items older than this many days.")
    parser.add_argument("--skipped-max-age-days", type=int, default=1, help="Prune skipped/dry-run items older than this many days.")
    parser.add_argument("--backup-max-age-days", type=int, default=7, help="Remove run-queue backup files older than this many days.")
    parser.add_argument(
        "--archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Archive pruned queue items under run-queue-prune logs.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")


def handle_runtime_init(args: argparse.Namespace) -> int:
    print(format_runtime_result(runtime_init(args.root)))
    return 0


def handle_runtime_doctor(args: argparse.Namespace) -> int:
    result = runtime_doctor(args.root)
    print(format_runtime_result(result))
    return 0 if result["ok"] else 1


def handle_runtime_run_next(args: argparse.Namespace) -> int:
    result = runtime_run_next(args.root, dry_run=not args.apply, item_id=args.item_id)
    print(format_runtime_result(result))
    return 0 if not args.apply or result["status"] not in {"failed", "blocked"} else 1


def handle_run_queue_prune(args: argparse.Namespace) -> int:
    result = run_queue_prune(
        args.root,
        dry_run=not args.apply,
        active_max_age_hours=args.active_max_age_hours,
        terminal_max_age_days=args.terminal_max_age_days,
        failed_max_age_days=args.failed_max_age_days,
        skipped_max_age_days=args.skipped_max_age_days,
        backup_max_age_days=args.backup_max_age_days,
        archive=args.archive,
    )
    print(format_runtime_result(result))
    return 0


def handle_runtime_supervise(args: argparse.Namespace) -> int:
    result = supervise_tick(args.root, dry_run=not args.apply)
    print(format_supervise_result(result))
    return 0 if result["ok"] else 1


def handle_heartbeat_list(args: argparse.Namespace) -> int:
    print(format_runtime_result(heartbeat_list(args.root)))
    return 0


def handle_heartbeat_run(args: argparse.Namespace) -> int:
    print(format_runtime_result(heartbeat_run(args.root, args.heartbeat_id, dry_run=not args.apply)))
    return 0


def handle_schedule_create(args: argparse.Namespace) -> int:
    print(
        format_runtime_result(
            schedule_create(
                args.root,
                args.schedule_id,
                cadence=args.cadence,
                timezone_name=args.timezone,
                command=args.command,
            )
        )
    )
    return 0


def handle_schedule_run_due(args: argparse.Namespace) -> int:
    print(format_runtime_result(schedule_run_due(args.root, dry_run=not args.apply)))
    return 0


def handle_integration_list(args: argparse.Namespace) -> int:
    print(format_runtime_result(integration_list(args.root)))
    return 0


def handle_integration_setup(args: argparse.Namespace) -> int:
    print(format_runtime_result(integration_setup(args.root, args.integration_id, dry_run=not args.apply)))
    return 0


def handle_integration_doctor(args: argparse.Namespace) -> int:
    result = integration_doctor(args.root, args.integration_id)
    print(format_runtime_result(result))
    return 0 if result["ok"] else 1


def register(subparsers) -> None:
    """Register the runtime / heartbeat / schedule / run-queue / integration command group."""
    runtime_parser = subparsers.add_parser(
        "runtime",
        help="Manage file-backed runtime state.",
        description=(
            "Manage the file-backed runtime surface: registries, run queue, heartbeats, schedules, integrations, and sources. "
            "All mutating subcommands default to --dry-run; pass --apply to write changes. "
            "'runtime supervise' runs a full supervisor tick across all subsystems at once."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/runtime-registry.yml", "Runtime registry: schedules, heartbeats, integrations."),
                ("harness/registries/run-queue.yml", "Run queue: pending and in-progress items."),
                ("harness/registries/automation-run-tracking.yml", "Automation run tracking."),
            ],
            examples=[
                ("agentic-os runtime init", "Create runtime registries and log folders."),
                ("agentic-os runtime doctor", "Check runtime registry health."),
                ("agentic-os runtime supervise --apply", "Run a full supervisor tick across all subsystems."),
                ("agentic-os runtime run-next --apply", "Dispatch the next safe queued item."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_init_parser = runtime_subparsers.add_parser("init", help="Create runtime registries and log folders.")
    runtime_init_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_init_parser.set_defaults(handler=handle_runtime_init)
    runtime_doctor_parser = runtime_subparsers.add_parser("doctor", help="Check runtime registry health.")
    runtime_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_doctor_parser.set_defaults(handler=handle_runtime_doctor)
    runtime_run_next_parser = runtime_subparsers.add_parser("run-next", help="Dispatch the next safe queued runtime item.")
    runtime_run_next_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_run_next_parser.add_argument("--item-id", help="Specific queue item id to inspect or dispatch.")
    runtime_run_next_mode = runtime_run_next_parser.add_mutually_exclusive_group()
    runtime_run_next_mode.add_argument("--dry-run", action="store_true", default=True)
    runtime_run_next_mode.add_argument("--apply", action="store_true")
    runtime_run_next_parser.set_defaults(handler=handle_runtime_run_next)
    runtime_prune_parser = runtime_subparsers.add_parser("prune", help="Prune stale run-queue items and old run-queue backups.")
    _add_run_queue_prune_args(runtime_prune_parser)
    runtime_prune_parser.set_defaults(handler=handle_run_queue_prune)
    runtime_supervise_parser = runtime_subparsers.add_parser(
        "supervise",
        help="Run one supervisor tick across the runtime surface (heartbeats, schedules, sources, events, run queue) plus a health check.",
    )
    runtime_supervise_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_supervise_mode = runtime_supervise_parser.add_mutually_exclusive_group()
    runtime_supervise_mode.add_argument("--dry-run", action="store_true", default=True)
    runtime_supervise_mode.add_argument("--apply", action="store_true")
    runtime_supervise_parser.set_defaults(handler=handle_runtime_supervise)

    heartbeat_parser = subparsers.add_parser("heartbeat", help="Manage runtime heartbeats.")
    heartbeat_subparsers = heartbeat_parser.add_subparsers(dest="heartbeat_command", required=True)
    heartbeat_list_parser = heartbeat_subparsers.add_parser("list", help="List configured heartbeats.")
    heartbeat_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_list_parser.set_defaults(handler=handle_heartbeat_list)
    heartbeat_run_parser = heartbeat_subparsers.add_parser("run", help="Run or dry-run a heartbeat.")
    heartbeat_run_parser.add_argument("heartbeat_id")
    heartbeat_run_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_run_mode = heartbeat_run_parser.add_mutually_exclusive_group()
    heartbeat_run_mode.add_argument("--dry-run", action="store_true", default=True)
    heartbeat_run_mode.add_argument("--apply", action="store_true")
    heartbeat_run_parser.set_defaults(handler=handle_heartbeat_run)
    heartbeat_doctor_parser = heartbeat_subparsers.add_parser("doctor", help="Check runtime heartbeat health.")
    heartbeat_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_doctor_parser.set_defaults(handler=handle_runtime_doctor)

    schedule_parser = subparsers.add_parser("schedule", help="Manage runtime schedules.")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command", required=True)
    schedule_create_parser = schedule_subparsers.add_parser("create", help="Create a schedule in the runtime registry.")
    schedule_create_parser.add_argument("schedule_id")
    schedule_create_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    schedule_create_parser.add_argument("--cadence", default="manual")
    schedule_create_parser.add_argument("--timezone", default="America/Chicago")
    schedule_create_parser.add_argument("--command")
    schedule_create_parser.set_defaults(handler=handle_schedule_create)
    schedule_run_due_parser = schedule_subparsers.add_parser("run-due", help="Queue due schedules without executing external effects.")
    schedule_run_due_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    schedule_run_due_mode = schedule_run_due_parser.add_mutually_exclusive_group()
    schedule_run_due_mode.add_argument("--dry-run", action="store_true", default=True)
    schedule_run_due_mode.add_argument("--apply", action="store_true")
    schedule_run_due_parser.set_defaults(handler=handle_schedule_run_due)

    run_queue_parser = subparsers.add_parser("run-queue", help="Manage the runtime run queue.")
    run_queue_subparsers = run_queue_parser.add_subparsers(dest="run_queue_command", required=True)
    run_queue_prune_parser = run_queue_subparsers.add_parser("prune", help="Prune stale run-queue items and old run-queue backups.")
    _add_run_queue_prune_args(run_queue_prune_parser)
    run_queue_prune_parser.set_defaults(handler=handle_run_queue_prune)

    integration_parser = subparsers.add_parser("integration", help="Manage runtime integrations.")
    integration_subparsers = integration_parser.add_subparsers(dest="integration_command", required=True)
    integration_list_parser = integration_subparsers.add_parser("list", help="List configured integrations.")
    integration_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_list_parser.set_defaults(handler=handle_integration_list)
    integration_setup_parser = integration_subparsers.add_parser("setup", help="Dry-run or record integration setup.")
    integration_setup_parser.add_argument("integration_id")
    integration_setup_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_setup_mode = integration_setup_parser.add_mutually_exclusive_group()
    integration_setup_mode.add_argument("--dry-run", action="store_true", default=True)
    integration_setup_mode.add_argument("--apply", action="store_true")
    integration_setup_parser.set_defaults(handler=handle_integration_setup)
    integration_doctor_parser = integration_subparsers.add_parser("doctor", help="Check integration setup contracts.")
    integration_doctor_parser.add_argument("integration_id", nargs="?")
    integration_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_doctor_parser.set_defaults(handler=handle_integration_doctor)
