#!/usr/bin/env python3
"""Build a write-free, idempotent M4 PR-family creation plan."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def plan(
    topology: dict[str, Any],
    ticket: dict[str, Any],
    source_sha: str,
    source_branch: str,
    existing_prs: list[dict[str, Any]],
) -> dict[str, Any]:
    key = str(ticket.get("key") or ticket.get("id") or "").strip()
    title = str(ticket.get("title") or "").strip()
    if not key or not source_sha or not source_branch:
        raise ValueError("ticket key, source SHA, and source branch are required")
    existing_by_base = {
        str(item.get("baseRefName") or item.get("base") or ""): item
        for item in existing_prs
    }
    required = [item["branch"] for item in topology.get("required_targets", []) if item.get("branch")]
    primary = required[0] if required else None
    proposals = []
    for base in topology.get("missing_targets", []):
        if base in existing_by_base:
            continue
        suffix = "" if base == primary else " 🍒"
        proposals.append(
            {
                "action": "open_pr",
                "base": base,
                "head": f"propagate/{key.lower()}-{_slug(base)}",
                "source_branch": source_branch,
                "source_sha": source_sha,
                "title": f"{key}: {title}{suffix}".strip(),
                "idempotency_key": f"{key}:{base}:{source_sha}",
            }
        )
    return {
        "schema_version": 1,
        "ticket_key": key,
        "source_sha": source_sha,
        "family_complete": not proposals and topology.get("family_complete") is True,
        "proposals": proposals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", required=True, type=Path)
    parser.add_argument("--ticket", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-branch", required=True)
    parser.add_argument("--existing-prs", required=True, type=Path)
    args = parser.parse_args()
    result = plan(
        json.loads(args.topology.read_text()),
        json.loads(args.ticket.read_text()),
        args.source_sha,
        args.source_branch,
        json.loads(args.existing_prs.read_text()),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
