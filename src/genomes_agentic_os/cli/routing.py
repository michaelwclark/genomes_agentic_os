"""CLI commands that route requests and build context packets."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from ..context_compaction import (
    apply_compaction_plan,
    build_compaction_plan,
    check_context_contracts,
    load_context_migration,
    restore_compaction_receipt,
    write_compaction_plan,
)
from ..context_contracts import resolve_context_contract
from ..routing import build_context, context_from_here, detect_from_cwd, format_packet, project_records, route_request
from ..scaffold import domain_path, expand_path, normalize_domain, validate_name

from ._shared import DEFAULT_ROOT


def handle_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request)))
    return 0


def handle_context_build(args: argparse.Namespace) -> int:
    domain = args.domain
    project = args.project
    workflow = args.workflow
    lane = args.lane
    cwd = Path.cwd()

    if not domain:
        inferred = detect_from_cwd(Path(args.root).expanduser().resolve(), cwd)
        domain = inferred.get("domain")
        if not project:
            project = inferred.get("project")
        if not workflow:
            workflow = inferred.get("workflow")
        if not lane:
            lane = inferred.get("lane")

    if not domain and project:
        matches = [record for record in project_records(Path(args.root).expanduser().resolve()) if record["project"] == project]
        if len(matches) == 1:
            domain = matches[0]["domain"]
            lane = lane or matches[0].get("lane") or None
        elif len(matches) > 1:
            raise ValueError(f"project is ambiguous; specify --domain: {project}")

    if not domain:
        raise ValueError("domain is required unless current directory or unique --project identifies a domain")

    print(
        format_packet(
            build_context(
                args.root,
                domain=domain,
                project=project,
                work_item=args.work_item,
                workflow=workflow,
                lane=lane,
                cwd=cwd,
            )
        )
    )
    return 0


def handle_here_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request, cwd=Path.cwd())))
    return 0


def handle_here_context_build(args: argparse.Namespace) -> int:
    print(format_packet(context_from_here(args.root, cwd=Path.cwd())))
    return 0


def _context_target(args: argparse.Namespace) -> tuple[Path, Path]:
    root = expand_path(args.root)
    if args.path:
        target = Path(args.path).expanduser().resolve()
    else:
        if not args.domain or not args.lane:
            raise ValueError("use --path or provide --domain, --lane, and --workflow/--automation")
        domain = normalize_domain(args.domain)
        lane = validate_name(args.lane, "lane")
        if args.workflow:
            target = domain_path(root, domain) / "03-workflows" / lane / validate_name(args.workflow, "workflow")
        elif args.automation:
            target = domain_path(root, domain) / "04-automations" / lane / validate_name(args.automation, "automation")
        else:
            raise ValueError("provide --workflow or --automation")
    if not target.is_dir():
        raise ValueError(f"context target not found: {target}")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"context target is outside root: {target}") from exc
    return root, target


def handle_context_explain(args: argparse.Namespace) -> int:
    root, target = _context_target(args)
    legacy_sources: list[Path] = []
    current = target
    ancestors: list[Path] = []
    while True:
        ancestors.append(current)
        if current == root:
            break
        current = current.parent
    for directory in reversed(ancestors):
        for filename in ("AGENTS.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
            path = directory / filename
            if path.is_file():
                legacy_sources.append(path)
    for filename in (
        "workflow.md",
        "automation.md",
        "quick-reference.md",
        "context-pack.md",
        "permissions.md",
        "runbook.md",
    ):
        path = target / filename
        if path.is_file():
            legacy_sources.append(path)
    resolved = resolve_context_contract(target, root=root, legacy_sources=legacy_sources)
    print(yaml.safe_dump(resolved.as_dict(), sort_keys=False).strip())
    return 0 if resolved.ok else 1


def handle_context_check(args: argparse.Namespace) -> int:
    result = check_context_contracts(args.root)
    print(yaml.safe_dump(result.as_dict(), sort_keys=False).strip())
    return 0 if result.ok else 1


def handle_context_compact(args: argparse.Namespace) -> int:
    if args.dry_run:
        if args.plan or args.receipt_dir:
            raise ValueError("--plan and --receipt-dir are valid only with --apply")
        if args.migration and (args.target or args.promote_legacy or args.baseline_validation):
            raise ValueError(
                "--migration cannot be combined with --target, --promote-legacy, or --baseline-validation"
            )
        migration = load_context_migration(args.root, args.migration) if args.migration else None
        targets = list(migration.targets) if migration else args.target
        promote_legacy = migration.promote_legacy if migration else args.promote_legacy
        baseline_validation = migration.baseline_validation if migration else args.baseline_validation
        migration_metadata = migration.plan_metadata(expand_path(args.root)) if migration else None
        if args.output_dir:
            _, _, plan = write_compaction_plan(
                args.root,
                args.output_dir,
                target_paths=targets,
                promote_legacy=promote_legacy,
                capture_validation_baseline=baseline_validation,
                migration_metadata=migration_metadata,
            )
        else:
            plan = build_compaction_plan(
                args.root,
                target_paths=targets,
                promote_legacy=promote_legacy,
                capture_validation_baseline=baseline_validation,
                migration_metadata=migration_metadata,
            )
        print(yaml.safe_dump(plan, sort_keys=False).strip())
        return 0
    if args.apply:
        if args.target or args.migration or args.promote_legacy or args.baseline_validation:
            raise ValueError(
                "--target, --migration, --promote-legacy, and --baseline-validation are dry-run planning options"
            )
        if not args.plan or not args.receipt_dir:
            raise ValueError("context compact --apply requires --plan and --receipt-dir")
        result = apply_compaction_plan(args.root, args.plan, args.receipt_dir)
        print(yaml.safe_dump(result, sort_keys=False).strip())
        return 0
    raise ValueError("context compact requires exactly one of --dry-run or --apply")


def handle_context_restore(args: argparse.Namespace) -> int:
    result = restore_compaction_receipt(args.root, args.receipt)
    print(yaml.safe_dump(result, sort_keys=False).strip())
    return 0


def _add_context_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", help="Workflow or automation folder to explain.")
    parser.add_argument("--domain")
    parser.add_argument("--lane")
    target_kind = parser.add_mutually_exclusive_group()
    target_kind.add_argument("--workflow")
    target_kind.add_argument("--automation")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")


def register(subparsers) -> None:
    """Register the route / context / here command group."""
    route_parser = subparsers.add_parser("route", help="Route a request to a domain, project, or workflow.")
    route_parser.add_argument("request")
    route_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    route_parser.set_defaults(handler=handle_route)

    context_parser = subparsers.add_parser("context", help="Build deterministic context packets.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build = context_subparsers.add_parser("build", help="Build a context packet.")
    context_build.add_argument("--domain")
    context_build.add_argument("--project")
    context_build.add_argument("--work-item")
    context_build.add_argument("--workflow")
    context_build.add_argument("--lane")
    context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_build.set_defaults(handler=handle_context_build)
    context_explain = context_subparsers.add_parser(
        "explain",
        help="Explain inherited context, overrides, skipped duplicates, and provider routes.",
    )
    _add_context_target_args(context_explain)
    context_explain.set_defaults(handler=handle_context_explain)
    context_check = context_subparsers.add_parser(
        "check",
        help="Validate context manifests and report copied legacy contracts.",
    )
    context_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_check.set_defaults(handler=handle_context_check)
    context_compact = context_subparsers.add_parser(
        "compact",
        help="Plan or apply a guarded, reversible context compaction.",
    )
    context_compact.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    compact_mode = context_compact.add_mutually_exclusive_group()
    compact_mode.add_argument("--dry-run", action="store_true", help="Build a plan without mutating context files.")
    compact_mode.add_argument("--apply", action="store_true", help="Apply a previously reviewed plan.")
    context_compact.add_argument("--output-dir", help="Optional directory for plan and rollback JSON receipts.")
    context_compact.add_argument(
        "--target",
        action="append",
        default=[],
        help="Managed workflow/automation path to migrate; repeat for a bounded group.",
    )
    context_compact.add_argument(
        "--migration",
        help="Approved named batch from the installed context-migrations registry.",
    )
    context_compact.add_argument(
        "--promote-legacy",
        action="store_true",
        help="With explicit --target, create a manifest and promote local contracts to its lane.",
    )
    context_compact.add_argument(
        "--baseline-validation",
        action="store_true",
        help="Record full installed validation so apply can reject new errors without requiring legacy drift cleanup.",
    )
    context_compact.add_argument("--plan", help="Reviewed plan JSON produced by --dry-run.")
    context_compact.add_argument("--receipt-dir", help="Required durable receipt directory for --apply.")
    context_compact.set_defaults(handler=handle_context_compact)
    context_restore = context_subparsers.add_parser(
        "restore",
        help="Restore exact pre-compaction bytes from an applied receipt.",
    )
    context_restore.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_restore.add_argument("--receipt", required=True, help="Applied context-compaction receipt JSON.")
    context_restore.set_defaults(handler=handle_context_restore)

    here_parser = subparsers.add_parser("here", help="Route from the current working directory.")
    here_subparsers = here_parser.add_subparsers(dest="here_command", required=True)
    here_route = here_subparsers.add_parser("route", help="Route a request from the current directory.")
    here_route.add_argument("request")
    here_route.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_route.set_defaults(handler=handle_here_route)
    here_context = here_subparsers.add_parser("context", help="Build context from the current directory.")
    here_context_subparsers = here_context.add_subparsers(dest="here_context_command", required=True)
    here_context_build = here_context_subparsers.add_parser("build", help="Build context from the current directory.")
    here_context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_context_build.set_defaults(handler=handle_here_context_build)
