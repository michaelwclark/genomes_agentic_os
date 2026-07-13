"""CLI commands for live work status, run logs, and thread closeouts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..cli_help import AosHelpFormatter, env_epilog
from ..event_graph import emit_run_close_event
from ..ps_ops import format_ps_result, ps_snapshot
from ..scaffold import create_run_log
from ..thread_closeout import (
    DEFAULT_STALE_DAYS,
    WORK_LEVELS,
    close_thread,
    format_thread_closeout_result,
    stale_finalize_threads,
)
from ..workflow_ops import close_run_log

from ._shared import DEFAULT_ROOT, print_result, yaml_dump


def handle_run_log_create(args: argparse.Namespace) -> int:
    print_result(create_run_log(args.root, args.domain, args.workflow_or_automation))
    return 0


def handle_run_log_close(args: argparse.Namespace) -> int:
    result = close_run_log(
        args.root,
        args.domain,
        args.run_id,
        status=args.status,
        summary=args.summary,
        validation=args.validation,
        artifacts=args.artifact,
        approvals=args.approval,
        next_action=args.next_action,
        owner=args.owner,
        learning=args.learning,
        project=args.project,
    )
    if args.emit_events:
        result["emitted_event"] = emit_run_close_event(args.root, result)
    print(yaml_dump(result))
    return 0


def handle_thread_closeout(args: argparse.Namespace) -> int:
    result = close_thread(
        args.root,
        mode=args.closeout_mode,
        thread_id=args.thread_id,
        domain=args.domain,
        project=args.project,
        work_item=args.work_item,
        work_level=args.work_level,
        summary=args.summary,
        next_action=args.next_action,
        validations=args.validation,
        artifacts=args.artifact,
        receipts=args.receipt,
        memory_receipts=args.memory_receipt,
        notion_url=args.notion_url,
        notion_warning=args.notion_warning,
        verified_notion_workspace=args.verified_notion_workspace,
        skip_notion=args.skip_notion,
        allow_blocked_archive=args.allow_blocked_archive,
        request=args.request,
        cwd=args.cwd,
    )
    print(format_thread_closeout_result(result))
    return 0


def handle_thread_stale_finalize(args: argparse.Namespace) -> int:
    result = stale_finalize_threads(
        args.root,
        older_than_days=args.older_than_days,
        domain=args.domain,
        project=args.project,
        apply=args.apply,
    )
    print(format_thread_closeout_result(result))
    return 0


def handle_ps(args: argparse.Namespace) -> int:
    mode = "all" if args.all else "active" if args.active else "now"
    color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())
    result = ps_snapshot(
        args.root,
        mode=mode,
        limit=args.limit,
        stale_days=args.stale_days,
    )
    result["prog"] = Path(sys.argv[0]).name if Path(sys.argv[0]).name in {"agentic-os", "aos"} else "agentic-os"
    print(format_ps_result(result, as_json=args.json, color=color))
    return 0


def register(subparsers) -> None:
    """Register the ps / run-log / thread / end-chat / finalize / cleanup-thread / archive command group."""
    def add_thread_closeout_args(closeout_parser: argparse.ArgumentParser, mode: str) -> None:
        closeout_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
        closeout_parser.add_argument("--domain", help="Domain that owns the work item.")
        closeout_parser.add_argument("--project", help="Project that owns the work item.")
        closeout_parser.add_argument("--work-item", help="Work item id, slug, title, or ticket.")
        closeout_parser.add_argument("--thread-id", help="Stable closeout id. Defaults to a timestamped id.")
        closeout_parser.add_argument("--work-level", choices=WORK_LEVELS, help="Closeout work level.")
        closeout_parser.add_argument("--summary", help="One-line closeout result.")
        closeout_parser.add_argument("--next-action", help="Concrete next action, or None.")
        closeout_parser.add_argument("--validation", action="append", default=[], help="Validation receipt to record.")
        closeout_parser.add_argument("--artifact", action="append", default=[], help="Artifact path or identifier to record.")
        closeout_parser.add_argument("--receipt", action="append", default=[], help="Command, PR, ticket, or external receipt.")
        closeout_parser.add_argument("--memory-receipt", action="append", default=[], help="Durable memory write or skip receipt.")
        closeout_parser.add_argument("--notion-url", help="Verified Genome's Notion projection URL to record.")
        closeout_parser.add_argument("--notion-warning", help="Non-blocking Notion projection warning to record.")
        closeout_parser.add_argument(
            "--verified-notion-workspace",
            help="Workspace verified for a supplied Notion projection. Must be Genome's Notion.",
        )
        closeout_parser.add_argument("--skip-notion", action="store_true", help="Record Notion projection as skipped.")
        closeout_parser.add_argument(
            "--allow-blocked-archive",
            action="store_true",
            help="Allow archive mode even when --next-action is unresolved.",
        )
        closeout_parser.add_argument("--request", help="Optional request text used for work-item disambiguation.")
        closeout_parser.add_argument("--cwd", help="Current working directory for context detection. Defaults to process cwd.")
        closeout_parser.set_defaults(handler=handle_thread_closeout, closeout_mode=mode)

    def add_stale_finalize_args(stale_parser: argparse.ArgumentParser) -> None:
        stale_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
        stale_parser.add_argument("--domain", help="Limit stale sweep to a domain.")
        stale_parser.add_argument("--project", help="Limit stale sweep to a project.")
        stale_parser.add_argument(
            "--older-than-days",
            type=int,
            default=DEFAULT_STALE_DAYS,
            help=f"Finalize candidates untouched for more than this many days (default: {DEFAULT_STALE_DAYS}).",
        )
        stale_mode = stale_parser.add_mutually_exclusive_group()
        stale_mode.add_argument("--dry-run", action="store_true", default=True, help="List candidates without writing.")
        stale_mode.add_argument("--apply", action="store_true", help="Write conservative status-only closeouts.")
        stale_parser.set_defaults(handler=handle_thread_stale_finalize)

    ps_parser = subparsers.add_parser(
        "ps",
        help="Show Agentic OS work running right now; use --active for the broader dashboard.",
        description=(
            "Show the current Agentic OS work snapshot. "
            "Default (no flags): in-flight async runs and recently started items. "
            "--active: adds queued work, enabled automations/schedules/watchers, and stale thread candidates. "
            "--all: includes disabled and terminal registry/queue rows."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/run-queue.yml", "Run-queue state read for active items."),
                ("harness/registries/runtime-registry.yml", "Runtime registry (schedules, heartbeats, integrations)."),
                ("harness/registries/automation-run-tracking.yml", "Automation run tracking state."),
            ],
            examples=[
                ("agentic-os ps", "Show in-flight runs only."),
                ("agentic-os ps --active", "Show full active work dashboard."),
                ("agentic-os ps --all --json", "Emit all rows as JSON."),
                ("agentic-os ps --limit 0", "Show all rows with no row cap."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    ps_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    ps_parser.add_argument("--json", action="store_true", help="Emit the snapshot as JSON.")
    ps_mode = ps_parser.add_mutually_exclusive_group()
    ps_mode.add_argument(
        "--active",
        action="store_true",
        help="Show queued work, enabled automations/schedules/watchers, active workflows, and stale thread candidates.",
    )
    ps_mode.add_argument("--all", action="store_true", help="Include disabled and terminal registry/queue rows.")
    ps_parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize table output (default: auto).",
    )
    ps_parser.add_argument(
        "--limit",
        type=int,
        default=120,
        help="Maximum rows to print; use 0 for no limit.",
    )
    ps_parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Thread stale-candidate threshold in days (default: {DEFAULT_STALE_DAYS}).",
    )
    ps_parser.set_defaults(handler=handle_ps)

    run_log_parser = subparsers.add_parser("run-log", help="Manage run logs.")
    run_log_subparsers = run_log_parser.add_subparsers(dest="run_log_command", required=True)
    run_log_create = run_log_subparsers.add_parser("create", help="Create a timestamped run log.")
    run_log_create.add_argument("domain")
    run_log_create.add_argument("workflow_or_automation")
    run_log_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_create.set_defaults(handler=handle_run_log_create)
    run_log_close = run_log_subparsers.add_parser("close", help="Close a run log with audit evidence.")
    run_log_close.add_argument("domain")
    run_log_close.add_argument("run_id")
    run_log_close.add_argument("--status", required=True, choices=("done", "waiting", "failed", "needs_approval"))
    run_log_close.add_argument("--summary", default="")
    run_log_close.add_argument("--validation", action="append", default=[])
    run_log_close.add_argument("--artifact", action="append", default=[])
    run_log_close.add_argument("--approval", action="append", default=[])
    run_log_close.add_argument("--next-action", default="")
    run_log_close.add_argument("--owner", default="OS Owner")
    run_log_close.add_argument("--learning", default="")
    run_log_close.add_argument("--project")
    run_log_close.add_argument("--emit-events", action="store_true")
    run_log_close.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_close.set_defaults(handler=handle_run_log_close)

    thread_parser = subparsers.add_parser("thread", help="Manage thread lifecycle closeouts.")
    thread_subparsers = thread_parser.add_subparsers(dest="thread_command", required=True)
    thread_end = thread_subparsers.add_parser("end", help="Finalize the current thread without archiving.")
    add_thread_closeout_args(thread_end, "artifact-closeout")
    thread_finalize = thread_subparsers.add_parser("finalize", help="Alias for thread end.")
    add_thread_closeout_args(thread_finalize, "artifact-closeout")
    thread_cleanup = thread_subparsers.add_parser("cleanup", help="Finalize and classify generated dirt without deletion.")
    add_thread_closeout_args(thread_cleanup, "cleanup")
    thread_archive = thread_subparsers.add_parser("archive", help="Finalize and archive when no unresolved next action remains.")
    add_thread_closeout_args(thread_archive, "archive")
    thread_stale = thread_subparsers.add_parser("stale-finalize", help="Dry-run or apply stale thread finalization.")
    add_stale_finalize_args(thread_stale)

    end_chat_parser = subparsers.add_parser("end-chat", help="Alias for agentic-os thread end.")
    add_thread_closeout_args(end_chat_parser, "artifact-closeout")
    finalize_parser = subparsers.add_parser("finalize", help="Alias for agentic-os thread finalize.")
    add_thread_closeout_args(finalize_parser, "artifact-closeout")
    cleanup_thread_parser = subparsers.add_parser("cleanup-thread", help="Alias for agentic-os thread cleanup.")
    add_thread_closeout_args(cleanup_thread_parser, "cleanup")
    archive_thread_parser = subparsers.add_parser("archive", help="Alias for agentic-os thread archive.")
    add_thread_closeout_args(archive_thread_parser, "archive")
