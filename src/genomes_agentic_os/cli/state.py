"""CLI registration for the ``state`` command group.

The state plane lives in :mod:`genomes_agentic_os.state`; this module only
adapts its self-contained registration function to the ``COMMAND_MODULES``
contract used by :mod:`genomes_agentic_os.cli`.
"""

from __future__ import annotations

import argparse

from ..state import register_state_cli


def register(subparsers: argparse._SubParsersAction) -> None:
    register_state_cli(subparsers)
