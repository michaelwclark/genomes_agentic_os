"""Explicit recovery-set CLI; maintenance actors remain independently owned."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import execution_fabric_recovery as recovery
from .. import execution_fabric_recovery_daily as daily
from ..execution_fabric_config import load_execution_fabric_config, resolve_execution_fabric_host_id
from ..hosts import load_hosts
from ._shared import DEFAULT_ROOT, yaml_dump


def _settings(args: argparse.Namespace, *, role: str | None = None) -> dict:
    config = load_execution_fabric_config(args.root)
    settings = config.value["execution_fabric"].get("recovery_sets", {})
    if args.apply:
        if settings.get("enabled") is not True:
            raise recovery.RecoverySetError("recovery sets must be explicitly enabled in canonical policy")
        if role:
            host = resolve_execution_fabric_host_id(args.root)
            if host != settings.get(role + "_host_id"):
                raise recovery.RecoverySetError("recovery actor is bound to a different canonical host")
    return settings


def _custodian_inputs(args: argparse.Namespace, settings: dict) -> None:
    if args.apply:
        for argument, configured in (("repository", "repository"), ("password_file", "password_file")):
            value = settings.get(configured)
            if not value or Path(getattr(args, argument)).expanduser().absolute() != Path(value).expanduser().absolute():
                raise recovery.RecoverySetError("custodian repository/key reference differs from canonical policy")


def handle(args: argparse.Namespace) -> int:
    try:
        action = args.recovery_action
        if action == "plan":
            result = recovery.plan_recovery_set(args.capture_plan)
        elif action == "daily":
            settings = _settings(args, role="primary")
            if args.apply and (not settings.get("daily_plan_file") or
                Path(args.daily_plan).expanduser().absolute() != Path(settings["daily_plan_file"]).expanduser().absolute()):
                raise recovery.RecoverySetError("daily plan must match the canonical configured source-bound plan")
            result = daily.run_daily_recovery(args.daily_plan, apply=args.apply)
        elif action == "prepare":
            _settings(args, role="primary")
            result = recovery.prepare_recovery_set(
                args.capture_plan, args.maintenance_receipt, args.output, apply=args.apply
            )
        elif action == "pull":
            settings = _settings(args, role="custodian")
            if args.source_host != settings.get("primary_host_id"):
                raise recovery.RecoverySetError("pull source must be the declared primary host")
            result = recovery.pull_recovery_set(
                args.source_host, args.remote_source, args.output,
                source_root=settings.get("remote_staging_root") or "",
                registered_hosts=load_hosts(args.root), apply=args.apply,
            )
        elif action == "collect":
            settings = _settings(args, role="custodian")
            _custodian_inputs(args, settings)
            result = recovery.collect_recovery_set(
                args.source_dir, args.repository, args.password_file, args.set_id,
                restic=args.restic, verify_target=args.verify_target, apply=args.apply,
                max_age_seconds=settings.get("max_age_seconds", 86400),
            )
        elif action == "collect-current":
            settings = _settings(args, role="custodian")
            _custodian_inputs(args, settings)
            if args.source_host != settings.get("primary_host_id"):
                raise recovery.RecoverySetError("current-set source must be the declared primary")
            if args.apply and (not settings.get("local_staging_root") or
                Path(args.local_root).expanduser().absolute() != Path(settings["local_staging_root"]).expanduser().absolute()):
                raise recovery.RecoverySetError("current-set destination differs from canonical private staging root")
            result = recovery.collect_current_recovery_set(
                args.source_host, args.local_root, args.repository, args.password_file,
                source_root=settings.get("remote_staging_root") or "",
                registered_hosts=load_hosts(args.root), restic=args.restic, apply=args.apply,
                max_age_seconds=settings.get("max_age_seconds", 86400),
            )
        elif action == "verify":
            result = recovery.verify_recovery_set(args.restored_root)
        elif action in ("restore-plan", "restore-isolated"):
            if action == "restore-isolated" and args.apply:
                settings = _settings(args, role="custodian")
                _custodian_inputs(args, settings)
            result = recovery.restore_recovery_set_isolated(
                args.repository, args.password_file, args.snapshot_id, args.target,
                restic=args.restic, apply=args.apply and action == "restore-isolated",
            )
        elif action in ("retention-plan", "retention-apply"):
            if action == "retention-apply" and args.apply:
                settings = _settings(args, role="custodian")
                _custodian_inputs(args, settings)
                result = recovery.apply_retention(
                    args.receipts_dir, args.repository, args.password_file,
                    args.maintenance_receipt, keep=args.daily, weekly=args.weekly,
                    monthly=args.monthly, pinned=tuple(args.pin),
                    restic=args.restic, apply=True,
                )
            else:
                result = recovery.plan_retention(
                    args.receipts_dir, keep=args.daily, weekly=args.weekly,
                    monthly=args.monthly, pinned=tuple(args.pin),
                )
        else:
            raise recovery.RecoverySetError("unsupported recovery command")
    except recovery.RecoverySetError as error:
        result = {"status": "held", "reason": str(error), "authorityTransferAuthorized": False}
        print(json.dumps(result, sort_keys=True) if args.json else yaml_dump(result))
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never expose paths, secret input payloads, configuration or subprocess output.
        result = {"status": "held", "reason": "required recovery input or canonical policy is invalid",
                  "authorityTransferAuthorized": False}
        print(json.dumps(result, sort_keys=True) if args.json else yaml_dump(result))
        return 1
    print(json.dumps(result, sort_keys=True) if args.json else yaml_dump(result))
    return 0


def _common(parser: argparse.ArgumentParser, *, mutation: bool = False) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root.")
    parser.add_argument("--json", action="store_true")
    if mutation:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Perform the explicit bounded operation.")
        mode.add_argument("--dry-run", action="store_true")
    else:
        parser.set_defaults(apply=False)
    parser.set_defaults(handler=handle)


def _repository(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True, help="Initialized custodian-local encrypted repository.")
    parser.add_argument("--password-file", required=True, help="Protected file reference; never a password value.")
    parser.add_argument("--restic", default="restic", help="Native restic executable.")


def register(runtime_subparsers: argparse._SubParsersAction) -> None:
    group = runtime_subparsers.add_parser("recovery-set", help="Capture, encrypt and verify complete recovery sets.")
    commands = group.add_subparsers(dest="recovery_action", required=True)
    plan = commands.add_parser("plan", help="Validate the capture contract without copying bytes.")
    plan.add_argument("--capture-plan", required=True)
    _common(plan)
    scheduled = commands.add_parser("daily", help="Produce a fresh complete set through qualified retained writer barriers.")
    scheduled.add_argument("--daily-plan", required=True)
    _common(scheduled, mutation=True)
    prepare = commands.add_parser("prepare", help="Capture complete source-bound bytes under verified maintenance.")
    prepare.add_argument("--capture-plan", required=True)
    prepare.add_argument("--maintenance-receipt", required=True)
    prepare.add_argument("--output", required=True, help="New private directory.")
    _common(prepare, mutation=True)
    pull = commands.add_parser("pull", help="Pull a declared primary staging set through fixed SSH/tar.")
    pull.add_argument("--source-host", required=True)
    pull.add_argument("--remote-source", required=True)
    pull.add_argument("--output", required=True)
    _common(pull, mutation=True)
    collect = commands.add_parser("collect", help="Encrypt and read back an exact snapshot on the custodian.")
    collect.add_argument("--source-dir", required=True)
    collect.add_argument("--set-id", required=True)
    collect.add_argument("--verify-target", help="New private isolated byte-readback target.")
    _repository(collect)
    _common(collect, mutation=True)
    current = commands.add_parser("collect-current", help="Collect the exact successful immutable source set selected by its manifest pointer.")
    current.add_argument("--source-host", required=True)
    current.add_argument("--local-root", required=True)
    _repository(current)
    _common(current, mutation=True)
    verify = commands.add_parser("verify", help="Verify bytes and all authority/reference closure.")
    verify.add_argument("--restored-root", required=True)
    _common(verify)
    for name in ("restore-plan", "restore-isolated"):
        restore = commands.add_parser(name, help="Restore exact encrypted snapshot into a new private root.")
        _repository(restore)
        restore.add_argument("--snapshot-id", required=True, help="Full immutable native snapshot ID.")
        restore.add_argument("--target", required=True)
        _common(restore, mutation=name == "restore-isolated")
    for name in ("retention-plan", "retention-apply"):
        retention = commands.add_parser(name, help="Preserve daily/weekly/monthly and drill-pinned snapshots.")
        retention.add_argument("--receipts-dir", required=True)
        retention.add_argument("--daily", type=int, default=14)
        retention.add_argument("--weekly", type=int, default=4)
        retention.add_argument("--monthly", type=int, default=3)
        retention.add_argument("--pin", action="append", default=[], help="Exact drill-pinned snapshot ID.")
        if name == "retention-apply":
            _repository(retention)
            retention.add_argument("--maintenance-receipt", required=True)
        _common(retention, mutation=name == "retention-apply")
