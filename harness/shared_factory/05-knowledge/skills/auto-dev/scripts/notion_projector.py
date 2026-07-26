#!/usr/bin/env python3
"""Render Auto Dev state for a best-effort Notion/operator projection.

This helper is intentionally projection-only: it reads local `state.json` and
writes a local projection artifact. Provider writes can consume that artifact,
but projector failures must not change Auto Dev state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "state.json").read_text(encoding="utf-8"))


def render_projection(state: dict[str, Any]) -> str:
    tracker = state.get("tracker") or {}
    pr = state.get("pr") or {}
    decision = state.get("current_state")
    lines = [
        f"# Auto Dev Projection: {state.get('work_item_id')}",
        "",
        f"- Project: `{state.get('project')}`",
        f"- Tracker: `{tracker.get('kind')}:{tracker.get('id')}`",
        f"- Current state: `{state.get('current_state')}`",
        f"- PR: {pr.get('url') or 'none'}",
        f"- Merge policy: `{(state.get('merge') or {}).get('policy')}`",
        f"- Updated at: `{state.get('updated_at')}`",
        "",
        "Projection is write-only/operator-facing; it is not an Auto Dev state source.",
    ]
    if state.get("blocked"):
        lines.insert(5, f"- Blocked: `{state['blocked'].get('reason')}`")
    return "\n".join(lines) + "\n"


def project(run_dir: Path, output: Path) -> dict[str, Any]:
    try:
        state = load_state(run_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_projection(state), encoding="utf-8")
        return {"ok": True, "output": str(output), "projected_at": utc_now()}
    except Exception as exc:  # Projector must be non-blocking.
        return {"ok": False, "error": str(exc), "projected_at": utc_now()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(project(args.run_dir, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
