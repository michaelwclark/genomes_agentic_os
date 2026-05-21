from __future__ import annotations

from pathlib import Path

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


def test_init_creates_domain_first_tree_and_shared_templates(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    for domain in ("personal", "clarks_consulting", "los", "shared_factory", "archive"):
        domain_root = root / domain
        assert domain_root.is_dir()
        assert (domain_root / "ROUTER.md").is_file()
        assert (domain_root / "AGENTS.md").is_file()
        assert (domain_root / "CLAUDE.md").is_file()
        assert (domain_root / "AGENT.md").is_file()
        assert (domain_root / "CONTEXT.md").is_file()
        assert (domain_root / "REFERENCES.md").is_file()
        assert (domain_root / "00-control-plane" / "routing-rules.md").is_file()
        assert (domain_root / "01-inbox" / "triage.md").is_file()
        assert (domain_root / "03-workflows" / "README.md").is_file()
        assert (domain_root / "03-workflows" / "engineering" / "README.md").is_file()
        assert (domain_root / "03-workflows" / "engineering").is_dir()
        assert (domain_root / "04-automations" / "README.md").is_file()
        assert (domain_root / "04-automations" / "operations" / "README.md").is_file()
        assert (domain_root / "04-automations" / "operations").is_dir()
        assert (domain_root / "05-knowledge" / "source-map.md").is_file()
        assert (domain_root / "06-runs-and-logs" / "runs").is_dir()
        assert (domain_root / "06-runs-and-logs" / "runs" / "README.md").is_file()
        assert (domain_root / "06-runs-and-logs" / "failures" / "README.md").is_file()
        assert (domain_root / "08-archive" / "README.md").is_file()

    assert (root / "ROUTER.md").is_file()
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()
    assert (root / "AGENT.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "workflow.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "outcome-brief.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "prd.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "domain" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "feature-spec.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "future-idea.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "notion" / "agentic-os-control-plane.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "router.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "routing-table.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "tool-index.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "source-priority.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "style-and-output-rules.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "decision-log.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "customer-handoff-checklist.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "notion" / "control-plane-database-spec.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "README.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "index.html").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "07-diagrams" / "layer-map.svg").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-route.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-capture-plan.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-discover-rooms.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-doctor.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "README.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "00-current-state-and-gap-map.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "09-future-ideas-intake.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "11-room-first-installer-and-routing.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "12-factory-template-import-backlog.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "13-reference-and-skill-index-layer.md"
    ).is_file()
    assert (
        root
        / "shared_factory"
        / "05-knowledge"
        / "plans"
        / "14-client-automation-and-control-plane-playbooks.md"
    ).is_file()
    assert (
        root
        / "shared_factory"
        / "05-knowledge"
        / "plans"
        / "15-always-on-runtime-heartbeats-schedules-and-integrations.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "16-connected-source-watch-registry.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "17-event-graph-and-chained-automations.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "room-builder" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "os-navigator" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "workflow-builder" / "SKILL.md").is_file()
    assert not (root / "domains").exists()
    assert not (root / "lenders").exists()


def test_domain_create_creates_expected_top_level_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["domain", "create", "client_delivery", "--root", str(root)]) == 0

    domain_root = root / "client_delivery"
    assert (domain_root / "README.md").is_file()
    assert (domain_root / "ROUTER.md").is_file()
    assert (domain_root / "AGENTS.md").is_file()
    assert (domain_root / "CLAUDE.md").is_file()
    assert (domain_root / "AGENT.md").is_file()
    assert (domain_root / "CONTEXT.md").is_file()
    assert (domain_root / "REFERENCES.md").is_file()
    domain_config = (domain_root / "domain.yml").read_text(encoding="utf-8")
    assert domain_config.startswith("id: client_delivery")
    assert "context_loading:" in domain_config
    assert (domain_root / "00-control-plane" / "active-work.md").is_file()
    assert (domain_root / "00-control-plane" / "approval-rules.md").is_file()
    assert (domain_root / "01-inbox" / "raw-ideas.md").is_file()
    assert (domain_root / "02-projects" / "README.md").is_file()
    assert (domain_root / "03-workflows" / "engineering").is_dir()
    assert (domain_root / "04-automations" / "support").is_dir()
    assert (domain_root / "05-knowledge" / "memory-policy.md").is_file()
    assert (domain_root / "06-runs-and-logs" / "activity-log.md").is_file()
    assert (domain_root / "07-metrics" / "scorecards.md").is_file()


def test_workflow_automation_run_log_and_validate(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    workflow_root = root / "los" / "03-workflows" / "engineering" / "feature_dev"
    assert (workflow_root / "workflow.md").is_file()
    assert (workflow_root / "outcome-brief.md").is_file()
    assert (workflow_root / "alignment-questions.md").is_file()
    assert (workflow_root / "prd.md").is_file()
    assert (workflow_root / "implementation-plan.md").is_file()
    assert (workflow_root / "dispatch-handoff.md").is_file()
    assert (workflow_root / "progress.md").is_file()
    assert (workflow_root / "quick-reference.md").is_file()
    assert (workflow_root / "state-machine.md").is_file()
    assert (workflow_root / "context-pack.md").is_file()
    assert (workflow_root / "approval-rules.md").is_file()
    assert (workflow_root / "output-contract.md").is_file()
    assert (workflow_root / "runbook.md").is_file()
    assert (workflow_root / "examples").is_dir()
    assert (workflow_root / "examples" / "README.md").is_file()
    assert (workflow_root / "runs").is_dir()
    assert (workflow_root / "runs" / "README.md").is_file()

    assert (
        main(
            [
                "automation",
                "create",
                "los",
                "support",
                "production_thread_intake",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    automation_root = root / "los" / "04-automations" / "support" / "production_thread_intake"
    assert (automation_root / "automation.md").is_file()
    assert (automation_root / "inputs.md").is_file()
    assert (automation_root / "outputs.md").is_file()
    assert (automation_root / "permissions.md").is_file()
    assert (automation_root / "failure-modes.md").is_file()
    assert (automation_root / "runbook.md").is_file()
    assert (automation_root / "tests.md").is_file()
    assert (automation_root / "logs").is_dir()
    assert (automation_root / "logs" / "README.md").is_file()

    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_logs = list((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev/run-log.md"))
    assert len(run_logs) == 1
    assert validate_root(root).ok
    assert main(["validate", "--root", str(root)]) == 0


def test_commands_are_safe_to_rerun(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    command = ["domain", "create", "client_delivery", "--root", str(root)]
    assert main(command) == 0
    before = (root / "client_delivery" / "domain.yml").read_text(encoding="utf-8")
    assert main(command) == 0
    after = (root / "client_delivery" / "domain.yml").read_text(encoding="utf-8")

    assert before == after


def test_docs_update_is_additive_and_preserves_local_edits(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    manual_readme = root / "shared_factory" / "05-knowledge" / "operating-manual" / "README.md"
    command_file = root / "shared_factory" / "05-knowledge" / "commands" / "os-sync-notion.md"
    plan_readme = root / "shared_factory" / "05-knowledge" / "plans" / "README.md"
    plan_file = root / "shared_factory" / "05-knowledge" / "plans" / "09-future-ideas-intake.md"
    planning_template = root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "feature-spec.md"
    domain_context_template = root / "shared_factory" / "05-knowledge" / "templates" / "domain" / "context.md"
    manual_readme.write_text("# local edit\n", encoding="utf-8")
    plan_readme.write_text("# local plan edit\n", encoding="utf-8")
    command_file.unlink()
    plan_file.unlink()
    planning_template.unlink()
    domain_context_template.unlink()

    assert main(["docs", "update", "--root", str(root)]) == 0

    content = manual_readme.read_text(encoding="utf-8")
    assert content == "# local edit\n"
    assert plan_readme.read_text(encoding="utf-8") == "# local plan edit\n"
    assert command_file.is_file()
    assert plan_file.is_file()
    assert planning_template.is_file()
    assert domain_context_template.is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "os-doctor" / "SKILL.md").is_file()
    assert main(["docs", "update", "--root", str(root)]) == 0
    assert manual_readme.read_text(encoding="utf-8") == "# local edit\n"
    assert plan_readme.read_text(encoding="utf-8") == "# local plan edit\n"


def test_lenders_alias_routes_to_los_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "lenders", "support", "lender_intake", "--root", str(root)]) == 0

    assert (root / "los" / "03-workflows" / "support" / "lender_intake" / "workflow.md").is_file()
    assert not (root / "lenders").exists()
    assert validate_root(root).ok


def test_generated_markdown_has_level_specific_contracts(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    workflow_root = root / "los" / "03-workflows" / "engineering" / "feature_dev"
    automation_root = root / "los" / "04-automations" / "support" / "production_thread_intake"
    run_log = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev/run-log.md"))

    required_sections = {
        root / "ROUTER.md": ("# Agent Router", "## Routing Table", "## Operating Rules"),
        root / "AGENTS.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "CLAUDE.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "AGENT.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "los" / "ROUTER.md": ("# Agent Router: LOS", "## Where To Put Work", "## Approval Rules"),
        root / "los" / "AGENTS.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "los" / "CLAUDE.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "los" / "AGENT.md": ("# Agent Router", "Source of truth: `ROUTER.md`.", "Load `ROUTER.md`"),
        root / "los" / "CONTEXT.md": ("# Context: LOS", "## What To Load", "## Tools And Skills", "## Done Means"),
        root / "los" / "REFERENCES.md": ("# References: LOS", "## Source Systems", "## Known Gaps"),
        root / "los" / "03-workflows" / "README.md": ("# Workflows: LOS", "## Lane Directories", "## Workflow Folder Format"),
        root / "los" / "03-workflows" / "engineering" / "README.md": (
            "# Workflow Lane: engineering",
            "## Workflow Folder Format",
            "## Routing Rule",
        ),
        workflow_root / "workflow.md": ("# Workflow: feature_dev", "## Metadata", "## Purpose", "## Validation"),
        workflow_root / "outcome-brief.md": (
            "# Outcome Brief: feature_dev",
            "## Definition Of Done",
            "## Acceptance Criteria",
        ),
        workflow_root / "alignment-questions.md": (
            "# Alignment Questions: feature_dev",
            "## Required Questions",
            "## Dispatch Decision",
        ),
        workflow_root / "prd.md": (
            "# PRD: feature_dev",
            "## Requirements",
            "## Validation",
        ),
        workflow_root / "implementation-plan.md": (
            "# Implementation Plan: feature_dev",
            "## Build Stages",
            "## Validation Plan",
        ),
        workflow_root / "dispatch-handoff.md": (
            "# Dispatch Handoff: feature_dev",
            "## Required Sources To Load",
            "## Stop Conditions",
        ),
        workflow_root / "progress.md": (
            "# Progress: feature_dev",
            "## Current State",
            "## Handoff Prompt",
        ),
        workflow_root / "quick-reference.md": (
            "# Quick Reference: feature_dev",
            "## Start Here",
            "## Common Failure Modes",
        ),
        workflow_root / "state-machine.md": ("# State Machine: feature_dev", "| From | To | Condition |"),
        workflow_root / "output-contract.md": ("# Output Contract: feature_dev", "## Required Outputs", "## Quality Bar"),
        workflow_root / "examples" / "README.md": ("# Examples: feature_dev", "## Example Format"),
        root / "los" / "04-automations" / "README.md": (
            "# Automations: LOS",
            "## Lane Directories",
            "## Automation Folder Format",
        ),
        automation_root / "automation.md": ("# Automation: production_thread_intake", "## Metadata", "## Trigger"),
        automation_root / "inputs.md": ("# Inputs: production_thread_intake", "| Input | Required | Source | Validation |"),
        automation_root / "logs" / "README.md": ("# Automation Logs: production_thread_intake", "## Log Format"),
        root / "los" / "06-runs-and-logs" / "runs" / "README.md": ("# Runs: LOS", "## Run Folder Format"),
        root / "los" / "06-runs-and-logs" / "failures" / "README.md": ("# Failures: LOS", "## Failure Record Format"),
        run_log: ("# Run Log:", "## Metadata", "## Input", "## Session Continuity", "## Validation", "## Handoff"),
    }

    for path, sections in required_sections.items():
        content = path.read_text(encoding="utf-8")
        assert content.startswith("# "), path
        for section in sections:
            assert section in content, path
