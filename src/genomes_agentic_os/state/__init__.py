"""SQLite state plane for the installed Agentic OS (AGE-39).

Replaces whole-file YAML rewrites (run-queue.yml, one-file-per-event
ledgers, cursor files) with an indexed, WAL-mode SQLite database using only
the Python standard library (``sqlite3`` — no new dependency). See
``docs/design-notes/state-plane.md`` for the schema reference, import
workflow, and the two-milestone cutover plan.

This package is self-contained: the only integration point the rest of the
CLI needs is ``register_state_cli`` (added once ``state/cli.py`` lands),
wired into the top-level argparse subparsers with one import and one call.
"""

from __future__ import annotations
