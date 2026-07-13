"""CLI projection commands for the local AgenticOSGui desktop app."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from ..cli_help import AosHelpFormatter
from ..gui_snapshot import DEFAULT_OUTPUT, build_gui_snapshot, build_transcript_snapshot, write_gui_snapshot
from ._shared import DEFAULT_ROOT


def _source_app_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "apps" / "agentic-os-gui"


def _gui_app_candidates(explicit_app: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_app:
        candidates.append(Path(explicit_app).expanduser())
    if configured := os.environ.get("AGENTIC_OS_GUI_APP"):
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path.home() / "Applications" / "AgenticOSGui.app",
            Path("/Applications/AgenticOSGui.app"),
            _source_app_dir() / "release" / "mac-arm64" / "AgenticOSGui.app",
        ]
    )
    return candidates


def handle_gui_open(args: argparse.Namespace) -> int:
    """Open the packaged desktop app without starting a web server."""
    root = Path(args.root).expanduser().resolve(strict=False)
    app_path = next((path.resolve(strict=False) for path in _gui_app_candidates(args.app) if path.is_dir()), None)
    if app_path is None:
        source_dir = _source_app_dir()
        print("AgenticOSGui.app was not found.")
        print(f"development: pnpm --dir {source_dir} dev")
        print(f"package: pnpm --dir {source_dir} package:mac")
        return 1

    result = subprocess.run(  # noqa: S603
        ["/usr/bin/open", str(app_path), "--args", f"--aos-root={root}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"AgenticOSGui could not be opened (status {result.returncode}).")
        return result.returncode
    print(f"app: {app_path}")
    print("opened: true")
    return 0


def handle_gui_snapshot(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve(strict=False)
    snapshot = build_gui_snapshot(
        root,
        codex_home=args.codex_home,
        claude_home=args.claude_home,
        claude_desktop_root=args.claude_desktop_root,
    )
    output_path = None
    if args.output:
        output_path = write_gui_snapshot(snapshot, args.output)
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        if output_path:
            print(f"snapshot: {output_path}")
        print(f"conversations: {snapshot['summary']['conversations']}")
        print(f"codex: {snapshot['summary']['codex']}")
        print(f"claude: {snapshot['summary']['claude']}")
    return 0


def handle_gui_transcript(args: argparse.Namespace) -> int:
    # --root is part of the stable GUI command contract even though provider
    # transcript resolution remains harness-local in v1.
    Path(args.root).expanduser().resolve(strict=False)
    transcript = build_transcript_snapshot(
        args.provider,
        args.conversation_id,
        codex_home=args.codex_home,
        claude_home=args.claude_home,
        claude_desktop_root=args.claude_desktop_root,
    )
    if args.json:
        print(json.dumps(transcript, indent=2, sort_keys=True))
    else:
        for message in transcript["messages"]:
            print(f"{message['role']}: {message['content']}")
    return 0 if transcript["messages"] else 1


def _provider_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", help=argparse.SUPPRESS)
    parser.add_argument("--claude-home", help=argparse.SUPPRESS)
    parser.add_argument("--claude-desktop-root", help=argparse.SUPPRESS)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "gui",
        help="Build local AgenticOSGui conversation projections.",
        description=(
            "Read local Claude/Codex session metadata and project routes into a "
            "versioned, renderer-safe AgenticOSGui snapshot."
        ),
        formatter_class=AosHelpFormatter,
    )
    commands = parser.add_subparsers(dest="gui_command", required=True)

    open_app = commands.add_parser("open", help="Open the packaged AgenticOSGui desktop application.")
    open_app.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    open_app.add_argument("--app", help="Optional explicit path to AgenticOSGui.app.")
    open_app.set_defaults(handler=handle_gui_open)

    snapshot = commands.add_parser("snapshot", help="Build the agentic-os-gui/v1 snapshot.")
    snapshot.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    snapshot.add_argument("--output", help=f"Optional JSON output path; recommended default is <root>/{DEFAULT_OUTPUT}.")
    snapshot.add_argument("--json", action="store_true", help="Print the complete JSON snapshot to stdout.")
    _provider_paths(snapshot)
    snapshot.set_defaults(handler=handle_gui_snapshot)

    transcript = commands.add_parser("transcript", help="Read one visible user/assistant transcript.")
    transcript.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    transcript.add_argument("--provider", required=True, choices=("codex", "claude"), help="Harness provider.")
    transcript.add_argument("--conversation-id", required=True, help="Native harness conversation/session ID.")
    transcript.add_argument("--json", action="store_true", help="Print the transcript JSON envelope to stdout.")
    _provider_paths(transcript)
    transcript.set_defaults(handler=handle_gui_transcript)
