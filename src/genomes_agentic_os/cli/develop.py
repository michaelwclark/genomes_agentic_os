"""CLI entry point for the canonical development-delivery program."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..development_delivery import DevelopmentDeliveryError, TaskState, start_development_run
from ._shared import DEFAULT_ROOT, yaml_dump


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, sort_keys=True) if json_output else yaml_dump(value))


def handle_start(args: argparse.Namespace) -> int:
    titles: dict[str, str] = {}
    for item in args.title or []:
        if "=" not in item:
            raise DevelopmentDeliveryError("--title must use TICKET=Title")
        ticket, title = item.split("=", 1)
        titles[ticket] = title
    result = start_development_run(
        args.root,
        args.domain,
        args.project,
        args.tickets,
        titles=titles,
        run_id=args.run_id,
        apply=args.apply,
    )
    _print(result, json_output=args.json)
    return 0


def handle_status(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    portfolio = json.loads((run_dir / "portfolio.json").read_text(encoding="utf-8"))
    tasks = []
    for state_path in sorted((run_dir / "tasks").glob("*/state.json")):
        tasks.append(TaskState(state_path).read())
    _print({"portfolio": portfolio, "tasks": tasks}, json_output=args.json)
    return 0


def handle_transition(args: argparse.Namespace) -> int:
    result = TaskState(Path(args.state_file).expanduser().resolve()).transition(
        args.to,
        receipt=args.receipt,
        idempotency_key=args.idempotency_key,
    )
    _print(result, json_output=args.json)
    return 0


def handle_fail(args: argparse.Namespace) -> int:
    result = TaskState(Path(args.state_file).expanduser().resolve()).fail(
        kind=args.kind,
        detail=args.detail,
        receipt=args.receipt,
        idempotency_key=args.idempotency_key,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("state") != "blocked" else 1


def handle_recover(args: argparse.Namespace) -> int:
    result = TaskState(Path(args.state_file).expanduser().resolve()).recover(
        receipt=args.receipt,
        idempotency_key=args.idempotency_key,
    )
    _print(result, json_output=args.json)
    return 0


def handle_heartbeat(args: argparse.Namespace) -> int:
    result = TaskState(Path(args.state_file).expanduser().resolve()).heartbeat(
        owner=args.owner,
        lease_minutes=args.lease_minutes,
        idempotency_key=args.idempotency_key,
    )
    _print(result, json_output=args.json)
    return 0


def _common_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "develop",
        help="Run one or many tracker tickets through canonical programming delivery.",
        description=(
            "Create or resume a receipt-backed portfolio. Dry-run is the default; --apply creates one active "
            "work item and one isolated project worktree per ticket, then hands each task to the configured harness."
        ),
    )
    sub = parser.add_subparsers(dest="develop_command", required=True)

    start = sub.add_parser("start", help="Plan or start a 1-N development portfolio.")
    start.add_argument("domain")
    start.add_argument("project")
    start.add_argument("tickets", nargs="+")
    start.add_argument("--title", action="append", help="Optional TICKET=Title mapping; repeat per ticket.")
    start.add_argument("--run-id", help="Stable caller-provided idempotency key/run identifier.")
    start.add_argument("--apply", action="store_true", help="Create state, active work items, and isolated worktrees.")
    start.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(start)
    start.set_defaults(handler=handle_start)

    status = sub.add_parser("status", help="Read a portfolio and all task state receipts.")
    status.add_argument("run_dir")
    _common_output(status)
    status.set_defaults(handler=handle_status)

    transition = sub.add_parser("transition", help="Advance one task by one legal receipt-backed state.")
    transition.add_argument("state_file")
    transition.add_argument("--to", required=True)
    transition.add_argument("--receipt", required=True)
    transition.add_argument("--idempotency-key", required=True)
    _common_output(transition)
    transition.set_defaults(handler=handle_transition)

    fail = sub.add_parser("fail", help="Record a classified failure and retry or block according to policy.")
    fail.add_argument("state_file")
    fail.add_argument("--kind", required=True)
    fail.add_argument("--detail", required=True)
    fail.add_argument("--receipt", required=True)
    fail.add_argument("--idempotency-key", required=True)
    _common_output(fail)
    fail.set_defaults(handler=handle_fail)

    recover = sub.add_parser("recover", help="Resume a task from its recorded recoverable failure state.")
    recover.add_argument("state_file")
    recover.add_argument("--receipt", required=True)
    recover.add_argument("--idempotency-key", required=True)
    _common_output(recover)
    recover.set_defaults(handler=handle_recover)

    heartbeat = sub.add_parser("heartbeat", help="Renew a non-terminal task worker lease.")
    heartbeat.add_argument("state_file")
    heartbeat.add_argument("--owner", required=True)
    heartbeat.add_argument("--lease-minutes", type=int, default=30)
    heartbeat.add_argument("--idempotency-key", required=True)
    _common_output(heartbeat)
    heartbeat.set_defaults(handler=handle_heartbeat)
