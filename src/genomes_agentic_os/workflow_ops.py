"""Workflow readiness and run closeout operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .scaffold import WORKFLOW_FILES, domain_path, expand_path, normalize_domain, validate_name


CLOSE_STATUSES = ("done", "waiting", "failed", "needs_approval")
SECTION_REQUIREMENTS = {
    "workflow.md": ("Invocation Contract",),
    "outcome-brief.md": ("Definition Of Done", "Acceptance Criteria"),
    "alignment-questions.md": ("Required Questions", "Dispatch Decision"),
    "context-pack.md": ("Source Links", "Operating Constraints"),
    "approval-rules.md": ("Approval Matrix",),
    "output-contract.md": ("Required Outputs",),
    "runbook.md": ("Before Running", "During The Run", "After Running"),
}
PLACEHOLDER_MARKERS = ("<", ">", "yes | no", "draft | ready", "`yes | no`")


@dataclass
class WorkflowFinding:
    severity: str
    path: Path
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": str(self.path), "message": self.message}


def section_body(content: str, heading: str) -> str:
    marker = f"## {heading}"
    start = content.find(marker)
    if start == -1:
        return ""
    after = content[start + len(marker) :]
    next_heading = after.find("\n## ")
    body = after if next_heading == -1 else after[:next_heading]
    return body.strip()


def meaningful_lines(body: str) -> list[str]:
    ignored_prefixes = ("| ---",)
    ignored_lines = {"-", "1.", "|  |  |", "|  |  |  |", "|  |  |  |  |", "|  |  |  |  |  |"}
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ignored_lines or stripped.startswith(ignored_prefixes):
            continue
        if stripped.startswith("|") and not stripped.replace("|", "").strip():
            continue
        lines.append(stripped)
    return lines


def is_empty_section(content: str, heading: str) -> bool:
    body = section_body(content, heading)
    if not body:
        return True
    return not meaningful_lines(body)


def has_placeholders(content: str, heading: str) -> bool:
    body = section_body(content, heading)
    lines = meaningful_lines(body)
    return any(any(marker in line for marker in PLACEHOLDER_MARKERS) for line in lines)


def workflow_root(root: str | Path, domain: str, lane: str, workflow: str) -> Path:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    workflow = validate_name(workflow, "workflow")
    return domain_path(root, domain) / "03-workflows" / lane / workflow


def check_workflow(root: str | Path, domain: str, lane: str, workflow: str) -> list[WorkflowFinding]:
    root_path = workflow_root(root, domain, lane, workflow)
    findings: list[WorkflowFinding] = []
    if not root_path.is_dir():
        return [WorkflowFinding("blocker", root_path, "workflow folder is missing")]

    for filename in WORKFLOW_FILES:
        path = root_path / filename
        if not path.is_file():
            findings.append(WorkflowFinding("blocker", path, "required workflow file is missing"))

    for filename, headings in SECTION_REQUIREMENTS.items():
        path = root_path / filename
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        for heading in headings:
            if f"## {heading}" not in content:
                findings.append(WorkflowFinding("blocker", path, f"missing required section: {heading}"))
            elif is_empty_section(content, heading):
                findings.append(WorkflowFinding("fix-soon", path, f"section needs content: {heading}"))
            elif has_placeholders(content, heading):
                findings.append(WorkflowFinding("fix-soon", path, f"section has unresolved placeholders: {heading}"))

    for path in (root_path / "examples" / "README.md", root_path / "runs" / "README.md"):
        if not path.is_file():
            findings.append(WorkflowFinding("cleanup", path, "supporting workflow README is missing"))

    if not findings:
        findings.append(WorkflowFinding("observation", root_path, "workflow has the required readiness files and sections"))
    return findings


def format_findings(findings: list[WorkflowFinding]) -> str:
    return yaml.safe_dump({"findings": [finding.as_dict() for finding in findings]}, sort_keys=False).strip()


def read_run_field(content: str, field: str) -> str:
    prefix = f"| {field} |"
    for line in content.splitlines():
        if line.startswith(prefix):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2:
                return cells[1]
    return ""


def update_run_field(content: str, field: str, value: str) -> str:
    prefix = f"| {field} |"
    lines = []
    changed = False
    for line in content.splitlines():
        if line.startswith(prefix):
            lines.append(f"| {field} | `{value}` |")
            changed = True
        else:
            lines.append(line)
    if not changed:
        return content
    suffix = "\n" if content.endswith("\n") else ""
    return "\n".join(lines) + suffix


def find_run(root: Path, domain: str, run_id: str) -> Path:
    runs_root = domain_path(root, domain) / "06-runs-and-logs" / "runs"
    candidate = runs_root / run_id / "run-log.md"
    if candidate.is_file():
        return candidate
    matches = sorted(runs_root.glob(f"*{run_id}*/run-log.md"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"run id is ambiguous: {run_id}")
    raise ValueError(f"run log not found: {run_id}")


def append_activity_log(root: Path, domain: str, status: str, run_id: str, next_action: str) -> None:
    log_path = domain_path(root, domain) / "06-runs-and-logs" / "activity-log.md"
    row = (
        f"| {datetime.now(timezone.utc).date().isoformat()} | agentic-os | close run `{run_id}` | "
        f"`{status}` | {next_action or ''} |\n"
    )
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    if row not in existing:
        log_path.write_text(f"{existing}{'' if existing.endswith(chr(10)) else chr(10)}{row}", encoding="utf-8")


def append_workflow_progress(root: Path, domain: str, workflow: str, status: str, run_id: str, next_action: str) -> None:
    matches = sorted((domain_path(root, domain) / "03-workflows").glob(f"*/{workflow}/progress.md"))
    if len(matches) != 1:
        return
    row = (
        f"| {datetime.now(timezone.utc).date().isoformat()} | agentic-os | "
        f"Run `{run_id}` closed as `{status}`. Next: {next_action or ''} | `06-runs-and-logs/runs/{run_id}/` |\n"
    )
    content = matches[0].read_text(encoding="utf-8")
    if row not in content:
        matches[0].write_text(f"{content}{'' if content.endswith(chr(10)) else chr(10)}{row}", encoding="utf-8")


def append_project_status(root: Path, domain: str, project: str | None, status: str, run_id: str, next_action: str) -> None:
    if not project:
        return
    project = validate_name(project, "project")
    status_path = domain_path(root, domain) / "02-projects" / project / "status.md"
    if not status_path.is_file():
        return
    row = (
        f"\n## Run Closeout {run_id}\n\n"
        f"- Status: `{status}`\n"
        f"- Next action: {next_action or ''}\n"
    )
    content = status_path.read_text(encoding="utf-8")
    if row not in content:
        status_path.write_text(f"{content}{row}", encoding="utf-8")


def close_run_log(
    root: str | Path,
    domain: str,
    run_id: str,
    *,
    status: str,
    summary: str = "",
    validation: list[str] | None = None,
    artifacts: list[str] | None = None,
    approvals: list[str] | None = None,
    next_action: str = "",
    owner: str = "OS Owner",
    learning: str = "",
    project: str | None = None,
) -> dict[str, Any]:
    if status not in CLOSE_STATUSES:
        raise ValueError(f"status must be one of {', '.join(CLOSE_STATUSES)}: {status!r}")
    validation = validation or []
    artifacts = artifacts or []
    approvals = approvals or []
    if status == "done" and not validation:
        raise ValueError("cannot close a run as done without validation evidence")

    os_root = expand_path(root)
    domain = normalize_domain(domain)
    run_path = find_run(os_root, domain, run_id)
    content = run_path.read_text(encoding="utf-8")
    workflow_or_automation = read_run_field(content, "Workflow Or Automation")
    completed_at = datetime.now(timezone.utc).isoformat()
    closeout = f"""

## Closeout

| Field | Value |
| --- | --- |
| Final Status | `{status}` |
| Completed At | `{completed_at}` |
| Owner | `{owner}` |

## Closeout Summary

{summary or '-'}

## Closeout Validation

{chr(10).join(f'- {item}' for item in validation) or '-'}

## Closeout Artifacts

{chr(10).join(f'- {item}' for item in artifacts) or '-'}

## Approval Gates Encountered

{chr(10).join(f'- {item}' for item in approvals) or '-'}

## Next Action

{next_action or '-'}

## Learning Promotion

{learning or 'Not promoted.'}
"""
    content = update_run_field(content, "Status", status)
    content = update_run_field(content, "Completed At", completed_at)
    if "## Closeout" in content:
        raise ValueError(f"run log is already closed: {run_path.parent.name}")
    run_path.write_text(f"{content.rstrip()}{closeout}\n", encoding="utf-8")

    append_activity_log(os_root, domain, status, run_path.parent.name, next_action)
    if workflow_or_automation:
        append_workflow_progress(os_root, domain, workflow_or_automation, status, run_path.parent.name, next_action)
    append_project_status(os_root, domain, project, status, run_path.parent.name, next_action)

    return {
        "run_log": str(run_path),
        "status": status,
        "workflow_or_automation": workflow_or_automation,
        "activity_log": str(domain_path(os_root, domain) / "06-runs-and-logs" / "activity-log.md"),
    }
