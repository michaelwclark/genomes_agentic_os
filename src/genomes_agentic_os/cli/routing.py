"""CLI commands that route requests and build context packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ..context_compaction import build_compaction_plan, check_context_contracts
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
    if not args.dry_run:
        raise ValueError("context compact is plan-only in this release; pass --dry-run")
    plan = build_compaction_plan(args.root)
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "context-compaction-plan.json").write_text(
            json.dumps({key: value for key, value in plan.items() if key != "rollback_manifest"}, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "context-compaction-rollback.json").write_text(
            json.dumps(plan["rollback_manifest"], indent=2) + "\n",
            encoding="utf-8",
        )
    print(yaml.safe_dump(plan, sort_keys=False).strip())
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
        help="Build a reversible compaction plan without deleting files.",
    )
    context_compact.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_compact.add_argument("--dry-run", action="store_true", help="Required; never mutates context files.")
    context_compact.add_argument("--output-dir", help="Optional directory for plan and rollback JSON receipts.")
    context_compact.set_defaults(handler=handle_context_compact)

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
