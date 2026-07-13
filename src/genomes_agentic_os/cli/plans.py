"""CLI commands that capture future OS ideas and plans."""

from __future__ import annotations

import argparse

from ..plans import capture_plan, format_plan_result

from ._shared import DEFAULT_ROOT


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


def register(subparsers) -> None:
    """Register the plan command group."""
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
