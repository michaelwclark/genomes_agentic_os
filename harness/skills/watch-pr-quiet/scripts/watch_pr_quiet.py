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
from pathlib import Path
from typing import Any


SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
FAILURE_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
SUCCESS_STATUS_STATES = {"success"}
FAILURE_STATUS_STATES = {"error", "failure"}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_gh(args: list[str], cwd: str | None = None) -> Any:
    """Run gh and parse JSON output without printing subprocess output."""
    result = subprocess.run(
        ["gh", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh exited with {result.returncode}")
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def infer_repo(cwd: str | None) -> str:
    """Infer owner/name from the current GitHub repository."""
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "could not infer repo; pass --repo owner/name")
    return result.stdout.strip()


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


def get_pr(repo: str, pr_number: int, cwd: str | None) -> dict[str, Any]:
    """Fetch the PR metadata needed for check polling."""
    return run_gh(
        [
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{repo}/pulls/{pr_number}",
        ],
        cwd=cwd,
    )


def get_check_runs(repo: str, sha: str, cwd: str | None) -> list[dict[str, Any]]:
    """Fetch latest GitHub check runs for a commit."""
    data = run_gh(
        [
            "api",
            "--method",
            "GET",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{repo}/commits/{sha}/check-runs",
            "-f",
            "per_page=100",
            "-f",
            "filter=latest",
        ],
        cwd=cwd,
    )
    return data.get("check_runs", [])


def get_status_contexts(repo: str, sha: str, cwd: str | None) -> list[dict[str, Any]]:
    """Fetch legacy commit status contexts for a commit."""
    data = run_gh(
        [
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{repo}/commits/{sha}/status",
        ],
        cwd=cwd,
    )
    return data.get("statuses", [])


def summarize_checks(
    pr: dict[str, Any],
    check_runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
    min_checks: int,
) -> dict[str, Any]:
    """Classify the current PR check state."""
    sha = pr["head"]["sha"]
    observed_count = len(check_runs) + len(statuses)
    checks: list[dict[str, str | None]] = []
    failures: list[str] = []
    pending: list[str] = []

    if pr.get("state") == "closed" and not pr.get("merged"):
        failures.append("PR is closed without merge")

    for run in check_runs:
        name = run.get("name") or run.get("app", {}).get("name") or "unnamed check"
        status = run.get("status")
        conclusion = run.get("conclusion")
        checks.append({"type": "check_run", "name": name, "status": status, "conclusion": conclusion})
        if status != "completed":
            pending.append(name)
        elif conclusion in FAILURE_CONCLUSIONS:
            failures.append(name)
        elif conclusion not in SUCCESS_CONCLUSIONS:
            pending.append(name)

    for context in statuses:
        name = context.get("context") or "unnamed status"
        state = context.get("state")
        checks.append({"type": "status", "name": name, "status": state, "conclusion": state})
        if state in FAILURE_STATUS_STATES:
            failures.append(name)
        elif state not in SUCCESS_STATUS_STATES:
            pending.append(name)

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
        "pr_state": pr.get("state"),
        "merged": bool(pr.get("merged")),
        "observed_count": observed_count,
        "failures": sorted(set(failures)),
        "pending": sorted(set(pending)),
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
    parser.add_argument("--cwd", default="", help="Repository working directory for gh auth/context")
    parser.add_argument("--min-checks", type=int, default=1, help="Minimum observed checks before success is allowed")
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
        }

        try:
            pr = get_pr(repo, args.pr, cwd)
            sha = pr["head"]["sha"]
            check_runs = get_check_runs(repo, sha, cwd)
            statuses = get_status_contexts(repo, sha, cwd)
            state = {**base_state, **summarize_checks(pr, check_runs, statuses, args.min_checks)}
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
