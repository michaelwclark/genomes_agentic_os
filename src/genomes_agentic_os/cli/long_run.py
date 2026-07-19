"""CLI wiring for the universal long-running execution safety contract."""

from __future__ import annotations

import argparse
import json

import yaml

from ..long_run import (
    control_run,
    list_runs,
    monitor_run,
    recover_run,
    recover_runs,
    start_run,
    status_for_run,
)
from ._shared import DEFAULT_ROOT


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, indent=2, sort_keys=True) if json_output else yaml.safe_dump(value, sort_keys=False).strip())


def _command_after_separator(command: list[str]) -> list[str]:
    return command[1:] if command and command[0] == "--" else command


def handle_start(args: argparse.Namespace) -> int:
    command = _command_after_separator(args.command)
    result = start_run(
        args.root,
        command=command,
        label=args.label or (command[0] if command else "long run"),
        kind=args.kind,
        artifact_dir=args.artifact_dir,
        run_id=args.run_id,
        work_dir=args.work_dir,
        shell=args.shell,
        budgets={
            "wall_clock_minutes": args.wall_clock_minutes,
            "no_progress_minutes": args.no_progress_minutes,
            "max_log_mb": args.max_log_mb,
            "log_rotations": args.log_rotations,
            "max_cpu_percent": args.max_cpu_percent,
            "max_rss_mb": args.max_rss_mb,
        },
        progress_file=args.progress_file,
        checkpoint_strategy=args.checkpoint_strategy,
        mutation_lock=args.mutation_lock,
        preflight_checks=args.preflight_check,
        post_run_checks=args.post_run_check,
        collateral_processes=args.collateral_process,
    )
    if args.json:
        _print(result, json_output=True)
    else:
        run_dir = result["run_dir"]
        print(f"run_dir={run_dir}")
        print(f"state={run_dir}/state.json")
        print(f"summary={run_dir}/summary.md")
        print(f"monitor_pid={result['monitor_pid']}")
    return 0


def handle_status(args: argparse.Namespace) -> int:
    _print(status_for_run(args.run_dir), json_output=args.json)
    return 0


def handle_list(args: argparse.Namespace) -> int:
    _print(list_runs(args.root, active_only=args.active, limit=args.limit), json_output=args.json)
    return 0


def handle_control(args: argparse.Namespace) -> int:
    _print(control_run(args.run_dir, args.long_run_command, grace_seconds=args.grace_seconds), json_output=args.json)
    return 0


def handle_recover(args: argparse.Namespace) -> int:
    result = (
        recover_run(args.run_dir, mark_stale=args.mark_stale)
        if args.run_dir
        else recover_runs(args.root, mark_stale=args.mark_stale)
    )
    _print(result, json_output=args.json)
    stale_count = result.get("stale_count", int(result.get("classification") == "stale"))
    return 1 if stale_count and not args.mark_stale else 0


def handle_monitor(args: argparse.Namespace) -> int:
    return monitor_run(args.run_dir)


def _json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "long-run",
        help="Run and control commands expected to exceed two minutes.",
        description=(
            "Start commands through the durable long-running safety contract: central registry, "
            "bounded logs, watchdogs, resource budgets, pause/resume/cancel, recovery, and terminal receipts."
        ),
    )
    commands = parser.add_subparsers(dest="long_run_command", required=True)

    start = commands.add_parser("start", help="Start one detached, governed long-running command.")
    start.add_argument("--root", default=DEFAULT_ROOT, help="Installed Agentic OS root path.")
    start.add_argument("--label", help="Human-readable run label; defaults to the command name.")
    start.add_argument(
        "--kind",
        choices=("command", "test", "build", "install", "scan", "sync", "import", "export", "backfill", "cleanup", "watcher", "deployment", "migration"),
        default="command",
    )
    start.add_argument("--artifact-dir", help="Parent artifact directory; async-runs is added when needed.")
    start.add_argument("--run-id", help="Override the generated dated run identifier.")
    start.add_argument("--work-dir", help="Working directory for the child process.")
    start.add_argument("--shell", action="store_true", help="Run the command through the shell.")
    start.add_argument("--wall-clock-minutes", "--timeout-minutes", dest="wall_clock_minutes", type=float)
    start.add_argument("--no-progress-minutes", type=float)
    start.add_argument("--max-log-mb", type=float)
    start.add_argument("--log-rotations", type=int)
    start.add_argument("--max-cpu-percent", type=float)
    start.add_argument("--max-rss-mb", type=float)
    start.add_argument("--progress-file", help="Cooperative semantic progress JSON file.")
    start.add_argument("--checkpoint-strategy", help="Required restart/checkpoint/rollback strategy for mutating kinds.")
    start.add_argument("--mutation-lock", help="Absolute lock path, or a name under the installed control-plane locks directory.")
    start.add_argument("--preflight-check", action="append", default=[], help="Bounded shell preflight; repeat as needed.")
    start.add_argument("--post-run-check", action="append", default=[], help="Post-run invariant shell command; repeat as needed.")
    start.add_argument(
        "--collateral-process",
        action="append",
        default=[],
        metavar="NAME:MAX_CPU:MAX_RSS_MB",
        help="System collateral budget; repeat for fseventsd, Docker, or other affected processes.",
    )
    _json(start)
    start.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --.")
    start.set_defaults(handler=handle_start)

    status = commands.add_parser("status", help="Read one durable run state.")
    status.add_argument("--run-dir", required=True)
    _json(status)
    status.set_defaults(handler=handle_status)

    listing = commands.add_parser("list", help="Read the central durable run registry.")
    listing.add_argument("--root", default=DEFAULT_ROOT)
    listing.add_argument("--active", action="store_true", help="Show active states only.")
    listing.add_argument("--limit", type=int, default=100)
    _json(listing)
    listing.set_defaults(handler=handle_list)

    for name in ("pause", "resume", "cancel"):
        control = commands.add_parser(name, help=f"{name.title()} a governed child process group.")
        control.add_argument("--run-dir", required=True)
        control.add_argument("--grace-seconds", type=int, default=20)
        _json(control)
        control.set_defaults(handler=handle_control)

    recover = commands.add_parser("recover", help="Detect and optionally mark orphaned central-registry runs stale.")
    recover.add_argument("--root", default=DEFAULT_ROOT)
    recover.add_argument("--run-dir", help="Recover one run directory instead of scanning the central registry.")
    recover.add_argument("--mark-stale", action="store_true")
    _json(recover)
    recover.set_defaults(handler=handle_recover)

    monitor = commands.add_parser("_monitor", help=argparse.SUPPRESS)
    monitor.add_argument("run_dir")
    monitor.set_defaults(handler=handle_monitor)
