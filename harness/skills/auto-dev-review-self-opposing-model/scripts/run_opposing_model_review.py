#!/usr/bin/env python3
"""Run one exact-head, receipt-backed opposing-model Auto-Dev review.

This is the sole executable transport behind
``$auto-dev-review-self-opposing-model <TICKET>``.  It deliberately owns no
PR mutation: it reconciles an existing PR and worktree, invokes the approved
read-only reviewer, and writes a deterministic finishing-review receipt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
# scripts/ -> skill -> skills -> harness -> checkout root
ROOT = SCRIPT_DIR.parents[3]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from genomes_agentic_os.review_coordination import (  # noqa: E402
    ReviewCoordinationError,
    ReviewCoordinator,
    ReviewSubject,
    canonical_review_purpose,
    load_review_receipt,
    review_chain_key,
    shared_review_coordination_root,
    stable_review_key,
)
from genomes_agentic_os.review_verdicts import reconcile_json_verdict  # noqa: E402

HELPER = ROOT / "harness/skills/finishing-touches-review/scripts/finishing_touches_review_helper.py"
TEMPLATE = ROOT / "harness/skills/auto-dev/templates/reviewer-prompt.md"
CLAUDE_ENV_REMOVED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLAUDE_TOOLS = "Read,Grep,Glob,Bash(git diff),Bash(git diff *),Bash(git show),Bash(git show *),Bash(git status),Bash(git status *)"
MAX_DIFF_CHARS = 40_000
PURPOSE_ALIASES = {
    "finalize",
    "merge-readiness",
    "review-others",
    "review-repair",
    "review-self",
    "review_others",
    "review_repair",
    "review_self",
}
SCOPE_ALIASES = {"full-pr": "full-pr", "full_pr": "full-pr", "pr": "full-pr"}
INSTALLED_OS_ROOT = Path.home() / "agentic_os"


class ReviewError(RuntimeError):
    """An input or provider invariant prevents review."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 30, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=False, timeout=timeout, env=env)


def normalized(ticket: str) -> str:
    return "".join(ch.lower() for ch in ticket if ch.isalnum())


def normalize_review_purpose(purpose: str, scope: str) -> tuple[str, str]:
    """Normalize every accepted entrypoint alias onto the shared subject key."""
    requested_purpose = str(purpose).strip().lower()
    normalized_scope = SCOPE_ALIASES.get(str(scope).strip().lower())
    if requested_purpose not in PURPOSE_ALIASES:
        raise ReviewError("review purpose must be a documented merge-readiness stage alias")
    if normalized_scope is None:
        raise ReviewError("review scope must resolve to full-pr")
    return (
        canonical_review_purpose(f"{requested_purpose}:{normalized_scope}"),
        normalized_scope,
    )


def parse_review_verdict(response: str) -> tuple[str, bool]:
    """Apply the shared CLEAN=no-active-blocking-findings contract."""
    return reconcile_json_verdict(response)


REVIEW_FINDINGS_PATTERN = re.compile(
    r"```json\s*(\[.*?\])\s*```", re.IGNORECASE | re.DOTALL
)
REQUIRED_FINDING_FIELDS = {
    "id",
    "severity",
    "category",
    "file",
    "line",
    "title",
    "detail",
    "suggested_fix",
    "blocking",
}


def parse_structured_findings(response: str) -> list[dict[str, Any]]:
    """Parse the reviewer-owned findings into the canonical local ledger.

    A reviewer may describe non-blocking advice while still using the legacy
    ``FINDINGS`` verdict.  The typed ``blocking`` field is the merge-gate
    authority, but every advisory remains durable evidence rather than being
    silently dropped before the finishing-review helper sees it.
    """

    blocks = REVIEW_FINDINGS_PATTERN.findall(response)
    if len(blocks) != 1:
        raise ReviewError("reviewer response must contain exactly one fenced JSON findings array")
    try:
        findings = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ReviewError(f"reviewer findings JSON is invalid: {exc}") from exc
    if not isinstance(findings, list):
        raise ReviewError("reviewer findings JSON must be an array")
    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(findings, start=1):
        if not isinstance(raw, dict):
            raise ReviewError(f"reviewer finding {index} must be an object")
        missing = sorted(REQUIRED_FINDING_FIELDS - set(raw))
        if missing:
            raise ReviewError(
                f"reviewer finding {index} missing fields: {', '.join(missing)}"
            )
        severity = str(raw["severity"]).strip().lower()
        if severity not in {"critical", "high", "medium", "low"}:
            raise ReviewError(f"reviewer finding {index} has invalid severity")
        if not isinstance(raw["blocking"], bool):
            raise ReviewError(f"reviewer finding {index} blocking must be boolean")
        finding_id = str(raw["id"]).strip()
        if not finding_id:
            raise ReviewError(f"reviewer finding {index} id must be non-empty")
        parsed.append({**raw, "id": finding_id, "severity": severity})
    return parsed


def ledger_events(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Represent both blocking findings and advisory evidence faithfully.

    The helper's event model does not have a separate advisory state.  An
    advisory is therefore opened and immediately reviewer-verified, preserving
    it in the immutable event history without manufacturing an active blocker.
    """

    created_at = now()
    events: list[dict[str, Any]] = []
    for finding in findings:
        evidence = f"{finding['file']}:{finding['line']} {finding['detail']}"
        base = {
            "created_at": created_at,
            "id": finding["id"],
            "severity": str(finding["severity"]).capitalize(),
            "summary": str(finding["title"]),
            "evidence": evidence,
            "category": finding["category"],
            "suggested_fix": finding["suggested_fix"],
            "blocking": finding["blocking"],
        }
        events.append({**base, "event_type": "finding_opened", "status": "OPEN"})
        if not finding["blocking"]:
            events.append(
                {
                    **base,
                    "event_type": "finding_verified",
                    "status": "VERIFIED",
                    "advisory": True,
                    "verification": "reviewer_marked_nonblocking",
                }
            )
    return events


def coordination_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Carry advisory evidence into coordination without leaving it open."""

    rows: list[dict[str, Any]] = []
    for finding in findings:
        advisory = not finding["blocking"]
        rows.append(
            {
                "id": finding["id"],
                "severity": finding["severity"],
                "summary": finding["title"],
                "evidence": [f"{finding['file']}:{finding['line']} {finding['detail']}"],
                "status": "resolved" if advisory else "open",
                "resolution_refs": (
                    [f"reviewer-nonblocking-advisory:{finding['id']}"]
                    if advisory
                    else []
                ),
                "advisory": advisory,
            }
        )
    return rows


def resolve_os_root(explicit: Path | None) -> Path:
    """Resolve only the configured or installed canonical OS root, never cwd."""
    configured = str(os.environ.get("AGENTIC_OS_ROOT") or "").strip()
    candidate = explicit or (Path(configured) if configured else INSTALLED_OS_ROOT)
    candidate = candidate.expanduser().resolve()
    # This also fails closed when an explicit root disagrees with AGENTIC_OS_ROOT.
    shared_review_coordination_root(candidate)
    required = [candidate / ".agentic_root", candidate / "harness", candidate / "domains"]
    if not all(path.exists() for path in required):
        raise ReviewError(
            "installed Agentic OS root is unavailable; pass --os-root or set "
            "AGENTIC_OS_ROOT to the canonical installed root"
        )
    return candidate


def one(paths: list[Path], description: str) -> Path:
    if len(paths) != 1:
        raise ReviewError(f"expected exactly one {description}; found {len(paths)}")
    return paths[0]


def project_roots(os_root: Path) -> list[Path]:
    """Return only canonical domain and shared-factory project surfaces."""

    roots = list(os_root.glob("domains/*/02-projects/*"))
    roots.extend((os_root / "harness/shared_factory/02-projects").glob("*"))
    return sorted({path.resolve() for path in roots if path.is_dir()})


def locate_work_item(os_root: Path, ticket: str) -> Path:
    key = normalized(ticket)
    matches = [
        manifest.parent
        for project in project_roots(os_root)
        for manifest in (project / "work-items").glob("**/autodev.json")
        if key in normalized(manifest.parent.name)
    ]
    return one(matches, f"work item for {ticket}")


def locate_worktree(os_root: Path, ticket: str) -> Path:
    key = normalized(ticket)
    matches = [
        path
        for project in project_roots(os_root)
        for path in (project / "worktrees").glob("*")
        if path.is_dir() and key in normalized(path.name)
    ]
    return one(matches, f"worktree for {ticket}")


def prior_request(work_item: Path, ticket: str) -> dict[str, Any] | None:
    requests = sorted(work_item.glob("artifacts/finishing-touches/**/review-request.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in requests:
        value = json.loads(path.read_text(encoding="utf-8"))
        if str(value.get("work_item_id", "")).upper() == ticket.upper():
            return value
    return None


def initial_request(work_item: Path, ticket: str, worktree: Path) -> dict[str, Any]:
    """Derive the first review request from immutable PR Create and packet truth."""

    readback_path = (
        work_item
        / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json"
    )
    manifest_path = work_item / "autodev.json"
    if not readback_path.is_file() or not manifest_path.is_file():
        raise ReviewError(
            f"no prior finishing-review request or canonical PR Create readback for {ticket}"
        )
    readback = json.loads(readback_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "number",
        "url",
        "state",
        "base_branch",
        "base_sha",
        "head_sha",
        "repository",
    }
    missing = sorted(required - set(readback))
    if missing:
        raise ReviewError(
            "PR Create provider readback missing required fields: " + ", ".join(missing)
        )
    if readback["state"] != "OPEN":
        raise ReviewError("PR Create provider readback is not OPEN")
    subject_revision = str(manifest.get("subject_revision") or "")
    if subject_revision and subject_revision != str(readback["head_sha"]):
        raise ReviewError(
            "PR Create provider readback head does not match the packet subject revision"
        )
    delivery = manifest.get("delivery") or {}
    supplied_policy_fingerprint = str(delivery.get("policy_fingerprint") or "")
    if len(supplied_policy_fingerprint) != 64:
        raise ReviewError("packet delivery policy fingerprint is missing or invalid")
    return {
        "work_item_id": ticket,
        "run_id": "pending-initial-review",
        "repo_path": str(worktree),
        "implementation_summary": str(
            readback.get("title") or f"Exact-head implementation for {ticket}"
        ),
        "spec_source": "SPEC.md" if (work_item / "SPEC.md").is_file() else "provider ticket",
        "builder_model": "codex",
        "selected_reviewer_model": "opus",
        "reviewer_selection_source": "auto-dev-review-self-opposing-model",
        "target_branch": str(readback["base_branch"]),
        "base_sha": str(readback["base_sha"]),
        "head_sha": str(readback["head_sha"]),
        "diff_hash": "pending-live-diff",
        "pr_number": int(readback["number"]),
        "artifact_dir": "pending-initial-review",
        "mode": "post_pr",
        "policy_fingerprint": supplied_policy_fingerprint,
        "request_origin": "auto-dev-pr-create-provider-readback",
        "provider_readback_ref": str(readback_path.relative_to(work_item)),
    }


def provider_pr(pr_number: int, worktree: Path) -> dict[str, Any]:
    completed = run(["gh", "pr", "view", str(pr_number), "--json", "number,url,state,headRefOid,baseRefName,baseRefOid,statusCheckRollup"], cwd=worktree)
    if completed.returncode:
        raise ReviewError("GitHub PR readback failed")
    value = json.loads(completed.stdout)
    if value.get("state") != "OPEN":
        raise ReviewError(f"PR #{pr_number} is not open")
    return value


def git_head(worktree: Path) -> str:
    completed = run(["git", "rev-parse", "HEAD"], cwd=worktree)
    if completed.returncode or not completed.stdout.strip():
        raise ReviewError("worktree HEAD is not verifiable")
    return completed.stdout.strip()


def git_repository(worktree: Path) -> str:
    completed = run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=worktree,
    )
    if completed.returncode or "/" not in completed.stdout.strip():
        raise ReviewError("provider repository is not verifiable")
    return completed.stdout.strip()


def policy_fingerprint(source: dict[str, Any]) -> str:
    supplied = str(source.get("policy_fingerprint") or "")
    if len(supplied) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in supplied):
        return supplied.lower()
    policy = source.get("review_policy") or source.get("effective_policy") or {
        "review_unavailable_policy": "block",
        "reviewer_transport": "claude_cli",
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_unavailable_policy(source: dict[str, Any]) -> str:
    """Read the routed project fallback policy without silently weakening it."""

    candidates: list[Any] = [source.get("review_unavailable_policy")]
    for key in ("review_policy", "effective_policy"):
        value = source.get(key)
        if isinstance(value, dict):
            candidates.extend(
                [value.get("review_unavailable_policy"), value.get("unavailable_policy")]
            )
    for candidate in candidates:
        if candidate in {"block", "continue_with_receipt"}:
            return str(candidate)
    # The routed Development Delivery policy configures a receipt-backed
    # fallback by default.  Unknown explicit values fail closed rather than
    # being treated as permission to continue.
    if any(candidate not in (None, "") for candidate in candidates):
        raise ReviewError("review_unavailable_policy must be block or continue_with_receipt")
    return "continue_with_receipt"


def diff_hash(worktree: Path, base: str, head: str) -> str:
    completed = run(["git", "diff", "--binary", f"{base}..{head}"], cwd=worktree)
    if completed.returncode:
        raise ReviewError("review diff could not be read")
    return hashlib.sha256(completed.stdout.encode()).hexdigest()


def validated_delta_hash(worktree: Path, parent_head: str, head: str) -> str:
    """Prove the delta is descendant-only and bind the complete delta by hash."""
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", parent_head, head], cwd=worktree
    )
    if ancestry.returncode:
        raise ReviewError("delta parent is not an ancestor of the current head")
    completed = run(["git", "diff", "--binary", f"{parent_head}..{head}"], cwd=worktree)
    if completed.returncode:
        raise ReviewError("review delta could not be read")
    return hashlib.sha256(completed.stdout.encode()).hexdigest()


def base_forward_evidence(worktree: Path, parent: ReviewSubject, subject: ReviewSubject) -> dict[str, object]:
    """Prove the only cross-chain delta: an unchanged-policy forward base."""
    if (parent.repository, parent.pull_request, parent.base_branch, parent.policy_fingerprint) != (subject.repository, subject.pull_request, subject.base_branch, subject.policy_fingerprint):
        raise ReviewError("base-forward parent changes repository, PR, branch, or policy")
    if parent.base_sha == subject.base_sha:
        raise ReviewError("base-forward continuation requires a changed base")
    if run(["git", "merge-base", "--is-ancestor", parent.base_sha, subject.base_sha], cwd=worktree).returncode:
        raise ReviewError("base-forward parent base is not an ancestor of current base")
    if run(["git", "merge-base", "--is-ancestor", parent.head_sha, subject.head_sha], cwd=worktree).returncode:
        raise ReviewError("base-forward parent head is not an ancestor of current head")
    return {"transition": "base_forward", "previous_base_sha": parent.base_sha, "current_base_sha": subject.base_sha, "base_ancestor": True, "parent_head_ancestor": True, "provider_verified": True}


def render_prompt(request: dict[str, Any], provider: dict[str, Any]) -> str:
    values = {
        "WORK_ITEM_ID": str(request["work_item_id"]), "PROJECT": "Auto-Dev",
        "TRACKER_ID": str(request["work_item_id"]), "TRACKER_URL": "provider-read ticket context",
        "BUILDER_FAMILY": "gpt", "REVIEWER_FAMILY": "opus", "MODE": str(request["mode"]),
        "PR_URL": str(provider["url"]), "BASE_SHA": str(request["base_sha"]), "HEAD_SHA": str(request["head_sha"]),
        "SPEC": str(request.get("spec_source", "provider ticket")),
        "ACCEPTANCE_CRITERIA": str(request.get("spec_source", "provider ticket")),
        "VALIDATION_SUMMARY": "provider and local validation are recorded in the work item",
        "CI_STATUS": "passed" if all(row.get("conclusion") in {"SUCCESS", "SKIPPED"} for row in provider.get("statusCheckRollup", [])) else "pending",
        "COPILOT_STATUS": "not_applicable",
        "DIFF_OR_FILE_LIST": (
            f"Review only git diff {request['delta_base_sha']}..{request['head_sha']}."
            if request.get("review_mode") == "delta"
            else "Read the exact local PR diff."
        ),
        "TOKENS": "Do not expose secrets, local paths, private links, or internal operational detail.",
    }
    prompt = TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def receipt_markdown(
    run_id: str,
    status: str,
    unavailable_policy: str,
    failure: str | None = None,
) -> str:
    lines = ["# Model Receipt", "", f"- Review run: `{run_id}`", "- Reviewer model: `opus`", "- Reviewer family: `opus`", "- Transport: `claude_cli`", "- Authentication: `cli_native`", f"- Reviewer status: `{status}`", f"- Unavailable policy: `{unavailable_policy}`"]
    if failure:
        lines.append(f"- Failure code: `{failure}`")
    return "\n".join(lines) + "\n"


def decide(run_dir: Path) -> dict[str, Any]:
    completed = run([sys.executable, str(HELPER), "decide", "--run-dir", str(run_dir)], cwd=ROOT)
    if completed.returncode:
        raise ReviewError("finishing-review decision failed")
    return json.loads((run_dir / "readiness-decision.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket")
    parser.add_argument(
        "--os-root",
        type=Path,
        help=(
            "Canonical installed Agentic OS root (default: AGENTIC_OS_ROOT or "
            "~/agentic_os; the current directory is never used)."
        ),
    )
    parser.add_argument("--work-item", type=Path)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--mode", choices=["full", "delta"], default="full")
    parser.add_argument("--parent-key")
    parser.add_argument(
        "--recover-advisory-from",
        type=Path,
        help=(
            "Derive immutable same-head clean authority from the named findings "
            "receipt and its matching all-nonblocking reviewer-response.md; "
            "does not invoke a reviewer."
        ),
    )
    parser.add_argument("--purpose", default="review_self")
    parser.add_argument("--scope", default="full-pr")
    args = parser.parse_args()
    try:
        os_root = resolve_os_root(args.os_root)
        work_item = (args.work_item or locate_work_item(os_root, args.ticket)).resolve()
        worktree = (args.worktree or locate_worktree(os_root, args.ticket)).resolve()
        source = prior_request(work_item, args.ticket) or initial_request(
            work_item, args.ticket, worktree
        )
        unavailable_policy = review_unavailable_policy(source)
        pr_number = int(source["pr_number"])
        provider = provider_pr(pr_number, worktree)
        head = git_head(worktree)
        if provider["headRefOid"] != head:
            raise ReviewError(f"exact-head mismatch: provider={provider['headRefOid']} worktree={head}")
        base = str(source["base_sha"])
        if provider.get("baseRefOid") and provider["baseRefOid"] != base:
            raise ReviewError(
                f"exact-base mismatch: provider={provider['baseRefOid']} request={base}"
            )
        repository = git_repository(worktree)
        purpose, _scope = normalize_review_purpose(args.purpose, args.scope)
        subject = ReviewSubject(
            repository=repository,
            pull_request=f"github:{repository}#{pr_number}",
            base_branch=str(provider["baseRefName"]),
            base_sha=base,
            head_sha=head,
            policy_fingerprint=policy_fingerprint(source),
            purpose=purpose,
        )
        coordinator = ReviewCoordinator(shared_review_coordination_root(os_root))
        review_key = stable_review_key(subject)
        if args.recover_advisory_from:
            parent = load_review_receipt(args.recover_advisory_from)
            parent_subject = ReviewSubject.from_mapping(parent["subject"])
            if parent_subject != subject:
                raise ReviewError("advisory recovery receipt does not match the current exact head")
            review_dir = Path(str((parent.get("review") or {}).get("review_run_dir") or ""))
            response_path = review_dir / "reviewer-response.md"
            findings = parse_structured_findings(
                response_path.read_text(encoding="utf-8").strip()
            )
            recovered = coordinator.derive_same_head_advisory_clean(
                args.recover_advisory_from,
                evidence_path=response_path,
                findings=findings,
            )
            receipt = {
                "schema": "opposing-model-review-recovery-receipt/v1",
                "outcome": recovered.receipt["outcome"],
                "ticket": args.ticket,
                "pr_number": pr_number,
                "pr_url": provider["url"],
                "head_sha": head,
                "parent_key": parent["key"],
                "review_key": recovered.key,
                "coordination_receipt": str(recovered.receipt_path),
                "evidence_ref": str(response_path),
                "reused": recovered.reused,
                "next_action": "consume exact-head receipt",
            }
            print(json.dumps(receipt, indent=2))
            return 0
        run_dir = work_item / "artifacts/finishing-touches/review-runs" / review_key
        # The finishing-review artifact contract binds run_id to the artifact
        # directory leaf. The stable coordination key already provides the
        # required deterministic identity, so use it directly rather than a
        # second display-oriented identifier.
        run_id = run_dir.name
        review_diff_base = base
        review_diff_hash: str | None = None
        continuation: dict[str, object] | None = None
        if args.mode == "delta":
            if not args.parent_key:
                raise ReviewError("delta review requires --parent-key")
            parent = load_review_receipt(coordinator.receipts / f"{args.parent_key}.json")
            parent_subject = ReviewSubject.from_mapping(parent["subject"])
            if review_chain_key(parent_subject) != review_chain_key(subject):
                continuation = base_forward_evidence(worktree, parent_subject, subject)
            review_diff_base = str(parent["subject"]["head_sha"])
            review_diff_hash = validated_delta_hash(worktree, review_diff_base, head)

        def execute_review() -> dict[str, Any]:
            failure: str | None = None
            request = {
                **source,
                "run_id": run_id,
                "artifact_dir": str(run_dir.relative_to(work_item)),
                "review_key": review_key,
                "review_mode": args.mode,
                "parent_key": args.parent_key,
                "delta_base_sha": review_diff_base,
                "head_sha": head,
                "base_sha": base,
                "diff_hash": review_diff_hash
                or diff_hash(worktree, review_diff_base, head),
                "reviewer_transport": "claude_cli",
                "reviewer_auth": "cli_native",
                "reviewer_environment_removed": list(CLAUDE_ENV_REMOVED),
                "provider_pr_url": provider["url"],
                "provider_read_at": now(),
            }
            plan = {
                "model_identity_status": "proven",
                "reviewer_status": "available",
                "review_unavailable_policy": unavailable_policy,
                "validation_status": "passed",
                "pr_check_status": "passed"
                if all(
                    row.get("conclusion") in {"SUCCESS", "SKIPPED"}
                    for row in provider.get("statusCheckRollup", [])
                )
                else "pending",
                "copilot_status": "not_applicable",
                "external_output_status": "clean",
                "external_output_paths": [],
                "loop_count": 1,
                "loop_limit": 3,
                "user_decision_blocker": False,
            }
            write_json(run_dir / "review-request.json", request)
            write_json(run_dir / "validation-plan.json", plan)
            (run_dir / "review-ledger.jsonl").write_text("", encoding="utf-8")
            prompt = render_prompt(request, provider)
            (run_dir / "reviewer-prompt.md").write_text(prompt, encoding="utf-8")
            claude = shutil.which("claude")
            response = ""
            parsed_outcome = "findings"
            verdict_structured = False
            findings: list[dict[str, Any]] = []
            if not claude:
                failure = "cli_not_found"
                plan["reviewer_status"] = "unavailable"
            else:
                env = os.environ.copy()
                for key in CLAUDE_ENV_REMOVED:
                    env.pop(key, None)
                try:
                    completed = run(
                        [
                            claude,
                            "-p",
                            "--model",
                            "opus",
                            "--safe-mode",
                            "--permission-mode",
                            "dontAsk",
                            "--tools",
                            "Read,Grep,Glob,Bash",
                            "--allowedTools",
                            CLAUDE_TOOLS,
                            "--no-session-persistence",
                            prompt,
                        ],
                        cwd=worktree,
                        timeout=args.timeout_seconds,
                        env=env,
                    )
                    if completed.returncode:
                        failure = "cli_runtime_failed"
                    elif not completed.stdout.strip():
                        failure = "cli_output_invalid"
                    else:
                        response = completed.stdout.strip()
                        parsed_outcome, verdict_structured = parse_review_verdict(response)
                        try:
                            findings = parse_structured_findings(response)
                        except ReviewError:
                            failure = "cli_output_invalid"
                        if not verdict_structured:
                            failure = "cli_output_invalid"
                        (run_dir / "reviewer-response.md").write_text(
                            response + "\n", encoding="utf-8"
                        )
                        if failure is None:
                            events = ledger_events(findings)
                            (run_dir / "review-ledger.jsonl").write_text(
                                "".join(
                                    json.dumps(event, sort_keys=True) + "\n"
                                    for event in events
                                ),
                                encoding="utf-8",
                            )
                except subprocess.TimeoutExpired:
                    failure = "cli_timeout"
                if failure:
                    plan["reviewer_status"] = "runtime_failure"

            # The paid review is not terminal until provider and worktree still
            # prove the same exact head after the model returns.
            post_provider = provider_pr(pr_number, worktree)
            post_head = git_head(worktree)
            if post_provider["headRefOid"] != head or post_head != head:
                failure = "head_changed_after_review"
                plan["reviewer_status"] = "runtime_failure"
            write_json(run_dir / "validation-plan.json", plan)
            (run_dir / "model-receipt.md").write_text(
                receipt_markdown(
                    run_id,
                    plan["reviewer_status"],
                    unavailable_policy,
                    failure,
                ),
                encoding="utf-8",
            )
            decision = decide(run_dir)
            if plan["reviewer_status"] in {"unavailable", "runtime_failure"}:
                outcome = "unavailable"
            elif (
                decision["decision"].startswith("ready_")
                and verdict_structured
                and not any(finding["blocking"] for finding in findings)
            ):
                outcome = "clean"
            else:
                outcome = "findings"
            return {
                "outcome": outcome,
                "ticket": args.ticket,
                "pr_number": pr_number,
                "pr_url": provider["url"],
                "head_sha": head,
                "review_run_dir": str(run_dir),
                "reviewer_status": plan["reviewer_status"],
                "failure_code": failure,
                "decision": decision["decision"],
                "response": response,
                "parsed_outcome": parsed_outcome,
                "verdict_structured": verdict_structured,
                "findings": coordination_findings(findings),
                "advisory_finding_count": sum(
                    not finding["blocking"] for finding in findings
                ),
                "readback_verified": failure != "head_changed_after_review",
            }

        result = coordinator.execute(
            subject,
            execute_review,
            mode=args.mode,
            parent_key=args.parent_key,
            base_forward_evidence=continuation,
        )
        review = dict(result.receipt["review"])
        receipt = {
            "schema": "opposing-model-review-receipt/v2",
            **review,
            "review_key": result.key,
            "review_mode": args.mode,
            "parent_key": args.parent_key,
            "coordination_receipt": str(result.receipt_path),
            "reused": result.reused,
            "next_action": (
                "repair findings"
                if result.receipt["outcome"] == "findings"
                else "resolve reviewer runtime or obtain governed review"
                if result.receipt["outcome"] == "unavailable"
                else "consume exact-head receipt"
            ),
        }
        write_json(run_dir / "opposing-model-review-receipt.json", receipt)
        print(json.dumps(receipt, indent=2))
        return 0 if result.receipt["outcome"] == "clean" else 2
    except (ReviewError, ReviewCoordinationError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
