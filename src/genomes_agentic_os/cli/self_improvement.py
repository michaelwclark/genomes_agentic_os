"""CLI commands for the self-improvement proposal lifecycle."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..self_improvement import (
    approve_self_improvement_proposal,
    format_self_improvement_result,
    list_self_improvement_proposals,
    list_self_improvement_toggles,
    nightly_apply_self_improvement,
    process_self_improvement_actions,
    promote_self_improvement_proposal,
    reconcile_self_improvement_queue,
    reject_self_improvement_proposal,
    run_self_improvement,
    self_improvement_status,
    set_self_improvement_toggle,
    show_self_improvement_proposal,
)

from ._shared import DEFAULT_ROOT


def handle_self_improvement_run(args: argparse.Namespace) -> int:
    # Bare invocation and --dry-run both produce dry_run=True (read-only, SPEC 15 first-run safety).
    # Only --apply flips to persist mode.
    print(format_self_improvement_result(run_self_improvement(args.root, dry_run=not args.apply)))
    return 0


def handle_self_improvement_status(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(self_improvement_status(args.root)))
    return 0


def handle_self_improvement_list(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(list_self_improvement_proposals(args.root)))
    return 0


def handle_self_improvement_show(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(show_self_improvement_proposal(args.root, args.proposal_id)))
    return 0


def handle_self_improvement_approve(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            approve_self_improvement_proposal(args.root, args.proposal_id, target=args.target)
        )
    )
    return 0


def handle_self_improvement_reject(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(reject_self_improvement_proposal(args.root, args.proposal_id)))
    return 0


def handle_self_improvement_promote(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            promote_self_improvement_proposal(args.root, args.proposal_id, target=args.target)
        )
    )
    return 0


def handle_self_improvement_actions(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(process_self_improvement_actions(args.root, dry_run=not args.apply)))
    return 0


def handle_self_improvement_reconcile_queue(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(reconcile_self_improvement_queue(args.root, dry_run=not args.apply)))
    return 0


def handle_self_improvement_toggles(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(list_self_improvement_toggles(args.root)))
    return 0


def handle_self_improvement_toggle(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            set_self_improvement_toggle(args.root, args.proposal_id, enabled=args.toggle_enabled)
        )
    )
    return 0


def handle_self_improvement_nightly_apply(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            nightly_apply_self_improvement(args.root, dry_run=not args.apply, limit=args.limit)
        )
    )
    return 0


def register(subparsers) -> None:
    """Register the self-improvement command group."""
    self_improvement_parser = subparsers.add_parser(
        "self-improvement",
        help="Review local evidence for proposal-only OS improvements.",
        description=(
            "Analyse run logs, doctor findings, and automation maturity to generate proposal-only OS improvement suggestions. "
            "Proposals are never auto-applied; they require explicit approve + promote steps. "
            "Use 'run --dry-run' (default) to preview without writing, or 'run --apply' to persist proposals and generate a daily report."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
                ("GENOMES_NOTION_PAT", "Notion API token for writing the daily report projection (--apply mode)."),
                ("GENOMES_NOTION_CONNECTOR", "Alternative Notion token (checked second after GENOMES_NOTION_PAT)."),
            ],
            config_files=[
                ("harness/shared_factory/06-self-improvement/", "Self-improvement proposals, run records, and reports."),
                ("harness/registries/self-improvement.yml", "Self-improvement config (review cadence, enabled checks)."),
            ],
            examples=[
                ("agentic-os self-improvement run", "Preview a review without writing anything (dry-run)."),
                ("agentic-os self-improvement run --apply", "Run review and persist proposals + report."),
                ("agentic-os self-improvement list", "List open proposals."),
                ("agentic-os self-improvement approve P042 --target harness/RULES.md", "Approve proposal P042 for a target file."),
                ("agentic-os self-improvement promote P042 --target harness/RULES.md", "Promote approved proposal into a draft."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    self_improvement_subparsers = self_improvement_parser.add_subparsers(
        dest="self_improvement_command",
        required=True,
    )
    self_improvement_run = self_improvement_subparsers.add_parser(
        "run",
        help="Run a self-improvement review (dry-run by default; use --apply to persist + document).",
    )
    self_improvement_run.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_run_mode = self_improvement_run.add_mutually_exclusive_group()
    self_improvement_run_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a review without writing run records, proposals, or a report (default behaviour).",
    )
    self_improvement_run_mode.add_argument(
        "--apply",
        action="store_true",
        help="Persist mode: write run records, proposals, daily report, and Notion projection.",
    )
    self_improvement_run.set_defaults(handler=handle_self_improvement_run)
    self_improvement_status_parser = self_improvement_subparsers.add_parser(
        "status",
        help="Summarize self-improvement run and proposal state.",
    )
    self_improvement_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_status_parser.set_defaults(handler=handle_self_improvement_status)
    self_improvement_list = self_improvement_subparsers.add_parser("list", help="List self-improvement proposals.")
    self_improvement_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_list.set_defaults(handler=handle_self_improvement_list)
    self_improvement_show = self_improvement_subparsers.add_parser("show", help="Show one self-improvement proposal.")
    self_improvement_show.add_argument("proposal_id")
    self_improvement_show.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_show.set_defaults(handler=handle_self_improvement_show)
    self_improvement_approve = self_improvement_subparsers.add_parser(
        "approve",
        help="Approve one proposal for a specific draft target.",
    )
    self_improvement_approve.add_argument("proposal_id")
    self_improvement_approve.add_argument("--target", required=True)
    self_improvement_approve.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_approve.set_defaults(handler=handle_self_improvement_approve)
    self_improvement_reject = self_improvement_subparsers.add_parser("reject", help="Reject one proposal and start cooldown.")
    self_improvement_reject.add_argument("proposal_id")
    self_improvement_reject.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_reject.set_defaults(handler=handle_self_improvement_reject)
    self_improvement_promote = self_improvement_subparsers.add_parser(
        "promote",
        help="Promote an approved proposal into a draft artifact.",
    )
    self_improvement_promote.add_argument("proposal_id")
    self_improvement_promote.add_argument("--target", required=True)
    self_improvement_promote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_promote.set_defaults(handler=handle_self_improvement_promote)
    self_improvement_actions = self_improvement_subparsers.add_parser(
        "actions",
        help="Consume checked Notion action boxes on self-improvement suggestion pages.",
    )
    self_improvement_actions.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_actions_mode = self_improvement_actions.add_mutually_exclusive_group()
    self_improvement_actions_mode.add_argument("--dry-run", action="store_true", help="Preview checked action boxes without queuing workers.")
    self_improvement_actions_mode.add_argument("--apply", action="store_true", help="Queue checked actions and update their Notion pages.")
    self_improvement_actions.set_defaults(handler=handle_self_improvement_actions)
    self_improvement_reconcile = self_improvement_subparsers.add_parser(
        "reconcile-queue",
        help="Mark stale self-improvement review queue rows done when covered by a later successful run.",
    )
    self_improvement_reconcile.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_reconcile_mode = self_improvement_reconcile.add_mutually_exclusive_group()
    self_improvement_reconcile_mode.add_argument("--dry-run", action="store_true", help="Preview queue reconciliation without writing.")
    self_improvement_reconcile_mode.add_argument("--apply", action="store_true", help="Apply local run-queue reconciliation.")
    self_improvement_reconcile.set_defaults(handler=handle_self_improvement_reconcile_queue)
    self_improvement_nightly = self_improvement_subparsers.add_parser(
        "nightly-apply",
        help="Auto-approve low-risk proposals and queue them into OS Work Intake (dry-run by default).",
    )
    self_improvement_nightly.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_nightly.add_argument("--limit", type=int, default=None, help="Cap approvals below the configured max_per_night.")
    self_improvement_nightly_mode = self_improvement_nightly.add_mutually_exclusive_group()
    self_improvement_nightly_mode.add_argument("--dry-run", action="store_true", help="Preview selection without approving, promoting, or queuing (default behaviour).")
    self_improvement_nightly_mode.add_argument("--apply", action="store_true", help="Approve, promote, and queue eligible proposals.")
    self_improvement_nightly.set_defaults(handler=handle_self_improvement_nightly_apply)
    self_improvement_toggles = self_improvement_subparsers.add_parser(
        "toggles",
        help="List per-improvement feature toggles recorded by the auto-implement lane.",
    )
    self_improvement_toggles.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_toggles.set_defaults(handler=handle_self_improvement_toggles)
    self_improvement_toggle = self_improvement_subparsers.add_parser(
        "toggle",
        help="Switch one auto-implemented improvement on or off (off parks its registered artifacts).",
    )
    self_improvement_toggle.add_argument("proposal_id")
    self_improvement_toggle_mode = self_improvement_toggle.add_mutually_exclusive_group(required=True)
    self_improvement_toggle_mode.add_argument(
        "--on",
        dest="toggle_enabled",
        action="store_true",
        help="Enable the improvement and restore its parked artifacts.",
    )
    self_improvement_toggle_mode.add_argument(
        "--off",
        dest="toggle_enabled",
        action="store_false",
        help="Disable the improvement and park its registered artifacts.",
    )
    self_improvement_toggle.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_toggle.set_defaults(handler=handle_self_improvement_toggle)
