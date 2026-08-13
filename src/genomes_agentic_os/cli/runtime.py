"""CLI commands for runtime registries, heartbeats, schedules, queues, integrations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os
from uuid import UUID, uuid4

from ..execution_fabric_config import ExecutionFabricConfigError
from ..execution_fabric_config import load_execution_fabric_config
from ..execution_fabric_config import redact_execution_fabric_config
from ..execution_fabric_config import resolve_execution_fabric_host_id
from ..execution_fabric_config import show_execution_fabric_config
from ..execution_fabric_remote import (
    activate_personal_fallback,
    clear_personal_fallback,
    ExecutionFabricClient,
    RemoteFabricWorker,
    build_remote_runtime_snapshot,
    materialize_approval_state,
    personal_fallback_status,
    probe_personal_fallback,
    resolve_remote_settings,
    validate_task_route,
)
from ..cli_help import AosHelpFormatter, env_epilog
from ..runtime_health import (
    build_runtime_health,
    notify_runtime_health,
    project_runtime_health,
    queue_runtime_self_heal,
    write_runtime_health,
)
from ..resource_actions import (
    schedule_create_governed,
    schedule_delete,
    schedule_get,
    schedule_list,
    schedule_queue_now,
    schedule_set_enabled,
    schedule_update,
)
from ..runtime_backend import (
    apply_queue_mode,
    execution_fabric_config_status,
    plan_queue_mode,
    plan_queue_mode_rollback,
    queue_mode_status,
    reconcile_execution_fabric_configuration,
    reconcile_execution_state,
    rollback_queue_mode,
)
from ..runtime_ops import (
    apply_runtime_tracking,
    build_runtime_tracking_plan,
    format_runtime_result,
    heartbeat_list,
    heartbeat_run,
    integration_doctor,
    integration_list,
    integration_setup,
    append_run_queue_item,
    run_queue_prune,
    runtime_doctor,
    runtime_init,
    runtime_run_next,
    schedule_run_due,
)
from ..runtime_snapshot import build_runtime_snapshot, format_runtime_snapshot, write_runtime_snapshot
from ..supervisor import format_supervise_result, supervise_tick

from ._shared import DEFAULT_ROOT


def _print_structured(result: dict, *, json_output: bool = False) -> None:
    print(json.dumps(result, sort_keys=True) if json_output else format_runtime_result(result))


def _add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _add_safe_mutation_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")


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


def handle_runtime_health_report(args: argparse.Namespace) -> int:
    report = build_runtime_health(args.root)
    paths = write_runtime_health(args.root, report)
    result = {
        "report": report,
        "paths": paths,
        "remediation": queue_runtime_self_heal(args.root, report, paths) if args.apply_remediation else {"queued": False},
        "notification": notify_runtime_health(args.root, report) if args.notify else {"sent": False},
        "notion": {"applied": False},
    }
    if args.apply_notion:
        projection = project_runtime_health(args.root, report, paths, automation_id=args.automation_id)
        result["notion"] = {"applied": projection["ok"], **projection}
    print(format_runtime_result(result))
    return 0 if not args.apply_notion or result["notion"]["applied"] else 1


def handle_runtime_snapshot(args: argparse.Namespace) -> int:
    snapshot = build_runtime_snapshot(
        args.root,
        queue_name=args.queue,
        statuses=args.status,
        task_limit=None if args.all else args.limit,
    )
    if args.output:
        snapshot["receipt_path"] = str(Path(args.output).expanduser().resolve())
        write_runtime_snapshot(snapshot["receipt_path"], snapshot)
    print(json.dumps(snapshot, sort_keys=True) if args.json else format_runtime_snapshot(snapshot))
    if args.output and not args.json:
        print(f"\nReceipt: {snapshot['receipt_path']}")
    return 0


def handle_runtime_run_next(args: argparse.Namespace) -> int:
    result = runtime_run_next(args.root, dry_run=not args.apply, item_id=args.item_id)
    print(format_runtime_result(result))
    return 0 if not args.apply or result["status"] not in {"failed", "blocked"} else 1


def _runtime_payload(args: argparse.Namespace) -> dict:
    if args.payload_json and args.payload_file:
        raise ValueError("use only one of --payload-json or --payload-file")
    if args.payload_file:
        loaded = json.loads(Path(args.payload_file).expanduser().read_text(encoding="utf-8"))
    else:
        loaded = json.loads(args.payload_json or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("task payload must be a JSON object")
    if args.command:
        loaded["command"] = args.command
    return loaded


def _configured_worker_defaults(
    root: str,
    queue_names: list[str],
    *,
    host_alias: str | None = None,
) -> tuple[int, int]:
    fabric = load_execution_fabric_config(
        root,
        host_alias=host_alias,
    ).value["execution_fabric"]
    selected = [
        pool
        for pool in fabric["worker_pools"]
        if pool.get("enabled") and set(pool.get("queues") or []).intersection(queue_names)
    ]
    if not selected:
        raise ValueError(
            "no enabled worker pool is configured for queues: " + ", ".join(queue_names)
        )
    concurrency = sum(
        int(pool["capacity"]["max_workers"])
        * int(pool["capacity"]["max_tasks_per_worker"])
        for pool in selected
    )
    concurrency = min(
        concurrency,
        int(fabric["admission"]["global_max_running"]),
    )
    # The shipped control plane keeps a short worker registration TTL. Heartbeat
    # more frequently than long task leases even when a pool's task heartbeat
    # policy is intentionally relaxed.
    heartbeat = min(
        15,
        *(int(pool["lease"]["heartbeat_seconds"]) for pool in selected),
    )
    return max(1, concurrency), max(1, heartbeat)


def handle_runtime_submit(args: argparse.Namespace) -> int:
    payload = _runtime_payload(args)
    settings = resolve_remote_settings(args.root, role="submit")
    route = validate_task_route(
        args.root,
        args.queue,
        args.task_type,
        payload=payload,
        remote=settings.remote,
    )
    task = {
        "namespace": args.namespace,
        "queue": args.queue,
        "taskType": args.task_type,
        "idempotencyKey": args.idempotency_key,
        "payload": payload,
        "requiredCapabilities": args.capability,
        "priority": args.priority,
        "maxAttempts": args.max_attempts,
    }
    if args.available_at:
        task["availableAt"] = args.available_at
    if not args.apply:
        _print_structured(
            {
                "status": "would-submit",
                "dry_run": True,
                "transport": settings.public(),
                "task": task,
            },
            json_output=args.json,
        )
        return 0
    if settings.remote:
        result = ExecutionFabricClient(settings).admit_task(task)
        _print_structured(
            {"status": "submitted", "transport": settings.public(), **result},
            json_output=args.json,
        )
        return 0
    local_item = {
        "id": args.idempotency_key,
        "idempotency_key": args.idempotency_key,
        "kind": "remote-compatible",
        "ref": f"{args.namespace}:{args.task_type}",
        "status": "queued",
        "queue_name": args.queue,
        "task_type": args.task_type,
        "priority": args.priority,
        "max_attempts": args.max_attempts,
        "due_at": args.available_at,
        **payload,
        "execution_target": args.execution_target or route["execution_target"],
        "approval_state": materialize_approval_state(
            str(route["approval_class"]),
            explicit_operator_apply=True,
        ),
    }
    result = append_run_queue_item(args.root, local_item)
    _print_structured(
        {
            "status": "submitted-local-degraded",
            "transport": settings.public(),
            **result,
        },
        json_output=args.json,
    )
    return 0


def handle_runtime_work(args: argparse.Namespace) -> int:
    settings = resolve_remote_settings(
        args.root,
        role="worker",
        host_alias=args.host_id,
    )
    host_id = resolve_execution_fabric_host_id(
        args.root,
        explicit=args.host_id,
        require_registered=settings.remote,
    )
    fabric = load_execution_fabric_config(
        args.root,
        host_alias=host_id if settings.remote or args.host_id else None,
    ).value["execution_fabric"]
    queues = args.queue or [
        str(queue["id"]) for queue in fabric["queues"] if queue.get("enabled")
    ]
    queues = list(dict.fromkeys(queues))
    if not queues:
        raise ValueError("no enabled queues are configured for runtime work")
    configured_concurrency, configured_heartbeat = _configured_worker_defaults(
        args.root,
        queues,
        host_alias=host_id if settings.remote or args.host_id else None,
    )
    max_concurrency = args.max_concurrency or (
        configured_concurrency if settings.remote else 1
    )
    heartbeat_seconds = args.heartbeat_seconds or configured_heartbeat
    worker_id = args.worker_id or f"{host_id}-{os.getpid()}"
    bootstrap_id = args.bootstrap_id or worker_id
    if not args.apply:
        _print_structured(
            {
                "status": "would-work",
                "dry_run": True,
                "transport": settings.public(),
                "worker_id": worker_id,
                "bootstrap_id": bootstrap_id,
                "host_id": host_id,
                "queues": queues,
                "capabilities": args.capability,
                "max_concurrency": max_concurrency,
                "heartbeat_seconds": heartbeat_seconds,
            },
            json_output=args.json,
        )
        return 0
    max_tasks = 1 if args.once else args.max_tasks
    if not settings.remote:
        if max_concurrency != 1:
            raise ValueError(
                "local/degraded worker mode supports max concurrency 1; use remote transport for a shared worker pool"
            )
        results = []
        queue_pools = {
            str(queue["id"]): str(queue["worker_pool"])
            for queue in fabric["queues"]
            if queue.get("enabled")
        }
        unknown_queues = [queue for queue in queues if queue not in queue_pools]
        if unknown_queues:
            raise ValueError(
                "runtime work requested disabled or unknown queues: "
                + ", ".join(unknown_queues)
            )
        completed_tasks = 0
        idle_queues: set[str] = set()
        queue_index = 0
        while max_tasks is None or completed_tasks < max_tasks:
            requested_queue = queues[queue_index]
            queue_index = (queue_index + 1) % len(queues)
            result = runtime_run_next(
                args.root,
                dry_run=False,
                queue_name=requested_queue,
                worker_pool=queue_pools[requested_queue],
            )
            result["requested_queue"] = requested_queue
            result["selected_queue"] = (result.get("queue_item") or {}).get("queue_name")
            results.append(result)
            if result.get("status") == "idle":
                idle_queues.add(requested_queue)
                if len(idle_queues) == len(queues):
                    break
                continue
            idle_queues.clear()
            completed_tasks += 1
        _print_structured(
            {
                "status": "stopped-local-degraded",
                "transport": settings.public(),
                "worker_id": worker_id,
                "results": results,
            },
            json_output=args.json,
        )
        return 0 if all(row.get("status") not in {"failed", "blocked"} for row in results) else 1
    worker = RemoteFabricWorker(
        ExecutionFabricClient(settings),
        root=args.root,
        worker_id=worker_id,
        bootstrap_id=bootstrap_id,
        host_id=host_id,
        queues=queues,
        capabilities=args.capability,
        max_concurrency=max_concurrency,
        heartbeat_seconds=heartbeat_seconds,
    )
    try:
        result = worker.work(max_tasks=max_tasks)
    except KeyboardInterrupt:
        result = {
            "status": "interrupted",
            "worker_id": worker_id,
            "host_id": host_id,
        }
    _print_structured(result, json_output=args.json)
    return 0 if not result.get("failed") else 1


def handle_runtime_status(args: argparse.Namespace) -> int:
    settings = resolve_remote_settings(args.root, role="observer")
    if settings.remote:
        result = build_remote_runtime_snapshot(
            args.root,
            task_id=args.task_id,
            limit=args.limit,
            client=ExecutionFabricClient(settings),
        )
    else:
        result = build_runtime_snapshot(args.root, task_limit=args.limit)
        result["transport"] = settings.public()
        result["degraded_mode"] = True
    print(json.dumps(result, sort_keys=True) if args.json else format_runtime_snapshot(result))
    return 0


def handle_runtime_fallback_status(args: argparse.Namespace) -> int:
    _print_structured(personal_fallback_status(args.root), json_output=args.json)
    return 0


def handle_runtime_fallback_probe(args: argparse.Namespace) -> int:
    result = probe_personal_fallback(args.root, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("primary_ready") or result.get("status") == "active" else 1


def handle_runtime_fallback_activate(args: argparse.Namespace) -> int:
    result = activate_personal_fallback(
        args.root,
        dry_run=not args.apply,
        reason=args.reason,
    )
    _print_structured(result, json_output=args.json)
    return 0


def handle_runtime_fallback_failback(args: argparse.Namespace) -> int:
    result = clear_personal_fallback(args.root, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0


def handle_queue_mode_status(args: argparse.Namespace) -> int:
    _print_structured(queue_mode_status(args.root), json_output=args.json)
    return 0


def handle_queue_mode_plan(args: argparse.Namespace) -> int:
    result = plan_queue_mode(args.root, args.target_mode)
    _print_structured(result, json_output=args.json)
    return 0 if result["ready"] else 1


def handle_queue_mode_apply(args: argparse.Namespace) -> int:
    result = apply_queue_mode(args.root, args.target_mode, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("ready", True) else 1


def handle_queue_mode_rollback(args: argparse.Namespace) -> int:
    result = (
        rollback_queue_mode(args.root, dry_run=False)
        if args.apply
        else plan_queue_mode_rollback(args.root) | {"dry_run": True, "applied": False}
    )
    _print_structured(result, json_output=args.json)
    return 0 if result.get("ready", True) else 1


def handle_queue_mode_reconcile(args: argparse.Namespace) -> int:
    result = reconcile_execution_state(args.root, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("ready", True) else 1


def handle_execution_fabric_config_status(args: argparse.Namespace) -> int:
    _print_structured(execution_fabric_config_status(args.root), json_output=args.json)
    return 0


def handle_execution_fabric_config_show(args: argparse.Namespace) -> int:
    _print_structured(show_execution_fabric_config(args.root), json_output=args.json)
    return 0


def handle_execution_fabric_config_diff(args: argparse.Namespace) -> int:
    result = execution_fabric_config_status(args.root)
    effective = load_execution_fabric_config(args.root)
    remote: dict[str, object] | None = None
    transport = effective.value["execution_fabric"].get("transport") or {}
    if transport.get("mode") == "remote":
        remote_status = ExecutionFabricClient.from_root(
            args.root,
            role="observer",
        ).status()
        remote = dict(remote_status.get("config") or {})
    in_sync = result["drift_count"] == 0 and (
        remote is None
        or remote.get("appliedFingerprint") == effective.fingerprint
    )
    output = {
        "ok": True,
        "root": result["root"],
        "fingerprint": effective.fingerprint,
        "local_catalog": {
            "queue_mode": result["queue_mode"],
            "drift_count": result["drift_count"],
            "drift": result["drift"],
        },
        "remote_policy": redact_execution_fabric_config(remote),
        "in_sync": in_sync,
    }
    _print_structured(output, json_output=args.json)
    return 0 if in_sync else 1


def _write_config_reload_receipt(root: str, payload: dict) -> Path:
    receipt_root = (
        Path(root).expanduser().resolve()
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/config-reloads"
    )
    receipt_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = receipt_root / f"{stamp}-{payload['fingerprint'][:12]}.json"
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination


def handle_execution_fabric_config_reload(args: argparse.Namespace) -> int:
    effective = load_execution_fabric_config(args.root)
    expected = str(args.expected_fingerprint or "").strip()
    rotation_id = str(args.rotation_id or "").strip()
    preparation_token_file = str(args.preparation_token_file or "").strip()
    if effective.value["execution_fabric"]["transport"].get("mode") != "remote":
        raise ExecutionFabricConfigError(
            "runtime config reload is a remote control-plane operation; "
            "use runtime config reconcile for local/degraded SQLite"
        )
    observer = ExecutionFabricClient.from_root(args.root, role="observer")
    before = observer.status()
    before_policy = dict(before.get("config") or {})
    current_fingerprint = str(before_policy.get("appliedFingerprint") or "")
    if len(current_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in current_fingerprint
    ):
        raise ExecutionFabricConfigError(
            "remote config reload requires a valid observer pre-read fingerprint"
        )
    plan = {
        "action": "runtime.execution-fabric.config.reload",
        "root": str(Path(args.root).expanduser().resolve()),
        "fingerprint": effective.fingerprint,
        "expected_fingerprint": expected or None,
        "expected_current_fingerprint": current_fingerprint,
        "rotation_id": rotation_id or None,
        "dry_run": not args.apply,
        "applied": False,
    }
    if expected and expected != effective.fingerprint:
        raise ExecutionFabricConfigError(
            "expected fingerprint does not match the validated effective configuration"
        )
    if not args.apply:
        _print_structured(
            {
                **plan,
                "ready": bool(expected and rotation_id and preparation_token_file),
                "blockers": [
                    blocker
                    for present, blocker in (
                        (
                            bool(expected),
                            "--expected-fingerprint is required for --apply",
                        ),
                        (
                            bool(rotation_id),
                            "--rotation-id is required for --apply",
                        ),
                        (
                            bool(preparation_token_file),
                            "--preparation-token-file is required for --apply",
                        ),
                    )
                    if not present
                ],
            },
            json_output=args.json,
        )
        return 0
    if not expected or not rotation_id or not preparation_token_file:
        raise ExecutionFabricConfigError(
            "--expected-fingerprint, --rotation-id, and --preparation-token-file "
            "are required when applying a remote config reload"
        )
    try:
        UUID(rotation_id)
    except ValueError as error:
        raise ExecutionFabricConfigError("--rotation-id must be a UUID") from error
    token_path = Path(preparation_token_file).expanduser().resolve()
    try:
        preparation_token = token_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ExecutionFabricConfigError(
            "witness preparation token file is unreadable"
        ) from error
    if not preparation_token.startswith("cpr1.") or len(
        preparation_token.split(".")
    ) != 3:
        raise ExecutionFabricConfigError(
            "witness preparation token file has an invalid envelope"
        )
    admin_settings = resolve_remote_settings(args.root, role="admin")
    reload_result = ExecutionFabricClient(admin_settings).reload_config(
        rotation_id=rotation_id,
        preparation_token=preparation_token,
        expected_current_fingerprint=current_fingerprint,
        expected_candidate_fingerprint=effective.fingerprint,
    )
    readback = observer.status()
    remote_policy = dict(readback.get("config") or {})
    applied_fingerprint = str(
        remote_policy.get("appliedFingerprint")
        or reload_result.get("appliedFingerprint")
        or ""
    )
    if applied_fingerprint != effective.fingerprint:
        raise ExecutionFabricConfigError(
            "remote config reload readback fingerprint does not match the local effective config"
        )
    receipt = {
        **plan,
        "schema_version": "agentic-os-execution-fabric-config-reload/v1",
        "dry_run": False,
        "applied": True,
        "reloaded": redact_execution_fabric_config(reload_result),
        "readback": redact_execution_fabric_config(remote_policy),
        "recorded_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    receipt_path = _write_config_reload_receipt(args.root, receipt)
    _print_structured(
        {**receipt, "receipt_path": str(receipt_path)},
        json_output=args.json,
    )
    return 0


def handle_execution_fabric_config_validate(args: argparse.Namespace) -> int:
    try:
        result = execution_fabric_config_status(args.root)
    except ExecutionFabricConfigError as exc:
        result = {
            "ok": False,
            "root": str(Path(args.root).expanduser().resolve()),
            "findings": [{"severity": "error", "message": str(exc)}],
        }
    _print_structured(result, json_output=args.json)
    return 0 if result["ok"] else 1


def handle_runtime_tracking(args: argparse.Namespace) -> int:
    try:
        os_root = Path(args.root).expanduser().resolve()
        if args.apply:
            result = apply_runtime_tracking(os_root, verified_workspace=args.workspace)
        else:
            from ..runtime_ops import _live_notion_config, _load_notion_tracking_config
            from ..notion_api import resolve_token
            config = _load_notion_tracking_config(os_root)
            parent_page_id, token_env, _title, _workspace = _live_notion_config(config)
            token_present = resolve_token(token_env) is not None
            result = {**build_runtime_tracking_plan(os_root), "applied": False, "mode": "plan",
                      "would_go_live": bool(parent_page_id and token_present),
                      "token_configured": token_present}
    except Exception as exc:
        result = {"applied": False, "ok": False, "error_type": type(exc).__name__, "error": str(exc), "manifest_path": str(Path(args.root) / ".notion-runtime-tracking" / "manifest.yml")}
        _print_structured(result, json_output=args.json)
        return 1
    _print_structured(result, json_output=args.json)
    return 0


def handle_execution_fabric_config_reconcile(args: argparse.Namespace) -> int:
    result = reconcile_execution_fabric_configuration(args.root, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result["ready"] else 1


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
    # Preserve the historical immediate-create behavior when neither new mode
    # flag is supplied. Command Center always supplies an explicit mode.
    governed_mode = args.dry_run is not None or args.apply
    dry_run = bool(args.dry_run) if governed_mode else False
    enabled = (not args.disabled) if not governed_mode else bool(args.enabled and not args.disabled)
    result = schedule_create_governed(
        args.root,
        args.schedule_id,
        cadence=args.cadence,
        timezone_name=args.timezone,
        command=args.command,
        enabled=enabled,
        dry_run=dry_run,
    )
    _print_structured(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_schedule_list(args: argparse.Namespace) -> int:
    _print_structured(schedule_list(args.root), json_output=args.json)
    return 0


def handle_schedule_get(args: argparse.Namespace) -> int:
    _print_structured(schedule_get(args.root, args.schedule_id), json_output=args.json)
    return 0


def handle_schedule_update(args: argparse.Namespace) -> int:
    changes = {
        key: value
        for key, value in {
            "display_name": args.display_name,
            "cadence": args.cadence,
            "timezone": args.timezone,
            "command": args.command,
            "local_time": None if args.clear_local_time else args.local_time,
            "execution_target": args.execution_target,
            "enabled": args.enabled,
        }.items()
        if value is not None or (key == "local_time" and args.clear_local_time)
    }
    result = schedule_update(args.root, args.schedule_id, changes=changes, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_schedule_enabled(args: argparse.Namespace) -> int:
    result = schedule_set_enabled(
        args.root,
        args.schedule_id,
        enabled=args.enabled_value,
        dry_run=not args.apply,
    )
    _print_structured(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_schedule_delete(args: argparse.Namespace) -> int:
    result = schedule_delete(args.root, args.schedule_id, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_schedule_queue_now(args: argparse.Namespace) -> int:
    result = schedule_queue_now(args.root, args.schedule_id, dry_run=not args.apply)
    _print_structured(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") and result.get("status") != "blocked" else 1


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
        help="Inspect and operate the selected runtime backend.",
        description=(
            "Inspect and operate the runtime surface: registries, selected queue backend, workers, heartbeats, schedules, integrations, and sources. "
            "All mutating subcommands default to --dry-run; pass --apply to write changes. "
            "'runtime supervise' runs a full supervisor tick across all subsystems at once."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
                (
                    "AGENTIC_OS_EXECUTION_FABRIC_TOKEN",
                    "Default bearer-token source for authenticated remote Execution Fabric requests.",
                ),
            ],
            config_files=[
                (
                    "harness/config/execution-fabric.yml",
                    "Canonical queue, worker-pool, admission, lease, and retry instance policy.",
                ),
                ("harness/registries/runtime-registry.yml", "Runtime registry: schedules, heartbeats, integrations."),
                ("harness/registries/run-queue.yml", "Run queue: pending and in-progress items."),
                ("harness/registries/automation-run-tracking.yml", "Automation run tracking."),
            ],
            examples=[
                ("agentic-os runtime init", "Create runtime registries and log folders."),
                ("agentic-os runtime doctor", "Check runtime registry health."),
                ("agentic-os runtime snapshot", "Capture queue, worker, and task state at one moment."),
                (
                    "agentic-os runtime config status --json",
                    "Show effective Execution Fabric config source, fingerprint, and drift.",
                ),
                ("agentic-os runtime supervise --apply", "Run a full supervisor tick across all subsystems."),
                ("agentic-os runtime run-next --apply", "Dispatch the next safe queued item."),
                (
                    "agentic-os runtime submit --queue codex --task-type llm.codex --idempotency-key example --payload-json '{\"work_item_id\":\"AGE-1\",\"instruction_ref\":\"harness/shared_factory/01-inbox/AGE-1.md\"}' --apply",
                    "Idempotently submit one commandless, closed-schema task through local or remote transport.",
                ),
                (
                    "agentic-os runtime work --queue non_llm --max-concurrency 2 --apply",
                    "Run a host-native worker against the configured transport.",
                ),
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
    runtime_health_parser = runtime_subparsers.add_parser(
        "health-report", help="Write a queue and worker-loop health report."
    )
    runtime_health_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_health_parser.add_argument(
        "--apply-notion", action="store_true", help="Replace the verified Notion summary page."
    )
    runtime_health_parser.add_argument(
        "--apply-remediation", action="store_true", help="Queue an idempotent Codex self-heal task when unhealthy."
    )
    runtime_health_parser.add_argument(
        "--notify", action="store_true", help="Send a governed local system notification when unhealthy."
    )
    runtime_health_parser.add_argument("--automation-id", default="queue-worker-health")
    runtime_health_parser.set_defaults(handler=handle_runtime_health_report)
    runtime_tracking_parser = runtime_subparsers.add_parser(
        "tracking", help="Plan or apply the guarded runtime tracking projection."
    )
    runtime_tracking_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_tracking_parser.add_argument(
        "--workspace", default="Genome's Notion", help="Verified Notion workspace name for live tracking."
    )
    runtime_tracking_mode = runtime_tracking_parser.add_mutually_exclusive_group()
    runtime_tracking_mode.add_argument("--dry-run", action="store_true", default=False)
    runtime_tracking_mode.add_argument("--apply", action="store_true")
    _add_json_arg(runtime_tracking_parser)
    runtime_tracking_parser.set_defaults(handler=handle_runtime_tracking)
    runtime_snapshot_parser = runtime_subparsers.add_parser(
        "snapshot",
        help="Capture a point-in-time queue, worker, and task snapshot from the selected backend.",
    )
    runtime_snapshot_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_snapshot_parser.add_argument("--queue", help="Restrict task rows to one named queue.")
    runtime_snapshot_parser.add_argument(
        "--status",
        action="append",
        default=[],
        choices=("dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped", "cancelled", "dead-letter"),
        help="Restrict task rows to a status; repeat to include multiple statuses.",
    )
    runtime_snapshot_limit = runtime_snapshot_parser.add_mutually_exclusive_group()
    runtime_snapshot_limit.add_argument("--limit", type=_positive_int, default=50, help="Maximum task rows to include (default: 50).")
    runtime_snapshot_limit.add_argument("--all", action="store_true", help="Include every matching task row.")
    runtime_snapshot_parser.add_argument("--output", help="Atomically write the complete snapshot JSON to this path.")
    _add_json_arg(runtime_snapshot_parser)
    runtime_snapshot_parser.set_defaults(handler=handle_runtime_snapshot)
    runtime_run_next_parser = runtime_subparsers.add_parser("run-next", help="Dispatch the next safe queued runtime item.")
    runtime_run_next_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_run_next_parser.add_argument("--item-id", help="Specific queue item id to inspect or dispatch.")
    runtime_run_next_mode = runtime_run_next_parser.add_mutually_exclusive_group()
    runtime_run_next_mode.add_argument("--dry-run", action="store_true", default=True)
    runtime_run_next_mode.add_argument("--apply", action="store_true")
    runtime_run_next_parser.set_defaults(handler=handle_runtime_run_next)
    runtime_submit_parser = runtime_subparsers.add_parser(
        "submit",
        help="Idempotently submit one task through the configured local or remote transport.",
    )
    runtime_submit_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_submit_parser.add_argument("--namespace", default="agentic_os")
    runtime_submit_parser.add_argument("--queue", required=True)
    runtime_submit_parser.add_argument("--task-type", required=True)
    runtime_submit_parser.add_argument("--idempotency-key", required=True)
    runtime_submit_parser.add_argument("--payload-json")
    runtime_submit_parser.add_argument("--payload-file")
    runtime_submit_parser.add_argument(
        "--command",
        help="Governed host-native command. Prefer a script below the installed OS root.",
    )
    runtime_submit_parser.add_argument(
        "--execution-target",
        choices=("script", "codex_harness", "claude_harness"),
    )
    runtime_submit_parser.add_argument("--capability", action="append", default=[])
    runtime_submit_parser.add_argument("--priority", type=int, default=0)
    runtime_submit_parser.add_argument("--max-attempts", type=_positive_int, default=3)
    runtime_submit_parser.add_argument("--available-at")
    _add_safe_mutation_mode(runtime_submit_parser)
    _add_json_arg(runtime_submit_parser)
    runtime_submit_parser.set_defaults(handler=handle_runtime_submit)
    runtime_work_parser = runtime_subparsers.add_parser(
        "work",
        help="Run a concurrent host-native worker against the configured transport.",
    )
    runtime_work_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_work_parser.add_argument("--worker-id")
    runtime_work_parser.add_argument("--bootstrap-id")
    runtime_work_parser.add_argument("--host-id")
    runtime_work_parser.add_argument("--queue", action="append", default=[])
    runtime_work_parser.add_argument("--capability", action="append", default=[])
    runtime_work_parser.add_argument("--max-concurrency", type=_positive_int)
    runtime_work_parser.add_argument("--heartbeat-seconds", type=_positive_int)
    runtime_work_limit = runtime_work_parser.add_mutually_exclusive_group()
    runtime_work_limit.add_argument("--once", action="store_true")
    runtime_work_limit.add_argument("--max-tasks", type=_positive_int)
    _add_safe_mutation_mode(runtime_work_parser)
    _add_json_arg(runtime_work_parser)
    runtime_work_parser.set_defaults(handler=handle_runtime_work)
    runtime_status_parser = runtime_subparsers.add_parser(
        "status",
        help="Read local/degraded or authenticated remote queue, worker, and run status.",
    )
    runtime_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_status_parser.add_argument("--task-id")
    runtime_status_parser.add_argument("--limit", type=_positive_int, default=200)
    _add_json_arg(runtime_status_parser)
    runtime_status_parser.set_defaults(handler=handle_runtime_status)
    runtime_fallback_parser = runtime_subparsers.add_parser(
        "fallback",
        help="Inspect or operate primary-control-plane to host-local fallback safety.",
    )
    runtime_fallback_subparsers = runtime_fallback_parser.add_subparsers(
        dest="fallback_command", required=True
    )
    fallback_status_parser = runtime_fallback_subparsers.add_parser(
        "status", help="Read durable personal fallback state."
    )
    fallback_status_parser.add_argument("--root", default=DEFAULT_ROOT)
    _add_json_arg(fallback_status_parser)
    fallback_status_parser.set_defaults(handler=handle_runtime_fallback_status)
    fallback_probe_parser = runtime_fallback_subparsers.add_parser(
        "probe", help="Probe the primary control plane and activate local fallback after sustained failure."
    )
    fallback_probe_parser.add_argument("--root", default=DEFAULT_ROOT)
    _add_safe_mutation_mode(fallback_probe_parser)
    _add_json_arg(fallback_probe_parser)
    fallback_probe_parser.set_defaults(handler=handle_runtime_fallback_probe)
    fallback_activate_parser = runtime_fallback_subparsers.add_parser(
        "activate", help="Manually latch this host into local fallback mode."
    )
    fallback_activate_parser.add_argument("--root", default=DEFAULT_ROOT)
    fallback_activate_parser.add_argument("--reason", default="operator_requested")
    _add_safe_mutation_mode(fallback_activate_parser)
    _add_json_arg(fallback_activate_parser)
    fallback_activate_parser.set_defaults(handler=handle_runtime_fallback_activate)
    fallback_failback_parser = runtime_fallback_subparsers.add_parser(
        "failback", help="Return to the primary only after its readiness is proven."
    )
    fallback_failback_parser.add_argument("--root", default=DEFAULT_ROOT)
    _add_safe_mutation_mode(fallback_failback_parser)
    _add_json_arg(fallback_failback_parser)
    fallback_failback_parser.set_defaults(handler=handle_runtime_fallback_failback)
    queue_mode_parser = runtime_subparsers.add_parser(
        "queue-mode",
        help="Read, plan, apply, or roll back the runtime queue backend selector.",
    )
    queue_mode_subparsers = queue_mode_parser.add_subparsers(dest="queue_mode_command", required=True)
    queue_mode_status_parser = queue_mode_subparsers.add_parser("status", help="Read the effective queue mode.")
    queue_mode_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(queue_mode_status_parser)
    queue_mode_status_parser.set_defaults(handler=handle_queue_mode_status)
    queue_mode_plan_parser = queue_mode_subparsers.add_parser("plan", help="Preflight a queue-mode switch.")
    queue_mode_plan_parser.add_argument("target_mode", choices=("filesystem", "execution_fabric"))
    queue_mode_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(queue_mode_plan_parser)
    queue_mode_plan_parser.set_defaults(handler=handle_queue_mode_plan)
    queue_mode_apply_parser = queue_mode_subparsers.add_parser(
        "apply",
        help="Plan by default; pass --apply to persist a preflighted queue-mode switch.",
    )
    queue_mode_apply_parser.add_argument("target_mode", choices=("filesystem", "execution_fabric"))
    queue_mode_apply_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(queue_mode_apply_parser)
    _add_json_arg(queue_mode_apply_parser)
    queue_mode_apply_parser.set_defaults(handler=handle_queue_mode_apply)
    queue_mode_rollback_parser = queue_mode_subparsers.add_parser(
        "rollback",
        help="Plan by default; pass --apply to restore the previous queue mode.",
    )
    queue_mode_rollback_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(queue_mode_rollback_parser)
    _add_json_arg(queue_mode_rollback_parser)
    queue_mode_rollback_parser.set_defaults(handler=handle_queue_mode_rollback)
    queue_mode_reconcile_parser = queue_mode_subparsers.add_parser(
        "reconcile",
        help="Archive and reconcile stale SQLite task state to the authoritative filesystem queue.",
    )
    queue_mode_reconcile_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(queue_mode_reconcile_parser)
    _add_json_arg(queue_mode_reconcile_parser)
    queue_mode_reconcile_parser.set_defaults(handler=handle_queue_mode_reconcile)
    fabric_config_parser = runtime_subparsers.add_parser(
        "config",
        help="Inspect, validate, or transactionally reconcile Execution Fabric instance configuration.",
    )
    fabric_config_subparsers = fabric_config_parser.add_subparsers(
        dest="execution_fabric_config_command",
        required=True,
    )
    fabric_config_status_parser = fabric_config_subparsers.add_parser(
        "status",
        help="Show the effective source, fingerprint, canonical dependencies, and runtime drift.",
    )
    fabric_config_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(fabric_config_status_parser)
    fabric_config_status_parser.set_defaults(handler=handle_execution_fabric_config_status)
    fabric_config_show_parser = fabric_config_subparsers.add_parser(
        "show",
        help="Show the redacted effective document with source and layer provenance.",
    )
    fabric_config_show_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(fabric_config_show_parser)
    fabric_config_show_parser.set_defaults(handler=handle_execution_fabric_config_show)
    fabric_config_diff_parser = fabric_config_subparsers.add_parser(
        "diff",
        help="Compare the effective fingerprint with local catalog and remote policy readback.",
    )
    fabric_config_diff_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(fabric_config_diff_parser)
    fabric_config_diff_parser.set_defaults(handler=handle_execution_fabric_config_diff)
    fabric_config_validate_parser = fabric_config_subparsers.add_parser(
        "validate",
        help="Validate the effective Execution Fabric instance configuration and cross-references.",
    )
    fabric_config_validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(fabric_config_validate_parser)
    fabric_config_validate_parser.set_defaults(handler=handle_execution_fabric_config_validate)
    fabric_config_reconcile_parser = fabric_config_subparsers.add_parser(
        "reconcile",
        help="Plan by default; pass --apply to atomically update queue, pool, limit, lease, and retry state.",
    )
    fabric_config_reconcile_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(fabric_config_reconcile_parser)
    _add_json_arg(fabric_config_reconcile_parser)
    fabric_config_reconcile_parser.set_defaults(handler=handle_execution_fabric_config_reconcile)
    fabric_config_reload_parser = fabric_config_subparsers.add_parser(
        "reload",
        help="Plan or apply an admin-scoped remote policy reload with fingerprint readback.",
    )
    fabric_config_reload_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    fabric_config_reload_parser.add_argument(
        "--expected-fingerprint",
        help="Validated local fingerprint required with --apply.",
    )
    fabric_config_reload_parser.add_argument(
        "--rotation-id",
        help="Witness-prepared rotation UUID required with --apply.",
    )
    fabric_config_reload_parser.add_argument(
        "--preparation-token-file",
        help="Path to the signed witness preparation token required with --apply.",
    )
    _add_safe_mutation_mode(fabric_config_reload_parser)
    _add_json_arg(fabric_config_reload_parser)
    fabric_config_reload_parser.set_defaults(handler=handle_execution_fabric_config_reload)
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
    schedule_create_enabled = schedule_create_parser.add_mutually_exclusive_group()
    schedule_create_enabled.add_argument(
        "--enabled",
        action="store_true",
        help="Enable a governed create; explicit-mode creates are disabled by default.",
    )
    schedule_create_enabled.add_argument("--disabled", action="store_true", help="Create the schedule disabled.")
    schedule_create_mode = schedule_create_parser.add_mutually_exclusive_group()
    schedule_create_mode.add_argument("--dry-run", action="store_true", default=None)
    schedule_create_mode.add_argument("--apply", action="store_true")
    _add_json_arg(schedule_create_parser)
    schedule_create_parser.set_defaults(handler=handle_schedule_create)
    schedule_list_parser = schedule_subparsers.add_parser("list", help="List configured schedules.")
    schedule_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(schedule_list_parser)
    schedule_list_parser.set_defaults(handler=handle_schedule_list)
    schedule_get_parser = schedule_subparsers.add_parser("get", help="Read and validate one schedule.")
    schedule_get_parser.add_argument("schedule_id")
    schedule_get_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_json_arg(schedule_get_parser)
    schedule_get_parser.set_defaults(handler=handle_schedule_get)
    schedule_update_parser = schedule_subparsers.add_parser(
        "update",
        help="Plan or apply an allowlisted schedule-field update.",
    )
    schedule_update_parser.add_argument("schedule_id")
    schedule_update_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    schedule_update_parser.add_argument("--display-name")
    schedule_update_parser.add_argument("--cadence")
    schedule_update_parser.add_argument("--timezone")
    schedule_update_parser.add_argument("--command")
    schedule_update_parser.add_argument("--local-time")
    schedule_update_parser.add_argument("--clear-local-time", action="store_true")
    schedule_update_parser.add_argument("--execution-target")
    schedule_update_parser.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=None)
    _add_safe_mutation_mode(schedule_update_parser)
    _add_json_arg(schedule_update_parser)
    schedule_update_parser.set_defaults(handler=handle_schedule_update)
    for command_name, enabled_value in (("enable", True), ("disable", False)):
        enabled_parser = schedule_subparsers.add_parser(
            command_name,
            help=f"Plan or apply a schedule {command_name} operation.",
        )
        enabled_parser.add_argument("schedule_id")
        enabled_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
        _add_safe_mutation_mode(enabled_parser)
        _add_json_arg(enabled_parser)
        enabled_parser.set_defaults(handler=handle_schedule_enabled, enabled_value=enabled_value)
    schedule_delete_parser = schedule_subparsers.add_parser(
        "delete",
        help="Delete a disabled schedule with no active queue references; dry-run by default.",
    )
    schedule_delete_parser.add_argument("schedule_id")
    schedule_delete_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(schedule_delete_parser)
    _add_json_arg(schedule_delete_parser)
    schedule_delete_parser.set_defaults(handler=handle_schedule_delete)
    schedule_queue_now_parser = schedule_subparsers.add_parser(
        "queue-now",
        help="Queue one named schedule without dispatching or executing it.",
    )
    schedule_queue_now_parser.add_argument("schedule_id")
    schedule_queue_now_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _add_safe_mutation_mode(schedule_queue_now_parser)
    _add_json_arg(schedule_queue_now_parser)
    schedule_queue_now_parser.set_defaults(handler=handle_schedule_queue_now)
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
