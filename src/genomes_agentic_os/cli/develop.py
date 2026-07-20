"""CLI entry point for the canonical development-delivery program."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..development_delivery import (
    DEVELOPMENT_POLICY_PLANES,
    DevelopmentDeliveryError,
    TaskState,
    resolve_development_policy,
    run_development_stage,
    start_development_run,
)
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
    overlays: dict[str, list[str]] = {}
    for item in args.policy_overlay or []:
        if "=" not in item:
            raise DevelopmentDeliveryError("--policy-overlay must use PLANE=PATH")
        plane, path = item.split("=", 1)
        if plane not in DEVELOPMENT_POLICY_PLANES or not path.strip():
            raise DevelopmentDeliveryError(
                "--policy-overlay plane must be dev_standards, qa_gates, or gitflow_topology"
            )
        overlays.setdefault(plane, []).append(path)
    result = start_development_run(
        args.root,
        args.domain,
        args.project,
        args.tickets,
        titles=titles,
        run_id=args.run_id,
        repository_id=args.repository,
        base_branch=args.base_branch,
        policy_overlays=overlays,
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
    raise DevelopmentDeliveryError(
        "direct lifecycle transitions are disabled because a string receipt cannot prove SDLC work; "
        "use `agentic-os develop stage` with development-stage-evidence/v1 receipts"
    )


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


def handle_policy(args: argparse.Namespace) -> int:
    result = resolve_development_policy(
        args.root,
        args.domain,
        args.project,
        args.plane,
        explicit_files=args.overlay or [],
    )
    _print(result, json_output=args.json)
    return 0


def handle_stage(args: argparse.Namespace) -> int:
    receipts: dict[str, str] = {}
    for item in args.receipt or []:
        if "=" not in item:
            raise DevelopmentDeliveryError("--receipt must use STATE=REFERENCE")
        state, reference = item.split("=", 1)
        if not state.strip() or not reference.strip():
            raise DevelopmentDeliveryError("--receipt must use STATE=REFERENCE")
        receipts[state.strip().lower().replace("-", "_")] = reference.strip()
    result = run_development_stage(
        args.state_file,
        stage=args.stage,
        receipts=receipts,
        idempotency_prefix=args.idempotency_prefix,
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
    start.add_argument(
        "--repository",
        help="Required repository id when the project config declares a multi-repository catalog.",
    )
    start.add_argument(
        "--base-branch",
        help="Explicit ticket/release-derived base branch; recorded in the run instead of changing project defaults.",
    )
    start.add_argument(
        "--policy-overlay",
        action="append",
        help="Invocation policy addendum as PLANE=PATH; repeatable.",
    )
    start.add_argument("--apply", action="store_true", help="Create state, active work items, and isolated worktrees.")
    start.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(start)
    start.set_defaults(handler=handle_start)

    status = sub.add_parser("status", help="Read a portfolio and all task state receipts.")
    status.add_argument("run_dir")
    _common_output(status)
    status.set_defaults(handler=handle_status)

    transition = sub.add_parser("transition", help="Deprecated unsafe transition adapter; always fails closed.")
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

    policy = sub.add_parser(
        "policy",
        help="Resolve the ordered root/domain/project Markdown standards for a development plane.",
    )
    policy.add_argument("domain")
    policy.add_argument("project")
    policy.add_argument("--plane", choices=DEVELOPMENT_POLICY_PLANES, default="dev_standards")
    policy.add_argument("--overlay", action="append", help="Invocation Markdown overlay; repeatable.")
    policy.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(policy)
    policy.set_defaults(handler=handle_policy)

    stage = sub.add_parser(
        "stage",
        help="Manually run one receipt-backed Auto-Dev delivery stage.",
    )
    stage.add_argument("state_file")
    stage.add_argument(
        "--stage",
        required=True,
        choices=("readiness", "implementation", "review", "release_propagation", "closeout"),
    )
    stage.add_argument(
        "--receipt",
        action="append",
        required=True,
        help="State or stage receipt as NAME=REFERENCE; repeat for each transition.",
    )
    stage.add_argument("--idempotency-prefix", required=True)
    _common_output(stage)
    stage.set_defaults(handler=handle_stage)
