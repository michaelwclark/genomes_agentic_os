#!/usr/bin/env python3
"""Read-only guard for the work-item, worktree, and Linear change contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys


SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from genomes_agentic_os.state.control_plane import ControlPlaneError, validate_change_linkage  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that one code change has a canonical work item, worktree, and Linear issue."
    )
    parser.add_argument("--db", required=True, help="Existing canonical state.db; opened read-only.")
    parser.add_argument("--work-item", required=True, help="Canonical work-item id for this change.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        message = "canonical state database is missing"
        print(json.dumps({"ok": False, "error": message}) if args.json else message)
        return 2
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM work_items WHERE id = ?", (args.work_item,)).fetchone()
        conn.close()
        if row is None:
            raise ControlPlaneError("canonical work item is not present")
        linkage = validate_change_linkage(dict(row))
    except (sqlite3.Error, ControlPlaneError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}) if args.json else str(exc))
        return 1
    result = {"ok": True, "linkage": linkage}
    print(json.dumps(result, sort_keys=True) if args.json else f"linked: {linkage['linear_issue']} {linkage['work_item_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
