"""CLI commands for conversation-report scans and the local cockpit."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..cli_help import AosHelpFormatter, env_epilog
from ..cockpit import (
    DEFAULT_OUTPUT as COCKPIT_DEFAULT_OUTPUT,
    build_cockpit_bundle,
    build_cockpit_snapshot,
    open_cockpit,
    write_cockpit_snapshot,
)
from ..conversation_reports import format_conversation_report_receipt, scan_conversation_reports

from ._shared import DEFAULT_ROOT, yaml_dump


def handle_conversation_reports_scan(args: argparse.Namespace) -> int:
    """Scan redacted conversation-report JSONL sidecars for repeated OS signals."""
    result = scan_conversation_reports(
        args.root,
        project=args.project,
        output_dir=args.output_dir,
        max_findings=args.max_findings,
        max_files=args.max_files,
    )
    if args.json:
        print(yaml_dump(result))
    else:
        print(format_conversation_report_receipt(result))
    return 0


def handle_cockpit_snapshot(args: argparse.Namespace) -> int:
    """Create the versioned read-only cockpit snapshot."""
    root = Path(args.root).expanduser().resolve()
    snapshot = build_cockpit_snapshot(
        root,
        max_files=args.max_files,
        include_harness_sessions=args.harness_sessions,
    )
    output = Path(args.output).expanduser() if args.output else root / COCKPIT_DEFAULT_OUTPUT / "snapshot.json"
    snapshot_path = write_cockpit_snapshot(snapshot, output)
    if args.json:
        print(yaml_dump(snapshot))
    else:
        print(f"snapshot: {snapshot_path}")
    return 0


def handle_cockpit_build(args: argparse.Namespace) -> int:
    """Build the self-contained local cockpit projection."""
    result = build_cockpit_bundle(
        args.root,
        output_dir=args.output_dir,
        max_files=args.max_files,
        include_harness_sessions=args.harness_sessions,
    )
    print(f"snapshot: {result['snapshot_path']}")
    print(f"cockpit: {result['html_path']}")
    return 0


def handle_cockpit_open(args: argparse.Namespace) -> int:
    """Build and open the local cockpit in the default browser."""
    result = open_cockpit(
        args.root,
        output_dir=args.output_dir,
        max_files=args.max_files,
        include_harness_sessions=args.harness_sessions,
    )
    print(f"cockpit: {result['html_path']}")
    print(f"opened: {str(result['opened']).lower()}")
    return 0


def register(subparsers) -> None:
    """Register the conversation-reports / cockpit command group."""
    conversation_reports_parser = subparsers.add_parser(
        "conversation-reports",
        help="Mine local conversation-report JSONL sidecars for repeated OS hardening signals.",
        description=(
            "Read redacted Agentic OS conversation-report JSONL sidecars and produce "
            "a local signal report. The scanner is read-only unless --output-dir is passed."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("<project>/work-items/*/*/logs/conversations/*.jsonl", "Redacted conversation transcripts."),
                ("<project>/work-items/", "Existing packet index used for duplicate matching."),
            ],
            examples=[
                (
                    "agentic-os conversation-reports scan --root ~/agentic_os --project genomes_agentic_os",
                    "Scan one project and print a compact report.",
                ),
                (
                    "agentic-os conversation-reports scan --root ~/agentic_os --project genomes_agentic_os --output-dir /tmp/aos-report",
                    "Write JSON, Markdown, and backlog-candidate artifacts.",
                ),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    conversation_reports_subparsers = conversation_reports_parser.add_subparsers(
        dest="conversation_reports_command",
        required=True,
    )
    conversation_reports_scan = conversation_reports_subparsers.add_parser(
        "scan",
        help="Scan conversation-report sidecars and optionally write report artifacts.",
    )
    conversation_reports_scan.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    conversation_reports_scan.add_argument("--project", help="Limit scan and work-item matching to one project slug.")
    conversation_reports_scan.add_argument("--output-dir", help="Directory for JSON, Markdown, and backlog report artifacts.")
    conversation_reports_scan.add_argument("--max-findings", type=int, default=200, help="Maximum findings to emit.")
    conversation_reports_scan.add_argument("--max-files", type=int, help="Maximum transcript files to scan, for smoke tests.")
    conversation_reports_scan.add_argument("--json", action="store_true", help="Print YAML-shaped machine-readable result.")
    conversation_reports_scan.set_defaults(handler=handle_conversation_reports_scan)

    cockpit_parser = subparsers.add_parser(
        "cockpit",
        help="Build or open the local engineering-lead OS cockpit.",
        description=(
            "Create a read-only, offline cockpit from canonical Agentic OS files and "
            "bounded Claude/Codex metadata. No external systems or cleanup actions are mutated."
        ),
        formatter_class=AosHelpFormatter,
    )
    cockpit_subparsers = cockpit_parser.add_subparsers(dest="cockpit_command", required=True)
    cockpit_snapshot = cockpit_subparsers.add_parser("snapshot", help="Write the versioned cockpit JSON snapshot.")
    cockpit_snapshot.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    cockpit_snapshot.add_argument("--output", help="Snapshot JSON path; defaults under the installed OS report root.")
    cockpit_snapshot.add_argument("--max-files", type=int, default=500, help="Maximum recent conversation/source files to inspect.")
    cockpit_snapshot.add_argument(
        "--harness-sessions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include bounded metadata from local Claude/Codex session stores.",
    )
    cockpit_snapshot.add_argument("--json", action="store_true", help="Also print the snapshot as YAML-shaped output.")
    cockpit_snapshot.set_defaults(handler=handle_cockpit_snapshot)

    cockpit_build = cockpit_subparsers.add_parser("build", help="Build snapshot.json and a self-contained index.html.")
    cockpit_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    cockpit_build.add_argument("--output-dir", help="Output directory; defaults under the installed OS report root.")
    cockpit_build.add_argument("--max-files", type=int, default=500, help="Maximum recent conversation/source files to inspect.")
    cockpit_build.add_argument(
        "--harness-sessions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include bounded metadata from local Claude/Codex session stores.",
    )
    cockpit_build.set_defaults(handler=handle_cockpit_build)

    cockpit_open = cockpit_subparsers.add_parser("open", help="Build and open the cockpit in the default browser.")
    cockpit_open.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    cockpit_open.add_argument("--output-dir", help="Output directory; defaults under the installed OS report root.")
    cockpit_open.add_argument("--max-files", type=int, default=500, help="Maximum recent conversation/source files to inspect.")
    cockpit_open.add_argument(
        "--harness-sessions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include bounded metadata from local Claude/Codex session stores.",
    )
    cockpit_open.set_defaults(handler=handle_cockpit_open)
