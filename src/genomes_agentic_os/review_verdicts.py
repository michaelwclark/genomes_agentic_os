"""Shared fail-closed reconciliation for Auto-Dev reviewer verdicts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


VERDICT_PATTERN = re.compile(
    r"AGENTIC_OS_REVIEW_VERDICT:\s*(CLEAN|FINDINGS)", re.IGNORECASE
)
JSON_ARRAY_PATTERN = re.compile(r"```json\s*(\[.*?\])\s*```", re.IGNORECASE | re.DOTALL)
MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE
)
BLOCKER_TITLE_PATTERN = re.compile(
    r"^(?:\*\*|__)?BLOCKER(?:\*\*|__)?"
    r"(?:\s+(?:#?\d+|[A-Za-z]\d+))?\s*(?::|[-\u2013\u2014])\s*\S",
    re.IGNORECASE,
)
INACTIVE_CONTEXT_PATTERN = re.compile(
    r"\b(?:addressed|closed|fixed|historical|previous(?:ly)?|prior|resolved|verified)\b",
    re.IGNORECASE,
)
INACTIVE_FINDING_STATUSES = {
    "addressed",
    "closed",
    "fixed",
    "resolved",
    "verified",
}
BLOCKING_SEVERITIES = {"blocker", "critical", "high"}


def _terminal_verdict(text: str) -> tuple[str | None, list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None, []
    match = VERDICT_PATTERN.fullmatch(lines[-1])
    return (match.group(1).upper() if match else None), lines


def _outside_fences(text: str) -> str:
    """Remove fenced examples so they cannot manufacture active headings."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def markdown_has_active_blocker(body: str) -> bool:
    """Detect unquoted active BLOCKER sections while ignoring prior/resolved ones."""
    headings: list[tuple[int, str]] = []
    for match in MARKDOWN_HEADING_PATTERN.finditer(_outside_fences(body)):
        level = len(match.group("marks"))
        title = match.group("title").strip()
        while headings and headings[-1][0] >= level:
            headings.pop()
        inactive_ancestor = any(INACTIVE_CONTEXT_PATTERN.search(value) for _, value in headings)
        if (
            BLOCKER_TITLE_PATTERN.match(title)
            and not inactive_ancestor
            and not INACTIVE_CONTEXT_PATTERN.search(title)
        ):
            return True
        headings.append((level, title))
    return False


def _is_template_example(findings: list[Any]) -> bool:
    """Recognize the literal schema example if a harness echoes its prompt."""
    if len(findings) != 1 or not isinstance(findings[0], Mapping):
        return False
    severity = str(findings[0].get("severity") or "")
    category = str(findings[0].get("category") or "")
    return "|" in severity or "|" in category


def _finding_is_active_blocker(finding: Any) -> bool:
    if not isinstance(finding, Mapping):
        return True
    status = str(finding.get("status") or "").strip().lower()
    if status in INACTIVE_FINDING_STATUSES or finding.get("resolved") is True:
        return False
    blocking = finding.get("blocking")
    if isinstance(blocking, bool):
        return blocking
    severity = str(finding.get("severity") or "").strip().lower()
    return severity in BLOCKING_SEVERITIES


def json_has_active_blocker(body: str) -> tuple[bool, bool]:
    """Inspect every reviewer findings array; later empty arrays cannot erase one."""
    blocks = JSON_ARRAY_PATTERN.findall(body)
    if not blocks:
        return False, False
    saw_findings_payload = False
    for raw in blocks:
        try:
            findings = json.loads(raw)
        except json.JSONDecodeError:
            return True, False
        if not isinstance(findings, list):
            return True, False
        if _is_template_example(findings):
            continue
        saw_findings_payload = True
        if any(_finding_is_active_blocker(finding) for finding in findings):
            return True, True
    return False, saw_findings_payload


def reconcile_markdown_verdict(text: str) -> tuple[str, bool]:
    """CLEAN permits warnings, but never an unresolved BLOCKER section."""
    declared, lines = _terminal_verdict(text)
    if declared is None:
        return "findings", False
    if declared == "FINDINGS":
        return "findings", True
    body = "\n".join(lines[:-1])
    return ("findings", True) if markdown_has_active_blocker(body) else ("clean", True)


def reconcile_json_verdict(text: str) -> tuple[str, bool]:
    """CLEAN permits resolved/non-blocking findings across all JSON arrays."""
    declared, lines = _terminal_verdict(text)
    if declared is None:
        return "findings", False
    if declared == "FINDINGS":
        return "findings", True
    blocking, valid_payload = json_has_active_blocker("\n".join(lines[:-1]))
    if not valid_payload:
        return "findings", False
    return ("findings", True) if blocking else ("clean", True)
