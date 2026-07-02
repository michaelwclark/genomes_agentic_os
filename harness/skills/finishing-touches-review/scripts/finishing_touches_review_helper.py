#!/usr/bin/env python3
"""Deterministic helper prototype for finishing-touches review artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


DECISION_PRECEDENCE = [
    "blocked_identity_unproven",
    "blocked_reviewer_unavailable",
    "blocked_reviewer_runtime",
    "blocked_severe_adjudication",
    "blocked_external_output",
    "blocked_review_findings",
    "blocked_copilot",
    "blocked_validation",
    "blocked_loop_limit",
    "blocked_user_decision",
    "pending_checks",
    "ready_post_pr_checks",
    "ready_pre_pr",
]

REQUEST_FIELDS = [
    "work_item_id",
    "run_id",
    "repo_path",
    "implementation_summary",
    "spec_source",
    "builder_model",
    "selected_reviewer_model",
    "reviewer_selection_source",
    "target_branch",
    "base_sha",
    "head_sha",
    "diff_hash",
    "pr_number",
    "artifact_dir",
    "mode",
]

LEDGER_EVENT_TYPES = {
    "finding_opened",
    "finding_accepted",
    "fix_started",
    "fix_recorded",
    "recheck_requested",
    "finding_verified",
    "finding_reopened",
    "finding_rejected",
    "finding_deferred",
    "approval_recorded",
    "validation_planned",
    "validation_downgraded",
    "validation_recorded",
    "copilot_thread_recorded",
    "model_identity_recorded",
    "blocker_computed",
    "readiness_decided",
}

SEVERITIES = {"Critical", "High", "Medium", "Low"}

FINDING_STATUSES = {
    "OPEN",
    "ACCEPTED",
    "FIXED_PENDING_RECHECK",
    "VERIFIED",
    "REJECTED_WITH_RATIONALE",
    "DEFERRED_WITH_OWNER",
    "BLOCKING_UNRESOLVED",
}

EVENT_STATUS = {
    "finding_opened": "OPEN",
    "finding_accepted": "ACCEPTED",
    "fix_recorded": "FIXED_PENDING_RECHECK",
    "finding_verified": "VERIFIED",
    "finding_reopened": "OPEN",
    "finding_rejected": "REJECTED_WITH_RATIONALE",
    "finding_deferred": "DEFERRED_WITH_OWNER",
}

TRANSITIONS = {
    None: {"OPEN"},
    "OPEN": {
        "ACCEPTED",
        "REJECTED_WITH_RATIONALE",
        "DEFERRED_WITH_OWNER",
        "BLOCKING_UNRESOLVED",
    },
    "ACCEPTED": {"FIXED_PENDING_RECHECK", "BLOCKING_UNRESOLVED"},
    "FIXED_PENDING_RECHECK": {"VERIFIED", "OPEN", "BLOCKING_UNRESOLVED"},
    "VERIFIED": set(),
    "REJECTED_WITH_RATIONALE": {"OPEN"},
    "DEFERRED_WITH_OWNER": {"OPEN"},
    "BLOCKING_UNRESOLVED": {
        "ACCEPTED",
        "REJECTED_WITH_RATIONALE",
        "DEFERRED_WITH_OWNER",
    },
}

APPROVAL_TYPES = {
    "reviewer_override",
    "paid_model_fallback",
    "severe_rejection",
    "severe_deferral",
    "medium_rejection_without_reviewer_verification",
    "medium_deferral",
    "security_sensitive_release",
    "validation_downgrade",
    "loop_extension",
}

PLAN_DEFAULTS = {
    "model_identity_status": "proven",
    "reviewer_status": "available",
    "validation_status": "not_started",
    "pr_check_status": "not_applicable",
    "copilot_status": "not_applicable",
    "external_output_status": "clean",
    "external_output_paths": [],
    "loop_count": 1,
    "loop_limit": 3,
    "user_decision_blocker": False,
}

LOCAL_PATH_RE = re.compile(r"(?<![\w.-])(/Users|/home|/private|/tmp)/[^\s)>\]]+")
HOME_REL_RE = re.compile(r"(?<!\w)~/[^\s)>\]]+")
NOTION_RE = re.compile(r"https?://(?:www\.)?(?:notion\.so|notion\.site)/[^\s)>\]]+", re.I)
AUTH_RE = re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic)\s+\S+", re.I)
SECRET_RE = re.compile(
    r"\b(?:API_KEY|TOKEN|SECRET|PASSWORD|PASS|PRIVATE_KEY|ACCESS_KEY)"
    r"\s*=\s*[^\s]+",
    re.I,
)


class HelperError(Exception):
    """Base exception for user-facing helper failures."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            value = json.load(fh)
    except FileNotFoundError as exc:
        raise HelperError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HelperError(f"invalid json in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HelperError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path, required: bool = True) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            raise HelperError(f"missing required file: {path}")
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HelperError(f"invalid jsonl at {path}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise HelperError(f"{path}:{line_no} must contain a JSON object")
            value["_append_order"] = len(rows)
            rows.append(value)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def require_keys(value: dict[str, Any], keys: list[str], path: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise HelperError(f"{path} missing required fields: {', '.join(missing)}")


def normalize_family(model: Any) -> str | None:
    if not model:
        return None
    text = str(model).lower()
    if "gpt" in text or "openai" in text or "codex" in text:
        return "gpt"
    if "opus" in text or "claude" in text or "anthropic" in text:
        return "opus"
    return text.split("-", 1)[0].strip() or None


def validate_request(request: dict[str, Any], path: str = "review-request.json") -> None:
    require_keys(request, REQUEST_FIELDS, path)
    if request["mode"] not in {"pre_pr", "post_pr"}:
        raise HelperError(f"{path} mode must be pre_pr or post_pr")
    if request.get("run_id") != Path(str(request.get("artifact_dir", ""))).name:
        artifact_leaf = Path(str(request.get("artifact_dir", ""))).name
        if artifact_leaf and artifact_leaf != ".":
            raise HelperError(f"{path} run_id must match artifact_dir leaf")


def validate_approvals(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    required = ["id", "type", "approved_by", "scope", "reason", "evidence", "created_at"]
    for row in rows:
        require_keys(row, required, "approval-receipts.jsonl")
        if row["type"] not in APPROVAL_TYPES:
            raise HelperError(f"unknown approval type: {row['type']}")
        if row["id"] in by_id:
            raise HelperError(f"duplicate approval id: {row['id']}")
        by_id[row["id"]] = row
    return by_id


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    merged = dict(PLAN_DEFAULTS)
    merged.update(plan)
    if merged["model_identity_status"] not in {"proven", "unproven"}:
        raise HelperError("validation-plan model_identity_status is invalid")
    if merged["reviewer_status"] not in {"available", "unavailable", "runtime_failure"}:
        raise HelperError("validation-plan reviewer_status is invalid")
    if merged["validation_status"] not in {
        "not_started",
        "passed",
        "failed",
        "blocked",
        "downgraded_to_pr_checks",
    }:
        raise HelperError("validation-plan validation_status is invalid")
    if merged["pr_check_status"] not in {"not_applicable", "pending", "passed", "failed"}:
        raise HelperError("validation-plan pr_check_status is invalid")
    if merged["copilot_status"] not in {"not_applicable", "resolved", "unresolved"}:
        raise HelperError("validation-plan copilot_status is invalid")
    if merged["external_output_status"] not in {"clean", "blocked"}:
        raise HelperError("validation-plan external_output_status is invalid")
    if not isinstance(merged["external_output_paths"], list):
        raise HelperError("validation-plan external_output_paths must be a list")
    if int(merged["loop_limit"]) < 1:
        raise HelperError("validation-plan loop_limit must be >= 1")
    return merged


def validate_ledger_event(event: dict[str, Any]) -> None:
    require_keys(event, ["event_type", "created_at"], "review-ledger.jsonl")
    if event["event_type"] not in LEDGER_EVENT_TYPES:
        raise HelperError(f"unknown ledger event_type: {event['event_type']}")
    status = event.get("status")
    if status is not None and status not in FINDING_STATUSES:
        raise HelperError(f"unknown finding status: {status}")
    severity = event.get("severity")
    if severity is not None and severity not in SEVERITIES:
        raise HelperError(f"unknown severity: {severity}")
    expected = EVENT_STATUS.get(event["event_type"])
    if expected and status != expected:
        raise HelperError(
            f"{event['event_type']} must use status {expected}, got {status}"
        )
    if status is not None:
        require_keys(event, ["id", "severity", "summary", "evidence"], "review-ledger.jsonl")


def reduce_ledger(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for event in rows:
        validate_ledger_event(event)
    ordered = sorted(rows, key=lambda row: (str(row.get("created_at")), row["_append_order"]))
    states: dict[str, dict[str, Any]] = {}
    for event in ordered:
        status = event.get("status")
        if status is None:
            continue
        finding_id = str(event["id"])
        previous = states.get(finding_id, {}).get("status")
        allowed = TRANSITIONS[previous]
        if status not in allowed:
            raise HelperError(
                f"illegal transition for {finding_id}: {previous or 'none'} -> {status}"
            )
        current = dict(event)
        current.pop("_append_order", None)
        current["previous_status"] = previous
        states[finding_id] = current
    return states


def approval_matches(
    state: dict[str, Any],
    approvals: dict[str, dict[str, Any]],
    approval_type: str,
) -> bool:
    receipt_id = state.get("approval_receipt_id")
    if receipt_id and approvals.get(str(receipt_id), {}).get("type") == approval_type:
        return True
    finding_id = state.get("id")
    for approval in approvals.values():
        if approval.get("type") != approval_type:
            continue
        if approval.get("finding_id") == finding_id:
            return True
    return False


def scrub_text(text: str) -> list[str]:
    failures: list[str] = []
    checks = [
        ("local_path", LOCAL_PATH_RE),
        ("home_relative_path", HOME_REL_RE),
        ("private_notion_link", NOTION_RE),
        ("authorization_header", AUTH_RE),
        ("secret_fragment", SECRET_RE),
    ]
    for name, pattern in checks:
        if pattern.search(text):
            failures.append(name)
    return failures


def scrub_files(run_dir: Path, paths: list[Any]) -> list[str]:
    failures: list[str] = []
    for raw_path in paths:
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = run_dir / path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            failures.append(f"missing_external_output:{raw_path}")
            continue
        for failure in scrub_text(text):
            failures.append(f"{raw_path}:{failure}")
    return failures


def compute_review_counts(
    states: dict[str, dict[str, Any]],
    approvals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    active: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    severe_unapproved: list[dict[str, Any]] = []
    medium_invalid: list[dict[str, Any]] = []

    for state in states.values():
        status = state["status"]
        severity = state["severity"]
        if status in {"OPEN", "ACCEPTED", "FIXED_PENDING_RECHECK", "BLOCKING_UNRESOLVED"}:
            active.append(state)
        if status in {"ACCEPTED", "FIXED_PENDING_RECHECK"}:
            accepted.append(state)
        if severity in {"Critical", "High"} and status == "REJECTED_WITH_RATIONALE":
            if not approval_matches(state, approvals, "severe_rejection"):
                severe_unapproved.append(state)
        if severity in {"Critical", "High"} and status == "DEFERRED_WITH_OWNER":
            if not approval_matches(state, approvals, "severe_deferral"):
                severe_unapproved.append(state)
        if severity == "Medium" and status == "REJECTED_WITH_RATIONALE":
            reviewer_verified = bool(state.get("reviewer_verified_rejection"))
            owner_approved = approval_matches(
                state,
                approvals,
                "medium_rejection_without_reviewer_verification",
            )
            if not reviewer_verified and not owner_approved:
                medium_invalid.append(state)
        if severity == "Medium" and status == "DEFERRED_WITH_OWNER":
            if not approval_matches(state, approvals, "medium_deferral"):
                medium_invalid.append(state)

    return {
        "active": active,
        "accepted": accepted,
        "severe_unapproved": severe_unapproved,
        "medium_invalid": medium_invalid,
    }


def choose_decision(
    request: dict[str, Any],
    plan: dict[str, Any],
    review_counts: dict[str, Any],
    external_failures: list[str],
) -> str:
    builder_family = normalize_family(request.get("builder_model"))
    reviewer_family = normalize_family(request.get("selected_reviewer_model"))
    identity_bad = (
        plan["model_identity_status"] != "proven"
        or builder_family is None
        or reviewer_family is None
        or builder_family == reviewer_family
    )
    if identity_bad:
        return "blocked_identity_unproven"
    if plan["reviewer_status"] == "unavailable":
        return "blocked_reviewer_unavailable"
    if plan["reviewer_status"] == "runtime_failure":
        return "blocked_reviewer_runtime"
    if review_counts["severe_unapproved"]:
        return "blocked_severe_adjudication"
    if plan["external_output_status"] == "blocked" or external_failures:
        return "blocked_external_output"
    if review_counts["active"] or review_counts["medium_invalid"]:
        return "blocked_review_findings"
    if plan["copilot_status"] == "unresolved":
        return "blocked_copilot"
    if plan["validation_status"] in {"failed", "blocked"}:
        return "blocked_validation"
    if int(plan["loop_count"]) > int(plan["loop_limit"]):
        return "blocked_loop_limit"
    if bool(plan["user_decision_blocker"]):
        return "blocked_user_decision"
    if request["mode"] == "post_pr" and plan["pr_check_status"] == "pending":
        return "pending_checks"
    if request["mode"] == "post_pr" and plan["pr_check_status"] == "passed":
        return "ready_post_pr_checks"
    if request["mode"] == "pre_pr" and plan["validation_status"] == "passed":
        return "ready_pre_pr"
    return "blocked_validation"


def render_active_blockers(decision: str, counts: dict[str, Any], failures: list[str]) -> str:
    lines = [f"# Active Blockers", "", f"Decision: `{decision}`", ""]
    for state in counts["severe_unapproved"]:
        lines.append(f"- Severe adjudication missing: {state['id']} {state['summary']}")
    for state in counts["medium_invalid"]:
        lines.append(f"- Medium terminal proof missing: {state['id']} {state['summary']}")
    for state in counts["active"]:
        lines.append(f"- Review finding active: {state['id']} {state['status']} {state['summary']}")
    for failure in failures:
        lines.append(f"- External output scrub failure: {failure}")
    if len(lines) == 4:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def render_accepted_fixes(counts: dict[str, Any]) -> str:
    lines = ["# Accepted Fixes", ""]
    for state in counts["accepted"]:
        lines.append(f"- {state['id']}: {state['status']} {state['summary']}")
    if len(lines) == 2:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    request = read_json(run_dir / "review-request.json")
    validate_request(request)
    ledger = read_jsonl(run_dir / "review-ledger.jsonl", required=True)
    approvals = validate_approvals(read_jsonl(run_dir / "approval-receipts.jsonl", required=False))
    plan = validate_plan(read_json(run_dir / "validation-plan.json"))
    return request, ledger, approvals, plan


def decide(run_dir: Path, write_outputs: bool = True) -> dict[str, Any]:
    request, ledger, approvals, plan = load_run(run_dir)
    states = reduce_ledger(ledger)
    counts = compute_review_counts(states, approvals)
    external_failures = scrub_files(run_dir, plan["external_output_paths"])
    decision = choose_decision(request, plan, counts, external_failures)
    artifact_refs = ["review-request.json", "review-ledger.jsonl", "validation-plan.json"]
    if approvals:
        artifact_refs.append("approval-receipts.jsonl")
    result = {
        "decision": decision,
        "active_blocker_count": (
            len(counts["active"])
            + len(counts["severe_unapproved"])
            + len(counts["medium_invalid"])
            + len(external_failures)
        ),
        "accepted_fix_count": len(counts["accepted"]),
        "severe_unapproved_count": len(counts["severe_unapproved"]),
        "validation_status": plan["validation_status"],
        "pr_check_status": plan["pr_check_status"],
        "copilot_status": plan["copilot_status"],
        "artifact_refs": artifact_refs,
        "decided_at": utc_now(),
    }
    if write_outputs:
        write_json(run_dir / "readiness-decision.json", result)
        (run_dir / "active-blockers.md").write_text(
            render_active_blockers(decision, counts, external_failures),
            encoding="utf-8",
        )
        (run_dir / "accepted-fixes.md").write_text(
            render_accepted_fixes(counts),
            encoding="utf-8",
        )
    return result


def command_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    request, ledger, approvals, plan = load_run(run_dir)
    reduce_ledger(ledger)
    scrub_failures = scrub_files(run_dir, plan["external_output_paths"])
    if scrub_failures:
        raise HelperError("external output scrub failures: " + ", ".join(scrub_failures))
    print(
        json.dumps(
            {
                "ok": True,
                "mode": request["mode"],
                "ledger_events": len(ledger),
                "approval_receipts": len(approvals),
            },
            sort_keys=True,
        )
    )
    return 0


def command_reduce(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    _, ledger, approvals, _ = load_run(run_dir)
    states = reduce_ledger(ledger)
    counts = compute_review_counts(states, approvals)
    output = {
        "finding_count": len(states),
        "active_finding_count": len(counts["active"]),
        "accepted_fix_count": len(counts["accepted"]),
        "severe_unapproved_count": len(counts["severe_unapproved"]),
        "medium_invalid_count": len(counts["medium_invalid"]),
        "findings": states,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def command_decide(args: argparse.Namespace) -> int:
    result = decide(Path(args.run_dir), write_outputs=True)
    print(json.dumps(result, sort_keys=True))
    return 0


def command_scrub(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    text = input_path.read_text(encoding="utf-8")
    failures = scrub_text(text)
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, sort_keys=True))
        return 2
    output_path = Path(args.output)
    output_path.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path)}, sort_keys=True))
    return 0


def default_request(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    value = {
        "work_item_id": "fixture",
        "run_id": "20260620T000000Z-fixture",
        "repo_path": "/workspace/repo",
        "implementation_summary": "Fixture implementation.",
        "spec_source": "SPEC.md",
        "builder_model": "gpt-5.5",
        "selected_reviewer_model": "opus-4.8",
        "reviewer_selection_source": "fixture",
        "target_branch": "feature/fixture",
        "base_sha": "base",
        "head_sha": "head",
        "diff_hash": "diff",
        "pr_number": None,
        "artifact_dir": "artifacts/finishing-touches/20260620T000000Z-fixture",
        "mode": "pre_pr",
    }
    if overrides:
        value.update(overrides)
    return value


def default_plan(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(PLAN_DEFAULTS)
    value["validation_status"] = "passed"
    if overrides:
        value.update(overrides)
    return value


def write_fixture_run(tmp_dir: Path, case: dict[str, Any]) -> Path:
    run_dir = tmp_dir / case["name"]
    run_dir.mkdir()
    request = default_request(case.get("request"))
    request["run_id"] = case["name"]
    request["artifact_dir"] = f"artifacts/finishing-touches/{case['name']}"
    write_json(run_dir / "review-request.json", request)
    write_jsonl(run_dir / "review-ledger.jsonl", case.get("ledger_events", []))
    write_jsonl(run_dir / "approval-receipts.jsonl", case.get("approvals", []))
    plan = default_plan(case.get("plan"))
    external_paths: list[str] = []
    for idx, content in enumerate(case.get("external_outputs", []), start=1):
        rel_path = f"external-output-{idx}.txt"
        (run_dir / rel_path).write_text(content, encoding="utf-8")
        external_paths.append(rel_path)
    if external_paths:
        plan["external_output_paths"] = external_paths
    write_json(run_dir / "validation-plan.json", plan)
    return run_dir


def fixture_event(
    finding_id: str,
    event_type: str,
    status: str,
    severity: str = "High",
    minute: int = 0,
    **extra: Any,
) -> dict[str, Any]:
    event = {
        "id": finding_id,
        "round": 1,
        "event_type": event_type,
        "severity": severity,
        "status": status,
        "summary": f"{finding_id} {status}",
        "evidence": "fixture",
        "requested_fix": "fixture",
        "owner": "builder",
        "verification": "fixture",
        "approval_receipt_id": None,
        "created_at": f"2026-06-20T00:{minute:02d}:00Z",
        "closed_at": None,
    }
    event.update(extra)
    return event


def built_in_suite() -> dict[str, Any]:
    return {
        "decision_cases": [
            {
                "name": "identity_missing",
                "request": {"builder_model": None},
                "plan": {"model_identity_status": "unproven"},
                "expected_decision": "blocked_identity_unproven",
            },
            {
                "name": "reviewer_binary_missing",
                "plan": {"reviewer_status": "unavailable"},
                "expected_decision": "blocked_reviewer_unavailable",
            },
            {
                "name": "reviewer_runtime_failure",
                "plan": {"reviewer_status": "runtime_failure"},
                "expected_decision": "blocked_reviewer_runtime",
            },
            {
                "name": "critical_rejected_no_approval",
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "Critical", 0),
                    fixture_event(
                        "FT-001",
                        "finding_rejected",
                        "REJECTED_WITH_RATIONALE",
                        "Critical",
                        1,
                    ),
                ],
                "expected_decision": "blocked_severe_adjudication",
            },
            {
                "name": "high_deferred_no_approval",
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event(
                        "FT-001",
                        "finding_deferred",
                        "DEFERRED_WITH_OWNER",
                        "High",
                        1,
                    ),
                ],
                "expected_decision": "blocked_severe_adjudication",
            },
            {
                "name": "medium_rejected_without_proof",
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "Medium", 0),
                    fixture_event(
                        "FT-001",
                        "finding_rejected",
                        "REJECTED_WITH_RATIONALE",
                        "Medium",
                        1,
                    ),
                ],
                "expected_decision": "blocked_review_findings",
            },
            {
                "name": "accepted_unresolved",
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 1),
                ],
                "expected_decision": "blocked_review_findings",
            },
            {
                "name": "fix_pending_recheck",
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 1),
                    fixture_event(
                        "FT-001",
                        "fix_recorded",
                        "FIXED_PENDING_RECHECK",
                        "High",
                        2,
                    ),
                ],
                "expected_decision": "blocked_review_findings",
            },
            {
                "name": "external_users_path",
                "external_outputs": ["Review says see /Users/genome/private/file"],
                "expected_decision": "blocked_external_output",
            },
            {
                "name": "external_notion_link",
                "external_outputs": ["Private page https://www.notion.so/example"],
                "expected_decision": "blocked_external_output",
            },
            {
                "name": "copilot_unresolved",
                "plan": {"copilot_status": "unresolved"},
                "expected_decision": "blocked_copilot",
            },
            {
                "name": "local_validation_failed",
                "plan": {"validation_status": "failed"},
                "expected_decision": "blocked_validation",
            },
            {
                "name": "ci_pending_post_pr",
                "request": {"mode": "post_pr", "pr_number": 123},
                "plan": {
                    "validation_status": "downgraded_to_pr_checks",
                    "pr_check_status": "pending",
                },
                "expected_decision": "pending_checks",
            },
            {
                "name": "ci_green_post_pr",
                "request": {"mode": "post_pr", "pr_number": 123},
                "plan": {
                    "validation_status": "downgraded_to_pr_checks",
                    "pr_check_status": "passed",
                },
                "expected_decision": "ready_post_pr_checks",
            },
            {
                "name": "local_green_pre_pr",
                "plan": {"validation_status": "passed"},
                "expected_decision": "ready_pre_pr",
            },
            {
                "name": "loop_count_exceeded",
                "plan": {"loop_count": 4, "loop_limit": 3},
                "expected_decision": "blocked_loop_limit",
            },
        ],
        "transition_cases": [
            {
                "name": "valid_fix_verified",
                "expect_valid": True,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 1),
                    fixture_event(
                        "FT-001",
                        "fix_recorded",
                        "FIXED_PENDING_RECHECK",
                        "High",
                        2,
                    ),
                    fixture_event("FT-001", "finding_verified", "VERIFIED", "High", 3),
                ],
            },
            {
                "name": "valid_rejected",
                "expect_valid": True,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "Low", 0),
                    fixture_event(
                        "FT-001",
                        "finding_rejected",
                        "REJECTED_WITH_RATIONALE",
                        "Low",
                        1,
                    ),
                ],
            },
            {
                "name": "valid_deferred",
                "expect_valid": True,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "Low", 0),
                    fixture_event(
                        "FT-001",
                        "finding_deferred",
                        "DEFERRED_WITH_OWNER",
                        "Low",
                        1,
                    ),
                ],
            },
            {
                "name": "valid_blocking_to_accepted",
                "expect_valid": True,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event(
                        "FT-001",
                        "recheck_requested",
                        "BLOCKING_UNRESOLVED",
                        "High",
                        1,
                    ),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 2),
                ],
            },
            {
                "name": "invalid_verified_reopened",
                "expect_valid": False,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 1),
                    fixture_event(
                        "FT-001",
                        "fix_recorded",
                        "FIXED_PENDING_RECHECK",
                        "High",
                        2,
                    ),
                    fixture_event("FT-001", "finding_verified", "VERIFIED", "High", 3),
                    fixture_event("FT-001", "finding_reopened", "OPEN", "High", 4),
                ],
            },
            {
                "name": "invalid_deferred_to_verified",
                "expect_valid": False,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "Low", 0),
                    fixture_event(
                        "FT-001",
                        "finding_deferred",
                        "DEFERRED_WITH_OWNER",
                        "Low",
                        1,
                    ),
                    fixture_event("FT-001", "finding_verified", "VERIFIED", "Low", 2),
                ],
            },
            {
                "name": "invalid_accepted_to_verified",
                "expect_valid": False,
                "ledger_events": [
                    fixture_event("FT-001", "finding_opened", "OPEN", "High", 0),
                    fixture_event("FT-001", "finding_accepted", "ACCEPTED", "High", 1),
                    fixture_event("FT-001", "finding_verified", "VERIFIED", "High", 2),
                ],
            },
        ],
        "scrubber_cases": [
            {"name": "users_path", "input": "/Users/genome/agentic_os/file", "expect_clean": False},
            {"name": "home_path", "input": "/home/genome/file", "expect_clean": False},
            {"name": "home_relative", "input": "~/private/file", "expect_clean": False},
            {"name": "notion_link", "input": "https://www.notion.so/private", "expect_clean": False},
            {"name": "authorization", "input": "Authorization: Bearer example", "expect_clean": False},
            {"name": "env_secret", "input": "API_KEY=example", "expect_clean": False},
            {"name": "spec_path", "input": "SPEC.md", "expect_clean": True},
            {
                "name": "skill_path",
                "input": "harness/skills/example/SKILL.md",
                "expect_clean": True,
            },
            {"name": "pr_ref", "input": "PR #12345", "expect_clean": True},
            {"name": "jira_ref", "input": "FLYWL-1234", "expect_clean": True},
            {"name": "commit_ref", "input": "commit abc1234", "expect_clean": True},
        ],
    }


def load_suite(fixtures: Path) -> dict[str, Any]:
    suite_path = fixtures / "fixture-suite.json"
    if suite_path.exists():
        return read_json(suite_path)
    return built_in_suite()


def command_fixture_test(args: argparse.Namespace) -> int:
    fixtures = Path(args.fixtures)
    suite = load_suite(fixtures)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ft-review-helper-") as tmp:
        tmp_dir = Path(tmp)
        for case in suite.get("decision_cases", []):
            run_dir = write_fixture_run(tmp_dir, case)
            try:
                result = decide(run_dir, write_outputs=True)
                actual = result["decision"]
            except HelperError as exc:
                failures.append(f"decision {case['name']} errored: {exc}")
                continue
            expected = case["expected_decision"]
            if actual != expected:
                failures.append(f"decision {case['name']}: expected {expected}, got {actual}")
        for case in suite.get("transition_cases", []):
            try:
                reduce_ledger(
                    [
                        dict(event, _append_order=idx)
                        for idx, event in enumerate(case["ledger_events"])
                    ]
                )
                valid = True
            except HelperError:
                valid = False
            if valid != bool(case["expect_valid"]):
                failures.append(
                    f"transition {case['name']}: expected valid={case['expect_valid']}, got {valid}"
                )
        for case in suite.get("scrubber_cases", []):
            clean = not scrub_text(case["input"])
            if clean != bool(case["expect_clean"]):
                failures.append(
                    f"scrubber {case['name']}: expected clean={case['expect_clean']}, got {clean}"
                )
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "decision_cases": len(suite.get("decision_cases", [])),
                "transition_cases": len(suite.get("transition_cases", [])),
                "scrubber_cases": len(suite.get("scrubber_cases", [])),
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finishing-touches-review-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--run-dir", required=True)
    validate_parser.set_defaults(func=command_validate)

    reduce_parser = subparsers.add_parser("reduce")
    reduce_parser.add_argument("--run-dir", required=True)
    reduce_parser.set_defaults(func=command_reduce)

    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--run-dir", required=True)
    decide_parser.set_defaults(func=command_decide)

    scrub_parser = subparsers.add_parser("scrub-external-output")
    scrub_parser.add_argument("--input", required=True)
    scrub_parser.add_argument("--output", required=True)
    scrub_parser.set_defaults(func=command_scrub)

    fixture_parser = subparsers.add_parser("fixture-test")
    fixture_parser.add_argument("--fixtures", required=True)
    fixture_parser.set_defaults(func=command_fixture_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HelperError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
