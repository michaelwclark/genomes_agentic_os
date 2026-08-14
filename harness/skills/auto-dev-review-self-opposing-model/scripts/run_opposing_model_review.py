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

HELPER = ROOT / "harness/skills/finishing-touches-review/scripts/finishing_touches_review_helper.py"
TEMPLATE = ROOT / "harness/skills/auto-dev/templates/reviewer-prompt.md"
CLAUDE_ENV_REMOVED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLAUDE_TOOLS = "Read,Grep,Glob,Bash(git diff),Bash(git diff *),Bash(git show),Bash(git show *),Bash(git status),Bash(git status *)"
MAX_DIFF_CHARS = 40_000


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


def one(paths: list[Path], description: str) -> Path:
    if len(paths) != 1:
        raise ReviewError(f"expected exactly one {description}; found {len(paths)}")
    return paths[0]


def locate_work_item(os_root: Path, ticket: str) -> Path:
    key = normalized(ticket)
    matches = [path for path in os_root.glob("domains/*/02-projects/*/work-items/*") if key in normalized(path.name)]
    return one(matches, f"work item for {ticket}")


def locate_worktree(os_root: Path, ticket: str) -> Path:
    key = normalized(ticket)
    matches = [path for path in os_root.glob("domains/*/02-projects/*/worktrees/*") if key in normalized(path.name)]
    return one(matches, f"worktree for {ticket}")


def prior_request(work_item: Path, ticket: str) -> dict[str, Any]:
    requests = sorted(work_item.glob("artifacts/finishing-touches/**/review-request.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in requests:
        value = json.loads(path.read_text(encoding="utf-8"))
        if str(value.get("work_item_id", "")).upper() == ticket.upper():
            return value
    raise ReviewError(f"no prior finishing-review request for {ticket}")


def provider_pr(pr_number: int, worktree: Path) -> dict[str, Any]:
    completed = run(["gh", "pr", "view", str(pr_number), "--json", "number,url,state,headRefOid,baseRefName,statusCheckRollup"], cwd=worktree)
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


def diff_hash(worktree: Path, base: str, head: str) -> str:
    completed = run(["git", "diff", "--binary", f"{base}..{head}"], cwd=worktree)
    if completed.returncode:
        raise ReviewError("review diff could not be read")
    return hashlib.sha256(completed.stdout.encode()).hexdigest()


def validated_delta_hash(worktree: Path, parent_head: str, head: str) -> str:
    """Prove the delta is descendant-only and small enough for one review."""
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", parent_head, head], cwd=worktree
    )
    if ancestry.returncode:
        raise ReviewError("delta parent is not an ancestor of the current head")
    completed = run(["git", "diff", "--binary", f"{parent_head}..{head}"], cwd=worktree)
    if completed.returncode:
        raise ReviewError("review delta could not be read")
    if len(completed.stdout) > MAX_DIFF_CHARS:
        raise ReviewError(
            f"review delta exceeds the {MAX_DIFF_CHARS}-character review bound"
        )
    return hashlib.sha256(completed.stdout.encode()).hexdigest()


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


def receipt_markdown(run_id: str, status: str, failure: str | None = None) -> str:
    lines = ["# Model Receipt", "", f"- Review run: `{run_id}`", "- Reviewer model: `opus`", "- Reviewer family: `opus`", "- Transport: `claude_cli`", "- Authentication: `cli_native`", f"- Reviewer status: `{status}`", "- Unavailable policy: `block`"]
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
    parser.add_argument("--os-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-item", type=Path)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--mode", choices=["full", "delta"], default="full")
    parser.add_argument("--parent-key")
    parser.add_argument("--purpose", default="review_self")
    parser.add_argument("--scope", default="full-pr")
    args = parser.parse_args()
    try:
        os_root = args.os_root.resolve()
        work_item = (args.work_item or locate_work_item(os_root, args.ticket)).resolve()
        worktree = (args.worktree or locate_worktree(os_root, args.ticket)).resolve()
        source = prior_request(work_item, args.ticket)
        pr_number = int(source["pr_number"])
        provider = provider_pr(pr_number, worktree)
        head = git_head(worktree)
        if provider["headRefOid"] != head:
            raise ReviewError(f"exact-head mismatch: provider={provider['headRefOid']} worktree={head}")
        base = str(source["base_sha"])
        repository = git_repository(worktree)
        if args.scope.replace("_", "-").lower() not in {"full-pr", "pr"}:
            raise ReviewError("review scope must resolve to full-pr")
        subject = ReviewSubject(
            repository=repository,
            pull_request=f"github:{repository}#{pr_number}",
            base_branch=str(provider["baseRefName"]),
            base_sha=base,
            head_sha=head,
            policy_fingerprint=policy_fingerprint(source),
            purpose=canonical_review_purpose(f"{args.purpose}:{args.scope}"),
        )
        coordinator = ReviewCoordinator(shared_review_coordination_root(os_root))
        review_key = stable_review_key(subject)
        run_id = f"{args.ticket.lower()}-pr{pr_number}-{args.mode}-{review_key[:12]}"
        run_dir = work_item / "artifacts/finishing-touches/review-runs" / review_key
        review_diff_base = base
        review_diff_hash: str | None = None
        if args.mode == "delta":
            if not args.parent_key:
                raise ReviewError("delta review requires --parent-key")
            parent = load_review_receipt(coordinator.receipts / f"{args.parent_key}.json")
            parent_subject = ReviewSubject.from_mapping(parent["subject"])
            if review_chain_key(parent_subject) != review_chain_key(subject):
                raise ReviewError(
                    "delta parent must belong to the same repository, PR, base, and policy"
                )
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
                "review_unavailable_policy": "block",
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
                        (run_dir / "reviewer-response.md").write_text(
                            response + "\n", encoding="utf-8"
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
                receipt_markdown(run_id, plan["reviewer_status"], failure),
                encoding="utf-8",
            )
            decision = decide(run_dir)
            if plan["reviewer_status"] in {"unavailable", "runtime_failure"}:
                outcome = "unavailable"
            elif decision["decision"].startswith("ready_"):
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
                "readback_verified": failure != "head_changed_after_review",
            }

        result = coordinator.execute(
            subject,
            execute_review,
            mode=args.mode,
            parent_key=args.parent_key,
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
