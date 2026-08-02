"""CLI commands for operator distribution: updates, license, backup, fleet, metrics."""

from __future__ import annotations

import argparse

from ..metrics_ops import format_metrics_result, metrics_refresh
from ..release_rollout import load_published_release, load_rollout_evidence, rollout_gate
from ..update_ops import (
    activate_license,
    backup_push,
    backup_restore_plan,
    backup_run,
    fleet_push,
    format_update_result,
    phone_home_payload,
    update_apply,
    update_check,
    update_plan,
    update_pull,
    update_register,
    update_rollback,
    update_status,
)

from ._shared import DEFAULT_ROOT


def handle_update_check(args: argparse.Namespace) -> int:
    print(format_update_result(update_check(args.root, manifest=args.manifest)))
    return 0


def handle_update_register(args: argparse.Namespace) -> int:
    print(format_update_result(update_register(args.root)))
    return 0


def handle_update_pull(args: argparse.Namespace) -> int:
    print(format_update_result(update_pull(args.root, dry_run=not args.apply)))
    return 0


def handle_update_plan(args: argparse.Namespace) -> int:
    print(format_update_result(update_plan(args.root, manifest=args.manifest)))
    return 0


def handle_update_apply(args: argparse.Namespace) -> int:
    result = update_apply(args.root, plan=args.plan, approve_risky=args.approve_risky)
    print(format_update_result(result))
    return 2 if result.get("blocked") else 0


def handle_update_rollback(args: argparse.Namespace) -> int:
    print(format_update_result(update_rollback(args.root, snapshot=args.snapshot)))
    return 0


def handle_update_status(args: argparse.Namespace) -> int:
    print(format_update_result(update_status(args.root)))
    return 0


def handle_update_phone_home(args: argparse.Namespace) -> int:
    print(format_update_result(phone_home_payload(args.root)))
    return 0


def handle_update_rollout_gate(args: argparse.Namespace) -> int:
    release = load_published_release(args.release_receipt)
    evidence = load_rollout_evidence(args.evidence) if args.evidence else {}
    result = rollout_gate(release, evidence)
    print(format_update_result(result))
    return 2 if result["status"] in {"blocked", "failed"} else 0


def handle_license_activate(args: argparse.Namespace) -> int:
    print(format_update_result(activate_license(args.root, key=args.key)))
    return 0


def handle_backup_run(args: argparse.Namespace) -> int:
    print(format_update_result(backup_run(args.root, dry_run=not args.apply)))
    return 0


def handle_backup_push(args: argparse.Namespace) -> int:
    print(format_update_result(backup_push(args.root)))
    return 0


def handle_backup_restore_plan(args: argparse.Namespace) -> int:
    print(format_update_result(backup_restore_plan(args.root, backup_log=args.backup_log)))
    return 0


def handle_fleet_push(args: argparse.Namespace) -> int:
    print(format_update_result(fleet_push(args.customer_slug, source=args.source)))
    return 0


def handle_metrics_refresh(args: argparse.Namespace) -> int:
    print(format_metrics_result(metrics_refresh(args.root)))
    return 0


def register(subparsers) -> None:
    """Register the update / license / backup / fleet / metrics command group."""
    update_parser = subparsers.add_parser("update", help="Check, plan, apply, and report installed OS updates.")
    update_subparsers = update_parser.add_subparsers(dest="update_command", required=True)
    update_check_parser = update_subparsers.add_parser("check", help="Check for available updates without mutating files.")
    update_check_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_check_parser.add_argument("--manifest", help="Update manifest YAML or JSON file.")
    update_check_parser.set_defaults(handler=handle_update_check)
    update_register_parser = update_subparsers.add_parser(
        "register",
        help="Generate local update/backup SSH keys and write an update grant.",
    )
    update_register_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_register_parser.set_defaults(handler=handle_update_register)
    update_pull_parser = update_subparsers.add_parser("pull", help="Plan or record an operator-pushed update pull.")
    update_pull_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_pull_mode = update_pull_parser.add_mutually_exclusive_group()
    update_pull_mode.add_argument("--dry-run", action="store_true", default=True)
    update_pull_mode.add_argument("--apply", action="store_true")
    update_pull_parser.set_defaults(handler=handle_update_pull)
    update_plan_parser = update_subparsers.add_parser("plan", help="Write an inspectable update plan.")
    update_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_plan_parser.add_argument("--manifest", help="Update manifest YAML or JSON file.")
    update_plan_parser.set_defaults(handler=handle_update_plan)
    update_apply_parser = update_subparsers.add_parser("apply", help="Apply safe additive update changes.")
    update_apply_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_apply_parser.add_argument("--plan", help="Previously reviewed update plan YAML file.")
    update_apply_parser.add_argument("--approve-risky", action="store_true", help="Allow approved risky changes in the plan.")
    update_apply_parser.set_defaults(handler=handle_update_apply)
    update_rollback_parser = update_subparsers.add_parser("rollback", help="Record rollback against the latest update snapshot.")
    update_rollback_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_rollback_parser.add_argument("--snapshot", help="Specific update snapshot to record.")
    update_rollback_parser.set_defaults(handler=handle_update_rollback)
    update_status_parser = update_subparsers.add_parser("status", help="Show local update status.")
    update_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_status_parser.set_defaults(handler=handle_update_status)
    update_phone_home_parser = update_subparsers.add_parser(
        "phone-home",
        help="Emit a heartbeat-safe operational metadata payload.",
    )
    update_phone_home_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_phone_home_parser.set_defaults(handler=handle_update_phone_home)
    update_rollout_parser = update_subparsers.add_parser(
        "rollout-gate",
        help="Read local release and host receipts to gate the first host before the second; never runs remote actions.",
    )
    update_rollout_parser.add_argument(
        "--release-receipt",
        required=True,
        help="Published release JSON/YAML receipt.",
    )
    update_rollout_parser.add_argument(
        "--evidence",
        help="Local JSON/YAML host receipt mapping; omitted means no host has rolled out.",
    )
    update_rollout_parser.set_defaults(handler=handle_update_rollout_gate)

    license_parser = subparsers.add_parser("license", help="Manage customer OS license metadata.")
    license_subparsers = license_parser.add_subparsers(dest="license_command", required=True)
    license_activate_parser = license_subparsers.add_parser(
        "activate",
        help="Activate a customer license without printing or storing the raw key.",
    )
    license_activate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    license_activate_parser.add_argument("--key", required=True, help="Customer license key.")
    license_activate_parser.set_defaults(handler=handle_license_activate)

    backup_parser = subparsers.add_parser("backup", help="Plan or run GitHub-backed OS state backups.")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command", required=True)
    backup_run_parser = backup_subparsers.add_parser("run", help="Plan or record a backup run.")
    backup_run_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_run_mode = backup_run_parser.add_mutually_exclusive_group()
    backup_run_mode.add_argument("--dry-run", action="store_true", default=True)
    backup_run_mode.add_argument("--apply", action="store_true")
    backup_run_parser.set_defaults(handler=handle_backup_run)
    backup_push_parser = backup_subparsers.add_parser(
        "push",
        help=(
            "Record a local backup push run log. "
            "Skips remote push when update grant is absent (no creds); always logs locally."
        ),
    )
    backup_push_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_push_parser.set_defaults(handler=handle_backup_push)
    backup_restore_plan_parser = backup_subparsers.add_parser(
        "restore-plan",
        help="Build a read-only operator restore plan from the latest backup log and policy.",
    )
    backup_restore_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_restore_plan_parser.add_argument("--backup-log", help="Specific backup log YAML to plan from.")
    backup_restore_plan_parser.set_defaults(handler=handle_backup_restore_plan)

    fleet_parser = subparsers.add_parser("fleet", help="Operator fleet management commands.")
    fleet_subparsers = fleet_parser.add_subparsers(dest="fleet_command", required=True)
    fleet_push_parser = fleet_subparsers.add_parser(
        "push",
        help=(
            "Record a simulated operator-push event for a customer installation. "
            "V1 local-only: no real SSH or network calls."
        ),
    )
    fleet_push_parser.add_argument("customer_slug", help="Customer slug (snake_case).")
    fleet_push_parser.add_argument(
        "--source",
        default="latest",
        help="Release ref or tag to push (default: latest).",
    )
    fleet_push_parser.set_defaults(handler=handle_fleet_push)

    metrics_parser = subparsers.add_parser("metrics", help="Compute and view OS metrics scorecards.")
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command", required=True)
    metrics_refresh_parser = metrics_subparsers.add_parser(
        "refresh",
        help=(
            "Compute a metrics scorecard from run logs, doctor findings, and automation maturity. "
            "Writes result to harness/shared_factory/07-metrics/scorecard.yml."
        ),
    )
    metrics_refresh_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    metrics_refresh_parser.set_defaults(handler=handle_metrics_refresh)
