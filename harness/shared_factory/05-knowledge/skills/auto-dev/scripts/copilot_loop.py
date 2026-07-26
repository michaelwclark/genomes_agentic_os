#!/usr/bin/env python3
"""Classify Copilot review threads for Auto Dev v2 receipts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ACTIONABLE = {"bug", "test_failure", "security", "correctness", "missing_ac"}
FALSE_POSITIVE = {"false_positive", "already_handled", "not_applicable"}
PRODUCT = {"product_decision", "scope_decision", "acceptance_question"}


def classify_thread(thread: dict[str, Any]) -> dict[str, Any]:
    raw = str(thread.get("classification") or "").strip().lower()
    body = str(thread.get("body") or "").lower()
    if raw in ACTIONABLE or any(term in body for term in ["bug", "failing test", "security", "acceptance criterion"]):
        action = "fix_required"
    elif raw in FALSE_POSITIVE or any(term in body for term in ["false positive", "already handled", "not applicable"]):
        action = "reply_and_resolve"
    elif raw in PRODUCT or any(term in body for term in ["product decision", "scope decision", "acceptance question"]):
        action = "block_for_product_decision"
    else:
        action = "needs_triage"
    return {
        "id": thread.get("id"),
        "action": action,
        "body_hash": hash(body),
        "source_classification": raw or None,
    }


def reduce_threads(payload: dict[str, Any]) -> dict[str, Any]:
    threads = payload.get("threads") or []
    rounds = int(payload.get("rounds") or 0)
    max_rounds = int(payload.get("max_rounds_without_progress") or 2)
    classified = [classify_thread(thread) for thread in threads]
    if rounds >= max_rounds and any(item["action"] in {"fix_required", "needs_triage"} for item in classified):
        decision = "blocked_loop_limit"
    elif any(item["action"] == "block_for_product_decision" for item in classified):
        decision = "blocked_product_decision"
    elif any(item["action"] in {"fix_required", "needs_triage"} for item in classified):
        decision = "fix_required"
    else:
        decision = "copilot_clean"
    return {"decision": decision, "rounds": rounds, "threads": classified}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = reduce_threads(json.loads(args.input.read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if result["decision"].startswith("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
