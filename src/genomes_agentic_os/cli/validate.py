"""CLI commands that validate the installed OS root."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..cli_help import AosHelpFormatter, env_epilog
from ..validate import StrictFinding, validate_root, validate_schemas_strict

from ._shared import DEFAULT_ROOT


def handle_validate(args: argparse.Namespace) -> int:
    result = validate_root(args.root)
    strict_findings: list[StrictFinding] = []
    if getattr(args, "strict", False):
        from pathlib import Path as _Path  # noqa: PLC0415
        strict_findings = validate_schemas_strict(_Path(args.root).expanduser())
    if result.ok and not strict_findings:
        print(f"valid: {Path(args.root).expanduser()}")
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for finding in strict_findings:
        print(f"strict: [{finding.schema}] {finding.path}: {finding.message}", file=sys.stderr)
    return 1 if (result.errors or strict_findings) else 0


def register(subparsers) -> None:
    """Register the validate command group."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an installed OS root.",
        description=(
            "Validate the installed OS root directory structure, required files, and YAML contracts. "
            "Exits 0 when valid; prints errors to stderr and exits 1 on failure. "
            "Use --strict to also check structured YAML/JSON files against JSON schemas."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("schemas/", "JSON schemas used by --strict validation (inside the repo package)."),
            ],
            examples=[
                ("agentic-os validate", "Validate the default OS root."),
                ("agentic-os validate --root ~/my-os", "Validate a non-default OS root."),
                ("agentic-os validate --strict", "Also validate YAML files against JSON schemas."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also validate structured files against JSON schemas in schemas/.",
    )
    validate_parser.set_defaults(handler=handle_validate)
