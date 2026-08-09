"""CLI facade for the plain-English Auto-Dev program."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..auto_dev_orchestration import (
    AUTO_DEV_STAGE_ORDER,
    prepare_auto_dev_health,
    read_auto_dev_state,
    record_auto_dev_stage,
    sync_delivery_projection,
)
from ..development_delivery import (
    DEVELOPMENT_POLICY_PLANES,
    DevelopmentDeliveryError,
    reconcile_historical_delivery,
    reopen_auto_dev_item,
    start_development_run,
)
from ._shared import DEFAULT_ROOT, yaml_dump


ACTION_TO_STAGE = {
    "groom": "groom",
    "grooming": "groom",
    "detective": "detective",
    "investigate": "detective",
    "create-artifacts": "create_artifacts",
    "create": "create_artifacts",
    "readiness": "readiness",
    "develop": "develop",
    "document": "document",
    "pr-create": "pr_create",
    "create-pr": "pr_create",
    "review-self": "review_self",
    "review-others": "review_others",
    "qa": "qa",
    "propagate": "pr_create",
    "release-propagation": "pr_create",
    "finalize": "finalize",
    "release": "release",
    "merge": "merge",
    "deploy": "deploy",
    "closeout": "closeout",
    "health": "health",
}
WORKTREE_REQUIRED_STAGES = {
    "readiness",
    "develop",
    "pr_create",
    "qa",
    "review_self",
    "finalize",
    "merge",
    "release",
    "deploy",
    "closeout",
}
EXISTING_STATE_REQUIRED_ACTIONS = {"merge", "deploy", "closeout", "health"}


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, sort_keys=True) if json_output else yaml_dump(value))


def _overlays(values: list[str] | None) -> dict[str, list[str]]:
    overlays: dict[str, list[str]] = {}
    for item in values or []:
        if "=" not in item:
            raise DevelopmentDeliveryError("--policy-overlay must use PLANE=PATH")
        plane, path = item.split("=", 1)
        if plane not in DEVELOPMENT_POLICY_PLANES or not path.strip():
            raise DevelopmentDeliveryError(
                f"--policy-overlay plane must be one of: {', '.join(DEVELOPMENT_POLICY_PLANES)}"
            )
        overlays.setdefault(plane, []).append(path)
    return overlays


def handle_launch(args: argparse.Namespace) -> int:
    action = args.auto_dev_action
    mode = action if action in {"default", "everything"} else "single_stage"
    requested_stage = None if mode in {"default", "everything"} else ACTION_TO_STAGE[action]
    domain = args.domain
    project = args.project
    tickets = list(args.tickets or [])
    run_id = args.run_id
    selected_work_item: Path | None = None
    if action in EXISTING_STATE_REQUIRED_ACTIONS and not args.state:
        raise DevelopmentDeliveryError(
            f"auto-dev {action} requires --state for an existing work item"
        )
    if args.state:
        selected_state = Path(args.state).expanduser().resolve()
        if selected_state.is_dir():
            selected_state = selected_state / "autodev.json"
        existing = read_auto_dev_state(args.state)
        selected_work_item = selected_state.parent
        state_domain = str(existing.get("domain") or "")
        state_project = str(existing.get("project") or "")
        state_ticket = str(existing.get("source", {}).get("key") or "")
        state_run_id = str(existing.get("delivery", {}).get("run_id") or "")
        if not all((state_domain, state_project, state_ticket, state_run_id)):
            raise DevelopmentDeliveryError(
                "--state must reference autodev.json with domain, project, source key, and delivery run id"
            )
        if domain and domain != state_domain:
            raise DevelopmentDeliveryError("--state domain does not match the positional domain")
        if project and project != state_project:
            raise DevelopmentDeliveryError("--state project does not match the positional project")
        if tickets and tickets != [state_ticket]:
            raise DevelopmentDeliveryError("--state ticket does not match the positional ticket")
        if run_id and run_id != state_run_id:
            raise DevelopmentDeliveryError("--run-id does not match the selected autodev.json")
        domain, project, tickets, run_id = state_domain, state_project, [state_ticket], state_run_id
    if not domain or not project or not tickets:
        raise DevelopmentDeliveryError(
            "provide DOMAIN PROJECT TICKET, or use --state <work-item-or-autodev.json>"
        )
    titles: dict[str, str] = {}
    for item in args.title or []:
        if "=" not in item:
            raise DevelopmentDeliveryError("--title must use TICKET=Title")
        ticket, title = item.split("=", 1)
        titles[ticket] = title
    launch_result = start_development_run(
        args.root,
        domain,
        project,
        tickets,
        titles=titles,
        run_id=run_id,
        repository_id=args.repository,
        base_branch=args.base_branch,
        policy_overlays=_overlays(args.policy_overlay),
        touched_paths=args.touched_path or [],
        subjects=args.subject or [],
        rulebook_ids=args.rulebook_id or [],
        auto_dev_mode=mode,
        requested_stage=requested_stage,
        goal=None if mode in {"default", "everything"} else requested_stage,
        provision_worktree=(mode in {"default", "everything"} or requested_stage in WORKTREE_REQUIRED_STAGES),
        selected_work_item=selected_work_item,
        existing_state_only=action in EXISTING_STATE_REQUIRED_ACTIONS,
        apply=args.apply,
    )
    if action == "health":
        result = prepare_auto_dev_health(args.state, apply=args.apply)
    else:
        result = launch_result
    _print(result, json_output=args.json)
    return 0


def handle_status(args: argparse.Namespace) -> int:
    _print(read_auto_dev_state(args.state), json_output=args.json)
    return 0


def handle_sync(args: argparse.Namespace) -> int:
    result = sync_delivery_projection(args.task_state)
    if result is None:
        raise DevelopmentDeliveryError("task state is not linked to a work item")
    _print(result, json_output=args.json)
    return 0


def handle_record(args: argparse.Namespace) -> int:
    result = record_auto_dev_stage(
        args.state,
        stage=args.stage,
        evidence_file=args.evidence,
        idempotency_key=args.idempotency_key,
    )
    _print(result, json_output=args.json)
    return 0


def handle_adopt(args: argparse.Namespace) -> int:
    result = start_development_run(
        args.root,
        args.domain,
        args.project,
        [args.ticket],
        titles=({args.ticket: args.title} if args.title else None),
        run_id=args.run_id,
        repository_id=args.repository,
        base_branch=args.base_branch,
        auto_dev_mode="everything",
        requested_stage=None,
        goal="delivery_complete",
        provision_worktree=False,
        selected_work_item=args.state,
        adopt_existing=True,
        apply=args.apply,
    )
    _print(result, json_output=args.json)
    return 0


def handle_reconcile_historical(args: argparse.Namespace) -> int:
    result = reconcile_historical_delivery(
        args.state,
        evidence_file=args.evidence,
        idempotency_key=args.idempotency_key,
        apply=args.apply,
    )
    _print(result, json_output=args.json)
    return 0


def handle_reopen(args: argparse.Namespace) -> int:
    result = reopen_auto_dev_item(
        args.root,
        args.state,
        run_id=args.run_id,
        reason=args.reason,
        requested_stage=args.stage,
        repository_id=args.repository,
        base_branch=args.base_branch,
        touched_paths=args.touched_path or [],
        subjects=args.subject or [],
        rulebook_ids=args.rulebook_id or [],
        reselect_context=args.reselect_context,
        apply=args.apply,
    )
    _print(result, json_output=args.json)
    return 0


def _common_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _launch_parser(subparsers, action: str, help_text: str) -> None:
    parser = subparsers.add_parser(action, help=help_text)
    parser.add_argument("domain", nargs="?")
    parser.add_argument("project", nargs="?")
    parser.add_argument("tickets", nargs="*")
    parser.add_argument(
        "--state",
        help="Resume and retarget an existing work-item directory or autodev.json.",
    )
    parser.add_argument("--title", action="append", help="Optional TICKET=Title mapping; repeat per ticket.")
    parser.add_argument("--run-id", help="Stable run identifier for safe resume.")
    parser.add_argument("--repository", help="Repository id for a multi-repository project.")
    parser.add_argument("--base-branch", help="Ticket/release-authoritative base branch.")
    parser.add_argument(
        "--policy-overlay",
        action="append",
        help="Invocation policy addendum as PLANE=PATH; repeatable.",
    )
    parser.add_argument(
        "--touched-path",
        action="append",
        help="Normalized repository-relative changed path for frozen context-kit selection; repeatable.",
    )
    parser.add_argument(
        "--subject",
        action="append",
        help="Declared semantic work subject for frozen context-kit selection; repeatable.",
    )
    parser.add_argument(
        "--rulebook-id",
        action="append",
        help="Exact Rules Engine rulebook identity for concrete catalog-kit selection; repeatable.",
    )
    apply_help = (
        "Resume the selected existing work item; this action never creates a replacement packet or worktree."
        if action in EXISTING_STATE_REQUIRED_ACTIONS
        else "Create/resume the work item, isolated worktree when required, delivery state, and autodev.json."
    )
    parser.add_argument("--apply", action="store_true", help=apply_help)
    parser.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(parser)
    parser.set_defaults(handler=handle_launch)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "auto-dev",
        help="Start or resume the full SDLC or one named Auto-Dev workflow.",
        description=(
            "Plain-English facade over the canonical Development Delivery engine. "
            "It initializes durable state; matching harness skills perform the actual work and record typed evidence."
        ),
    )
    sub = parser.add_subparsers(dest="auto_dev_action", required=True)
    _launch_parser(
        sub,
        "default",
        "Run the project-defined default development workflow through PR creation or later.",
    )
    _launch_parser(sub, "everything", "Take each ticket through every applicable workflow and approval gate.")
    for action, stage in ACTION_TO_STAGE.items():
        _launch_parser(sub, action, f"Start or resume only the {stage.replace('_', ' ')} workflow.")

    adopt = sub.add_parser(
        "adopt",
        help="Add canonical Auto-Dev state to one exact active pre-vNext work-item packet.",
    )
    adopt.add_argument("domain")
    adopt.add_argument("project")
    adopt.add_argument("ticket")
    adopt.add_argument("--state", required=True, help="Exact existing work-item directory without autodev.json.")
    adopt.add_argument("--run-id", required=True, help="Stable migration and resume identifier.")
    adopt.add_argument("--title")
    adopt.add_argument("--repository")
    adopt.add_argument("--base-branch")
    adopt.add_argument("--apply", action="store_true")
    adopt.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(adopt)
    adopt.set_defaults(handler=handle_adopt)

    reconcile = sub.add_parser(
        "reconcile-historical",
        help="Bind provider-read historical delivery evidence to one legacy worktree_ready task.",
    )
    reconcile.add_argument("--state", required=True, help="Exact development task state.json.")
    reconcile.add_argument(
        "--evidence",
        required=True,
        help=(
            "Path to a file holding auto-dev-historical-delivery-reconciliation/v1 "
            "JSON with the complete missing delivery ledger. Inline JSON is not accepted."
        ),
    )
    reconcile.add_argument("--idempotency-key", required=True)
    reconcile.add_argument("--apply", action="store_true")
    _common_output(reconcile)
    reconcile.set_defaults(handler=handle_reconcile_historical)

    reopen = sub.add_parser(
        "reopen",
        help="Preserve one Health-completed packet and start a fresh QA or development follow-up.",
    )
    reopen.add_argument(
        "--state",
        required=True,
        help="Exact finished work-item directory or its autodev.json.",
    )
    reopen.add_argument("--run-id", required=True, help="New stable delivery run identifier.")
    reopen.add_argument("--reason", required=True, help="Durable reason for reopening the item.")
    reopen.add_argument("--stage", choices=("develop", "qa"), default="qa")
    reopen.add_argument("--repository", help="Repository id for a multi-repository project.")
    reopen.add_argument("--base-branch", help="Ticket/release-authoritative base branch.")
    reopen.add_argument(
        "--reselect-context",
        "--reselect-rules-engine-context",
        dest="reselect_context",
        action="store_true",
        help=(
            "Explicitly replace the prior frozen context using the supplied selectors; "
            "the reopen receipt records both prior and new context hashes."
        ),
    )
    reopen.add_argument(
        "--touched-path",
        action="append",
        help="New repository-relative selector path; requires --reselect-context.",
    )
    reopen.add_argument(
        "--subject",
        action="append",
        help="New semantic selector subject; requires --reselect-context.",
    )
    reopen.add_argument(
        "--rulebook-id",
        action="append",
        help="Exact Rules Engine rulebook identity for a reselect; requires --reselect-context.",
    )
    reopen.add_argument(
        "--apply",
        action="store_true",
        help="Create one fresh active packet, worktree, runtime registration, and delivery run.",
    )
    reopen.add_argument("--root", default=DEFAULT_ROOT)
    _common_output(reopen)
    reopen.set_defaults(handler=handle_reopen)

    status = sub.add_parser("status", help="Read a work item's autodev.json projection.")
    status.add_argument("state", help="Work-item directory or autodev.json path.")
    _common_output(status)
    status.set_defaults(handler=handle_status)

    sync = sub.add_parser("sync", help="Refresh autodev.json from canonical Development Delivery state.")
    sync.add_argument("task_state", help="Canonical development task state.json.")
    _common_output(sync)
    sync.set_defaults(handler=handle_sync)

    record = sub.add_parser(
        "record",
        help="Record a standalone workflow or strict Health result from typed evidence.",
        description=(
            "Record standalone Auto-Dev stages from auto-dev-stage-evidence/v1, "
            "or Health from auto-dev-health-evidence/v1. Delivery-managed stages "
            "must be recorded with `agentic-os develop stage`."
        ),
    )
    record.add_argument("state", help="Work-item directory or autodev.json path.")
    record.add_argument(
        "--stage",
        required=True,
        choices=AUTO_DEV_STAGE_ORDER,
        help=(
            "Standalone stage to record; Health uses its strict Health schema. "
            "Use `agentic-os develop stage` for delivery-managed stages."
        ),
    )
    record.add_argument(
        "--evidence",
        required=True,
        help=(
            "Path to a file holding auto-dev-stage-evidence/v1 JSON for a "
            "standalone stage, or auto-dev-health-evidence/v1 JSON for Health. "
            "Inline JSON is not accepted."
        ),
    )
    record.add_argument("--idempotency-key", required=True)
    _common_output(record)
    record.set_defaults(handler=handle_record)
