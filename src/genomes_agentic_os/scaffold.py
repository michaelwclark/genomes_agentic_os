"""Filesystem scaffolding for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil


BASE_FOLDERS = (
    "domains",
    "workflows",
    "automations",
    "inbox",
    "runs",
    "context",
    "memory",
    "notion",
    "config",
    "templates",
)

DOMAIN_CONTEXT_FILES = (
    "business.md",
    "systems.md",
    "stakeholders.md",
    "access-policy.md",
)

NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)

    def extend(self, other: "ScaffoldResult") -> None:
        self.created.extend(other.created)
        self.skipped.extend(other.skipped)
        self.updated.extend(other.updated)

    def messages(self) -> list[str]:
        lines: list[str] = []
        for label, paths in (
            ("created", self.created),
            ("updated", self.updated),
        ):
            for path in paths:
                lines.append(f"{label}: {path}")
        return lines


def expand_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def validate_name(value: str, label: str = "name") -> str:
    if not NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must use lowercase letters, numbers, and underscores only: {value!r}")
    return value


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def template_source_dir() -> Path:
    candidate = repo_root() / "templates"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository templates directory")


def ensure_dir(path: Path, result: ScaffoldResult) -> None:
    if path.is_dir():
        result.skipped.append(path)
        return
    path.mkdir(parents=True, exist_ok=True)
    result.created.append(path)


def write_file_once(path: Path, content: str, result: ScaffoldResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(path)


def copy_file_once(source: Path, destination: Path, result: ScaffoldResult) -> None:
    if destination.exists():
        result.skipped.append(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def copy_tree_missing(source: Path, destination: Path) -> ScaffoldResult:
    result = ScaffoldResult()
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            ensure_dir(target, result)
        else:
            copy_file_once(item, target, result)
    return result


def init_os(target: str | Path) -> ScaffoldResult:
    root = expand_path(target)
    result = ScaffoldResult()
    for folder in BASE_FOLDERS:
        ensure_dir(root / folder, result)
    result.extend(copy_tree_missing(template_source_dir(), root / "templates"))
    return result


def titleize_name(name: str) -> str:
    return name.replace("_", " ").title()


def domain_config(domain: str) -> str:
    return f"""id: {domain}
name: {titleize_name(domain)}
owner: OS Owner
status: active

purpose: >
  Describe the operating boundary this domain owns.

lanes:
  - engineering
  - support
  - operations

source_systems:
  - name: Notion
    role: control_plane
    url: ""
  - name: GitHub
    role: code_and_prs
    url: ""

approval_policy:
  external_writes_require_approval: true
  customer_visible_output_requires_approval: true
  production_changes_require_approval: true

notion:
  os_home_page_id: ""
  inbox_database_id: ""
  work_items_database_id: ""
  runs_database_id: ""
  approvals_database_id: ""

storage:
  active_state: filesystem
  artifacts: filesystem
  cockpit: notion
  memory: agent_memory
"""


def create_domain(root: str | Path, domain: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    os_root = expand_path(root)
    result = init_os(os_root)
    domain_root = os_root / "domains" / domain
    for folder in ("context", "workflows", "automations", "decisions", "notion"):
        ensure_dir(domain_root / folder, result)
    write_file_once(domain_root / "domain.yml", domain_config(domain), result)
    readme_template = template_source_dir() / "domain" / "README.md"
    readme = readme_template.read_text(encoding="utf-8").replace("Domain Template", titleize_name(domain))
    write_file_once(domain_root / "README.md", readme, result)
    for filename in DOMAIN_CONTEXT_FILES:
        heading = filename.removesuffix(".md").replace("-", " ").title()
        write_file_once(domain_root / "context" / filename, f"# {heading}\n\n", result)
    return result


def render_template(content: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        content = content.replace(key, value)
    return content


def create_workflow(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    lane = validate_name(lane, "lane")
    name = validate_name(name, "workflow")
    result = create_domain(root, domain)
    template = template_source_dir() / "workflow" / "workflow.md"
    content = render_template(
        template.read_text(encoding="utf-8"),
        {
            "<workflow_name>": name,
            "<domain>": domain,
            "<lane>": lane,
            "<owner>": "OS Owner",
            "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
        },
    )
    destination = expand_path(root) / "domains" / domain / "workflows" / lane / f"{name}.md"
    write_file_once(destination, content, result)
    return result


def create_automation(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    lane = validate_name(lane, "lane")
    name = validate_name(name, "automation")
    result = create_domain(root, domain)
    template = template_source_dir() / "automation" / "automation.md"
    content = render_template(
        template.read_text(encoding="utf-8"),
        {
            "<automation_name>": name,
            "<domain>": domain,
            "<lane>": lane,
            "<owner>": "OS Owner",
            "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
        },
    )
    destination = expand_path(root) / "domains" / domain / "automations" / lane / f"{name}.md"
    write_file_once(destination, content, result)
    return result


def unique_run_log_path(runs_dir: Path, run_id: str) -> Path:
    candidate = runs_dir / f"{run_id}.md"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = runs_dir / f"{run_id}-{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def create_run_log(root: str | Path, domain: str, workflow_or_automation: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    workflow_or_automation = validate_name(workflow_or_automation, "workflow_or_automation")
    result = init_os(root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{domain}-{workflow_or_automation}"
    iso_timestamp = datetime.now(timezone.utc).isoformat()
    template = template_source_dir() / "workflow" / "run-log.md"
    content = render_template(
        template.read_text(encoding="utf-8"),
        {
            "<run_id>": run_id,
            "<domain>": domain,
            "<name>": workflow_or_automation,
            "<codex_or_claude_or_automation>": "codex",
            "<timestamp>": iso_timestamp,
            "<done_waiting_failed_needs_approval>": "running",
        },
    )
    destination = unique_run_log_path(expand_path(root) / "runs", run_id)
    write_file_once(destination, content, result)
    return result
