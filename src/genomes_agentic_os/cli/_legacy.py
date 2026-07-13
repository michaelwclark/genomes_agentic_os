"""Legacy CLI remainder pending the AGE-36 split into cli/ group modules."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ..cli_help import AosHelpFormatter, env_epilog
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

from ..automation_ops import (
    AUTOMATION_MATURITY_LEVELS,
    attach_automation,
    check_automation,
    format_automation_check,
    set_automation_maturity,
)
from ..automation_control import (
    automation_control_doctor,
    format_automation_control_result,
    list_automation_control,
    run_automation_control,
)
from ..cockpit import (
    DEFAULT_OUTPUT as COCKPIT_DEFAULT_OUTPUT,
    build_cockpit_bundle,
    build_cockpit_snapshot,
    open_cockpit,
    write_cockpit_snapshot,
)
from ..config_ops import LAYERS as CONFIG_LAYERS
from ..config_ops import doctor_config, install_config, install_config_tree
from ..conversation_reports import format_conversation_report_receipt, scan_conversation_reports
from ..customer import customer_init, customer_update, customer_validate, format_customer_result, scaffold_customer_brief
from ..doc_config import build_doc_config_plan, doc_config_doctor, format_doc_config_result, init_doc_config
from ..documentation_upkeep import build_documentation_upkeep_plan, format_documentation_upkeep_result
from ..doctor import doctor, doctor_all, format_doctor_result
from ..event_graph import (
    append_event,
    chain_doctor,
    chain_list,
    emit_run_close_event,
    format_event_graph_result,
    list_events,
    process_due,
    replay_event,
    summarize_events,
    test_chain_rule,
)
from ..hook_ops import hook_doctor, hook_sync
from ..lifecycle import WORK_LIFECYCLE_STATES, cleanup_terminal_worktrees, create_project_work_item, infer_complete_work_items, repair_project_work_item
from ..lifecycle import finalize_lingering_work_items, sync_active_container
from ..migrations import format_migration_result, migrate_apply, migrate_plan
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
from ..plans import capture_plan, format_plan_result
from ..ps_ops import format_ps_result, ps_snapshot
from ..room_profile import format_profile_result, install_profile_os, load_os_profile, write_profile_template
from ..routing import build_context, context_from_here, detect_from_cwd, format_packet, project_records, route_request
from ..runtime_ops import (
    apply_runtime_tracking,
    build_runtime_tracking_plan,
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
from ..self_improvement import (
    approve_self_improvement_proposal,
    format_self_improvement_result,
    list_self_improvement_proposals,
    nightly_apply_self_improvement,
    process_self_improvement_actions,
    promote_self_improvement_proposal,
    reconcile_self_improvement_queue,
    reject_self_improvement_proposal,
    run_self_improvement,
    self_improvement_status,
    show_self_improvement_proposal,
)
from ..supervisor import format_supervise_result, supervise_tick
from ..scaffold import (
    DEFAULT_PROJECTS_SOURCE,
    create_automation,
    create_domain,
    create_instance_program,
    create_program,
    create_project,
    create_project_worktree,
    create_run_log,
    create_workflow,
    install_docs,
    init_os,
    link_project_remote,
    link_project_source,
    onboard_project,
    register_project_worktree,
)
from ..hosts import format_host_routing_status, host_routing_status, list_hosts, upsert_host
from ..remote_ops import sync_project_remote
from ..remote_mounts import exec_remote, mount_remote, unmount_remote
from ..source_watch import (
    create_watch_source,
    doctor_connected_system,
    doctor_watch_source,
    format_source_watch_result,
    list_connected_systems,
    list_watch_sources,
    parse_external_refs,
    poll_watch_source,
    run_due_watch_sources,
)
from ..thread_closeout import (
    DEFAULT_STALE_DAYS,
    WORK_LEVELS,
    close_thread,
    format_thread_closeout_result,
    stale_finalize_threads,
)
from ..metrics_ops import format_metrics_result, metrics_refresh
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
from ..capability_registry import (
    REGISTRY_FILES,
    inventory_markdown,
    load_registry,
    registry_payloads,
)
from ..validate import StrictFinding, validate_root, validate_schemas_strict
from ..workflow_ops import check_workflow, close_run_log, format_findings

from ._shared import DEFAULT_ROOT, print_result, yaml_dump


def handle_capability_list(args: argparse.Namespace) -> int:
    """List capabilities from installed registry files, optionally filtered by type."""
    root = Path(args.root).expanduser()
    cap_type = getattr(args, "type", None)
    payloads = registry_payloads()
    if cap_type:
        if cap_type not in payloads:
            print(f"Unknown capability type '{cap_type}'. Known types: {', '.join(sorted(payloads))}")
            return 1
        types_to_show = {cap_type: payloads[cap_type]}
    else:
        types_to_show = payloads
    for name, payload in types_to_show.items():
        collection_key = next(iter(payload))
        entries = payload[collection_key]
        print(f"\n## {name} ({len(entries)})")
        for entry in entries:
            entry_id = entry.get("id") or entry.get("command") or "(unknown)"
            description = entry.get("description", "")
            print(f"  {entry_id}" + (f" — {description}" if description else ""))
    installed_path = root / REGISTRY_FILES.get("capabilities", "harness/registries/capabilities.yml")
    if installed_path.exists():
        installed = load_registry(installed_path, "capabilities")
        if installed:
            print(f"\n## installed capabilities ({len(installed)})")
            for cap in installed:
                ref = cap.get("ref", "")
                cap_type_label = cap.get("type", "")
                print(f"  {ref}" + (f" [{cap_type_label}]" if cap_type_label else ""))
    return 0


def handle_capability_inventory(args: argparse.Namespace) -> int:
    """Show or regenerate INVENTORY.md from installed registry state."""
    root = Path(args.root).expanduser()
    content = inventory_markdown()
    if getattr(args, "regenerate", False):
        from ..scaffold import harness_path, write_file_once
        from ..scaffold import ScaffoldResult

        result = ScaffoldResult()
        write_file_once(harness_path(root) / "INVENTORY.md", content, result)
        for msg in result.messages():
            print(msg)
        if not result.messages():
            print("INVENTORY.md already up to date")
    else:
        inventory_path = root / "harness" / "INVENTORY.md"
        if inventory_path.exists():
            print(inventory_path.read_text(encoding="utf-8"))
        else:
            print(content)
    return 0


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


def handle_plan_capture(args: argparse.Namespace) -> int:
    print(
        format_plan_result(
            capture_plan(
                args.root,
                title=args.title,
                summary=args.summary,
                kind=args.kind,
                domain=args.domain,
                project=args.project,
            )
        )
    )
    return 0


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


def handle_self_improvement_nightly_apply(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            nightly_apply_self_improvement(args.root, dry_run=not args.apply, limit=args.limit)
        )
    )
    return 0


def handle_connected_system_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_connected_systems(args.root)))
    return 0


def handle_connected_system_doctor(args: argparse.Namespace) -> int:
    result = doctor_connected_system(args.root, args.system_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_watch_sources(args.root)))
    return 0


def handle_watch_source_create(args: argparse.Namespace) -> int:
    result = create_watch_source(
        args.root,
        args.source_id,
        connected_system=args.connected_system,
        source_type=args.source_type,
        display_name=args.display_name,
        cadence=args.cadence,
        external_ref=parse_external_refs(args.external_ref),
        route_to=args.route_to,
        enabled=args.enabled,
    )
    print(format_source_watch_result(result))
    return 0


def handle_watch_source_doctor(args: argparse.Namespace) -> int:
    result = doctor_watch_source(args.root, args.source_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_poll(args: argparse.Namespace) -> int:
    result = poll_watch_source(args.root, args.source_id, dry_run=args.dry_run)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_run_due(args: argparse.Namespace) -> int:
    print(format_source_watch_result(run_due_watch_sources(args.root, dry_run=args.dry_run)))
    return 0


def handle_event_append(args: argparse.Namespace) -> int:
    print(
        format_event_graph_result(
            append_event(
                args.root,
                event_type=args.event_type,
                source_ref=args.source_ref,
                summary=args.summary,
                correlation_id=args.correlation_id,
            )
        )
    )
    return 0


def handle_event_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(list_events(args.root, limit=args.limit)))
    return 0


def handle_event_summary(args: argparse.Namespace) -> int:
    print(format_event_graph_result(summarize_events(args.root, limit=args.limit)))
    return 0


def handle_event_process_due(args: argparse.Namespace) -> int:
    print(format_event_graph_result(process_due(args.root, dry_run=args.dry_run)))
    return 0


def handle_event_replay(args: argparse.Namespace) -> int:
    print(format_event_graph_result(replay_event(args.root, args.event_id, dry_run=args.dry_run)))
    return 0


def handle_chain_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(chain_list(args.root)))
    return 0


def handle_chain_test(args: argparse.Namespace) -> int:
    print(format_event_graph_result(test_chain_rule(args.root, args.chain_rule_id, args.event)))
    return 0


def handle_chain_doctor(args: argparse.Namespace) -> int:
    result = chain_doctor(args.root)
    print(format_event_graph_result(result))
    return 0 if result["ok"] else 1


def handle_validate(args: argparse.Namespace) -> int:
    result = validate_root(args.root)
    strict_findings: list[StrictFinding] = []
    if getattr(args, "strict", False):
        from pathlib import Path as _Path  # noqa: PLC0415
        strict_findings = validate_schemas_strict(_Path(args.root).expanduser())
    if result.ok and not strict_findings:
        print(f"valid: {Path(args.root).expanduser()}")
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for finding in strict_findings:
        print(f"strict: [{finding.schema}] {finding.path}: {finding.message}", file=sys.stderr)
    return 1 if (result.errors or strict_findings) else 0


def handle_docs_install(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_update(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_upkeep(args: argparse.Namespace) -> int:
    result = build_documentation_upkeep_plan(
        args.root,
        write_receipt=bool(args.write_receipt),
        output_dir=args.output_dir,
    )
    print(format_documentation_upkeep_result(result))
    return 0 if result.get("ok") else 1


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


def register_remaining(subparsers) -> None:
    """Register command groups not yet moved to cli/ modules."""
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

    plan_parser = subparsers.add_parser("plan", help="Capture future OS ideas and plans.")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)
    plan_capture = plan_subparsers.add_parser("capture", help="Capture a future idea in the right OS location.")
    plan_capture.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    plan_capture.add_argument("--title", required=True)
    plan_capture.add_argument("--summary", required=True)
    plan_capture.add_argument("--kind", default="os", choices=("os", "domain", "customer"))
    plan_capture.add_argument("--domain")
    plan_capture.add_argument("--project")
    plan_capture.set_defaults(handler=handle_plan_capture)

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

    connected_parser = subparsers.add_parser("connected-system", help="Manage connected source systems.")
    connected_subparsers = connected_parser.add_subparsers(dest="connected_system_command", required=True)
    connected_list = connected_subparsers.add_parser("list", help="List connected systems and selected providers.")
    connected_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_list.set_defaults(handler=handle_connected_system_list)
    connected_doctor = connected_subparsers.add_parser("doctor", help="Check a connected system.")
    connected_doctor.add_argument("system_id")
    connected_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_doctor.set_defaults(handler=handle_connected_system_doctor)

    watch_parser = subparsers.add_parser("watch-source", help="Manage connected source watchers.")
    watch_subparsers = watch_parser.add_subparsers(dest="watch_source_command", required=True)
    watch_list = watch_subparsers.add_parser("list", help="List watch sources.")
    watch_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_list.set_defaults(handler=handle_watch_source_list)
    watch_create = watch_subparsers.add_parser("create", help="Create a file-backed watch source.")
    watch_create.add_argument("source_id")
    watch_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_create.add_argument("--connected-system", default="notion_genome")
    watch_create.add_argument("--source-type", default="notion_database")
    watch_create.add_argument("--display-name")
    watch_create.add_argument("--cadence", default="manual")
    watch_create.add_argument("--external-ref", action="append", default=[])
    watch_create.add_argument("--route-to", default="shared_factory")
    watch_create.add_argument("--enabled", action="store_true")
    watch_create.set_defaults(handler=handle_watch_source_create)
    watch_doctor = watch_subparsers.add_parser("doctor", help="Check a watch source.")
    watch_doctor.add_argument("source_id")
    watch_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_doctor.set_defaults(handler=handle_watch_source_doctor)
    watch_poll = watch_subparsers.add_parser("poll", help="Poll one watch source.")
    watch_poll.add_argument("source_id")
    watch_poll.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_poll_mode = watch_poll.add_mutually_exclusive_group(required=True)
    watch_poll_mode.add_argument("--dry-run", action="store_true")
    watch_poll_mode.add_argument("--apply", action="store_true")
    watch_poll.set_defaults(handler=handle_watch_source_poll)
    watch_run_due = watch_subparsers.add_parser("run-due", help="Poll enabled watch sources.")
    watch_run_due.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_run_due_mode = watch_run_due.add_mutually_exclusive_group(required=True)
    watch_run_due_mode.add_argument("--dry-run", action="store_true")
    watch_run_due_mode.add_argument("--apply", action="store_true")
    watch_run_due.set_defaults(handler=handle_watch_source_run_due)

    event_parser = subparsers.add_parser("event", help="Manage the file-backed event ledger.")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)
    event_append = event_subparsers.add_parser("append", help="Append a normalized event.")
    event_append.add_argument("--type", required=True, dest="event_type")
    event_append.add_argument("--source", required=True, dest="source_ref")
    event_append.add_argument("--summary", default="")
    event_append.add_argument("--correlation-id")
    event_append.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_append.set_defaults(handler=handle_event_append)
    event_list = event_subparsers.add_parser("list", help="List recent events.")
    event_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_list.add_argument("--limit", type=int, default=20)
    event_list.set_defaults(handler=handle_event_list)
    event_summary = event_subparsers.add_parser("summary", help="Summarize recent events and pending follow-up.")
    event_summary.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_summary.add_argument("--limit", type=int, default=20)
    event_summary.set_defaults(handler=handle_event_summary)
    event_process = event_subparsers.add_parser("process-due", help="Process matching chain rules.")
    event_process.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_process_mode = event_process.add_mutually_exclusive_group(required=True)
    event_process_mode.add_argument("--dry-run", action="store_true")
    event_process_mode.add_argument("--apply", action="store_true")
    event_process.set_defaults(handler=handle_event_process_due)
    event_replay = event_subparsers.add_parser("replay", help="Replay one event against chain rules.")
    event_replay.add_argument("event_id")
    event_replay.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_replay_mode = event_replay.add_mutually_exclusive_group(required=True)
    event_replay_mode.add_argument("--dry-run", action="store_true")
    event_replay_mode.add_argument("--apply", action="store_true")
    event_replay.set_defaults(handler=handle_event_replay)

    chain_parser = subparsers.add_parser("chain", help="Manage event chain rules.")
    chain_subparsers = chain_parser.add_subparsers(dest="chain_command", required=True)
    chain_list_parser = chain_subparsers.add_parser("list", help="List chain rules.")
    chain_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_list_parser.set_defaults(handler=handle_chain_list)
    chain_test = chain_subparsers.add_parser("test", help="Test a chain rule against an event file.")
    chain_test.add_argument("chain_rule_id")
    chain_test.add_argument("--event", required=True)
    chain_test.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_test.set_defaults(handler=handle_chain_test)
    chain_doctor_parser = chain_subparsers.add_parser("doctor", help="Check chain rule safety.")
    chain_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_doctor_parser.set_defaults(handler=handle_chain_doctor)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an installed OS root.",
        description=(
            "Validate the installed OS root directory structure, required files, and YAML contracts. "
            "Exits 0 when valid; prints errors to stderr and exits 1 on failure. "
            "Use --strict to also check structured YAML/JSON files against JSON schemas."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("schemas/", "JSON schemas used by --strict validation (inside the repo package)."),
            ],
            examples=[
                ("agentic-os validate", "Validate the default OS root."),
                ("agentic-os validate --root ~/my-os", "Validate a non-default OS root."),
                ("agentic-os validate --strict", "Also validate YAML files against JSON schemas."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also validate structured files against JSON schemas in schemas/.",
    )
    validate_parser.set_defaults(handler=handle_validate)

    docs_parser = subparsers.add_parser(
        "docs",
        help="Install or update runtime OS documentation.",
        description=(
            "Install, update, or run upkeep on runtime OS documentation assets: "
            "templates, manuals, commands, skills, and plans. "
            "'install' is a one-shot full install; 'update' adds only missing assets without overwriting local edits; "
            "'upkeep' runs the observe-mode drift planner against the upkeep registry."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/docs/", "Installed runtime documentation assets."),
                ("harness/registries/documentation-upkeep.yml", "Documentation upkeep registry (used by 'upkeep')."),
            ],
            examples=[
                ("agentic-os docs install", "Install all runtime documentation assets."),
                ("agentic-os docs update", "Add missing assets without overwriting existing ones."),
                ("agentic-os docs upkeep --write-receipt", "Run upkeep drift planner and write receipt artifacts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_install = docs_subparsers.add_parser(
        "install",
        help="Install runtime templates, manual, commands, skills, and plans.",
    )
    docs_install.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_install.set_defaults(handler=handle_docs_install)
    docs_update = docs_subparsers.add_parser(
        "update",
        help="Add missing runtime template, manual, command, skill, and plan assets without overwriting local edits.",
    )
    docs_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_update.set_defaults(handler=handle_docs_update)
    docs_upkeep = docs_subparsers.add_parser(
        "upkeep",
        help="Run the observe-mode documentation upkeep registry and drift planner.",
    )
    docs_upkeep.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_upkeep.add_argument("--write-receipt", action="store_true", help="Write local YAML/Markdown receipt artifacts.")
    docs_upkeep.add_argument("--output-dir", help="Optional receipt output directory.")
    docs_upkeep.set_defaults(handler=handle_docs_upkeep)

    capability_parser = subparsers.add_parser("capability", help="Inspect installed OS capabilities.")
    capability_subparsers = capability_parser.add_subparsers(dest="capability_command", required=True)
    capability_list_parser = capability_subparsers.add_parser("list", help="List capabilities from installed registry.")
    capability_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_list_parser.add_argument("--type", dest="type", help="Filter by capability type (e.g. commands, skills, mcp_servers).")
    capability_list_parser.set_defaults(handler=handle_capability_list)
    capability_inventory_parser = capability_subparsers.add_parser("inventory", help="Show or regenerate INVENTORY.md.")
    capability_inventory_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_inventory_parser.add_argument("--regenerate", action="store_true", help="Rewrite INVENTORY.md from current registry state.")
    capability_inventory_parser.set_defaults(handler=handle_capability_inventory)

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
