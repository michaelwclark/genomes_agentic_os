"""Automation maturity and attachment operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .scaffold import AUTOMATION_FILES, append_once, expand_path, normalize_domain, validate_name


AUTOMATION_MATURITY_LEVELS = ("observe", "prepare", "propose", "execute_approved", "execute_guarded")
SAFE_START_LEVELS = ("observe", "prepare")
SECTION_REQUIREMENTS = {
    "automation.md": (
        "Metadata",
        "Trigger",
        "Idempotency",
        "Permissions",
        "Outputs",
        "Audit Requirements",
    ),
    "inputs.md": ("| Input | Required | Source | Validation |",),
    "outputs.md": ("| Output | Destination | Required | Notes |",),
    "permissions.md": ("Automation Level", "Permission Record", "Ask-Before-Acting Rules"),
    "failure-modes.md": ("Failure Table",),
    "runbook.md": ("Start", "Operate", "Recover"),
    "tests.md": ("Dry Run", "Failure Tests"),
}


@dataclass
class AutomationFinding:
    severity: str
    path: Path
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": str(self.path), "message": self.message}


def automation_root(root: str | Path, domain: str, lane: str, automation: str) -> Path:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    automation = validate_name(automation, "automation")
    return expand_path(root) / domain / "04-automations" / lane / automation


def section_body(content: str, heading: str) -> str:
    marker = f"## {heading}"
    start = content.find(marker)
    if start == -1:
        return ""
    after = content[start + len(marker) :]
    next_heading = after.find("\n## ")
    body = after if next_heading == -1 else after[:next_heading]
    return body.strip()


def section_has_content(content: str, heading: str) -> bool:
    body = section_body(content, heading)
    if not body:
        return False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and stripped not in {"-", "1.", "|  |  |  |", "|  |  |  |  |"}:
            return True
    return False


def read_table_field(content: str, field: str) -> str:
    prefix = f"| {field} |"
    for line in content.splitlines():
        if line.startswith(prefix):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2:
                return cells[1]
    return ""


def update_table_field(content: str, field: str, value: str) -> str:
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


def bullet_value(content: str, label: str) -> str:
    prefix = f"- {label}:"
    for line in content.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("`")
    return ""


def check_required_evidence(path: Path, content: str) -> list[AutomationFinding]:
    checks = {
        "trigger source": bullet_value(content, "Source"),
        "trigger frequency": bullet_value(content, "Frequency"),
        "idempotency key": bullet_value(content, "Key"),
        "duplicate handling": bullet_value(content, "Duplicate handling"),
        "read permissions": bullet_value(content, "Read"),
        "write permissions": bullet_value(content, "Write"),
        "approval gates": bullet_value(content, "Requires approval"),
        "default pre-approval action": bullet_value(content, "Default action before approval"),
    }
    findings = []
    for label, value in checks.items():
        if not value:
            findings.append(AutomationFinding("blocker", path, f"missing required evidence: {label}"))
    if not section_has_content(content, "Outputs"):
        findings.append(AutomationFinding("blocker", path, "missing required evidence: outputs"))
    return findings


def current_maturity(automation_md: Path) -> str:
    content = automation_md.read_text(encoding="utf-8")
    level = read_table_field(content, "Level") or "observe"
    if level not in AUTOMATION_MATURITY_LEVELS:
        raise ValueError(f"unknown automation maturity level in {automation_md}: {level!r}")
    return level


def check_automation(root: str | Path, domain: str, lane: str, automation: str) -> dict[str, Any]:
    root_path = automation_root(root, domain, lane, automation)
    findings: list[AutomationFinding] = []
    if not root_path.is_dir():
        return {"automation": str(root_path), "level": "", "findings": [AutomationFinding("blocker", root_path, "automation folder is missing").as_dict()]}

    for filename in AUTOMATION_FILES:
        path = root_path / filename
        if not path.is_file():
            findings.append(AutomationFinding("blocker", path, "required automation file is missing"))
    logs_readme = root_path / "logs" / "README.md"
    if not logs_readme.is_file():
        findings.append(AutomationFinding("blocker", logs_readme, "run evidence folder README is missing"))

    for filename, markers in SECTION_REQUIREMENTS.items():
        path = root_path / filename
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker.startswith("|"):
                if marker not in content:
                    findings.append(AutomationFinding("blocker", path, f"missing required table: {marker}"))
            elif f"## {marker}" not in content:
                findings.append(AutomationFinding("blocker", path, f"missing required section: {marker}"))
            elif marker in {"Trigger", "Idempotency", "Permissions", "Outputs"} and not section_has_content(content, marker):
                findings.append(AutomationFinding("fix-soon", path, f"section needs content: {marker}"))

    automation_md = root_path / "automation.md"
    level = ""
    if automation_md.is_file():
        content = automation_md.read_text(encoding="utf-8")
        level = read_table_field(content, "Level") or "observe"
        if level not in AUTOMATION_MATURITY_LEVELS:
            findings.append(AutomationFinding("blocker", automation_md, f"unknown maturity level: {level}"))
        if level not in SAFE_START_LEVELS:
            findings.append(AutomationFinding("observation", automation_md, f"automation is configured for `{level}`"))
        findings.extend(check_required_evidence(automation_md, content))

    if not findings:
        findings.append(AutomationFinding("observation", root_path, "automation contract has required maturity evidence"))
    return {"automation": str(root_path), "level": level, "findings": [finding.as_dict() for finding in findings]}


def format_automation_check(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


def blockers_for(result: dict[str, Any]) -> list[dict[str, str]]:
    return [finding for finding in result["findings"] if finding["severity"] == "blocker"]


def set_automation_maturity(root: str | Path, domain: str, lane: str, automation: str, level: str) -> dict[str, Any]:
    if level not in AUTOMATION_MATURITY_LEVELS:
        raise ValueError(f"level must be one of {', '.join(AUTOMATION_MATURITY_LEVELS)}: {level!r}")
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    automation = validate_name(automation, "automation")
    root_path = automation_root(os_root, domain, lane, automation)
    automation_md = root_path / "automation.md"
    if not automation_md.is_file():
        raise ValueError(f"automation metadata file is missing: {automation_md}")

    old_level = current_maturity(automation_md)
    if AUTOMATION_MATURITY_LEVELS.index(level) > AUTOMATION_MATURITY_LEVELS.index(old_level) and level not in SAFE_START_LEVELS:
        blockers = blockers_for(check_automation(os_root, domain, lane, automation))
        if blockers:
            first = blockers[0]
            raise ValueError(f"cannot advance automation to {level}; unresolved blocker: {first['message']}")

    content = automation_md.read_text(encoding="utf-8")
    updated = update_table_field(content, "Level", level)
    if updated == content:
        updated = f"{content.rstrip()}\n\n## Maturity\n\n| Field | Value |\n| --- | --- |\n| Level | `{level}` |\n"
    automation_md.write_text(updated, encoding="utf-8")

    decision_path = os_root / domain / "00-control-plane" / "decisions.md"
    date = datetime.now(timezone.utc).date().isoformat()
    append_once(
        decision_path,
        (
            f"| {date} | Automation `{automation}` maturity changed from `{old_level}` to `{level}` | "
            f"File-first reconfiguration | Execution level is now `{level}` | "
            f"`04-automations/{lane}/{automation}/automation.md` |\n"
        ),
        _Result(),
    )
    return {
        "automation": str(root_path),
        "old_level": old_level,
        "new_level": level,
        "decision_log": str(decision_path),
    }


def attach_automation(root: str | Path, domain: str, lane: str, automation: str, project: str) -> dict[str, Any]:
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    automation = validate_name(automation, "automation")
    project = validate_name(project, "project")
    root_path = automation_root(os_root, domain, lane, automation)
    if not root_path.is_dir():
        raise ValueError(f"automation folder is missing: {root_path}")
    project_root = os_root / domain / "02-projects" / project
    if not project_root.is_dir():
        raise ValueError(f"project folder is missing: {project_root}")

    automation_link = f"`04-automations/{lane}/{automation}/`"
    project_status = project_root / "status.md"
    append_once(
        project_status,
        "\n## Automation Attachments\n\n| Automation | Lane | Maturity | Link |\n| --- | --- | --- | --- |\n",
        _Result(),
    )
    level = current_maturity(root_path / "automation.md") if (root_path / "automation.md").is_file() else "observe"
    append_once(project_status, f"| `{automation}` | `{lane}` | `{level}` | {automation_link} |\n", _Result())

    source_map = project_root / "source-map.md"
    append_once(
        source_map,
        f"| Automation | 04-automations/{lane}/{automation}/ | Operating contract and run evidence | Level `{level}` |\n",
        _Result(),
    )

    automation_md = root_path / "automation.md"
    append_once(
        automation_md,
        "\n## Project Attachments\n\n| Project | Link |\n| --- | --- |\n",
        _Result(),
    )
    append_once(automation_md, f"| `{project}` | `02-projects/{project}/` |\n", _Result())

    return {
        "automation": str(root_path),
        "project": str(project_root),
        "project_status": str(project_status),
        "source_map": str(source_map),
    }


@dataclass
class _Result:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
