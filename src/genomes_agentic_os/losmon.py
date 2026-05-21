"""LOSMon replacement validation scaffolding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .scaffold import create_automation, create_project, create_run_log, create_workflow, expand_path
from .workflow_ops import close_run_log


VALIDATION_WORKFLOWS = (
    ("engineering", "pr_review", "LOS PR review intake"),
    ("engineering", "failing_ci_triage", "LOS failing CI triage"),
    ("operations", "deploy_planning", "LOS deploy planning"),
)
VALIDATION_AUTOMATIONS = (("support", "thread_intake"),)


def latest_run_id(root: Path, domain: str, name: str) -> str:
    runs = sorted((root / domain / "06-runs-and-logs" / "runs").glob(f"*-{domain}-{name}"))
    if not runs:
        raise ValueError(f"run log was not created for {name}")
    return runs[-1].name


def comparison_report(repo: str | None) -> str:
    repo_line = repo or "Not linked yet."
    return f"""# LOSMon Replacement Validation

## Source

| Field | Value |
| --- | --- |
| Candidate Repo | {repo_line} |
| Mode | Read-only validation |

## Comparison Criteria

| Criterion | Agentic OS Evidence | LOSMon Still Better / Required | Gap |
| --- | --- | --- | --- |
| Time to route a request | Route/context commands can target project and workflows. | Existing losmon services already watch live inputs. | Need live connected-source watcher. |
| Context quality | Workflow specs and project source map are explicit files. | losmon has service-specific runtime context. | Need imported live source references. |
| Approval safety | Approval rules and run closeout gates are explicit. | losmon may have existing operational guardrails. | Need tenant/environment approval matrices. |
| Reconfiguration effort | Automation maturity is file-first. | losmon behavior may already be code-tested. | Need migration map from code paths to OS contracts. |
| Evidence quality | Run logs include summary, validation, and next action. | losmon logs may contain raw service telemetry. | Need telemetry-to-run-log adapter. |
| Failed-run recovery | Doctor reports stale run logs. | losmon service supervisors may retry automatically. | Need guarded retry policy. |
| Codex/Claude handoff | Shared AGENTS/CLAUDE surfaces point to the same workflow files. | losmon is service-centric, not agent-centric. | Need live handoff trials. |

## Next Implementation Gaps

- Add connected-source watchers before replacing any live losmon automation.
- Import losmon service context into source maps and workflow context packs.
- Define environment-specific approval gates for deploy and production triage.
- Build telemetry adapters before claiming parity with existing service monitoring.
"""


def losmon_validate(root: str | Path, repo: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    created = []
    create_project(os_root, "los", "losmon_replacement", repo=repo, status="active", lane="engineering")
    project_root = os_root / "los" / "02-projects" / "losmon_replacement"
    created.append(str(project_root))

    for lane, name, _title in VALIDATION_WORKFLOWS:
        create_workflow(os_root, "los", lane, name)
        created.append(str(os_root / "los" / "03-workflows" / lane / name))
    for lane, name in VALIDATION_AUTOMATIONS:
        create_automation(os_root, "los", lane, name)
        created.append(str(os_root / "los" / "04-automations" / lane / name))

    run_logs = []
    for lane, name, title in VALIDATION_WORKFLOWS:
        create_run_log(os_root, "los", name)
        run_id = latest_run_id(os_root, "los", name)
        result = close_run_log(
            os_root,
            "los",
            run_id,
            status="waiting",
            summary=f"Prepared read-only validation run for {title}.",
            validation=[f"Required workflow exists at los/03-workflows/{lane}/{name}/"],
            artifacts=[f"los/03-workflows/{lane}/{name}/", "los/02-projects/losmon_replacement/artifacts/losmon-comparison.md"],
            approvals=["No external write performed."],
            next_action="Run this workflow against a real read-only LOS task and paste evidence into the run log.",
            project="losmon_replacement",
        )
        run_logs.append(result["run_log"])

    artifact = project_root / "artifacts" / "losmon-comparison.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if not artifact.exists():
        artifact.write_text(comparison_report(repo), encoding="utf-8")

    status_path = project_root / "status.md"
    status_content = status_path.read_text(encoding="utf-8")
    marker = "## LOSMon Replacement Validation"
    if marker not in status_content:
        status_path.write_text(
            f"{status_content.rstrip()}\n\n{marker}\n\n- Three read-only validation workflows are scaffolded with run logs.\n- Next action: execute against real LOS inputs before replacing losmon automation.\n",
            encoding="utf-8",
        )

    return {
        "project": str(project_root),
        "created_or_verified": created,
        "run_logs": run_logs,
        "comparison": str(artifact),
    }


def format_losmon_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
