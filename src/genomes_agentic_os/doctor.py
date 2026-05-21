"""Health checks and additive repairs for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .automation_ops import check_automation
from .customer import customer_update
from .scaffold import expand_path, init_os, install_docs
from .validate import validate_root
from .workflow_ops import check_workflow


@dataclass
class DoctorFinding:
    severity: str
    path: Path
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": str(self.path), "message": self.message}


def table_field(content: str, field: str) -> str:
    prefix = f"| {field} |"
    for line in content.splitlines():
        if line.startswith(prefix):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2:
                return cells[1]
    return ""


def managed_repair(root: Path) -> list[str]:
    if (root / "customer.yml").is_file():
        data = yaml.safe_load((root / "customer.yml").read_text(encoding="utf-8")) or {}
        slug = (data.get("customer") or {}).get("slug")
        if not slug:
            raise ValueError("customer.yml is missing customer.slug")
        customer_update(str(slug), root)
        return ["customer update"]
    init_os(root)
    install_docs(root)
    return ["init os", "install docs"]


def workflow_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    for workflow in sorted(root.glob("*/03-workflows/*/*/workflow.md")):
        domain = workflow.parents[3].name
        lane = workflow.parent.parent.name
        name = workflow.parent.name
        for finding in check_workflow(root, domain, lane, name):
            if finding.severity != "observation":
                findings.append(DoctorFinding(finding.severity, finding.path, f"workflow `{name}`: {finding.message}"))
    return findings


def automation_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    for automation in sorted(root.glob("*/04-automations/*/*/automation.md")):
        domain = automation.parents[3].name
        lane = automation.parent.parent.name
        name = automation.parent.name
        result = check_automation(root, domain, lane, name)
        for item in result["findings"]:
            if item["severity"] != "observation":
                findings.append(DoctorFinding(item["severity"], Path(item["path"]), f"automation `{name}`: {item['message']}"))
    return findings


def active_work_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    for active_work in sorted(root.glob("*/00-control-plane/active-work.md")):
        for line in active_work.read_text(encoding="utf-8").splitlines():
            if line.startswith("| `") and ("Define next action" in line or "|  |" in line):
                findings.append(DoctorFinding("fix-soon", active_work, "active work row is missing a concrete next action"))
    return findings


def project_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    for project_dir in sorted(root.glob("*/02-projects/*")):
        if not project_dir.is_dir():
            continue
        for filename in ("project.yml", "status.md", "source-map.md"):
            path = project_dir / filename
            if not path.is_file():
                findings.append(DoctorFinding("blocker", path, f"project `{project_dir.name}` is missing {filename}"))
    return findings


def run_log_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    for run_log in sorted(root.glob("*/06-runs-and-logs/runs/*/run-log.md")):
        content = run_log.read_text(encoding="utf-8")
        status = table_field(content, "Status")
        if status in {"", "running", "draft"} and "## Closeout" not in content:
            findings.append(DoctorFinding("fix-soon", run_log, "run log has no final status or closeout"))
    return findings


def doctor(root: str | Path, *, fix_missing: bool = False) -> dict[str, Any]:
    os_root = expand_path(root)
    repairs = managed_repair(os_root) if fix_missing else []
    validation = validate_root(os_root)
    findings: list[DoctorFinding] = []
    findings.extend(DoctorFinding("blocker", os_root, message) for message in validation.errors)
    findings.extend(DoctorFinding("cleanup", os_root, message) for message in validation.warnings)
    if validation.ok:
        findings.append(DoctorFinding("observation", os_root, "required files and folders are present"))
    findings.extend(active_work_findings(os_root))
    findings.extend(project_findings(os_root))
    findings.extend(workflow_findings(os_root))
    findings.extend(automation_findings(os_root))
    findings.extend(run_log_findings(os_root))
    if repairs:
        findings.append(DoctorFinding("observation", os_root, f"additive repair executed: {', '.join(repairs)}"))
    return {"root": str(os_root), "ok": not any(f.severity == "blocker" for f in findings), "repairs": repairs, "findings": [f.as_dict() for f in findings]}


def format_doctor_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
