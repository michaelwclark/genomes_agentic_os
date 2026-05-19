"""Filesystem scaffolding for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil


DEFAULT_DOMAINS = (
    "personal",
    "clarks_consulting",
    "los",
    "lenders",
    "shared_factory",
    "archive",
)

STANDARD_LANES = (
    "engineering",
    "marketing",
    "sales",
    "support",
    "operations",
    "finance",
    "personal_admin",
    "learning",
)

CONTROL_PLANE_FILES = (
    "README.md",
    "active-work.md",
    "decisions.md",
    "routing-rules.md",
    "approval-rules.md",
)

INBOX_FILES = (
    "raw-ideas.md",
    "triage.md",
)

KNOWLEDGE_FILES = (
    "source-map.md",
    "glossary.md",
    "memory-policy.md",
)

METRIC_FILES = (
    "baselines.md",
    "scorecards.md",
)

DOMAIN_DIRECTORIES = (
    "00-control-plane",
    "01-inbox",
    "02-projects",
    "03-workflows",
    "04-automations",
    "05-knowledge",
    "06-runs-and-logs",
    "06-runs-and-logs/runs",
    "06-runs-and-logs/failures",
    "07-metrics",
    "08-archive",
)

WORKFLOW_FILES = (
    "workflow.md",
    "state-machine.md",
    "context-pack.md",
    "approval-rules.md",
    "output-contract.md",
    "runbook.md",
)

AUTOMATION_FILES = (
    "automation.md",
    "inputs.md",
    "outputs.md",
    "permissions.md",
    "failure-modes.md",
    "runbook.md",
    "tests.md",
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


def titleize_name(name: str) -> str:
    known_names = {
        "personal": "Personal",
        "clarks_consulting": "Clark's Consulting",
        "los": "LOS",
        "lenders": "Lenders",
        "shared_factory": "Shared Factory",
        "archive": "Archive",
    }
    return known_names.get(name, name.replace("_", " ").title())


def domain_purpose(domain: str) -> str:
    purposes = {
        "personal": "Personal administration, household operations, learning, planning, and life logistics.",
        "clarks_consulting": "Client delivery, consulting operations, sales, marketing, and reusable service workflows.",
        "los": "Loan origination system product work, support, releases, implementation, and operational knowledge.",
        "lenders": "Lender-specific knowledge, requests, implementations, and reusable lender-facing workflows.",
        "shared_factory": "Shared patterns, templates, routers, reusable automations, schemas, and cross-domain tools.",
        "archive": "Inactive work, retired projects, historical runs, and preserved decisions.",
    }
    return purposes.get(domain, "Describe the operating boundary this domain owns.")


def root_readme() -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in DEFAULT_DOMAINS)
    return f"""# Installed Agentic OS

This is the live operating system root for agentic work. It is domain-first: choose the domain, then use that domain's control plane, inbox, projects, workflows, automations, knowledge, runs, metrics, and archive.

## Domains

{domains}

## Standard Domain Shape

Each domain uses the same numbered operating lanes:

- `00-control-plane/` - active work, routing, approvals, and decisions.
- `01-inbox/` - raw capture and triage.
- `02-projects/` - active project folders.
- `03-workflows/` - repeatable human-and-agent workflow specs.
- `04-automations/` - trigger-driven automation specs and logs.
- `05-knowledge/` - source maps, glossary, memory policy, and reference material.
- `06-runs-and-logs/` - execution records, artifacts, failures, and activity logs.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - closed or inactive material.

## Agent Entry Point

Start with `AGENTS.md` in this directory, then follow the domain router in the selected domain.
"""


def root_agents() -> str:
    routing_rows = "\n".join(
        f"| `{domain}` | {domain_purpose(domain)} | `{domain}/01-inbox/` |"
        for domain in DEFAULT_DOMAINS
    )
    return f"""# Agent Router

Use this file before touching work inside the installed Agentic OS.

## Routing Table

| Domain | Use For | Intake Path |
| --- | --- | --- |
{routing_rows}

## Operating Rules

- Pick a domain before creating projects, workflows, automations, or run logs.
- Do not create new root-level work folders for active work.
- Put workflow specs in `<domain>/03-workflows/<lane>/<workflow>/`.
- Put automation specs in `<domain>/04-automations/<lane>/<automation>/`.
- Put execution records in `<domain>/06-runs-and-logs/runs/`.
- Use `shared_factory` for reusable templates, schemas, and cross-domain operating patterns.
- Use `archive` only for inactive or historical material.

## Standard Lanes

{chr(10).join(f"- `{lane}`" for lane in STANDARD_LANES)}

## Approval Defaults

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval unless a domain rule narrows the restriction further.
"""


def agent_shim() -> str:
    return """# Agent Router

Use `AGENTS.md` in this directory. This compatibility file exists for tools or habits that look for singular `AGENT.md`.
"""


def domain_config(domain: str) -> str:
    lanes = "\n".join(f"  - {lane}" for lane in STANDARD_LANES)
    return f"""id: {domain}
name: {titleize_name(domain)}
owner: OS Owner
status: active

purpose: >
  {domain_purpose(domain)}

lanes:
{lanes}

directories:
  control_plane: 00-control-plane
  inbox: 01-inbox
  projects: 02-projects
  workflows: 03-workflows
  automations: 04-automations
  knowledge: 05-knowledge
  runs_and_logs: 06-runs-and-logs
  metrics: 07-metrics
  archive: 08-archive

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
  destructive_actions_require_approval: true

notion:
  domain_home_page_id: ""
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


def domain_readme(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# {display_name}

## Purpose

{domain_purpose(domain)}

## Active Outcomes

-

## Main Systems

| System | Role | Link |
| --- | --- | --- |
| Notion | Control plane |  |
| GitHub | Code and pull requests |  |

## Repositories / Notion / Jira

- Repositories:
- Notion:
- Jira:

## Approval Rules

See `00-control-plane/approval-rules.md`.

## Sensitive Data Rules

- Record what can be read.
- Record what can be written.
- Require approval for external writes, production changes, secrets, billing, and legal records.

## Common Workflows

Workflows live under `03-workflows/<lane>/<workflow>/`.

## Active Automations

Automations live under `04-automations/<lane>/<automation>/`.

## Source Map

See `05-knowledge/source-map.md`.

## Current Risks

-
"""


def domain_agents(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Agent Router: {display_name}

## First Decision

Classify the request into one of this domain's operating lanes, then choose the narrowest matching project, workflow, or automation.

## Where To Put Work

| Work Type | Path |
| --- | --- |
| Raw capture | `01-inbox/raw-ideas.md` |
| Triage notes | `01-inbox/triage.md` |
| Active project | `02-projects/<project>/` |
| Workflow spec | `03-workflows/<lane>/<workflow>/workflow.md` |
| Automation spec | `04-automations/<lane>/<automation>/automation.md` |
| Knowledge | `05-knowledge/` |
| Run log | `06-runs-and-logs/runs/<run-id>/run-log.md` |
| Failure record | `06-runs-and-logs/failures/` |
| Metrics | `07-metrics/` |
| Archive | `08-archive/` |

## Routing Rules

- Read `00-control-plane/routing-rules.md` before creating a new workflow or automation.
- Use `03-workflows` when judgment, context assembly, or approval gates are central.
- Use `04-automations` when a trigger can safely run a repeatable action with declared permissions.
- Use `shared_factory` when a pattern should be reused by multiple domains.

## Approval Rules

- Follow `00-control-plane/approval-rules.md`.
- Escalate before external writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records.
- Write a run log before ending any non-trivial execution.
"""


def control_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    headings = {
        "README.md": f"""# {display_name} Control Plane

This folder owns routing, approvals, active work, and durable decisions for `{domain}`.
""",
        "active-work.md": f"""# Active Work: {display_name}

| Work | Status | Owner | Next Action | Link |
| --- | --- | --- | --- | --- |
""",
        "decisions.md": f"""# Decisions: {display_name}

| Date | Decision | Why | Impact | Link |
| --- | --- | --- | --- | --- |
""",
        "routing-rules.md": f"""# Routing Rules: {display_name}

## Default Route

1. Identify the domain.
2. Identify the lane.
3. Check active projects.
4. Reuse an existing workflow or automation when one fits.
5. Create a new workflow only when the process should be repeated.

## Lane Hints

{chr(10).join(f"- `{lane}` -" for lane in STANDARD_LANES)}
""",
        "approval-rules.md": f"""# Approval Rules: {display_name}

## Default Rule

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval.

## Approval Matrix

| Action | Approval Required | Approver | Notes |
| --- | --- | --- | --- |
| Read source systems | no |  |  |
| Draft internal summary | no |  |  |
| Create internal work item | no |  |  |
| Send external message | yes |  |  |
| Comment on customer-visible ticket | yes |  |  |
| Merge PR | yes |  |  |
| Deploy production change | yes |  |  |

## Never Allowed Without Explicit Human Instruction

- Delete customer data.
- Rotate or expose secrets.
- Merge or deploy production code.
- Send customer-visible messages.
- Modify billing or legal records.
""",
    }
    return headings[filename]


def inbox_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "raw-ideas.md":
        return f"""# Raw Ideas: {display_name}

Capture untriaged ideas, notes, messages, and prompts here before routing them.

| Date | Source | Raw Input | Next Step |
| --- | --- | --- | --- |
"""
    return f"""# Triage: {display_name}

| Date | Input | Domain | Lane | Intent | Risk | Confidence | Routed To |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def knowledge_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "source-map.md":
        return f"""# Source Map: {display_name}

| Source | Location | Purpose | Owner | Notes |
| --- | --- | --- | --- | --- |
| Notion |  | Control plane |  |  |
| GitHub |  | Source and PRs |  |  |
| Local files |  | Working artifacts |  |  |
"""
    if filename == "glossary.md":
        return f"""# Glossary: {display_name}

| Term | Meaning | Source |
| --- | --- | --- |
"""
    return f"""# Memory Policy: {display_name}

## Record In Memory

- Durable preferences.
- Repeated workflow decisions.
- Stable source maps.

## Do Not Record In Memory

- Secrets.
- Temporary credentials.
- Sensitive customer data unless explicitly approved and sanitized.

## Refresh Rules

- Verify drift-prone facts before acting.
- Cite source files, tickets, pages, or run logs when recording durable facts.
"""


def metric_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "baselines.md":
        return f"""# Baselines: {display_name}

| Metric | Current Baseline | Source | Date |
| --- | --- | --- | --- |
"""
    return f"""# Scorecards: {display_name}

| Period | Workflow / Automation | Result | Notes |
| --- | --- | --- | --- |
"""


def simple_readme(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


def render_template(content: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        content = content.replace(key, value)
    return content


def ensure_root_files(root: Path, result: ScaffoldResult) -> None:
    ensure_dir(root, result)
    write_file_once(root / "README.md", root_readme(), result)
    write_file_once(root / "AGENTS.md", root_agents(), result)
    write_file_once(root / "AGENT.md", agent_shim(), result)


def create_domain_structure(os_root: Path, domain: str, result: ScaffoldResult) -> None:
    domain = validate_name(domain, "domain")
    domain_root = os_root / domain
    ensure_dir(domain_root, result)
    write_file_once(domain_root / "README.md", domain_readme(domain), result)
    write_file_once(domain_root / "AGENTS.md", domain_agents(domain), result)
    write_file_once(domain_root / "AGENT.md", agent_shim(), result)
    write_file_once(domain_root / "domain.yml", domain_config(domain), result)

    for directory in DOMAIN_DIRECTORIES:
        ensure_dir(domain_root / directory, result)

    for filename in CONTROL_PLANE_FILES:
        write_file_once(domain_root / "00-control-plane" / filename, control_file_content(domain, filename), result)

    for filename in INBOX_FILES:
        write_file_once(domain_root / "01-inbox" / filename, inbox_file_content(domain, filename), result)

    write_file_once(
        domain_root / "02-projects" / "README.md",
        simple_readme(
            f"Projects: {titleize_name(domain)}",
            "Create one folder per active project. Project folders should link back to workflows, automations, source systems, and run logs.",
        ),
        result,
    )

    for lane in STANDARD_LANES:
        ensure_dir(domain_root / "03-workflows" / lane, result)
        ensure_dir(domain_root / "04-automations" / lane, result)

    for filename in KNOWLEDGE_FILES:
        write_file_once(domain_root / "05-knowledge" / filename, knowledge_file_content(domain, filename), result)

    write_file_once(
        domain_root / "06-runs-and-logs" / "activity-log.md",
        simple_readme(
            f"Activity Log: {titleize_name(domain)}",
            "| Date | Actor | Action | Result | Link |\n| --- | --- | --- | --- | --- |",
        ),
        result,
    )

    for filename in METRIC_FILES:
        write_file_once(domain_root / "07-metrics" / filename, metric_file_content(domain, filename), result)

    write_file_once(
        domain_root / "08-archive" / "README.md",
        simple_readme(
            f"Archive: {titleize_name(domain)}",
            "Move inactive or historical material here when it should no longer appear in active routing.",
        ),
        result,
    )


def ensure_default_domains(os_root: Path, result: ScaffoldResult) -> None:
    for domain in DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result)
    result.extend(copy_tree_missing(template_source_dir(), os_root / "shared_factory" / "05-knowledge" / "templates"))


def init_os(target: str | Path) -> ScaffoldResult:
    root = expand_path(target)
    result = ScaffoldResult()
    ensure_root_files(root, result)
    ensure_default_domains(root, result)
    return result


def create_domain(root: str | Path, domain: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    os_root = expand_path(root)
    result = init_os(os_root)
    if domain not in DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result)
    return result


def workflow_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<workflow_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
        "<work_item_or_run>": name,
        "<workflow>": name,
        "<work_item_id>": "",
        "<workflow_or_domain>": name,
    }
    template_dir = template_source_dir() / "workflow"
    if filename == "workflow.md":
        return render_template((template_dir / "workflow.md").read_text(encoding="utf-8"), replacements)
    if filename == "context-pack.md":
        return render_template((template_dir / "context-pack.md").read_text(encoding="utf-8"), replacements)
    if filename == "approval-rules.md":
        return render_template((template_dir / "approval-rules.md").read_text(encoding="utf-8"), replacements)
    if filename == "state-machine.md":
        return f"""# State Machine: {name}

| From | To | Condition |
| --- | --- | --- |
| `new` | `triaged` | Domain and lane selected. |
| `triaged` | `ready` | Required context is present. |
| `ready` | `running` | Agent starts execution. |
| `running` | `needs_approval` | Output crosses an approval gate. |
| `running` | `done` | Output validated and recorded. |
| `running` | `failed` | Execution cannot safely continue. |
"""
    if filename == "output-contract.md":
        return f"""# Output Contract: {name}

## Required Outputs

- Run log.
- Links to artifacts.
- State update.
- Next action or closure reason.

## Quality Bar

- Source links are preserved.
- Approval gates are followed.
- The output can be resumed by another agent or human.
"""
    return f"""# Runbook: {name}

## Before Running

- Confirm the request belongs to `{domain}`.
- Confirm the lane is `{lane}`.
- Load the workflow spec, context pack, and approval rules.

## During The Run

- Record material actions.
- Preserve evidence links.
- Stop at approval gates.

## After Running

- Write or update the run log.
- Store artifacts in the run folder.
- Update active work or project state.
"""


def create_workflow(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    lane = validate_name(lane, "lane")
    name = validate_name(name, "workflow")
    result = create_domain(root, domain)
    workflow_root = expand_path(root) / domain / "03-workflows" / lane / name
    ensure_dir(workflow_root, result)
    ensure_dir(workflow_root / "examples", result)
    ensure_dir(workflow_root / "runs", result)
    for filename in WORKFLOW_FILES:
        write_file_once(workflow_root / filename, workflow_scaffold_content(domain, lane, name, filename), result)
    return result


def automation_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<automation_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
    }
    template_dir = template_source_dir() / "automation"
    if filename == "automation.md":
        return render_template((template_dir / "automation.md").read_text(encoding="utf-8"), replacements)
    if filename == "permissions.md":
        return (template_dir / "permissions.md").read_text(encoding="utf-8")
    if filename == "failure-modes.md":
        return (template_dir / "failure-modes.md").read_text(encoding="utf-8")
    if filename == "inputs.md":
        return f"""# Inputs: {name}

| Input | Required | Source | Validation |
| --- | --- | --- | --- |
| Trigger payload | yes |  |  |
| Domain | yes | `{domain}` | Must match this automation's domain. |
| Lane | yes | `{lane}` | Must match this automation's lane. |
"""
    if filename == "outputs.md":
        return f"""# Outputs: {name}

| Output | Destination | Required | Notes |
| --- | --- | --- | --- |
| Run log | `logs/` and domain runs folder | yes |  |
| State update | Control plane or project | yes |  |
| Artifact |  | no |  |
"""
    if filename == "tests.md":
        return f"""# Tests: {name}

## Dry Run

- Confirm the automation can classify input without writing externally.
- Confirm idempotency behavior.
- Confirm approval-required actions stop before write.

## Failure Tests

- Missing input.
- Duplicate input.
- Unavailable source system.
- Permission denied.
"""
    return f"""# Runbook: {name}

## Start

- Confirm trigger source.
- Confirm declared permissions.
- Run in dry-run mode before enabling writes.

## Operate

- Validate inputs.
- Execute only safe actions.
- Stop at approval gates.

## Recover

- Preserve the failing input reference.
- Write a failure log.
- Route to manual review or retry.
"""


def create_automation(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    lane = validate_name(lane, "lane")
    name = validate_name(name, "automation")
    result = create_domain(root, domain)
    automation_root = expand_path(root) / domain / "04-automations" / lane / name
    ensure_dir(automation_root, result)
    ensure_dir(automation_root / "logs", result)
    for filename in AUTOMATION_FILES:
        write_file_once(automation_root / filename, automation_scaffold_content(domain, lane, name, filename), result)
    return result


def unique_run_log_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = runs_dir / run_id
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = runs_dir / f"{run_id}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def create_run_log(root: str | Path, domain: str, workflow_or_automation: str) -> ScaffoldResult:
    domain = validate_name(domain, "domain")
    workflow_or_automation = validate_name(workflow_or_automation, "workflow_or_automation")
    result = create_domain(root, domain)
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
    run_root = unique_run_log_dir(expand_path(root) / domain / "06-runs-and-logs" / "runs", run_id)
    ensure_dir(run_root, result)
    ensure_dir(run_root / "artifacts", result)
    write_file_once(run_root / "run-log.md", content, result)
    return result
