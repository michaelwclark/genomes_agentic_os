"""Command-line interface for Genome's Agentic OS.

Each command group lives in its own module under this package and
exposes ``register(subparsers)``. Adding a group = one import line
plus one ``COMMAND_MODULES`` entry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..cli_help import AosHelpFormatter, env_epilog
from . import scaffold
from . import project
from . import workflow
from . import hosts
from . import automation
from . import run_lifecycle
from . import routing
from . import cockpit
from . import customer
from . import operator
from . import config
from . import notion
from . import runtime
from . import doctor
from . import plans
from . import self_improvement
from . import source_watch
from . import event_graph
from . import state
from . import validate
from . import docs
from . import capability
from . import adaptive
from . import spec
from .project import handle_project_exec

__all__ = ["COMMAND_MODULES", "build_parser", "main"]

COMMAND_MODULES = [
    scaffold,
    project,
    workflow,
    hosts,
    automation,
    run_lifecycle,
    routing,
    cockpit,
    customer,
    operator,
    config,
    notion,
    runtime,
    doctor,
    plans,
    self_improvement,
    source_watch,
    event_graph,
    state,
    validate,
    docs,
    capability,
    adaptive,
    spec,
]


def build_parser(prog: str = "agentic-os") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Scaffold, validate, and operate an Agentic OS root.\n\n"
            "Run 'agentic-os <command> --help' for per-command options."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (used as --root default when set). Default: ~/agentic_os."),
            ],
            config_files=[
                ("~/agentic_os/harness/registries/", "Central registries (automations, skills, commands, etc.)."),
                ("~/agentic_os/harness/shared_factory/", "Shared factory outputs (metrics, run logs, etc.)."),
                ("~/agentic_os/config/hosts.yml", "SSH host registry read by project remote commands."),
            ],
            examples=[
                ("agentic-os init", "Create the base OS tree at ~/agentic_os."),
                ("agentic-os doctor", "Run OS health checks."),
                ("agentic-os validate", "Validate OS root structure."),
                ("agentic-os ps --active", "Show active work dashboard."),
                ("agentic-os self-improvement run --apply", "Run and persist a self-improvement review."),
                ("agentic-os runtime supervise --apply", "Run one full supervisor tick."),
                ("agentic-os config install-tree --apply", "Install config.toml across the OS tree."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_module in COMMAND_MODULES:
        command_module.register(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    prog = Path(sys.argv[0]).name if argv is None else "agentic-os"
    if prog not in {"agentic-os", "aos"}:
        prog = "agentic-os"
    parser = build_parser(prog=prog)
    parse_argv = list(sys.argv[1:] if argv is None else argv)
    project_exec_cmd: list[str] | None = None
    if parse_argv[:2] == ["project", "exec"] and "--" in parse_argv:
        separator = parse_argv.index("--")
        project_exec_cmd = parse_argv[separator + 1 :]
        parse_argv = parse_argv[:separator]
    args = parser.parse_args(parse_argv)
    if project_exec_cmd is not None and getattr(args, "handler", None) == handle_project_exec:
        args.cmd = project_exec_cmd
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
