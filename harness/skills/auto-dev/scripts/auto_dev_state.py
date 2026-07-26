#!/usr/bin/env python3
"""Operate Auto Dev v2 local state-machine artifacts.

The canonical run directory is the work item's nested artifact directory:
`artifacts/auto-dev/`. Its authoritative state file is `state.json`; the
append-only transition ledger is `step-ledger.jsonl`.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import project_context
import run_store

try:
    import yaml
except ImportError:  # pragma: no cover - Agentic OS declares pyyaml available.
    yaml = None


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
FINISHING_HELPER = (
    ROOT
    / "harness"
    / "skills"
    / "finishing-touches-review"
    / "scripts"
    / "finishing_touches_review_helper.py"
)
REVIEWER_TEMPLATE = ROOT / "harness" / "skills" / "auto-dev" / "templates" / "reviewer-prompt.md"
RUNSTORE_ENV_VAR = "AUTO_DEV_RUNSTORE"

NON_TERMINAL_STATES = {
    "discovered",
    "claimed",
    "context_loaded",
    "planned",
    "worktree_ready",
    "implementing",
    "local_validation",
    "finishing_review",
    "awaiting_human_review",
    "pr_open",
    "ci_watch",
    "copilot_watch",
    "ready_for_merge",
}
TERMINAL_STATES = {"merged", "blocked", "abandoned"}
ALL_STATES = NON_TERMINAL_STATES | TERMINAL_STATES

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"claimed", "blocked", "abandoned"},
    "claimed": {"context_loaded", "blocked", "abandoned"},
    "context_loaded": {"planned", "blocked", "abandoned"},
    "planned": {"worktree_ready", "blocked", "abandoned"},
    "worktree_ready": {"implementing", "pr_open", "blocked", "abandoned"},
    "implementing": {"local_validation", "blocked", "abandoned"},
    "local_validation": {"finishing_review", "blocked", "abandoned"},
    "finishing_review": {"awaiting_human_review", "pr_open", "ready_for_merge", "implementing", "blocked", "abandoned"},
    "awaiting_human_review": {"implementing", "pr_open", "ci_watch", "ready_for_merge", "blocked", "abandoned"},
    "pr_open": {"ci_watch", "copilot_watch", "finishing_review", "blocked", "abandoned"},
    "ci_watch": {"copilot_watch", "finishing_review", "ready_for_merge", "blocked", "abandoned"},
    "copilot_watch": {"finishing_review", "ready_for_merge", "blocked", "abandoned"},
    "ready_for_merge": {"merged", "blocked", "abandoned"},
    "merged": set(),
    "blocked": set(),
    "abandoned": set(),
}

TRACKER_KINDS = {"jira", "linear", "hybrid"}
REVIEW_MODES = {"pre_pr", "post_pr"}
READY_DECISIONS = {"pre_pr": "ready_pre_pr", "post_pr": "ready_post_pr_checks"}
REVIEWER_TRANSPORTS = {"claude_cli"}
REVIEW_UNAVAILABLE_POLICIES = {"continue_with_receipt", "block"}
REVIEW_FAILURE_CODES = {
    "cli_not_found",
    "cli_auth_failed",
    "cli_credit_or_api_route",
    "cli_timeout",
    "cli_runtime_failed",
    "cli_output_invalid",
    "unknown",
}
CLAUDE_CLI_STRIPPED_ENV = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
SKIP_RECEIPT_TYPES = {"validation_downgrade", "reviewer_override", "paid_model_fallback"}
LOCAL_PATH_RE = re.compile(r"(?:(?:/Users|/home|/private|/tmp)/[^\s)>\]]+|~/(?:[^\s)>\]]+))")
NOTION_RE = re.compile(r"https?://(?:www\.)?(?:notion\.so|notion\.site|app\.notion\.com)/[^\s)>\]]+", re.I)
LINEAR_RE = re.compile(r"https?://(?:www\.)?linear\.app/[^\s)>\]]+", re.I)
OS_INTERNAL_RE = re.compile(r"\b(?:Agentic OS|auto_dev_queue|harness/skills|work-items/0[1-4]-|artifacts/auto-dev)\b")
SECRET_RE = re.compile(
    r"\b(?:Authorization\s*:\s*(?:Bearer|Basic)\s+\S+|API_KEY|TOKEN|SECRET|PASSWORD|PASS|PRIVATE_KEY|ACCESS_KEY)\s*[:=]?\s*[^\s]+",
    re.I,
)
RECEIPT_CREDENTIAL_RE = re.compile(
    r"(?ix)"
    r"(?:[\"']?[a-z][a-z0-9_-]*(?:key|token|secret|password|passwd)[\"']?"
    r"|[\"']?(?:api_key|access_key|private_key|session_token|password|passwd)[\"']?)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
)
RECEIPT_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:sk-ant|sk-proj|sk)-[a-z0-9_-]{12,}"
    r"|gh[pousr]_[a-z0-9]{12,}"
    r"|github_pat_[a-z0-9_]{12,}"
    r"|xox[a-z]-[a-z0-9-]{12,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|eyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}"
    r")\b",
)
CLAUDE_REVIEW_ALLOWED_TOOLS = (
    "Read,Grep,Glob,"
    "Bash(git diff),Bash(git diff *),"
    "Bash(git show),Bash(git show *),"
    "Bash(git status),Bash(git status *),"
    "Bash(git log),Bash(git log *)"
)


class AutoDevStateError(Exception):
    """Raised for user-facing state-machine failures."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def ledger_path(run_dir: Path) -> Path:
    return run_dir / "step-ledger.jsonl"


def read_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise AutoDevStateError(f"missing required file: {path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AutoDevStateError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AutoDevStateError(f"{path} must contain a JSON object")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def read_jsonl(path: Path, required: bool = True) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            raise AutoDevStateError(f"missing required file: {path}")
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AutoDevStateError(f"{path}:{line_no} invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise AutoDevStateError(f"{path}:{line_no} must be a JSON object")
        rows.append(row)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def load_state(run_dir: Path) -> dict[str, Any]:
    return read_json(state_path(run_dir))


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(state_path(run_dir), state)


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def local_pid_alive(pid: Any, host: str | None) -> bool:
    if host and host != socket.gethostname():
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim_is_live(claim: dict[str, Any] | None) -> bool:
    if not claim:
        return False
    heartbeat = claim.get("heartbeat_at")
    ttl = int(claim.get("heartbeat_ttl_seconds") or 0)
    if not heartbeat or ttl <= 0:
        return False
    try:
        heartbeat_dt = dt.datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00"))
    except ValueError:
        return False
    age = dt.datetime.now(dt.timezone.utc) - heartbeat_dt
    return age.total_seconds() <= ttl and local_pid_alive(claim.get("pid"), claim.get("host"))


def require_state(value: str) -> None:
    if value not in ALL_STATES:
        raise AutoDevStateError(f"unknown state: {value}")


def transition_allowed(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


def ledger_event(
    state: dict[str, Any],
    from_state: str,
    to_state: str,
    actor: str,
    receipt: str,
    reason: str,
    idempotency_key: str | None,
    ref: str | None = None,
) -> dict[str, Any]:
    events = read_jsonl(ledger_path_from_state(state), required=False)
    return {
        "seq": len(events) + 1,
        "ts": utc_now(),
        "run_id": state["run_id"],
        "from": from_state,
        "to": to_state,
        "actor": actor,
        "reason": reason,
        "receipt": receipt,
        "idempotency_key": idempotency_key or f"{to_state}:{len(events) + 1}",
        **({"ref": ref} if ref else {}),
    }


def ledger_path_from_state(state: dict[str, Any]) -> Path:
    run_dir = Path(str(state.get("_run_dir", ".")))
    return ledger_path(run_dir)


def validate_state(state: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    required = ["schema_version", "run_id", "work_item_id", "project", "tracker", "current_state", "context", "quality_gates"]
    for key in required:
        if key not in state:
            failures.append(f"state.json missing {key}")
    current = state.get("current_state")
    if current not in ALL_STATES:
        failures.append(f"unknown current_state: {current}")
    tracker = state.get("tracker") if isinstance(state.get("tracker"), dict) else {}
    if tracker.get("kind") not in TRACKER_KINDS:
        failures.append("tracker.kind must be jira, linear, or hybrid")
    if not tracker.get("id"):
        failures.append("tracker.id is required")
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    if not context.get("merge_policy"):
        failures.append("context.merge_policy is required")
    if state.get("terminal") is True and current not in TERMINAL_STATES:
        failures.append("terminal true is only valid for merged, blocked, or abandoned")
    if current == "awaiting_human_review" and state.get("claim"):
        failures.append("awaiting_human_review must release the local claim")
    return failures


def validate_event(event: dict[str, Any], index: int) -> list[str]:
    failures: list[str] = []
    for key in ["seq", "ts", "run_id", "from", "to", "actor", "receipt", "idempotency_key"]:
        if event.get(key) in (None, ""):
            failures.append(f"event {index} missing {key}")
    from_state = event.get("from")
    to_state = event.get("to")
    if from_state not in ALL_STATES:
        failures.append(f"event {index} unknown from state: {from_state}")
    if to_state not in ALL_STATES:
        failures.append(f"event {index} unknown to state: {to_state}")
    if from_state in ALL_STATES and to_state in ALL_STATES and not transition_allowed(str(from_state), str(to_state)):
        failures.append(f"event {index} illegal transition: {from_state} -> {to_state}")
    if from_state in TERMINAL_STATES:
        failures.append(f"event {index} attempts to leave terminal state: {from_state}")
    return failures


def reduce_ledger(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    failures = validate_state(state)
    current = "discovered"
    seen_keys: set[str] = set()
    transitions: list[dict[str, Any]] = []
    for index, event in enumerate(events, 1):
        failures.extend(validate_event(event, index))
        key = str(event.get("idempotency_key"))
        if key in seen_keys:
            failures.append(f"event {index} duplicate idempotency_key: {key}")
        seen_keys.add(key)
        if event.get("from") != current:
            failures.append(f"event {index} starts from {event.get('from')} but reduced state is {current}")
        current = str(event.get("to"))
        transitions.append(
            {
                "seq": event.get("seq"),
                "from": event.get("from"),
                "to": event.get("to"),
                "receipt": event.get("receipt"),
                "idempotency_key": event.get("idempotency_key"),
            }
        )
    if not events:
        current = str(state.get("current_state", "discovered"))
    if events and state.get("current_state") != current:
        failures.append(f"state.json current_state {state.get('current_state')} does not match reduced state {current}")
    return {
        "schema_version": 1,
        "run_id": state.get("run_id"),
        "current_state": current,
        "terminal": current in TERMINAL_STATES,
        "state_hash": stable_hash({"state": without_runtime(state), "events": events}),
        "transitions": transitions,
        "failures": failures,
    }


def without_runtime(state: dict[str, Any]) -> dict[str, Any]:
    copy = dict(state)
    copy.pop("_run_dir", None)
    return copy


def status_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("status")
    if isinstance(value, str):
        return value
    return None


def read_approvals(run_dir: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(run_dir / "approval-receipts.jsonl", required=False)
    finishing_root = run_dir / "finishing-touches"
    if finishing_root.exists():
        for path in finishing_root.glob("*/approval-receipts.jsonl"):
            rows.extend(read_jsonl(path, required=False))
    return rows


def has_skip_receipt(run_dir: Path) -> bool:
    for row in read_approvals(run_dir):
        if row.get("type") in SKIP_RECEIPT_TYPES:
            return True
    return False


def finishing_decision_ok(run_dir: Path, state: dict[str, Any], mode: str) -> bool:
    expected = READY_DECISIONS[mode]
    ref = ((state.get("finishing") or {}).get(mode) or {}).get("ref")
    recorded = ((state.get("finishing") or {}).get(mode) or {}).get("decision")
    if recorded == expected:
        return True
    if ref:
        path = Path(str(ref))
        if not path.is_absolute():
            path = run_dir / path
        if path.exists() and read_json(path).get("decision") == expected:
            return True
    return False


def ready_failures(run_dir: Path, state: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    current = state.get("current_state")
    gates = state.get("quality_gates") if isinstance(state.get("quality_gates"), dict) else {}
    if current in {"ready_for_merge", "merged"}:
        if not finishing_decision_ok(run_dir, state, "post_pr") and not has_skip_receipt(run_dir):
            failures.append("post_pr readiness-decision.json == ready_post_pr_checks is required before ready_for_merge")
        for gate_name in ["ci_green", "copilot", "merge_policy"]:
            gate_status = status_value(gates.get(gate_name))
            if gate_status not in {"passed", "pass", "skipped_with_receipt", "not_applicable", "n/a"}:
                failures.append(f"{gate_name} gate must pass or have an explicit skip receipt before ready_for_merge")
    return failures


def decide(run_dir: Path, write_outputs: bool = True) -> dict[str, Any]:
    state = load_state(run_dir)
    state["_run_dir"] = str(run_dir)
    events = read_jsonl(ledger_path(run_dir), required=False)
    summary = reduce_ledger(state, events)
    failures = list(summary["failures"])
    failures.extend(ready_failures(run_dir, state))
    blocked = state.get("blocked")
    active_blockers = [blocked] if blocked else []
    decision = "blocked" if failures or active_blockers else summary["current_state"]
    result = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "run_id": summary["run_id"],
        "state": summary["current_state"],
        "decision": decision,
        "terminal": summary["terminal"],
        "state_hash": summary["state_hash"],
        "active_blockers": active_blockers,
        "failures": failures,
        "next_action": choose_next_action(str(summary["current_state"]), failures, active_blockers),
    }
    if write_outputs:
        atomic_write_json(run_dir / "state-decision.json", result)
    return result


def choose_next_action(state: str, failures: list[str], blockers: list[Any]) -> str:
    if state == "awaiting_human_review":
        return "Run run-review for Claude CLI, or save reviewer-response.md and run ingest-review."
    if blockers:
        return "Resolve active blockers, refresh external state, then rerun decide."
    if failures:
        return "Fix state, ledger, or gate failures, then rerun validate and decide."
    if state == "ready_for_merge":
        return "Await merge approval; never auto-merge unless project merge policy allows it."
    if state == "merged":
        return "Run post-merge closeout and release the local claim."
    if state in {"blocked", "abandoned"}:
        return "No automatic resume. Human decision required."
    return "Resume from the next legal state transition."


def scrub_text(text: str) -> list[str]:
    findings: list[str] = []
    checks = [
        ("local_path", LOCAL_PATH_RE),
        ("private_notion_link", NOTION_RE),
        ("linear_url", LINEAR_RE),
        ("os_internal_reference", OS_INTERNAL_RE),
        ("secret_fragment", SECRET_RE),
    ]
    for name, pattern in checks:
        if pattern.search(text):
            findings.append(name)
    return sorted(set(findings))


def runstore_enabled() -> bool:
    return os.environ.get(RUNSTORE_ENV_VAR, "off").lower() == "sqlite"


def state_refs(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    tracker = state.get("tracker") or {}
    return {
        "work_item_id": state["work_item_id"],
        "project": state["project"],
        "tracker_kind": tracker.get("kind"),
        "tracker_id": tracker.get("id"),
        "work_item_path": str(run_dir),
        "pr_url": (state.get("pr") or {}).get("url"),
        "blocker": ((state.get("blocked") or {}).get("reason")),
    }


def sync_runstore(state: dict[str, Any], run_dir: Path, event: dict[str, Any] | None = None) -> None:
    if not runstore_enabled():
        return
    store = run_store.create_run_store()
    store.upsert_state(state["run_id"], state["current_state"], bool(state["terminal"]), state["updated_at"], state_refs(state, run_dir))
    if event is not None:
        store.record_step(state["run_id"], event["seq"], event["from"], event["to"], event["idempotency_key"], event["ts"], event.get("receipt"))


def sanitize_receipt_summary(text: str) -> str:
    """Return a bounded, single-line failure summary safe for a local receipt."""

    value = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    value = LOCAL_PATH_RE.sub("[REDACTED_LOCAL_PATH]", value)
    value = NOTION_RE.sub("[REDACTED_NOTION_LINK]", value)
    value = re.sub(
        r"(?i)\bAuthorization\s*:\s*(?:Bearer|Basic)\s+\S+",
        "[REDACTED_CREDENTIAL]",
        value,
    )
    value = re.sub(
        r"(?i)(https?://[^:/\s]+:)[^@\s]+@",
        r"\1[REDACTED_CREDENTIAL]@",
        value,
    )
    value = re.sub(
        r"(?i)--(?:api[-_]?key|access[-_]?key|token|secret|password|passwd)"
        r"(?:\s+|=)(?:\"[^\"]*\"|'[^']*'|\S+)",
        "[REDACTED_CREDENTIAL]",
        value,
    )
    value = RECEIPT_CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", value)
    value = RECEIPT_SECRET_VALUE_RE.sub("[REDACTED_CREDENTIAL]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:500] or "Claude CLI review failed without a diagnostic summary."


def default_state(args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    run_id = args.run_id or f"auto-dev-{now.replace(':', '').replace('-', '').lower()}"
    tracker_url = args.tracker_url
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "work_item_id": args.work_item_id,
        "project": args.project,
        "tracker": {
            "kind": args.tracker_kind,
            "id": args.tracker_id,
            "url": tracker_url,
            "spec_source": args.spec_source,
            "workflow_source": args.workflow_source,
            "personal_todo": args.personal_todo,
            "snapshot_ref": args.snapshot_ref,
            "snapshot_at": now if args.snapshot_ref else None,
            "snapshot_hash": args.snapshot_hash,
        },
        "current_state": "discovered",
        "previous_state": None,
        "terminal": False,
        "context": {
            "repo_path": args.repo_path,
            "base_branch": args.base_branch,
            "branch": args.branch,
            "worktree": args.worktree,
            "test_cmd": args.test_cmd,
            "merge_policy": args.merge_policy,
            "finishing_required": True,
            "reviewer_mode": args.reviewer_mode,
            "resolved_at": now,
        },
        "claim": None,
        "step_ledger_ref": "step-ledger.jsonl",
        "checklist": [],
        "quality_gates": {
            "ac_coverage": {"status": "pending", "ref": "checklist"},
            "regression_tests": {"status": "pending"},
            "lint_type_precommit": {"status": "pending"},
            "architecture": {"status": "pending"},
            "security": {"status": "pending"},
            "durability_idempotency": {"status": "pending"},
            "ux_api_behavior": {"status": "n/a"},
            "finishing_review": {"status": "pending"},
            "copilot": {"status": "pending"},
            "ci_green": {"status": "pending"},
            "merge_policy": {"status": "pending"},
        },
        "artifacts": {},
        "pr": {
            "number": None,
            "url": None,
            "head_sha": args.head_sha,
            "ci": {"status": "pending", "ref": None},
            "copilot": {"status": "unresolved", "rounds": 0, "last_reset_at": None},
        },
        "finishing": {
            "pre_pr": {"decision": None, "ref": None},
            "post_pr": {"decision": None, "ref": None},
        },
        "merge": {"state": "not_ready", "policy": args.merge_policy, "approved_by": None, "merged_sha": None},
        "blocked": None,
        "updated_at": now,
    }
    return state


def command_init(args: argparse.Namespace) -> int:
    if state_path(args.run_dir).exists() and not args.force:
        raise AutoDevStateError(f"state.json already exists: {state_path(args.run_dir)}")
    state = default_state(args)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    save_state(args.run_dir, state)
    if not ledger_path(args.run_dir).exists():
        ledger_path(args.run_dir).write_text("", encoding="utf-8")
    sync_runstore(state, args.run_dir)
    print(json.dumps({"ok": True, "state": "discovered", "state_path": str(state_path(args.run_dir))}, indent=2))
    return 0


def command_transition(args: argparse.Namespace) -> int:
    require_state(args.to)
    state = load_state(args.run_dir)
    from_state = args.from_state or state["current_state"]
    require_state(from_state)
    if from_state != state["current_state"]:
        raise AutoDevStateError(f"state is {state['current_state']}, not requested --from {from_state}")
    if not transition_allowed(from_state, args.to):
        raise AutoDevStateError(f"illegal transition: {from_state} -> {args.to}")
    if args.idempotency_key:
        for event in read_jsonl(ledger_path(args.run_dir), required=False):
            if event.get("idempotency_key") == args.idempotency_key:
                print(json.dumps({"ok": True, "noop": True, "state": state["current_state"]}, indent=2))
                return 0
    event = {
        "seq": len(read_jsonl(ledger_path(args.run_dir), required=False)) + 1,
        "ts": utc_now(),
        "run_id": state["run_id"],
        "from": from_state,
        "to": args.to,
        "actor": args.actor,
        "reason": args.reason,
        "receipt": args.receipt,
        "idempotency_key": args.idempotency_key or f"{from_state}->{args.to}:{utc_now()}",
        **({"ref": args.ref} if args.ref else {}),
    }
    append_jsonl(ledger_path(args.run_dir), event)
    state["previous_state"] = from_state
    state["current_state"] = args.to
    state["terminal"] = args.to in TERMINAL_STATES
    if args.to == "awaiting_human_review":
        state["claim"] = None
    if args.to == "blocked":
        state["blocked"] = {"reason": args.reason, "receipt": args.receipt, "at": utc_now()}
    save_state(args.run_dir, state)
    sync_runstore(state, args.run_dir, event)
    print(json.dumps({"ok": True, "from": from_state, "to": args.to, "seq": event["seq"]}, indent=2))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    state["_run_dir"] = str(args.run_dir)
    events = read_jsonl(ledger_path(args.run_dir), required=False)
    summary = reduce_ledger(state, events)
    if summary["failures"]:
        print(json.dumps({"ok": False, "failures": summary["failures"]}, indent=2))
        return 1
    print(json.dumps({"ok": True, "state": summary["current_state"], "state_hash": summary["state_hash"]}, indent=2))
    return 0


def command_reduce(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    state["_run_dir"] = str(args.run_dir)
    summary = reduce_ledger(state, read_jsonl(ledger_path(args.run_dir), required=False))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["failures"] else 0


def command_decide(args: argparse.Namespace) -> int:
    result = decide(args.run_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["failures"] else 0


def command_render(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    decision = read_json(args.run_dir / "state-decision.json", required=False)
    if args.format == "json":
        print(json.dumps({"state": state, "decision": decision}, indent=2, sort_keys=True))
        return 0
    lines = [
        f"# Auto Dev State: {state['work_item_id']}",
        "",
        f"- Run: `{state['run_id']}`",
        f"- Project: `{state['project']}`",
        f"- Tracker: `{(state.get('tracker') or {}).get('kind')}:{(state.get('tracker') or {}).get('id')}`",
        f"- Current state: `{state['current_state']}`",
        f"- Decision: `{decision.get('decision', 'not computed')}`",
        f"- Next action: {decision.get('next_action', 'run decide')}",
    ]
    print("\n".join(lines))
    return 0


def command_claim(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    if claim_is_live(state.get("claim")):
        print(json.dumps({"ok": False, "reason": "duplicate_claim", "claim": state.get("claim")}, indent=2))
        return 2
    if runstore_enabled():
        refs = state_refs(state, args.run_dir)
        claim_refs = {
            key: refs[key]
            for key in ("project", "work_item_path", "tracker_kind", "tracker_id")
        }
        verdict = run_store.create_run_store().claim(
            state["work_item_id"], state["run_id"], args.owner_run_id, socket.gethostname(), os.getpid(),
            args.heartbeat_ttl_seconds, current_state=state["current_state"], **claim_refs,
        )
        if not verdict.granted:
            print(json.dumps({"ok": False, "reason": verdict.reason}, indent=2))
            return 2
    state["claim"] = {
        "owner_run_id": args.owner_run_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "heartbeat_at": utc_now(),
        "heartbeat_ttl_seconds": args.heartbeat_ttl_seconds,
        "distributed_token": args.distributed_token,
        "claimed_at": state.get("claim", {}).get("claimed_at") if state.get("claim") else utc_now(),
    }
    if state["current_state"] == "discovered":
        from_state = "discovered"
        to_state = "claimed"
        append_jsonl(
            ledger_path(args.run_dir),
            {
                "seq": len(read_jsonl(ledger_path(args.run_dir), required=False)) + 1,
                "ts": utc_now(),
                "run_id": state["run_id"],
                "from": from_state,
                "to": to_state,
                "actor": args.actor,
                "reason": "tracker claim confirmed by re-read",
                "receipt": args.receipt,
                "idempotency_key": args.idempotency_key or f"claim:{(state.get('tracker') or {}).get('id')}",
            },
        )
        state["previous_state"] = from_state
        state["current_state"] = to_state
    save_state(args.run_dir, state)
    sync_runstore(state, args.run_dir)
    print(json.dumps({"ok": True, "state": state["current_state"], "claim": state["claim"]}, indent=2))
    return 0


def command_release(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    released = state.get("claim")
    state["claim"] = None
    save_state(args.run_dir, state)
    if runstore_enabled():
        run_store.create_run_store().release(state["run_id"])
    print(json.dumps({"ok": True, "released": bool(released), "reason": args.reason}, indent=2))
    return 0


def command_recover(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    claim = state.get("claim")
    if claim_is_live(claim):
        print(json.dumps({"ok": False, "status": "active", "reason": "duplicate_claim", "claim": claim}, indent=2))
        return 2
    if claim:
        claim.update(
            {
                "owner_run_id": args.owner_run_id or claim.get("owner_run_id"),
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "heartbeat_at": utc_now(),
                "heartbeat_ttl_seconds": args.heartbeat_ttl_seconds,
                "recovered_at": utc_now(),
            }
        )
        state["claim"] = claim
        save_state(args.run_dir, state)
        status = "stale_reclaimed"
    else:
        status = "no_claim"
    decision = decide(args.run_dir)
    print(json.dumps({"ok": True, "status": status, "state": state["current_state"], "decision": decision["decision"]}, indent=2))
    return 0


def template_values(state: dict[str, Any], review_dir: Path, mode: str, args: argparse.Namespace) -> dict[str, str]:
    tracker = state.get("tracker") or {}
    context = state.get("context") or {}
    pr = state.get("pr") or {}
    return {
        "WORK_ITEM_ID": str(state.get("work_item_id", "")),
        "PROJECT": str(state.get("project", "")),
        "TRACKER_ID": str(tracker.get("id", "")),
        "TRACKER_URL": str(tracker.get("url") or "none"),
        "BUILDER_FAMILY": args.builder_family,
        "REVIEWER_FAMILY": args.reviewer_family,
        "MODE": mode,
        "PR_URL": str(args.pr_url or pr.get("url") or "none yet"),
        "BASE_SHA": str(args.base_sha or context.get("base_sha") or "unknown"),
        "HEAD_SHA": str(args.head_sha or pr.get("head_sha") or "unknown"),
        "SPEC": args.spec or "See tracker snapshot and local SPEC/PLAN artifacts.",
        "ACCEPTANCE_CRITERIA": args.acceptance_criteria or "Acceptance criteria must be present in the tracker description or configured source.",
        "VALIDATION_SUMMARY": args.validation_summary or "local validation passed",
        "CI_STATUS": args.ci_status or status_value((state.get("quality_gates") or {}).get("ci_green")) or "not_applicable",
        "COPILOT_STATUS": args.copilot_status or status_value((state.get("quality_gates") or {}).get("copilot")) or "not_applicable",
        "DIFF_OR_FILE_LIST": args.diff_or_file_list or "See PR diff or generated patch artifacts.",
        "TOKENS": args.tokens or "No secrets, local paths, Notion links, or OS-internal references may appear in external writeback.",
    }


def render_reviewer_prompt(state: dict[str, Any], review_dir: Path, mode: str, args: argparse.Namespace) -> str:
    template = REVIEWER_TEMPLATE.read_text(encoding="utf-8")
    values = template_values(state, review_dir, mode, args)
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def canonical_review_repo(state: dict[str, Any]) -> Path | None:
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    raw_path = context.get("worktree") or context.get("repo_path")
    if not raw_path:
        return None
    return Path(str(raw_path)).expanduser().resolve()


def known_git_head(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.lower() == "unknown" or normalized == "HEAD":
        return None
    return normalized


def read_git_head(repo_path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return known_git_head(completed.stdout)


def command_prepare_review(args: argparse.Namespace) -> int:
    if args.mode not in REVIEW_MODES:
        raise AutoDevStateError("--mode must be pre_pr or post_pr")
    state = load_state(args.run_dir)
    if state["current_state"] != "finishing_review":
        raise AutoDevStateError("prepare-review requires current_state == finishing_review")
    review_run_id = args.review_run_id or f"{state['run_id']}-{args.mode}"
    review_dir = args.review_run_dir or args.run_dir / "finishing-touches" / review_run_id
    review_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = str(review_dir)
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    reviewed_repo = canonical_review_repo(state)
    requested_head = known_git_head(args.head_sha) or known_git_head((state.get("pr") or {}).get("head_sha"))
    expected_head = requested_head or (read_git_head(reviewed_repo) if reviewed_repo and reviewed_repo.is_dir() else None)
    args.head_sha = expected_head or args.head_sha
    request = {
        "work_item_id": state["work_item_id"],
        "run_id": review_dir.name,
        "repo_path": str(reviewed_repo or ""),
        "reviewed_repo_path": str(reviewed_repo or ""),
        "expected_head_sha": expected_head or "unknown",
        "implementation_summary": args.implementation_summary,
        "spec_source": (state.get("tracker") or {}).get("spec_source") or "tracker",
        "builder_model": args.builder_model,
        "selected_reviewer_model": args.reviewer_model,
        "reviewer_selection_source": "opposing-family-cli",
        "reviewer_transport": args.reviewer_transport,
        "reviewer_auth": "cli_native",
        "reviewer_environment_removed": CLAUDE_CLI_STRIPPED_ENV,
        "target_branch": context.get("branch") or "",
        "base_sha": args.base_sha or "unknown",
        "head_sha": expected_head or "unknown",
        "diff_hash": args.diff_hash or "unknown",
        "pr_number": str((state.get("pr") or {}).get("number") or ""),
        "artifact_dir": artifact_dir,
        "mode": args.mode,
    }
    plan = {
        "model_identity_status": "proven",
        "reviewer_status": "available",
        "reviewer_transport": args.reviewer_transport,
        "review_unavailable_policy": args.review_unavailable_policy,
        "validation_status": args.validation_status,
        "pr_check_status": args.pr_check_status,
        "copilot_status": args.copilot_status,
        "external_output_status": "clean",
        "external_output_paths": [],
        "loop_count": 1,
        "loop_limit": args.loop_limit,
        "user_decision_blocker": False,
    }
    atomic_write_json(review_dir / "review-request.json", request)
    atomic_write_json(review_dir / "validation-plan.json", plan)
    if not (review_dir / "review-ledger.jsonl").exists():
        (review_dir / "review-ledger.jsonl").write_text("", encoding="utf-8")
    prompt = render_reviewer_prompt(state, review_dir, args.mode, args)
    (review_dir / "reviewer-prompt.md").write_text(prompt, encoding="utf-8")
    rel_decision = str((review_dir / "readiness-decision.json").relative_to(args.run_dir))
    state.setdefault("finishing", {}).setdefault(args.mode, {})["ref"] = rel_decision
    save_state(args.run_dir, state)
    transition_args = argparse.Namespace(
        run_dir=args.run_dir,
        to="awaiting_human_review",
        from_state=None,
        actor=args.actor,
        reason=f"{args.mode} review prepared for Claude CLI",
        receipt=str((review_dir / "reviewer-prompt.md").relative_to(args.run_dir)),
        idempotency_key=args.idempotency_key or f"review-prompt:{review_dir.name}",
        ref=str((review_dir / "reviewer-prompt.md").relative_to(args.run_dir)),
    )
    command_transition(transition_args)
    print(json.dumps({"ok": True, "review_dir": str(review_dir), "prompt": str(review_dir / "reviewer-prompt.md")}, indent=2))
    return 0


def write_unavailable_model_receipt(
    review_dir: Path,
    *,
    failure_code: str,
    failure_summary: str,
    policy: str,
) -> None:
    receipt = [
        "# Model Receipt",
        "",
        f"- Review run: `{review_dir.name}`",
        "- Reviewer status: `unavailable`",
        "- Transport: `claude_cli`",
        "- Authentication: `cli_native`",
        "- Removed environment: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`",
        f"- Failure code: `{failure_code}`",
        f"- Unavailable policy: `{policy}`",
        f"- Recorded at: `{utc_now()}`",
        "",
        "## Sanitized failure summary",
        "",
        failure_summary,
        "",
        "No reviewer findings were produced or accepted by this unavailable review attempt.",
    ]
    (review_dir / "model-receipt.md").write_text("\n".join(receipt) + "\n", encoding="utf-8")


def command_record_review_unavailable(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    if state["current_state"] not in {"finishing_review", "awaiting_human_review"}:
        raise AutoDevStateError(
            "record-review-unavailable requires current_state == finishing_review or awaiting_human_review"
        )
    review_dir = args.review_run_dir.resolve()
    try:
        review_dir.relative_to(args.run_dir.resolve())
    except ValueError as exc:
        raise AutoDevStateError("--review-run-dir must be inside --run-dir") from exc
    request = read_json(review_dir / "review-request.json")
    mode = request.get("mode")
    if mode not in REVIEW_MODES:
        raise AutoDevStateError("review-request.json mode must be pre_pr or post_pr")
    if request.get("reviewer_transport") != "claude_cli":
        raise AutoDevStateError("review unavailability may only be recorded for reviewer_transport claude_cli")
    ledger_rows = read_jsonl(review_dir / "review-ledger.jsonl", required=False)
    if any(row.get("event_type") == "finding_opened" for row in ledger_rows):
        raise AutoDevStateError("cannot record reviewer unavailability after review findings were opened")

    plan_path = review_dir / "validation-plan.json"
    plan = read_json(plan_path)
    plan["reviewer_status"] = "unavailable"
    plan["reviewer_transport"] = "claude_cli"
    plan["review_unavailable_policy"] = args.review_unavailable_policy
    plan["review_failure_code"] = args.failure_code
    atomic_write_json(plan_path, plan)
    summary = sanitize_receipt_summary(args.failure_summary)
    write_unavailable_model_receipt(
        review_dir,
        failure_code=args.failure_code,
        failure_summary=summary,
        policy=args.review_unavailable_policy,
    )

    decision = run_finishing_decide(review_dir)
    rel_decision = str((review_dir / "readiness-decision.json").relative_to(args.run_dir.resolve()))
    state.setdefault("finishing", {}).setdefault(mode, {})
    state["finishing"][mode]["decision"] = decision["decision"]
    state["finishing"][mode]["ref"] = rel_decision
    save_state(args.run_dir, state)
    next_state = {
        "ready_pre_pr": "pr_open",
        "ready_post_pr_checks": "ready_for_merge",
        "pending_checks": "ci_watch",
    }.get(decision["decision"])
    if next_state and state["current_state"] in {"finishing_review", "awaiting_human_review"}:
        command_transition(
            argparse.Namespace(
                run_dir=args.run_dir,
                to=next_state,
                from_state=None,
                actor=args.actor,
                reason=f"Claude CLI unavailable; finishing {mode} decision {decision['decision']}",
                receipt=rel_decision,
                idempotency_key=args.idempotency_key or f"review-unavailable:{review_dir.name}",
                ref=rel_decision,
            )
        )
    print(
        json.dumps(
            {
                "ok": True,
                "mode": mode,
                "reviewer_transport": "claude_cli",
                "review_unavailable_policy": args.review_unavailable_policy,
                "decision": decision["decision"],
                "next_state": next_state,
                "receipt": str(review_dir / "model-receipt.md"),
            },
            indent=2,
        )
    )
    return 0


def classify_claude_cli_failure(returncode: int, stderr: str) -> tuple[str, str]:
    diagnostic = sanitize_receipt_summary(stderr)
    lowered = diagnostic.lower()
    if "credit balance" in lowered or "api credit" in lowered or "api key" in lowered:
        code = "cli_credit_or_api_route"
    elif "unauthorized" in lowered or "authentication" in lowered or "login" in lowered or "401" in lowered:
        code = "cli_auth_failed"
    else:
        code = "cli_runtime_failed"
    return code, f"Claude CLI exited {returncode}: {diagnostic}"


def record_claude_cli_failure(
    args: argparse.Namespace,
    *,
    failure_code: str,
    failure_summary: str,
) -> int:
    return command_record_review_unavailable(
        argparse.Namespace(
            run_dir=args.run_dir,
            review_run_dir=args.review_run_dir,
            failure_code=failure_code,
            failure_summary=failure_summary,
            review_unavailable_policy=args.review_unavailable_policy,
            actor=args.actor,
            idempotency_key=args.idempotency_key,
        )
    )


def record_malformed_review_output(
    args: argparse.Namespace,
    review_dir: Path,
    request: dict[str, Any],
    error: AutoDevStateError,
) -> int:
    error_path = review_dir / "review-output-error.json"
    rel_error = str(error_path.relative_to(args.run_dir.resolve()))
    payload = {
        "schema_version": 1,
        "recorded_at": utc_now(),
        "decision": "malformed_reviewer_output",
        "mode": request.get("mode"),
        "reviewer_transport": "claude_cli",
        "response_ref": "reviewer-response.md",
        "error": sanitize_receipt_summary(str(error)),
        "next_action": "Inspect or replace reviewer-response.md, then rerun ingest-review.",
    }
    atomic_write_json(error_path, payload)
    plan_path = review_dir / "validation-plan.json"
    plan = read_json(plan_path)
    plan["review_output_status"] = "malformed"
    plan["review_output_error_ref"] = "review-output-error.json"
    atomic_write_json(plan_path, plan)
    state = load_state(args.run_dir)
    mode = request.get("mode")
    if mode in REVIEW_MODES:
        state.setdefault("finishing", {}).setdefault(mode, {})
        state["finishing"][mode]["decision"] = "malformed_reviewer_output"
        state["finishing"][mode]["output_error_ref"] = rel_error
        save_state(args.run_dir, state)
    if state.get("current_state") == "finishing_review":
        command_transition(
            argparse.Namespace(
                run_dir=args.run_dir,
                to="awaiting_human_review",
                from_state=None,
                actor=args.actor,
                reason="Claude CLI returned malformed reviewer output",
                receipt=rel_error,
                idempotency_key=args.idempotency_key or f"malformed-review:{review_dir.name}",
                ref=rel_error,
            )
        )
        state = load_state(args.run_dir)
    print(
        json.dumps(
            {
                "ok": False,
                "decision": "malformed_reviewer_output",
                "state": state.get("current_state"),
                "error_ref": rel_error,
                "next_action": payload["next_action"],
            },
            indent=2,
        )
    )
    return 2


def record_review_input_error(
    args: argparse.Namespace,
    review_dir: Path,
    request: dict[str, Any],
    *,
    error_code: str,
    summary: str,
    expected_head: str | None = None,
    observed_head: str | None = None,
) -> int:
    error_path = review_dir / "review-input-error.json"
    rel_error = str(error_path.relative_to(args.run_dir.resolve()))
    payload = {
        "schema_version": 1,
        "recorded_at": utc_now(),
        "decision": "review_input_error",
        "error_code": error_code,
        "mode": request.get("mode"),
        "reviewer_transport": "claude_cli",
        "summary": sanitize_receipt_summary(summary),
        "expected_head_sha": expected_head,
        "observed_head_sha": observed_head,
        "next_action": "Refresh the review request from canonical state, then rerun run-review.",
    }
    atomic_write_json(error_path, payload)
    plan_path = review_dir / "validation-plan.json"
    plan = read_json(plan_path)
    plan["review_input_status"] = "error"
    plan["review_input_error_ref"] = "review-input-error.json"
    atomic_write_json(plan_path, plan)
    state = load_state(args.run_dir)
    mode = request.get("mode")
    if mode in REVIEW_MODES:
        state.setdefault("finishing", {}).setdefault(mode, {})
        state["finishing"][mode]["decision"] = "review_input_error"
        state["finishing"][mode]["input_error_ref"] = rel_error
        save_state(args.run_dir, state)
    if state.get("current_state") == "finishing_review":
        command_transition(
            argparse.Namespace(
                run_dir=args.run_dir,
                to="awaiting_human_review",
                from_state=None,
                actor=args.actor,
                reason=f"Claude review input failed integrity check: {error_code}",
                receipt=rel_error,
                idempotency_key=args.idempotency_key or f"review-input-error:{review_dir.name}:{error_code}",
                ref=rel_error,
            )
        )
        state = load_state(args.run_dir)
    print(
        json.dumps(
            {
                "ok": False,
                "decision": "review_input_error",
                "error_code": error_code,
                "state": state.get("current_state"),
                "error_ref": rel_error,
                "next_action": payload["next_action"],
            },
            indent=2,
        )
    )
    return 2


def command_run_review(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    if state["current_state"] not in {"finishing_review", "awaiting_human_review"}:
        raise AutoDevStateError("run-review requires current_state == finishing_review or awaiting_human_review")
    review_dir = args.review_run_dir.resolve()
    try:
        review_dir.relative_to(args.run_dir.resolve())
    except ValueError as exc:
        raise AutoDevStateError("--review-run-dir must be inside --run-dir") from exc
    request = read_json(review_dir / "review-request.json")
    if request.get("reviewer_transport") != "claude_cli":
        raise AutoDevStateError("run-review requires reviewer_transport claude_cli")
    prompt_path = review_dir / "reviewer-prompt.md"
    if not prompt_path.exists():
        raise AutoDevStateError(f"missing required file: {prompt_path}")

    canonical_repo = canonical_review_repo(state)
    requested_repo_raw = request.get("reviewed_repo_path") or request.get("repo_path")
    requested_repo = Path(str(requested_repo_raw)).expanduser().resolve() if requested_repo_raw else None
    if canonical_repo is None or requested_repo is None or requested_repo != canonical_repo:
        return record_review_input_error(
            args,
            review_dir,
            request,
            error_code="canonical_repo_mismatch",
            summary="Claude CLI review repository does not match the canonical Auto Dev worktree.",
        )
    repo_path = canonical_repo
    if not repo_path.is_dir():
        return record_review_input_error(
            args,
            review_dir,
            request,
            error_code="canonical_repo_unavailable",
            summary="The canonical Auto Dev worktree is unavailable.",
        )
    actual_head = read_git_head(repo_path)
    if actual_head is None:
        return record_review_input_error(
            args,
            review_dir,
            request,
            error_code="git_head_unverifiable",
            summary="Claude CLI review repository HEAD could not be verified.",
        )
    expected_head = known_git_head(request.get("expected_head_sha")) or known_git_head(request.get("head_sha"))
    if expected_head and actual_head != expected_head:
        return record_review_input_error(
            args,
            review_dir,
            request,
            error_code="git_head_mismatch",
            summary="Claude CLI review HEAD does not match the prepared review request.",
            expected_head=expected_head,
            observed_head=actual_head,
        )

    claude_binary = shutil.which("claude")
    if not claude_binary:
        return record_claude_cli_failure(
            args,
            failure_code="cli_not_found",
            failure_summary="Claude CLI executable was not found on PATH.",
        )
    child_env = os.environ.copy()
    for name in CLAUDE_CLI_STRIPPED_ENV:
        child_env.pop(name, None)
    command = [
        claude_binary,
        "-p",
        "--model",
        args.reviewer_model,
        "--safe-mode",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Grep,Glob,Bash",
        "--allowedTools",
        CLAUDE_REVIEW_ALLOWED_TOOLS,
        "--no-session-persistence",
    ]
    try:
        completed = subprocess.run(
            command,
            input=prompt_path.read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            check=False,
            timeout=args.timeout_seconds,
            env=child_env,
            cwd=str(repo_path),
        )
    except subprocess.TimeoutExpired:
        return record_claude_cli_failure(
            args,
            failure_code="cli_timeout",
            failure_summary=f"Claude CLI timed out after {args.timeout_seconds} seconds.",
        )
    except OSError as exc:
        return record_claude_cli_failure(
            args,
            failure_code="cli_runtime_failed",
            failure_summary=f"Claude CLI could not start: {exc}",
        )

    if completed.returncode != 0:
        failure_code, summary = classify_claude_cli_failure(completed.returncode, completed.stderr)
        return record_claude_cli_failure(args, failure_code=failure_code, failure_summary=summary)
    if not completed.stdout.strip():
        return record_claude_cli_failure(
            args,
            failure_code="cli_output_invalid",
            failure_summary="Claude CLI returned an empty reviewer response.",
        )

    response_path = review_dir / "reviewer-response.md"
    response_path.write_text(completed.stdout, encoding="utf-8")
    try:
        parse_reviewer_response(completed.stdout)
    except AutoDevStateError as exc:
        return record_malformed_review_output(args, review_dir, request, exc)
    return command_ingest_review(
        argparse.Namespace(
            run_dir=args.run_dir,
            review_run_dir=review_dir,
            response=response_path,
            reviewer_model=args.reviewer_model,
            reviewer_transport="claude_cli",
            attested_by=args.attested_by,
            actor=args.actor,
            idempotency_key=args.idempotency_key,
        )
    )


def parse_reviewer_response(text: str) -> tuple[list[dict[str, Any]], str]:
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.S | re.I)
    if not json_match:
        raise AutoDevStateError("reviewer-response.md missing fenced json findings array")
    try:
        findings = json.loads(json_match.group(1))
    except json.JSONDecodeError as exc:
        raise AutoDevStateError(f"reviewer findings JSON invalid: {exc}") from exc
    if not isinstance(findings, list):
        raise AutoDevStateError("reviewer findings JSON must be an array")
    verdicts = re.findall(r"^VERDICT:\s*(ready|changes_required)\s*$", text, re.M | re.I)
    if len(verdicts) != 1:
        raise AutoDevStateError("reviewer-response.md must contain exactly one VERDICT line")
    required = {"id", "severity", "category", "file", "line", "title", "detail", "suggested_fix", "blocking"}
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            raise AutoDevStateError(f"finding {index} must be an object")
        missing = sorted(required - set(finding))
        if missing:
            raise AutoDevStateError(f"finding {index} missing keys: {', '.join(missing)}")
        severity = str(finding["severity"]).lower()
        if severity not in {"critical", "high", "medium", "low"}:
            raise AutoDevStateError(f"finding {index} invalid severity: {finding['severity']}")
        if not isinstance(finding["blocking"], bool):
            raise AutoDevStateError(f"finding {index} blocking must be boolean")
    if verdicts[0].lower() == "ready" and any(bool(f.get("blocking")) for f in findings):
        raise AutoDevStateError("VERDICT ready is invalid when blocking findings are present")
    if verdicts[0].lower() == "changes_required" and not findings:
        raise AutoDevStateError("VERDICT changes_required is invalid when the findings array is empty")
    return findings, verdicts[0].lower()


def append_review_findings(review_dir: Path, findings: list[dict[str, Any]]) -> None:
    ledger = review_dir / "review-ledger.jsonl"
    for finding in findings:
        severity = str(finding["severity"]).lower().capitalize()
        if severity == "Critical":
            severity = "Critical"
        append_jsonl(
            ledger,
            {
                "event_type": "finding_opened",
                "created_at": utc_now(),
                "id": finding["id"],
                "severity": severity,
                "summary": finding["title"],
                "evidence": f"{finding['file']}:{finding['line']} {finding['detail']}",
                "status": "OPEN",
                "category": finding["category"],
                "suggested_fix": finding["suggested_fix"],
                "blocking": finding["blocking"],
            },
        )


def normalize_reviewer_model(model: str) -> str:
    value = model.lower()
    if "claude" in value or "opus" in value or "anthropic" in value:
        return "opus"
    return "gpt"


def write_model_receipt(review_dir: Path, args: argparse.Namespace, verdict: str, findings: list[dict[str, Any]]) -> None:
    reviewer_family = "opus" if normalize_reviewer_model(args.reviewer_model) == "opus" else "gpt"
    receipt = [
        "# Model Receipt",
        "",
        f"- Review run: `{review_dir.name}`",
        f"- Reviewer model: `{args.reviewer_model}`",
        f"- Reviewer family: `{reviewer_family}`",
        f"- Attested by: `{args.attested_by}`",
        f"- Attested at: `{utc_now()}`",
        f"- Transport: `{args.reviewer_transport}`",
        "- Authentication: `cli_native`",
        "- Removed environment: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`",
        f"- Verdict: `{verdict}`",
        f"- Finding count: `{len(findings)}`",
        "",
        "This receipt attests that the saved `reviewer-response.md` came from the selected opposing-family CLI reviewer.",
    ]
    (review_dir / "model-receipt.md").write_text("\n".join(receipt) + "\n", encoding="utf-8")


def run_finishing_decide(review_dir: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(FINISHING_HELPER), "decide", "--run-dir", str(review_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AutoDevStateError(completed.stderr.strip() or completed.stdout.strip() or "finishing decide failed")
    return read_json(review_dir / "readiness-decision.json")


def command_ingest_review(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir)
    review_dir = args.review_run_dir
    if review_dir is None:
        mode_ref = None
        for mode in REVIEW_MODES:
            ref = ((state.get("finishing") or {}).get(mode) or {}).get("ref")
            if ref:
                candidate = args.run_dir / Path(str(ref)).parent
                if candidate.exists() and (candidate / "reviewer-response.md").exists():
                    review_dir = candidate
                    mode_ref = mode
                    break
        if review_dir is None:
            raise AutoDevStateError("--review-run-dir required when no reviewer-response.md can be inferred")
    response_path = args.response or review_dir / "reviewer-response.md"
    findings, verdict = parse_reviewer_response(response_path.read_text(encoding="utf-8"))
    append_review_findings(review_dir, findings)
    write_model_receipt(review_dir, args, verdict, findings)
    decision = run_finishing_decide(review_dir)
    request = read_json(review_dir / "review-request.json")
    mode = request["mode"]
    rel_decision = str((review_dir / "readiness-decision.json").relative_to(args.run_dir))
    state.setdefault("finishing", {}).setdefault(mode, {})
    state["finishing"][mode]["decision"] = decision["decision"]
    state["finishing"][mode]["ref"] = rel_decision
    save_state(args.run_dir, state)
    next_state = {
        "ready_pre_pr": "pr_open",
        "ready_post_pr_checks": "ready_for_merge",
        "pending_checks": "ci_watch",
        "blocked_review_findings": "implementing",
    }.get(decision["decision"])
    if next_state and state["current_state"] == "awaiting_human_review":
        command_transition(
            argparse.Namespace(
                run_dir=args.run_dir,
                to=next_state,
                from_state=None,
                actor=args.actor,
                reason=f"finishing {mode} decision {decision['decision']}",
                receipt=rel_decision,
                idempotency_key=args.idempotency_key or f"ingest-review:{review_dir.name}",
                ref=rel_decision,
            )
        )
    print(json.dumps({"ok": True, "mode": mode, "decision": decision["decision"], "next_state": next_state}, indent=2))
    return 0


def command_scrub(args: argparse.Namespace) -> int:
    text = args.input.read_text(encoding="utf-8")
    findings = scrub_text(text)
    scrubbed = LOCAL_PATH_RE.sub("[REDACTED_LOCAL_PATH]", text)
    scrubbed = NOTION_RE.sub("[REDACTED_NOTION_LINK]", scrubbed)
    scrubbed = LINEAR_RE.sub("[REDACTED_LINEAR_LINK]", scrubbed)
    scrubbed = SECRET_RE.sub("[REDACTED_SECRET]", scrubbed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(scrubbed, encoding="utf-8")
    result = {"ok": not findings, "findings": findings, "output": str(args.output)}
    print(json.dumps(result, indent=2))
    return 2 if findings else 0


def command_context_load(args: argparse.Namespace) -> int:
    try:
        dev_factory = project_context.load_dev_factory(args.project_config)
    except project_context.ConfigMissingError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, indent=2))
        return 2
    tracker = dev_factory["tracker"]
    repo = dev_factory["repo"]
    branch = dev_factory["branch"]
    print(json.dumps({"ok": True, "summary": {"spec_source": tracker["spec_source"], "merge_policy": dev_factory["merge"]["policy"], "repo_path": repo["path"], "base_branch": branch["base"]}}, indent=2))
    return 0


def command_list_in_flight(args: argparse.Namespace) -> int:
    if not runstore_enabled():
        print(json.dumps({"ok": False, "reason": "runstore_disabled"}, indent=2))
        return 1
    rows = [row.__dict__ for row in run_store.create_run_store().list_in_flight(args.project)]
    print(json.dumps({"ok": True, "rows": rows}, indent=2))
    return 0


def load_cases(fixtures: Path) -> list[dict[str, Any]]:
    cases_file = fixtures / "cases.yml"
    if not cases_file.exists():
        raise AutoDevStateError(f"missing fixture file: {cases_file}")
    if yaml is None:
        raise AutoDevStateError("pyyaml is required to load fixture cases")
    payload = yaml.safe_load(cases_file.read_text(encoding="utf-8")) or {}
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise AutoDevStateError("fixtures/cases.yml must contain a cases list")
    return cases


def fixture_init_args(run_dir: Path, case: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        run_dir=run_dir,
        force=True,
        run_id=case.get("run_id", f"fixture-{case['name']}"),
        work_item_id=case.get("work_item_id", f"fixture/{case['name']}"),
        project=case.get("project", "fixture_project"),
        tracker_kind=case.get("tracker_kind", "jira"),
        tracker_id=case.get("tracker_id", "FIX-1"),
        tracker_url=case.get("tracker_url"),
        spec_source=case.get("spec_source", "fixture"),
        workflow_source=case.get("workflow_source", "fixture"),
        personal_todo=case.get("personal_todo", "none"),
        snapshot_ref=case.get("snapshot_ref", "tracker/source-snapshot.json"),
        snapshot_hash=case.get("snapshot_hash", "fixture-snapshot"),
        repo_path=case.get("repo_path", "/tmp/fixture-repo"),
        base_branch=case.get("base_branch", "main"),
        branch=case.get("branch", "feature/FIX-1-fixture"),
        worktree=case.get("worktree"),
        test_cmd=case.get("test_cmd", "make test"),
        merge_policy=case.get("merge_policy", "never_auto"),
        reviewer_mode=case.get("reviewer_mode", "human"),
        head_sha=case.get("head_sha", "HEAD"),
    )


def run_fixture_case(tmp_root: Path, case: dict[str, Any]) -> dict[str, Any]:
    run_dir = tmp_root / case["name"]
    def quiet(func: Any, namespace: argparse.Namespace) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return func(namespace)

    quiet(command_init, fixture_init_args(run_dir, case))
    for to_state in case.get("path", []):
        if to_state == "claimed":
            quiet(
                command_claim,
                argparse.Namespace(
                    run_dir=run_dir,
                    owner_run_id=f"claim-{case['name']}",
                    heartbeat_ttl_seconds=900,
                    distributed_token=f"fixture:{case['name']}",
                    actor="fixture",
                    receipt="fixture claim",
                    idempotency_key=f"claim:{case['name']}",
                ),
            )
            continue
        quiet(
            command_transition,
            argparse.Namespace(
                run_dir=run_dir,
                to=to_state,
                from_state=None,
                actor="fixture",
                reason=f"fixture to {to_state}",
                receipt=f"fixture:{to_state}",
                idempotency_key=f"{case['name']}:{to_state}",
                ref=None,
            ),
        )
    state = load_state(run_dir)
    for key, value in (case.get("quality_gates") or {}).items():
        state.setdefault("quality_gates", {})[key] = {"status": value}
    if case.get("post_pr_decision"):
        finishing_dir = run_dir / "finishing-touches" / f"{state['run_id']}-post_pr"
        finishing_dir.mkdir(parents=True, exist_ok=True)
        decision = {"decision": case["post_pr_decision"], "decided_at": utc_now()}
        atomic_write_json(finishing_dir / "readiness-decision.json", decision)
        state["finishing"]["post_pr"] = {
            "decision": case["post_pr_decision"],
            "ref": str((finishing_dir / "readiness-decision.json").relative_to(run_dir)),
        }
    save_state(run_dir, state)
    if case.get("scenario") == "human_review":
        if load_state(run_dir)["current_state"] != "finishing_review":
            quiet(
                command_transition,
                argparse.Namespace(
                    run_dir=run_dir,
                    to="finishing_review",
                    from_state=None,
                    actor="fixture",
                    reason="fixture human review gate",
                    receipt="fixture",
                    idempotency_key=f"{case['name']}:finishing_review_auto",
                    ref=None,
                ),
            )
        quiet(
            command_prepare_review,
            argparse.Namespace(
                run_dir=run_dir,
                mode=case.get("mode", "pre_pr"),
                review_run_id=None,
                review_run_dir=None,
                builder_model="gpt-5.6-codex",
                reviewer_model="claude-opus",
                builder_family="gpt",
                reviewer_family="opus",
                reviewer_transport="claude_cli",
                review_unavailable_policy="continue_with_receipt",
                actor="fixture",
                implementation_summary="fixture",
                validation_status="passed",
                pr_check_status="not_applicable" if case.get("mode", "pre_pr") == "pre_pr" else "passed",
                copilot_status="not_applicable" if case.get("mode", "pre_pr") == "pre_pr" else "resolved",
                loop_limit=3,
                base_sha="base",
                head_sha="head",
                diff_hash="fixture",
                pr_url=None,
                spec="fixture spec",
                acceptance_criteria="fixture AC",
                validation_summary="fixture validation passed",
                ci_status="not_applicable",
                diff_or_file_list="fixture files",
                tokens="none",
                idempotency_key=f"{case['name']}:prepare_review",
            ),
        )
        state = load_state(run_dir)
        review_ref = state["finishing"][case.get("mode", "pre_pr")]["ref"]
        review_dir = run_dir / Path(review_ref).parent
        (review_dir / "reviewer-response.md").write_text(case["reviewer_response"], encoding="utf-8")
        quiet(
            command_ingest_review,
            argparse.Namespace(
                run_dir=run_dir,
                review_run_dir=review_dir,
                response=None,
                reviewer_model="claude-opus",
                reviewer_transport="claude_cli",
                attested_by="Michael Clark",
                actor="fixture",
                idempotency_key=f"{case['name']}:ingest_review",
            ),
        )
    result = decide(run_dir, write_outputs=True)
    ok = True
    failures: list[str] = []
    expected_decision = case.get("expect_decision")
    expected_state = case.get("expect_state", case.get("state"))
    actual_state = load_state(run_dir)["current_state"]
    if expected_decision and result["decision"] != expected_decision:
        ok = False
        failures.append(f"expected decision {expected_decision}, got {result['decision']}")
    if expected_state and actual_state != expected_state:
        ok = False
        failures.append(f"expected state {expected_state}, got {actual_state}")
    if case.get("expect_failures") is not None and bool(case["expect_failures"]) != bool(result["failures"]):
        ok = False
        failures.append(f"expected failures={case['expect_failures']}, got {bool(result['failures'])}")
    if case.get("forbid_decision") and result["decision"] == case["forbid_decision"]:
        ok = False
        failures.append(f"forbidden decision returned: {result['decision']}")
    return {"name": case["name"], "ok": ok, "failures": failures, "decision": result["decision"], "state": actual_state}


def command_fixture_test(args: argparse.Namespace) -> int:
    cases = load_cases(args.fixtures)
    tmp_root = Path(tempfile.mkdtemp(prefix="auto-dev-state-fixtures-"))
    try:
        results = [run_fixture_case(tmp_root, case) for case in cases]
    finally:
        if not args.keep_tmp:
            shutil.rmtree(tmp_root, ignore_errors=True)
    failed = [result for result in results if not result["ok"]]
    print(json.dumps({"ok": not failed, "cases": results}, indent=2, sort_keys=True))
    return 1 if failed else 0


def add_common_init_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--work-item-id", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--tracker-kind", choices=sorted(TRACKER_KINDS), required=True)
    parser.add_argument("--tracker-id", required=True)
    parser.add_argument("--tracker-url")
    parser.add_argument("--spec-source", default="tracker")
    parser.add_argument("--workflow-source", default="tracker")
    parser.add_argument("--personal-todo", default="none")
    parser.add_argument("--snapshot-ref")
    parser.add_argument("--snapshot-hash")
    parser.add_argument("--repo-path")
    parser.add_argument("--base-branch")
    parser.add_argument("--branch")
    parser.add_argument("--worktree")
    parser.add_argument("--test-cmd")
    parser.add_argument("--merge-policy", default="never_auto")
    parser.add_argument("--reviewer-mode", choices=["human", "auto"], default="human")
    parser.add_argument("--head-sha")
    parser.add_argument("--force", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate Auto Dev v2 local state-machine artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    add_common_init_args(init_parser)
    init_parser.set_defaults(func=command_init)

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("--run-dir", type=Path, required=True)
    transition_parser.add_argument("--to", required=True)
    transition_parser.add_argument("--from", dest="from_state")
    transition_parser.add_argument("--actor", default="codex")
    transition_parser.add_argument("--reason", default="manual transition")
    transition_parser.add_argument("--receipt", required=True)
    transition_parser.add_argument("--idempotency-key")
    transition_parser.add_argument("--ref")
    transition_parser.set_defaults(func=command_transition)

    for name, func in [("validate", command_validate), ("reduce", command_reduce), ("decide", command_decide), ("render", command_render)]:
        sub = subparsers.add_parser(name)
        sub.add_argument("--run-dir", type=Path, required=True)
        if name == "render":
            sub.add_argument("--format", choices=["json", "markdown"], default="markdown")
        sub.set_defaults(func=func)

    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--run-dir", type=Path, required=True)
    claim_parser.add_argument("--owner-run-id", required=True)
    claim_parser.add_argument("--distributed-token", required=True)
    claim_parser.add_argument("--heartbeat-ttl-seconds", type=int, default=900)
    claim_parser.add_argument("--actor", default="codex")
    claim_parser.add_argument("--receipt", required=True)
    claim_parser.add_argument("--idempotency-key")
    claim_parser.set_defaults(func=command_claim)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--run-dir", type=Path, required=True)
    release_parser.add_argument("--reason", default="manual release")
    release_parser.set_defaults(func=command_release)

    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--run-dir", type=Path, required=True)
    recover_parser.add_argument("--owner-run-id")
    recover_parser.add_argument("--heartbeat-ttl-seconds", type=int, default=900)
    recover_parser.set_defaults(func=command_recover)

    prepare_parser = subparsers.add_parser("prepare-review")
    prepare_parser.add_argument("--run-dir", type=Path, required=True)
    prepare_parser.add_argument("--mode", choices=sorted(REVIEW_MODES), required=True)
    prepare_parser.add_argument("--review-run-id")
    prepare_parser.add_argument("--review-run-dir", type=Path)
    prepare_parser.add_argument("--builder-model", default="gpt-5.6-codex")
    prepare_parser.add_argument("--reviewer-model", default="claude-opus")
    prepare_parser.add_argument("--builder-family", default="gpt")
    prepare_parser.add_argument("--reviewer-family", default="opus")
    prepare_parser.add_argument(
        "--reviewer-transport",
        choices=sorted(REVIEWER_TRANSPORTS),
        default="claude_cli",
    )
    prepare_parser.add_argument(
        "--review-unavailable-policy",
        choices=sorted(REVIEW_UNAVAILABLE_POLICIES),
        default="continue_with_receipt",
    )
    prepare_parser.add_argument("--actor", default="codex")
    prepare_parser.add_argument("--implementation-summary", default="See local artifacts.")
    prepare_parser.add_argument("--validation-status", default="passed")
    prepare_parser.add_argument("--pr-check-status", default="not_applicable")
    prepare_parser.add_argument("--copilot-status", default="not_applicable")
    prepare_parser.add_argument("--loop-limit", type=int, default=3)
    prepare_parser.add_argument("--base-sha")
    prepare_parser.add_argument("--head-sha")
    prepare_parser.add_argument("--diff-hash")
    prepare_parser.add_argument("--pr-url")
    prepare_parser.add_argument("--spec")
    prepare_parser.add_argument("--acceptance-criteria")
    prepare_parser.add_argument("--validation-summary")
    prepare_parser.add_argument("--ci-status")
    prepare_parser.add_argument("--diff-or-file-list")
    prepare_parser.add_argument("--tokens")
    prepare_parser.add_argument("--idempotency-key")
    prepare_parser.set_defaults(func=command_prepare_review)

    ingest_parser = subparsers.add_parser("ingest-review")
    ingest_parser.add_argument("--run-dir", type=Path, required=True)
    ingest_parser.add_argument("--review-run-dir", type=Path)
    ingest_parser.add_argument("--response", type=Path)
    ingest_parser.add_argument("--reviewer-model", default="claude-opus")
    ingest_parser.add_argument(
        "--reviewer-transport",
        choices=sorted(REVIEWER_TRANSPORTS),
        default="claude_cli",
    )
    ingest_parser.add_argument("--attested-by", default="Michael Clark")
    ingest_parser.add_argument("--actor", default="codex")
    ingest_parser.add_argument("--idempotency-key")
    ingest_parser.set_defaults(func=command_ingest_review)

    run_review_parser = subparsers.add_parser("run-review")
    run_review_parser.add_argument("--run-dir", type=Path, required=True)
    run_review_parser.add_argument("--review-run-dir", type=Path, required=True)
    run_review_parser.add_argument("--reviewer-model", default="opus")
    run_review_parser.add_argument("--timeout-seconds", type=int, default=1800)
    run_review_parser.add_argument(
        "--review-unavailable-policy",
        choices=sorted(REVIEW_UNAVAILABLE_POLICIES),
        default="continue_with_receipt",
    )
    run_review_parser.add_argument("--attested-by", default="Auto Dev Claude CLI runner")
    run_review_parser.add_argument("--actor", default="codex")
    run_review_parser.add_argument("--idempotency-key")
    run_review_parser.set_defaults(func=command_run_review)

    unavailable_parser = subparsers.add_parser("record-review-unavailable")
    unavailable_parser.add_argument("--run-dir", type=Path, required=True)
    unavailable_parser.add_argument("--review-run-dir", type=Path, required=True)
    unavailable_parser.add_argument("--failure-code", choices=sorted(REVIEW_FAILURE_CODES), required=True)
    unavailable_parser.add_argument("--failure-summary", required=True)
    unavailable_parser.add_argument(
        "--review-unavailable-policy",
        choices=sorted(REVIEW_UNAVAILABLE_POLICIES),
        default="continue_with_receipt",
    )
    unavailable_parser.add_argument("--actor", default="codex")
    unavailable_parser.add_argument("--idempotency-key")
    unavailable_parser.set_defaults(func=command_record_review_unavailable)

    scrub_parser = subparsers.add_parser("scrub-external-output")
    scrub_parser.add_argument("--input", type=Path, required=True)
    scrub_parser.add_argument("--output", type=Path, required=True)
    scrub_parser.set_defaults(func=command_scrub)

    context_parser = subparsers.add_parser("context-load")
    context_parser.add_argument("--project-config", type=Path, required=True)
    context_parser.set_defaults(func=command_context_load)

    in_flight_parser = subparsers.add_parser("list-in-flight")
    in_flight_parser.add_argument("--project")
    in_flight_parser.set_defaults(func=command_list_in_flight)

    fixture_parser = subparsers.add_parser("fixture-test")
    fixture_parser.add_argument("--fixtures", type=Path, required=True)
    fixture_parser.add_argument("--keep-tmp", action="store_true")
    fixture_parser.set_defaults(func=command_fixture_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AutoDevStateError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
