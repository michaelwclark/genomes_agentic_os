"""Manual cold recovery CLI with fixed, explicit offline actor entrypoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from ..cold_recovery import cold_recovery_operation

ACTIONS = ("inspect", "prepare", "approve", "apply", "status", "resume", "canary", "accept", "initialize-anchor")


def handle(args: argparse.Namespace) -> int:
    """Validate a dry-run by default; never infer an installed service identity."""
    service_root = Path(args.service_root).expanduser().absolute()
    node = shutil.which("node")
    if node is None:
        print(json.dumps({"ok": False, "error": "node_unavailable"}))
        return 1
    witness = service_root / "execution-fabric-leadership-witness/dist/src/cold-recovery-main.js"
    ledger = service_root / "execution-fabric-control-plane/dist/src/cold-recovery-main.js"
    try:
        result = cold_recovery_operation(
            args.cold_action,
            args.request,
            policy_file=args.policy,
            anchor_file=args.anchor,
            journal_dir=args.journal_dir,
            witness_command=[node, str(witness)],
            ledger_command=[node, str(ledger), "--database-url-file", args.database_url_file],
            dry_run=not args.apply,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Paths are references only; actor/database exception text may contain secrets.
        print(json.dumps({"ok": False, "error": "cold_recovery_refused", "error_class": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2 if args.json else None))
    return 0 if result.get("ok", False) else 1


def register(runtime_subparsers) -> None:
    parser = runtime_subparsers.add_parser(
        "cold-recovery",
        help="Plan and operate an explicit fenced offline recovery; defaults to dry-run.",
    )
    actions = parser.add_subparsers(dest="cold_action", required=True)
    for action in ACTIONS:
        command = actions.add_parser(action)
        command.add_argument("--request", required=True, help="Closed exact recovery request JSON.")
        command.add_argument("--policy", required=True, help="Reviewed cold recovery policy JSON.")
        command.add_argument("--anchor", required=True, help="Independent durable freshness anchor.")
        command.add_argument("--journal-dir", required=True, help="Private immutable recovery journal directory.")
        command.add_argument("--service-root", required=True, help="Reviewed service build root containing the two fixed dist entrypoints.")
        command.add_argument("--database-url-file", required=True, help="Private target-only PostgreSQL credential reference; no URL in argv.")
        command.add_argument("--apply", action="store_true", help="Execute this exact qualified operation; never starts production services.")
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=handle)
