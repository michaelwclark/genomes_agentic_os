"""CLI for effective Agentic OS rule queries."""

from __future__ import annotations

import argparse
import json

from ..rule_hierarchy import ALLOWED_EFFECTS, SCOPE_RANK, effective_rules, resolve_rule_target
from ._shared import DEFAULT_ROOT, yaml_dump


def handle_effective_rules(args: argparse.Namespace) -> int:
    root, target = resolve_rule_target(
        args.root,
        path=args.path,
        domain=args.domain,
        project=args.project,
        lane=args.lane,
        workflow=args.workflow,
        automation=args.automation,
    )
    result = effective_rules(
        root,
        target,
        query=args.query,
        scopes=args.scope,
        effects=args.effect,
        local_only=args.local_only,
        conflicts_only=args.conflicts_only,
    )
    print(json.dumps(result, sort_keys=True) if args.json else yaml_dump(result))
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("rules", help="Query effective inherited rules and conflict evidence.")
    commands = parser.add_subparsers(dest="rules_command", required=True)
    effective = commands.add_parser("effective", help="Project deterministic rules applicable to an OS target.")
    effective.add_argument("--path", help="Target folder inside the installed OS root.")
    effective.add_argument("--domain")
    effective.add_argument("--project")
    effective.add_argument("--lane")
    target = effective.add_mutually_exclusive_group()
    target.add_argument("--workflow")
    target.add_argument("--automation")
    effective.add_argument("--query", help="Search IDs, keys, names, summaries, and source references.")
    effective.add_argument("--scope", action="append", choices=tuple(SCOPE_RANK), default=[])
    effective.add_argument("--effect", action="append", choices=tuple(sorted(ALLOWED_EFFECTS)), default=[])
    effective.add_argument("--local-only", action="store_true")
    effective.add_argument("--conflicts-only", action="store_true")
    effective.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    effective.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")
    effective.set_defaults(handler=handle_effective_rules)
