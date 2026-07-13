"""CLI commands that route requests and build context packets."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..routing import build_context, context_from_here, detect_from_cwd, format_packet, project_records, route_request

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
