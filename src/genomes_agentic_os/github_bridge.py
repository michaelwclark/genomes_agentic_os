"""Versioned subprocess boundary for the TypeScript GitHub port.

The Agentic OS source package is Python while ``@genomes/github`` is an ESM
package.  This module deliberately makes that runtime boundary explicit rather
than pretending the TypeScript port can be imported by Python.  It speaks one
JSON request and response per process invocation; credentials are passed only
through the child environment and never appear in returned errors.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any


BRIDGE_VERSION = 1
# Provider revision reviewed with this first migration slice. Runtime selection
# remains explicit through GENOMES_GITHUB_BRIDGE_COMMAND; this pin makes the
# cross-repository contract auditable and forces later revisions through review.
REVIEWED_PLATFORM_BRIDGE_REVISION = "ef9fc7ef5f6c8ee0b88ef0d897f4c2be20823b20"


class GitHubBridgeError(RuntimeError):
    """A safe, structured failure returned by the GitHub bridge."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


BridgeRunner = Callable[..., subprocess.CompletedProcess[str]]


def command_from_environment(environ: Mapping[str, str] | None = None) -> list[str] | None:
    """Return the explicitly configured bridge command, never invoking a shell."""
    value = (environ or os.environ).get("GENOMES_GITHUB_BRIDGE_COMMAND", "").strip()
    return shlex.split(value) if value else None


def call_github_bridge(
    command: Sequence[str],
    request: Mapping[str, Any],
    *,
    token: str,
    runner: BridgeRunner = subprocess.run,
    timeout: float = 30,
) -> dict[str, Any]:
    """Call one bridge operation and return its versioned result.

    ``command`` is an argv sequence, not shell text.  The token is supplied to
    the child only as ``GITHUB_TOKEN`` and no child stderr is propagated into a
    raised error, avoiding accidental credential disclosure.
    """
    if not command:
        raise GitHubBridgeError("BRIDGE_UNCONFIGURED", "GitHub bridge command is not configured")
    payload = {"version": BRIDGE_VERSION, **dict(request)}
    child_env = dict(os.environ)
    child_env["GITHUB_TOKEN"] = token
    try:
        completed = runner(
            list(command),
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=child_env,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubBridgeError("BRIDGE_UNAVAILABLE", "GitHub bridge could not be executed") from exc

    if completed.returncode != 0:
        raise GitHubBridgeError("BRIDGE_FAILED", "GitHub bridge exited unsuccessfully")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubBridgeError("BRIDGE_INVALID_RESPONSE", "GitHub bridge returned invalid JSON") from exc
    if not isinstance(response, dict) or response.get("version") != BRIDGE_VERSION:
        raise GitHubBridgeError("BRIDGE_INVALID_RESPONSE", "GitHub bridge returned an unsupported response")
    if response.get("ok") is not True:
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        code = str(error.get("code") or "BRIDGE_OPERATION_FAILED")
        raise GitHubBridgeError(code, "GitHub bridge operation failed")
    result = response.get("result")
    if not isinstance(result, dict):
        raise GitHubBridgeError("BRIDGE_INVALID_RESPONSE", "GitHub bridge result must be an object")
    return result


def list_pull_requests(
    command: Sequence[str],
    *,
    owner: str,
    repo: str,
    token: str,
    state: str = "all",
    limit: int = 30,
    runner: BridgeRunner = subprocess.run,
) -> list[dict[str, Any]]:
    """Return JSON-safe pull request summaries from the shared GitHub port."""
    result = call_github_bridge(
        command,
        {
            "operation": "listPullRequests",
            "repo": {"owner": owner, "repo": repo},
            "filter": {"state": state, "limit": limit},
        },
        token=token,
        runner=runner,
    )
    pull_requests = result.get("pullRequests")
    if not isinstance(pull_requests, list) or not all(isinstance(item, dict) for item in pull_requests):
        raise GitHubBridgeError("BRIDGE_INVALID_RESPONSE", "GitHub bridge returned invalid pull requests")
    return [dict(item) for item in pull_requests]


def list_issues(
    command: Sequence[str],
    *,
    owner: str,
    repo: str,
    token: str,
    state: str = "all",
    since: str | None = None,
    limit: int = 30,
    runner: BridgeRunner = subprocess.run,
) -> list[dict[str, Any]]:
    """Return JSON-safe issue summaries from the shared GitHub port."""
    issue_filter: dict[str, Any] = {"state": state, "limit": limit}
    if since is not None:
        issue_filter["since"] = since
    result = call_github_bridge(
        command,
        {
            "operation": "listIssues",
            "repo": {"owner": owner, "repo": repo},
            "filter": issue_filter,
        },
        token=token,
        runner=runner,
    )
    issues = result.get("issues")
    if not isinstance(issues, list) or not all(isinstance(item, dict) for item in issues):
        raise GitHubBridgeError("BRIDGE_INVALID_RESPONSE", "GitHub bridge returned invalid issues")
    return [dict(item) for item in issues]


def get_pull_request(
    command: Sequence[str],
    *,
    owner: str,
    repo: str,
    number: int,
    token: str,
    runner: BridgeRunner = subprocess.run,
) -> dict[str, Any] | None:
    """Return one JSON-safe pull request summary from the shared GitHub port."""
    result = call_github_bridge(
        command,
        {
            "operation": "getPullRequest",
            "repo": {"owner": owner, "repo": repo},
            "number": number,
        },
        token=token,
        runner=runner,
    )
    pull_request = result.get("pullRequest")
    if pull_request is None:
        return None
    if not isinstance(pull_request, dict):
        raise GitHubBridgeError(
            "BRIDGE_INVALID_RESPONSE",
            "GitHub bridge returned an invalid pull request",
        )
    return dict(pull_request)


def list_workflow_runs(
    command: Sequence[str],
    *,
    owner: str,
    repo: str,
    token: str,
    branch: str | None = None,
    limit: int = 100,
    runner: BridgeRunner = subprocess.run,
) -> list[dict[str, Any]]:
    """Return JSON-safe workflow runs from the shared GitHub port."""
    workflow_filter: dict[str, Any] = {"limit": limit}
    if branch is not None:
        workflow_filter["branch"] = branch
    result = call_github_bridge(
        command,
        {
            "operation": "listWorkflowRuns",
            "repo": {"owner": owner, "repo": repo},
            "filter": workflow_filter,
        },
        token=token,
        runner=runner,
    )
    workflow_runs = result.get("workflowRuns")
    if not isinstance(workflow_runs, list) or not all(
        isinstance(item, dict) for item in workflow_runs
    ):
        raise GitHubBridgeError(
            "BRIDGE_INVALID_RESPONSE",
            "GitHub bridge returned invalid workflow runs",
        )
    return [dict(item) for item in workflow_runs]
