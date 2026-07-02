"""Shared argparse help utilities for the agentic-os CLI.

Use ``AosHelpFormatter`` as the ``formatter_class`` on any parser that needs an
ENVIRONMENT / FILES / EXAMPLES epilog rendered verbatim.  Use ``env_epilog`` to
build the epilog string from structured tables so every tool follows the same
layout without copy-pasting.
"""

from __future__ import annotations

import argparse
import textwrap


class AosHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """RawDescriptionHelpFormatter with a slightly wider default column.

    Subclassing keeps the epilog blocks readable (no line-wrapping) while
    staying 100 % argparse-native — no monkey-patching required.
    """

    def __init__(self, prog: str, indent_increment: int = 2, max_help_position: int = 28, width: int | None = None) -> None:
        super().__init__(prog, indent_increment=indent_increment, max_help_position=max_help_position, width=width)


def env_epilog(
    *,
    env_vars: list[tuple[str, str]] | None = None,
    config_files: list[tuple[str, str]] | None = None,
    examples: list[tuple[str, str]] | None = None,
) -> str:
    """Build a standardised ENVIRONMENT / CONFIG FILES / EXAMPLES epilog string.

    Each argument is a list of ``(name, description)`` tuples.  Sections whose
    list is ``None`` or empty are omitted.

    Example usage::

        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/skills.yml", "Skill registry."),
            ],
            examples=[
                ("agentic-os validate", "Validate the default OS root."),
                ("agentic-os validate --strict", "Also check JSON schemas."),
            ],
        )
    """
    parts: list[str] = []

    if env_vars:
        parts.append("ENVIRONMENT")
        col = max(len(name) for name, _ in env_vars) + 2
        for name, desc in env_vars:
            parts.append(f"  {name:<{col}}{desc}")
        parts.append("")

    if config_files:
        parts.append("CONFIG FILES (read at runtime)")
        col = max(len(path) for path, _ in config_files) + 2
        for path, desc in config_files:
            parts.append(f"  {path:<{col}}{desc}")
        parts.append("")

    if examples:
        parts.append("EXAMPLES")
        for cmd, desc in examples:
            parts.append(f"  {cmd}")
            if desc:
                parts.append(f"      {desc}")
        parts.append("")

    return "\n".join(parts)
