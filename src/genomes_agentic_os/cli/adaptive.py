"""CLI commands for adaptive routing plans, observations, and rollback."""

from __future__ import annotations

import argparse

from ..adaptive_operations import (
    build_plan as build_adaptive_plan,
    canonical_json as adaptive_canonical_json,
    evaluate as evaluate_adaptive_holdout,
    load_explicit_policy,
    load_holdout_report,
    rollback_plan as build_adaptive_rollback_plan,
    runtime_policy_fingerprint,
    status as adaptive_routing_status,
)
from ..adaptive_observation_reports import DuplicateCorrelationError
from ..adaptive_observation_runner import (
    ObservationRunnerError,
    load_observation_config,
    observation_paths,
    record_plan_observation,
    run_observation_report,
)
from ..adaptive_observation_projection import ObservationProjectionError

from ._shared import DEFAULT_ROOT


def handle_adaptive_routing_plan(args: argparse.Namespace) -> int:
    document = load_explicit_policy(args.policy_file)
    report = load_holdout_report(args.holdout_report)
    result, exit_code = build_adaptive_plan(
        task=args.task,
        document=document,
        tier=args.tier,
        model_override=args.model_override,
        reasoning_effort=args.reasoning_effort,
        owner_identifier=args.owner_id,
        owner_kind=args.owner_kind,
        owner_minimum_tier=args.owner_minimum_tier,
        owner_verification=tuple(args.owner_verification),
        no_sub_agents=args.no_sub_agents,
        holdout_report=report,
    )
    print(adaptive_canonical_json(result))
    return exit_code


def handle_adaptive_routing_observe(args: argparse.Namespace) -> int:
    try:
        config = load_observation_config(args.root, args.config_file)
        paths = observation_paths(args.root, config)
        document = load_explicit_policy(args.policy_file or paths["policy"])
        result, exit_code = build_adaptive_plan(
            task=args.task,
            document=document,
            tier=args.tier,
            model_override=args.model_override,
            reasoning_effort=args.reasoning_effort,
            no_sub_agents=args.no_sub_agents,
        )
        try:
            observation = record_plan_observation(
                args.root,
                result,
                policy_fingerprint=runtime_policy_fingerprint(document),
                correlation_id=args.correlation_id,
                config_file=args.config_file,
            )
        except DuplicateCorrelationError:
            observation = {"status": "already_observed", "written": False}
        print(adaptive_canonical_json({**result, "observation": observation}))
        return exit_code
    except (ObservationRunnerError, OSError) as exc:
        raise ValueError(str(exc)) from exc


def handle_adaptive_routing_report(args: argparse.Namespace) -> int:
    try:
        result = run_observation_report(
            args.root,
            hours=args.hours,
            apply_notion=args.apply_notion,
            config_file=args.config_file,
        )
    except (ObservationRunnerError, ObservationProjectionError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    print(adaptive_canonical_json(result))
    return 1 if result.get("status") == "complete_with_projection_blocked" else 0


def handle_adaptive_routing_evaluate(args: argparse.Namespace) -> int:
    document = load_explicit_policy(args.policy_file)
    result, exit_code = evaluate_adaptive_holdout(
        holdout_file=args.holdout_file,
        document=document,
        approval_granted=args.approve,
    )
    print(adaptive_canonical_json(result))
    return exit_code


def handle_adaptive_routing_status(args: argparse.Namespace) -> int:
    document = load_explicit_policy(args.policy_file)
    report = load_holdout_report(args.holdout_report)
    result, exit_code = adaptive_routing_status(
        document=document,
        holdout_report=report,
    )
    print(adaptive_canonical_json(result))
    return exit_code


def handle_adaptive_routing_rollback_plan(args: argparse.Namespace) -> int:
    document = load_explicit_policy(args.policy_file)
    last_known_good = (
        load_explicit_policy(args.last_known_good_policy_file)
        if args.last_known_good_policy_file
        else None
    )
    result, exit_code = build_adaptive_rollback_plan(
        document=document,
        last_known_good=last_known_good,
    )
    print(adaptive_canonical_json(result))
    return exit_code


def register(subparsers) -> None:
    """Register the adaptive-routing command group."""
    adaptive_routing_parser = subparsers.add_parser(
        "adaptive-routing",
        help="Read-only operator controls for adaptive routing.",
    )
    adaptive_routing_subparsers = adaptive_routing_parser.add_subparsers(
        dest="adaptive_routing_command",
        required=True,
    )
    adaptive_plan = adaptive_routing_subparsers.add_parser(
        "plan",
        help="Build a canonical, non-executing adaptive routing plan.",
    )
    adaptive_plan.add_argument("task", help="Explicit task text; it is assessed locally and never emitted.")
    adaptive_plan.add_argument("--policy-file", required=True, help="Explicit reviewed adaptive policy YAML.")
    adaptive_plan.add_argument("--holdout-report", help="Explicit approved holdout JSON required by enforce mode.")
    adaptive_plan.add_argument("--tier", choices=("economy", "balanced", "frontier", "frontier_max", "human_gate"), help="Strengthen the requested minimum model tier.")
    adaptive_plan.add_argument("--model", dest="model_override", help="Policy-allowed model override only.")
    adaptive_plan.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"), help="Strengthen requested reasoning effort.")
    adaptive_plan.add_argument("--owner-id", help="Explicit selected owner identifier.")
    adaptive_plan.add_argument("--owner-kind", choices=("workflow", "skill"), help="Kind for an explicit owner override.")
    adaptive_plan.add_argument("--owner-minimum-tier", choices=("economy", "balanced", "frontier", "frontier_max", "human_gate"), help="Owner-derived tier floor.")
    adaptive_plan.add_argument("--owner-verification", action="append", default=[], help="Required verification added by the owner; repeatable.")
    adaptive_plan.add_argument("--no-sub-agents", action="store_true", help="Request operator-only topology when it preserves all required verification.")
    adaptive_plan.set_defaults(handler=handle_adaptive_routing_plan)

    adaptive_observe = adaptive_routing_subparsers.add_parser(
        "observe",
        help="Build and durably record one non-executing route for the active Codex task.",
    )
    adaptive_observe.add_argument("task", help="Explicit task text; assessed locally and never persisted.")
    adaptive_observe.add_argument("--root", default=DEFAULT_ROOT, help="Installed Agentic OS root path.")
    adaptive_observe.add_argument("--config-file", help="Explicit observation-report config YAML.")
    adaptive_observe.add_argument("--policy-file", help="Explicit reviewed adaptive policy YAML; defaults to the installed control plane.")
    adaptive_observe.add_argument("--correlation-id", help="Opaque task/session correlation; defaults to CODEX_THREAD_ID.")
    adaptive_observe.add_argument("--tier", choices=("economy", "balanced", "frontier", "frontier_max", "human_gate"))
    adaptive_observe.add_argument("--model", dest="model_override")
    adaptive_observe.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    adaptive_observe.add_argument("--no-sub-agents", action="store_true")
    adaptive_observe.set_defaults(handler=handle_adaptive_routing_observe)

    adaptive_report = adaptive_routing_subparsers.add_parser(
        "report",
        help="Analyze observed routes against actual Codex session telemetry.",
    )
    adaptive_report.add_argument("--root", default=DEFAULT_ROOT, help="Installed Agentic OS root path.")
    adaptive_report.add_argument("--hours", type=int, default=12, help="Rolling report window in hours.")
    adaptive_report.add_argument("--config-file", help="Explicit observation-report config YAML.")
    adaptive_report.add_argument("--apply-notion", action="store_true", help="Append one idempotent entry to the verified Genome's Notion report database.")
    adaptive_report.set_defaults(handler=handle_adaptive_routing_report)

    adaptive_evaluate = adaptive_routing_subparsers.add_parser(
        "evaluate",
        help="Run the supplied holdout against the built-in catalog and explicit baseline.",
    )
    adaptive_evaluate.add_argument("--holdout-file", required=True, help="Explicit reviewed holdout YAML.")
    adaptive_evaluate.add_argument("--policy-file", required=True, help="Exact reviewed runtime policy to bind to the holdout evidence.")
    adaptive_evaluate.add_argument("--approve", action="store_true", required=True, help="Record explicit operator approval for the guarded-mode decision.")
    adaptive_evaluate.set_defaults(handler=handle_adaptive_routing_evaluate)

    adaptive_status = adaptive_routing_subparsers.add_parser(
        "status",
        help="Show policy lifecycle, version, and enforce eligibility without changes.",
    )
    adaptive_status.add_argument("--policy-file", required=True, help="Explicit reviewed adaptive policy YAML.")
    adaptive_status.add_argument("--holdout-report", help="Explicit holdout JSON used only for enforce eligibility.")
    adaptive_status.set_defaults(handler=handle_adaptive_routing_status)

    adaptive_rollback = adaptive_routing_subparsers.add_parser(
        "rollback-plan",
        help="Build non-mutating Feature 62 static rollback instructions.",
    )
    adaptive_rollback.add_argument("--policy-file", required=True, help="Explicit current adaptive policy YAML.")
    adaptive_rollback.add_argument("--last-known-good-policy-file", help="Explicit prior reviewed policy YAML; metadata only.")
    adaptive_rollback.set_defaults(handler=handle_adaptive_routing_rollback_plan)
