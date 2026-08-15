#!/usr/bin/env python3
"""Quietly watch GitHub PR checks and write status artifacts to disk."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from genomes_agentic_os.github_bridge import (
    BridgeRunner,
    command_from_environment,
    get_pull_request as bridge_get_pull_request,
    list_workflow_runs as bridge_list_workflow_runs,
)


SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
REQUIRED_SUCCESS_CONCLUSIONS = {"success"}
FAILURE_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
REQUIRED_CHECK_EMISSION_SETTLED_POLLS = 2


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def infer_repo(cwd: str | None) -> str:
    """Infer owner/name from the local checkout's GitHub origin."""
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "could not infer repo; pass --repo owner/name")
    remote = result.stdout.strip()
    if "github.com:" in remote:
        repo = remote.split("github.com:", 1)[1]
    elif "github.com/" in remote:
        repo = remote.split("github.com/", 1)[1]
    else:
        raise RuntimeError("origin is not a GitHub repository; pass --repo owner/name")
    repo = repo.removesuffix(".git").strip("/")
    if len(repo.split("/")) != 2 or not all(repo.split("/")):
        raise RuntimeError("could not infer repo; pass --repo owner/name")
    return repo


def github_token_from_environment(environ: Mapping[str, str] | None = None) -> str:
    """Resolve the token passed to the shared bridge without invoking another client."""
    values = environ or os.environ
    token = values.get("GITHUB_TOKEN", "").strip() or values.get("GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN must be set for the GitHub port bridge")
    return token


def split_repo(repo: str) -> tuple[str, str]:
    """Validate and split an owner/name repository reference."""
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise RuntimeError("repo must use owner/name format")
    return parts[0], parts[1]


def atomic_write(path: Path, content: str) -> None:
    """Write a file atomically in its target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        tmp_name = handle.name
    os.replace(tmp_name, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def get_pr(
    command: Sequence[str],
    repo: str,
    pr_number: int,
    token: str,
    *,
    runner: BridgeRunner = subprocess.run,
) -> dict[str, Any]:
    """Fetch normalized PR metadata through the shared GitHub port."""
    owner, name = split_repo(repo)
    pull_request = bridge_get_pull_request(
        command,
        owner=owner,
        repo=name,
        number=pr_number,
        token=token,
        runner=runner,
    )
    if pull_request is None:
        raise RuntimeError(f"pull request {pr_number} was not found")
    if not isinstance(pull_request.get("headSha"), str) or not pull_request["headSha"]:
        raise RuntimeError("GitHub port returned a pull request without a head SHA")
    if not isinstance(pull_request.get("headBranch"), str) or not pull_request["headBranch"]:
        raise RuntimeError("GitHub port returned a pull request without a head branch")
    return pull_request


def get_workflow_runs(
    command: Sequence[str],
    repo: str,
    branch: str,
    token: str,
    *,
    runner: BridgeRunner = subprocess.run,
) -> list[dict[str, Any]]:
    """Fetch normalized workflow runs through the shared GitHub port."""
    owner, name = split_repo(repo)
    return bridge_list_workflow_runs(
        command,
        owner=owner,
        repo=name,
        branch=branch,
        token=token,
        limit=100,
        runner=runner,
    )


def validate_required_check_contract(
    required_checks: list[str],
    workflow_runs: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Validate required labels against the settled exact-head check context."""
    required_names = sorted(set(required_checks))
    observed_names = sorted({str(run.get("name") or "unnamed check") for run in workflow_runs})
    missing_required_checks = sorted(set(required_names) - set(observed_names))
    context_is_settled = bool(workflow_runs) and all(run.get("status") == "completed" for run in workflow_runs)
    return {
        "observed_check_names": observed_names,
        "missing_required_checks": missing_required_checks,
        "invalid_required_checks": [],
        "check_context_settled": context_is_settled,
    }


def apply_required_check_emission_grace(
    state: Mapping[str, Any],
    *,
    previous_missing_required_checks: Sequence[str] = (),
    settled_missing_required_observations: int = 0,
) -> tuple[dict[str, Any], list[str], int]:
    """Fail stale required labels only after stable settled observations.

    A completed workflow run does not prove GitHub has emitted every downstream
    run for the exact head. Preserve one additional settled poll for the same
    missing labels before treating them as invalid configuration.
    """
    updated = dict(state)
    missing_required_checks = list(updated.get("missing_required_checks") or [])
    if not updated.get("check_context_settled") or not missing_required_checks:
        updated["required_check_emission_observations"] = 0
        return updated, [], 0

    if sorted(previous_missing_required_checks) == missing_required_checks:
        observations = settled_missing_required_observations + 1
    else:
        observations = 1
    updated["required_check_emission_observations"] = observations
    if observations < REQUIRED_CHECK_EMISSION_SETTLED_POLLS:
        return updated, missing_required_checks, observations

    invalid_required_checks = list(missing_required_checks)
    invalid_failures = [
        f"required check label not emitted at exact head: {name}"
        for name in invalid_required_checks
    ]
    updated["invalid_required_checks"] = invalid_required_checks
    updated["failures"] = sorted(set([*(updated.get("failures") or []), *invalid_failures]))
    updated["pending"] = [
        item
        for item in updated.get("pending") or []
        if item not in {f"required check not observed: {name}" for name in invalid_required_checks}
    ]
    updated["status"] = "failure"
    return updated, missing_required_checks, observations


def summarize_checks(
    pr: dict[str, Any],
    workflow_runs: list[dict[str, Any]],
    min_checks: int,
    expected_head_sha: str = "",
    required_checks: list[str] | None = None,
    expected_head_seen: bool = False,
) -> dict[str, Any]:
    """Classify the current PR check state."""
    sha = pr["headSha"]
    required_checks = required_checks or []
    checks: list[dict[str, str | None]] = []
    failures: list[str] = []
    pending: list[str] = []
    required_check_names = set(required_checks)

    if pr.get("state") == "closed":
        failures.append("PR is closed without merge")
    if expected_head_sha and sha != expected_head_sha:
        if expected_head_seen:
            failures.append("PR head changed from expected SHA")
        else:
            pending.append("waiting for expected PR head SHA")

    classify_observed_checks = not expected_head_sha or sha == expected_head_sha
    relevant_workflow_runs = (
        [run for run in workflow_runs if run.get("headSha") == sha]
        if classify_observed_checks
        else []
    )
    observed_count = len(relevant_workflow_runs)

    for run in relevant_workflow_runs:
        name = run.get("name") or "unnamed check"
        status = run.get("status")
        conclusion = run.get("conclusion")
        checks.append(
            {"type": "workflow_run", "name": name, "status": status, "conclusion": conclusion}
        )
        if status != "completed":
            pending.append(name)
        elif name in required_check_names and conclusion not in REQUIRED_SUCCESS_CONCLUSIONS:
            failures.append(f"required check did not pass: {name} ({conclusion or 'unknown'})")
        elif conclusion in FAILURE_CONCLUSIONS:
            failures.append(name)
        elif conclusion not in SUCCESS_CONCLUSIONS:
            pending.append(name)

    required_check_contract = validate_required_check_contract(required_checks, relevant_workflow_runs)
    missing_required_checks = required_check_contract["missing_required_checks"]
    invalid_required_checks = required_check_contract["invalid_required_checks"]
    failures.extend(
        f"required check label not emitted at exact head: {name}" for name in invalid_required_checks
    )
    pending.extend(
        f"required check not observed: {name}"
        for name in missing_required_checks
        if name not in invalid_required_checks
    )

    if failures:
        status = "failure"
    elif observed_count < min_checks:
        status = "pending"
        pending.append(f"observed {observed_count} checks, waiting for at least {min_checks}")
    elif pending:
        status = "pending"
    else:
        status = "success"

    return {
        "status": status,
        "sha": sha,
        "expected_head_sha": expected_head_sha,
        "head_matches_expected": not expected_head_sha or sha == expected_head_sha,
        "pr_state": pr.get("state"),
        "merged": pr.get("state") == "merged",
        "observed_count": observed_count,
        "failures": sorted(set(failures)),
        "pending": sorted(set(pending)),
        "missing_required_checks": missing_required_checks,
        "invalid_required_checks": invalid_required_checks,
        "check_context_settled": required_check_contract["check_context_settled"],
        "observed_check_names": required_check_contract["observed_check_names"],
        "checks": sorted(checks, key=lambda item: (item.get("type") or "", item.get("name") or "")),
    }


def build_summary(state: dict[str, Any]) -> str:
    """Render a compact Markdown summary for humans."""
    lines = [
        f"# PR {state['pr']} Watch",
        "",
        f"- Repo: `{state['repo']}`",
        f"- Status: `{state['status']}`",
        f"- SHA: `{state.get('sha', '')}`",
        f"- Expected SHA: `{state.get('expected_head_sha', '')}`",
        f"- Updated: {state['updated_at']}",
        f"- Deadline: {state['deadline_at']}",
        f"- Checks observed: {state.get('observed_count', 0)}",
        "",
    ]
    if state.get("failures"):
        lines.append("## Failures")
        lines.extend(f"- {name}" for name in state["failures"])
        lines.append("")
    if state.get("pending"):
        lines.append("## Pending")
        lines.extend(f"- {name}" for name in state["pending"])
        lines.append("")
    checks = state.get("checks") or []
    if checks:
        lines.append("## Checks")
        lines.append("")
        lines.append("| Type | Name | Status | Conclusion |")
        lines.append("| --- | --- | --- | --- |")
        for check in checks:
            lines.append(
                "| {type} | {name} | {status} | {conclusion} |".format(
                    type=check.get("type") or "",
                    name=str(check.get("name") or "").replace("|", "\\|"),
                    status=check.get("status") or "",
                    conclusion=check.get("conclusion") or "",
                )
            )
        lines.append("")
    return "\n".join(lines)


def write_state_files(output_dir: Path, pr_number: int, state: dict[str, Any]) -> None:
    """Write all watcher artifacts for one poll."""
    state_path = output_dir / f"pr-{pr_number}-watch-state.json"
    events_path = output_dir / f"pr-{pr_number}-watch-events.jsonl"
    summary_path = output_dir / f"pr-{pr_number}-watch-summary.md"
    atomic_write(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")
    append_jsonl(events_path, state)
    atomic_write(summary_path, build_summary(state))


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Quietly watch GitHub PR checks and write files.")
    parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    parser.add_argument("--output-dir", required=True, help="Folder for watcher artifacts")
    parser.add_argument("--timeout-minutes", type=float, required=True, help="Maximum watch timeframe")
    parser.add_argument("--interval-minutes", type=float, default=5.0, help="Minutes between polls")
    parser.add_argument("--repo", default="", help="GitHub repo as owner/name; inferred from cwd when omitted")
    parser.add_argument("--cwd", default="", help="Repository working directory for repo inference")
    parser.add_argument("--min-checks", type=int, default=1, help="Minimum observed checks before success is allowed")
    parser.add_argument(
        "--expected-head-sha",
        default="",
        help="Exact PR head SHA that must be observed before success is allowed",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        default=[],
        help="Exact check name that must appear before success; repeat for multiple checks",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the watcher loop."""
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    cwd = str(Path(args.cwd).expanduser().resolve()) if args.cwd else None
    interval_seconds = max(args.interval_minutes * 60.0, 1.0)
    started_at = dt.datetime.now(dt.timezone.utc)
    deadline = started_at + dt.timedelta(minutes=args.timeout_minutes)
    repo = args.repo or infer_repo(cwd)
    expected_head_seen = False
    previous_missing_required_checks: list[str] = []
    settled_missing_required_observations = 0

    while True:
        now = dt.datetime.now(dt.timezone.utc)
        base_state: dict[str, Any] = {
            "repo": repo,
            "pr": args.pr,
            "status": "pending",
            "started_at": started_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "updated_at": utc_now(),
            "deadline_at": deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "interval_minutes": args.interval_minutes,
            "timeout_minutes": args.timeout_minutes,
            "required_checks": sorted(set(args.required_check)),
        }

        try:
            command = command_from_environment()
            if not command:
                raise RuntimeError("GENOMES_GITHUB_BRIDGE_COMMAND must be configured")
            token = github_token_from_environment()
            pr = get_pr(command, repo, args.pr, token)
            sha = pr["headSha"]
            workflow_runs = get_workflow_runs(command, repo, pr["headBranch"], token)
            state = {
                **base_state,
                **summarize_checks(
                    pr,
                    workflow_runs,
                    args.min_checks,
                    expected_head_sha=args.expected_head_sha,
                    required_checks=args.required_check,
                    expected_head_seen=expected_head_seen,
                ),
            }
            (
                state,
                previous_missing_required_checks,
                settled_missing_required_observations,
            ) = apply_required_check_emission_grace(
                state,
                previous_missing_required_checks=previous_missing_required_checks,
                settled_missing_required_observations=settled_missing_required_observations,
            )
            if args.expected_head_sha and sha == args.expected_head_sha:
                expected_head_seen = True
        except Exception as exc:  # noqa: BLE001 - watcher must record all query failures quietly.
            state = {**base_state, "status": "error", "error": str(exc)}

        if now >= deadline and state["status"] == "pending":
            state = {**state, "status": "timeout", "updated_at": utc_now()}

        write_state_files(output_dir, args.pr, state)

        if state["status"] in {"success", "failure", "timeout", "error"}:
            return {"success": 0, "failure": 1, "timeout": 124, "error": 2}[state["status"]]

        sleep_seconds = min(interval_seconds, max((deadline - dt.datetime.now(dt.timezone.utc)).total_seconds(), 0))
        if sleep_seconds <= 0:
            continue
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130)
