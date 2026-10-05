"""Strict native Claude result framing for new opposing-review invocations."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import ValidationError, validate


class NativeReviewOutputError(ValueError):
    """A native result cannot establish structured review authority."""


FINDING_STRINGS = (
    "id", "severity", "category", "file", "title", "detail", "suggested_fix"
)
NATIVE_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "findings"],
    "properties": {
        "verdict": {"type": "string", "enum": ["CLEAN", "FINDINGS"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [*FINDING_STRINGS, "line", "blocking"],
                "properties": {
                    **{key: {"type": "string", "minLength": 1} for key in FINDING_STRINGS},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "category": {
                        "type": "string",
                        "enum": ["correctness", "acceptance", "security", "architecture", "durability", "tests", "api_ux"],
                    },
                    "line": {"type": "integer", "minimum": 1},
                    "blocking": {"type": "boolean"},
                },
            },
        },
    },
}
VERDICT_MARKER = re.compile(r"AGENTIC_OS_REVIEW_VERDICT[^\r\n]*", re.IGNORECASE)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise NativeReviewOutputError("native result contains duplicate object keys")
        value[key] = item
    return value


def _invalid_constant(_value: str) -> None:
    raise NativeReviewOutputError("native result contains a non-JSON numeric constant")


def parse_native_review_output(stdout: bytes) -> dict[str, Any]:
    """Validate one success envelope and a single explicit typed review payload.

    Native metadata remains outside the verdict contract. Commentary never
    supplies verdict authority; explicit markers must agree with the payload.
    """

    try:
        envelope = json.loads(
            stdout.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeReviewOutputError("native result must be one UTF-8 JSON object") from exc
    if not isinstance(envelope, dict):
        raise NativeReviewOutputError("native result envelope must be an object")
    if not (
        envelope.get("type") == "result"
        and envelope.get("subtype") == "success"
        and envelope.get("is_error") is False
    ):
        raise NativeReviewOutputError("native result envelope is not successful")
    if envelope.get("error") or envelope.get("errors"):
        raise NativeReviewOutputError("native success envelope contains errors")
    if "verdict" in envelope or "findings" in envelope:
        raise NativeReviewOutputError("native result contains ambiguous verdict fields")
    if not isinstance(envelope.get("result"), str):
        raise NativeReviewOutputError("native result commentary must be a string")
    payload = envelope.get("structured_output")
    try:
        validate(payload, NATIVE_REVIEW_SCHEMA)
    except ValidationError as exc:
        raise NativeReviewOutputError("native structured review does not match its schema") from exc
    findings = payload["findings"]
    ids: set[str] = set()
    for finding in findings:
        if type(finding["line"]) is not int:
            raise NativeReviewOutputError("native finding line must be an integer")
        if any(not finding[key].strip() for key in FINDING_STRINGS):
            raise NativeReviewOutputError("native finding text must be non-empty")
        finding_id = finding["id"].strip()
        if finding_id in ids:
            raise NativeReviewOutputError("native findings contain duplicate IDs")
        ids.add(finding_id)
        if finding["blocking"] and finding["severity"] not in {"critical", "high"}:
            raise NativeReviewOutputError("native blocking finding must be critical or high")
    verdict = payload["verdict"]
    if verdict == "CLEAN" and any(finding["blocking"] for finding in findings):
        raise NativeReviewOutputError("native CLEAN verdict contradicts blocking findings")
    if verdict == "FINDINGS" and not findings:
        raise NativeReviewOutputError("native FINDINGS verdict requires findings")
    commentary = "\n".join([envelope["result"], payload.get("summary", "")])
    markers = VERDICT_MARKER.findall(commentary)
    if markers and (len(markers) != 1 or markers[0].strip().upper() != f"AGENTIC_OS_REVIEW_VERDICT: {verdict}"):
        raise NativeReviewOutputError("native commentary contains ambiguous or contradictory verdict markers")
    return {
        **payload,
        "findings": [{**finding, "id": finding["id"].strip()} for finding in findings],
    }


def project_native_review(payload: dict[str, Any]) -> str:
    """Derive deterministic legacy ledger input without rewriting native stdout."""

    return (
        "```json\n"
        + json.dumps(payload["findings"], indent=2, sort_keys=True)
        + "\n```\nAGENTIC_OS_REVIEW_VERDICT: "
        + payload["verdict"]
        + "\n"
    )
