"""CLI commands that install, update, and upkeep OS docs."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..documentation_upkeep import build_documentation_upkeep_plan, format_documentation_upkeep_result
from ..scaffold import install_docs

from ._shared import DEFAULT_ROOT, print_result


def handle_docs_install(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_update(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_upkeep(args: argparse.Namespace) -> int:
    result = build_documentation_upkeep_plan(
        args.root,
        write_receipt=bool(args.write_receipt),
        output_dir=args.output_dir,
    )
    print(format_documentation_upkeep_result(result))
    return 0 if result.get("ok") else 1


def register(subparsers) -> None:
    """Register the docs command group."""
    docs_parser = subparsers.add_parser(
        "docs",
        help="Install or update runtime OS documentation.",
        description=(
            "Install, update, or run upkeep on runtime OS documentation assets: "
            "templates, manuals, commands, skills, and plans. "
            "'install' is a one-shot full install; 'update' adds only missing assets without overwriting local edits; "
            "'upkeep' runs the observe-mode drift planner against the upkeep registry."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/docs/", "Installed runtime documentation assets."),
                ("harness/registries/documentation-upkeep.yml", "Documentation upkeep registry (used by 'upkeep')."),
            ],
            examples=[
                ("agentic-os docs install", "Install all runtime documentation assets."),
                ("agentic-os docs update", "Add missing assets without overwriting existing ones."),
                ("agentic-os docs upkeep --write-receipt", "Run upkeep drift planner and write receipt artifacts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_install = docs_subparsers.add_parser(
        "install",
        help="Install runtime templates, manual, commands, skills, and plans.",
    )
    docs_install.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_install.set_defaults(handler=handle_docs_install)
    docs_update = docs_subparsers.add_parser(
        "update",
        help="Add missing runtime template, manual, command, skill, and plan assets without overwriting local edits.",
    )
    docs_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_update.set_defaults(handler=handle_docs_update)
    docs_upkeep = docs_subparsers.add_parser(
        "upkeep",
        help="Run the observe-mode documentation upkeep registry and drift planner.",
    )
    docs_upkeep.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_upkeep.add_argument("--write-receipt", action="store_true", help="Write local YAML/Markdown receipt artifacts.")
    docs_upkeep.add_argument("--output-dir", help="Optional receipt output directory.")
    docs_upkeep.set_defaults(handler=handle_docs_upkeep)
