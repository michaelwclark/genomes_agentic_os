#!/usr/bin/env python3
"""Block unsafe external tracker/GitHub writeback text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CHECKS = [
    ("local_path", re.compile(r"(?:(?:/Users|/home|/private|/tmp)/[^\s)>\]]+|~/(?:[^\s)>\]]+))")),
    ("private_notion_link", re.compile(r"https?://(?:www\.)?(?:notion\.so|notion\.site|app\.notion\.com)/[^\s)>\]]+", re.I)),
    ("linear_url", re.compile(r"https?://(?:www\.)?linear\.app/[^\s)>\]]+", re.I)),
    ("os_internal_reference", re.compile(r"\b(?:Agentic OS|auto_dev_queue|harness/skills|work-items/0[1-4]-|artifacts/auto-dev)\b")),
    (
        "secret_fragment",
        re.compile(
            r"\b(?:Authorization\s*:\s*(?:Bearer|Basic)\s+\S+|API_KEY|TOKEN|SECRET|PASSWORD|PASS|PRIVATE_KEY|ACCESS_KEY)\s*[:=]?\s*[^\s]+",
            re.I,
        ),
    ),
]


def scrub_text(text: str) -> list[str]:
    return [name for name, pattern in CHECKS if pattern.search(text)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    findings = scrub_text(args.input.read_text(encoding="utf-8"))
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
