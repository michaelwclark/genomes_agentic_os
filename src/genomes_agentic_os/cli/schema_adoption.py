"""Operator adapter for explicit schema adoption and consumer migration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from ..cli_help import AosHelpFormatter, env_epilog
from ..schema_adoption import (
    DEFAULT_SCHEMA, SchemaAdoptionError, apply_schema_plan,
    plan_schema_adoption, rollback_schema_transaction,
)
from ._shared import DEFAULT_ROOT


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _guard(handler: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Keep permanent safety refusals typed on the public JSON surface."""
    def guarded(args: argparse.Namespace) -> int:
        try:
            return handler(args)
        except SchemaAdoptionError as exc:
            _print({"schema": "schema-adoption-failure/v1", "error_code": exc.error_code,
                    "retryable": False, "message": str(exc)})
            return 2
    return guarded


def handle_plan(args: argparse.Namespace) -> int:
    result = plan_schema_adoption(
        args.root, schema_name=args.schema_name, consumers=args.consumer,
        historical=args.historical_consumer,
        migrate_consumers=args.schema_adoption_command == "consumer-plan",
    )
    if args.output:
        path = Path(args.output).expanduser().absolute()
        if path.exists() or path.is_symlink() or path.parent.resolve() != path.parent:
            raise SchemaAdoptionError("plan_output", "plan output must be a new file under a canonical existing directory")
        with path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
    _print(result)
    return 0


def handle_apply(args: argparse.Namespace) -> int:
    path = Path(args.plan).expanduser()
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise SchemaAdoptionError("plan_input", "plan must be a bounded existing JSON file")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise SchemaAdoptionError("plan_input", "plan must be valid JSON") from exc
    if not isinstance(plan, dict):
        raise SchemaAdoptionError("plan_input", "plan must be a JSON object")
    if not args.apply:
        raise SchemaAdoptionError("apply_required", "--apply explicitly authorizes local selected-file writes and backups")
    _print(apply_schema_plan(plan, expected_plan_sha256=args.plan_sha256,
                            acknowledge_installed_sha256=args.acknowledge_installed_sha256))
    return 0


def handle_rollback(args: argparse.Namespace) -> int:
    if not args.apply:
        raise SchemaAdoptionError("apply_required", "--apply explicitly authorizes exact backup restoration")
    _print(rollback_schema_transaction(args.root, args.journal, expected_plan_sha256=args.plan_sha256))
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "schema-adoption", help="Plan, adopt, migrate selected consumers, or restore exact schema bytes.",
        description="Manage explicit hash-guarded schema ownership and selected active consumers. Unknown overrides and historical packets are preserved by default.",
        formatter_class=AosHelpFormatter,
        epilog=env_epilog(
            env_vars=[("AGENTIC_OS_ROOT", "Installed OS root default; each plan freezes its exact root.")],
            config_files=[("harness/schemas/package-manifest.yml", "Package ownership and installed schema readback."),
                          ("harness/shared_factory/00-control-plane/state.db", "Read-only canonical active or historical work identity.")],
            examples=[("agentic-os schema-adoption plan --root /tmp/os --output /tmp/adoption-plan.json", "Freeze schema identities without changing the installed schema."),
                      ("agentic-os schema-adoption consumer-plan --root /tmp/os --consumer domains/acme/02-projects/app/work-items/item/autodev.json", "Preview one explicit active legacy consumer migration.")],
        ),
    )
    sub = parser.add_subparsers(dest="schema_adoption_command", required=True)
    for command, description in (
        ("plan", "Freeze one installed/bundled schema and exact selected consumer diagnostics. No installed schema or consumer is changed."),
        ("consumer-plan", "Freeze a supported version-aware active consumer migration. Historical selections are diagnostic-only."),
    ):
        child = sub.add_parser(command, help=description, description=description, formatter_class=AosHelpFormatter)
        child.add_argument("--root", default=DEFAULT_ROOT, help="Installed root (default: %(default)s).")
        child.add_argument("--schema", dest="schema_name", default=DEFAULT_SCHEMA, help="One bundled schema filename (default: %(default)s).")
        child.add_argument("--consumer", action="append", default=[], help="Exact registered active autodev.json path; repeat up to the selection bound.")
        child.add_argument("--historical-consumer", action="append", default=[], help="Exact registered historical autodev.json path for diagnostics only; repeatable.")
        child.add_argument("--output", help="New plan file; omitted output prints the plan without writes.")
        child.set_defaults(handler=_guard(handle_plan))
    apply = sub.add_parser("apply", help="Apply a frozen acknowledged plan.", description="Write only the frozen selected schema/manifest or active consumers. Creates exact backups and a recovery journal.", formatter_class=AosHelpFormatter)
    apply.add_argument("--plan", required=True, help="Frozen JSON plan file. Required.")
    apply.add_argument("--plan-sha256", required=True, help="Exact reviewed plan identity. Required.")
    apply.add_argument("--acknowledge-installed-sha256", required=True, help="Explicit current schema hash, or 'absent' for a fresh root. Required.")
    apply.add_argument("--apply", action="store_true", help="Authorize selected local writes, backups, and readback; no provider or deployment actions.")
    apply.set_defaults(handler=_guard(handle_apply))
    rollback = sub.add_parser("rollback", help="Restore an exact transaction backup.", description="Restore acknowledged original bytes after verifying all current target and backup hashes. Unknown concurrent changes are refused.", formatter_class=AosHelpFormatter)
    rollback.add_argument("--root", default=DEFAULT_ROOT, help="Installed root (default: %(default)s).")
    rollback.add_argument("--journal", required=True, help="Exact transaction journal path. Required.")
    rollback.add_argument("--plan-sha256", required=True, help="Exact frozen plan identity. Required.")
    rollback.add_argument("--apply", action="store_true", help="Authorize selected exact backup restoration and terminal readback.")
    rollback.set_defaults(handler=_guard(handle_rollback))
