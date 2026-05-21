from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

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
    assert (root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "tool-index.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "source-priority.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "style-and-output-rules.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "decision-log.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "naming-conventions.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "source-priority.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "style-and-output-rules.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "decision-log.md").is_file()
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


def test_project_create_creates_project_state_and_indexes(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert (
        main(
            [
                "project",
                "create",
                "los",
                "losmon_replacement",
                "--root",
                str(root),
                "--repo",
                "/Users/genome/projects/losmon",
                "--notion",
                "https://notion.so/example",
                "--jira",
                "LOS",
                "--lane",
                "engineering",
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "losmon_replacement"
    assert (project_root / "README.md").is_file()
    assert (project_root / "project.yml").is_file()
    assert (project_root / "status.md").is_file()
    assert (project_root / "decisions.md").is_file()
    assert (project_root / "source-map.md").is_file()
    assert (project_root / "artifacts").is_dir()
    assert "repo: /Users/genome/projects/losmon" in (project_root / "project.yml").read_text(encoding="utf-8")
    assert "| Repo | /Users/genome/projects/losmon |" in (project_root / "source-map.md").read_text(
        encoding="utf-8"
    )
    assert "`losmon_replacement`" in (root / "los" / "02-projects" / "README.md").read_text(encoding="utf-8")
    assert "`losmon_replacement`" in (root / "los" / "00-control-plane" / "active-work.md").read_text(
        encoding="utf-8"
    )
    assert validate_root(root).ok


def test_project_create_is_idempotent_and_preserves_local_edits(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    command = ["project", "create", "los", "losmon_replacement", "--root", str(root)]

    assert main(command) == 0
    status_file = root / "los" / "02-projects" / "losmon_replacement" / "status.md"
    status_file.write_text("# local status edit\n", encoding="utf-8")
    assert main(command) == 0

    assert status_file.read_text(encoding="utf-8") == "# local status edit\n"
    active_work = (root / "los" / "00-control-plane" / "active-work.md").read_text(encoding="utf-8")
    assert active_work.count("| `losmon_replacement` |") == 1
    assert validate_root(root).ok


def test_project_create_rejects_invalid_names_and_normalizes_domain_alias(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "bad-name", "--root", str(root)]) == 2
    assert main(["project", "create", "lenders", "lender_portal", "--root", str(root)]) == 0
    assert (root / "los" / "02-projects" / "lender_portal" / "project.yml").is_file()
    assert not (root / "lenders").exists()


def test_route_classifies_project_request_and_approval_risk(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "losmon_repo"
    repo.mkdir()

    assert main(["project", "create", "los", "losmon_replacement", "--repo", str(repo), "--root", str(root)]) == 0
    assert main(["route", "Deploy losmon_replacement to production", "--root", str(root)]) == 0

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"].endswith("los/02-projects/losmon_replacement")
    assert "production change" in packet["approval_risks"]
    assert any(path.endswith("source-map.md") for path in packet["sources_to_load"])


def test_context_build_returns_exact_project_sources(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert (
        main(
            [
                "context",
                "build",
                "--domain",
                "los",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert str(root / "ROUTER.md") in packet["sources_to_load"]
    assert str(root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md") in packet[
        "sources_to_load"
    ]
    assert str(root / "shared_factory" / "05-knowledge" / "references" / "source-priority.md") in packet[
        "sources_to_load"
    ]
    assert str(root / "los" / "ROUTER.md") in packet["sources_to_load"]
    assert str(root / "los" / "02-projects" / "losmon_replacement" / "project.yml") in packet["sources_to_load"]


def test_here_detects_os_path_and_linked_project_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "losmon_repo"
    repo.mkdir()

    assert main(["project", "create", "los", "losmon_replacement", "--repo", str(repo), "--root", str(root)]) == 0
    monkeypatch.chdir(root / "los")
    assert main(["here", "route", "Summarize active work", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "domain"

    monkeypatch.chdir(repo)
    assert main(["here", "context", "build", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"].endswith("los/02-projects/losmon_replacement")


def test_route_fails_safely_when_ambiguous(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["route", "Do the thing", "--root", str(root)]) == 2
    assert main(["route", "Compare los and personal work", "--root", str(root)]) == 2


def write_ready_automation_contract(path: Path) -> None:
    path.write_text(
        """# Automation: production_thread_intake

## Metadata

| Field | Value |
| --- | --- |
| Domain | `los` |
| Lane | `support` |
| Status | `draft` |
| Level | `observe` |
| Owner | `OS Owner` |
| Last Reviewed | `2026-05-21` |

## Trigger

- Type: `manual`
- Source: `support queue`
- Frequency: `on demand`

## Idempotency

- Key: `support_thread_id`
- Duplicate handling: `link existing run log`

## Permissions

- Read: `support queue`
- Write: `filesystem only`
- Requires approval: `external messages`
- Default action before approval: `propose`

## Outputs

- Run log with evidence.
- Draft response for approval.

## Audit Requirements

- Input reference.
- Action taken.
- Result.
- Evidence.
""",
        encoding="utf-8",
    )


def test_automation_check_and_safe_maturity_levels(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    automation_md = root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    assert "| Level | `observe` |" in automation_md.read_text(encoding="utf-8")

    capsys.readouterr()
    assert main(["automation", "check", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["level"] == "observe"
    assert any(finding["severity"] == "blocker" for finding in packet["findings"])

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "prepare",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert "| Level | `prepare` |" in automation_md.read_text(encoding="utf-8")
    decisions = (root / "los" / "00-control-plane" / "decisions.md").read_text(encoding="utf-8")
    assert "maturity changed from `observe` to `prepare`" in decisions

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "propose",
                "--root",
                str(root),
            ]
        )
        == 2
    )


def test_automation_maturity_advances_after_file_first_evidence(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    automation_md = root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    write_ready_automation_contract(automation_md)

    capsys.readouterr()
    assert main(["automation", "check", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert not [finding for finding in packet["findings"] if finding["severity"] == "blocker"]

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "propose",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["old_level"] == "observe"
    assert result["new_level"] == "propose"
    assert "| Level | `propose` |" in automation_md.read_text(encoding="utf-8")


def test_automation_attach_updates_project_status_and_source_map(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0

    capsys.readouterr()
    assert (
        main(
            [
                "automation",
                "attach",
                "los",
                "support",
                "production_thread_intake",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["project"].endswith("los/02-projects/losmon_replacement")

    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "## Automation Attachments" in project_status
    assert "`production_thread_intake`" in project_status
    source_map = (root / "los" / "02-projects" / "losmon_replacement" / "source-map.md").read_text(
        encoding="utf-8"
    )
    assert "| Automation | 04-automations/support/production_thread_intake/ |" in source_map
    automation_md = (
        root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    ).read_text(encoding="utf-8")
    assert "## Project Attachments" in automation_md
    assert "`losmon_replacement`" in automation_md


def write_customer_profile(path: Path) -> None:
    path.write_text(
        """customer:
  slug: acme_ops
  display_name: Acme Operations
  owner: Operations Lead
  notion_workspace: Acme Notion
  approved_domains:
    - support
  source_systems:
    - name: helpdesk
      role: customer support inbox
  default_workflows:
    - domain: support
      lane: support
      name: intake_triage
  default_automations:
    - domain: support
      lane: support
      name: thread_intake
  approval_policy:
    external_writes_require_approval: true
    customer_visible_output_requires_approval: true
    production_changes_require_approval: true
    destructive_actions_require_approval: true
""",
        encoding="utf-8",
    )


def write_room_profile(path: Path) -> None:
    path.write_text(
        """os:
  display_name: Studio OS
  owner: Operator
approval_policy:
  external_writes_require_approval: true
rooms:
  - slug: writing_room
    display_name: Writing Room
    purpose: Ideas become polished drafts.
    inputs:
      - rough ideas
      - research notes
    output_folders:
      drafts: drafts
      finals: final
    routing:
      - task: write blog post
        read_first:
          - docs/voice.md
        read_when_needed:
          - docs/audience.md
        skip_by_default:
          - production docs
        output_path: drafts/
    tools:
      - name: humanizer
        trigger: before final
        notes: remove generic wording
    done_means:
      - output exists in the expected folder
      - source files are preserved
""",
        encoding="utf-8",
    )


def customer_text_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".yml", ".yaml"}
    ]


def test_customer_init_generates_public_customer_os_from_profile(tmp_path: Path, capsys) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["customer"] == "acme_ops"
    assert (root / "README.md").is_file()
    assert (root / "ROUTER.md").is_file()
    assert (root / "customer.yml").is_file()
    assert (root / "support" / "domain.yml").is_file()
    assert (root / "support" / "03-workflows" / "support" / "intake_triage" / "workflow.md").is_file()
    assert (root / "support" / "04-automations" / "support" / "thread_intake" / "automation.md").is_file()
    assert not (root / "clarks_consulting").exists()
    assert not (root / "los").exists()

    disallowed = ("genome", "clark", "clarks_consulting", "los", "lenders")
    generated_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in customer_text_files(root))
    assert not any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", generated_text) for term in disallowed)

    assert main(["customer", "validate", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["ok"] is True
    assert packet["core_errors"] == []
    assert packet["profile_warnings"] == []


def test_customer_update_is_additive_and_preserves_local_edits(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    handoff = root / "customer" / "handoff-checklist.md"
    brief = root / "customer" / "client-automation-brief.md"
    handoff.write_text("# local customer handoff edit\n", encoding="utf-8")
    brief.unlink()

    assert main(["customer", "update", "acme_ops", "--root", str(root)]) == 0

    assert handoff.read_text(encoding="utf-8") == "# local customer handoff edit\n"
    assert brief.is_file()
    assert main(["customer", "validate", "--root", str(root)]) == 0


def test_customer_init_rejects_private_source_domains(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    profile.write_text(
        """customer:
  slug: acme_ops
  display_name: Acme Operations
  owner: Operations Lead
  approved_domains:
    - los
""",
        encoding="utf-8",
    )

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(tmp_path / "out")]) == 2


def test_room_profile_init_creates_custom_room_without_default_domains(tmp_path: Path, capsys) -> None:
    profile = tmp_path / "room-profile.yml"
    root = tmp_path / "studio_os"
    write_room_profile(profile)

    assert main(["profile", "validate", str(profile)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["rooms"] == ["writing_room"]

    assert main(["init", "--target", str(root), "--profile", str(profile)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["rooms"] == ["writing_room"]
    assert (root / "writing_room" / "CONTEXT.md").is_file()
    assert not (root / "los").exists()
    assert not (root / "clarks_consulting").exists()

    context = (root / "writing_room" / "CONTEXT.md").read_text(encoding="utf-8")
    assert "rough ideas" in context
    assert "docs/voice.md" in context
    assert "humanizer" in context
    assert "output exists in the expected folder" in context
    router = (root / "ROUTER.md").read_text(encoding="utf-8")
    assert "`writing_room`" in router
    assert main(["validate", "--root", str(root)]) == 0

    (root / "writing_room" / "CONTEXT.md").write_text("# local room context edit\n<!-- room-profile-managed -->\n", encoding="utf-8")
    assert main(["room", "update", "writing_room", "--root", str(root), "--from-profile", str(profile)]) == 0
    assert (root / "writing_room" / "CONTEXT.md").read_text(encoding="utf-8").startswith("# local room context edit")


def test_profile_validate_rejects_duplicate_rooms_and_missing_approvals(tmp_path: Path) -> None:
    profile = tmp_path / "bad-profile.yml"
    profile.write_text(
        """rooms:
  - slug: writing_room
    purpose: Drafts.
    done_means:
      - done
  - slug: writing_room
    purpose: Duplicate.
    done_means:
      - done
""",
        encoding="utf-8",
    )
    assert main(["profile", "validate", str(profile)]) == 2


def test_factory_templates_install_and_customer_facing_templates_are_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
    ).is_file()

    sanitized_roots = [
        Path("templates/room"),
        Path("templates/stage"),
        Path("templates/reference"),
        Path("templates/profile"),
        Path("templates/customer"),
    ]
    disallowed = ("eduba", "school", "acme", "clarks_consulting")
    for relative_root in sanitized_roots:
        for path in relative_root.rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8").lower()
                assert not any(term in content for term in disallowed), path


def test_notion_sync_plan_maps_filesystem_objects_and_is_idempotent(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    capsys.readouterr()
    assert main(["notion", "plan-sync", "--root", str(root)]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    action_kinds = {(action["action"], action["kind"]) for action in plan["actions"]}
    assert ("create", "domain") in action_kinds
    assert ("create", "project") in action_kinds
    assert ("create", "workflow") in action_kinds
    assert ("create", "automation") in action_kinds
    assert ("create", "run") in action_kinds
    assert not (root / ".notion-sync" / "mapping.yml").exists()

    assert main(["notion", "sync", "--root", str(root), "--apply"]) == 2
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Michael Clark Personal Notion",
            ]
        )
        == 2
    )

    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 0
    )
    assert (root / ".notion-sync" / "mapping.yml").is_file()

    capsys.readouterr()
    assert main(["notion", "sync", "--root", str(root), "--dry-run"]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert {action["action"] for action in plan["actions"]} == {"no-op"}


def test_customer_notion_sync_requires_configured_customer_workspace(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Acme Notion",
            ]
        )
        == 0
    )


def test_notion_bootstrap_requires_verified_workspace_and_parent(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    capsys.readouterr()
    assert main(["notion", "bootstrap", "--root", str(root), "--dry-run"]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert plan["home_page"]["name"] == "Agentic OS"
    assert {database["name"] for database in plan["databases"]} >= {
        "OS Inbox",
        "Work Items",
        "Runs",
        "Approvals",
        "Domains",
    }
    assert plan["seed_records"]["runs"]
    assert not (root / ".notion-control-plane" / "manifest.yml").exists()

    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Michael Clark Personal Notion",
                "--parent-page-id",
                "abc123",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
                "--parent-page-id",
                "366683b48dab81a1ab5fc73e7e1f5c60",
            ]
        )
        == 0
    )
    manifest = yaml.safe_load((root / ".notion-control-plane" / "manifest.yml").read_text(encoding="utf-8"))
    assert manifest["workspace"] == "Genome's Notion"
    assert manifest["home_page"]["name"] == "Agentic OS"


def test_doctor_reports_stale_run_logs_and_repairs_missing_managed_files(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    missing_doc = root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
    missing_doc.unlink()
    local_readme = root / "README.md"
    local_readme.write_text("# local root edit\n", encoding="utf-8")

    assert main(["doctor", "--root", str(root)]) == 1
    report = yaml.safe_load(capsys.readouterr().out)
    assert any(finding["severity"] == "blocker" and str(missing_doc) in finding["message"] for finding in report["findings"])

    assert main(["doctor", "--root", str(root), "--fix-missing"]) == 0
    report = yaml.safe_load(capsys.readouterr().out)
    assert report["repairs"]
    assert missing_doc.is_file()
    assert local_readme.read_text(encoding="utf-8") == "# local root edit\n"

    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--root", str(root)]) == 0
    report = yaml.safe_load(capsys.readouterr().out)
    assert any("run log has no final status" in finding["message"] for finding in report["findings"])


def test_migration_plan_and_apply_require_stable_preview(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 2

    assert main(["migrate", "plan", "--root", str(root)]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert plan["migrations"][0]["migration_id"] == "notion-sync-readme-v1"
    assert "---" in plan["migrations"][0]["diff"]

    target = root / ".notion-sync" / "README.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# changed after preview\n", encoding="utf-8")
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 2

    target.unlink()
    assert main(["migrate", "plan", "--root", str(root)]) == 0
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 0
    assert "Filesystem state remains the source of truth" in target.read_text(encoding="utf-8")


def test_losmon_validate_creates_required_validation_objects(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "los_repo"
    repo.mkdir()

    assert main(["losmon", "validate", "--root", str(root), "--repo", str(repo)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["project"].endswith("los/02-projects/losmon_replacement")

    required_paths = [
        root / "los" / "02-projects" / "losmon_replacement" / "project.yml",
        root / "los" / "03-workflows" / "engineering" / "pr_review" / "workflow.md",
        root / "los" / "03-workflows" / "engineering" / "failing_ci_triage" / "workflow.md",
        root / "los" / "03-workflows" / "operations" / "deploy_planning" / "workflow.md",
        root / "los" / "04-automations" / "support" / "thread_intake" / "automation.md",
        root / "los" / "02-projects" / "losmon_replacement" / "artifacts" / "losmon-comparison.md",
    ]
    for path in required_paths:
        assert path.is_file(), path

    comparison = (root / "los" / "02-projects" / "losmon_replacement" / "artifacts" / "losmon-comparison.md").read_text(
        encoding="utf-8"
    )
    assert "LOSMon Still Better / Required" in comparison
    assert "Need live connected-source watcher" in comparison
    assert len(result["run_logs"]) == 3
    for run_log in result["run_logs"]:
        content = Path(run_log).read_text(encoding="utf-8")
        assert "## Closeout" in content
        assert "Run this workflow against a real read-only LOS task" in content
    assert main(["validate", "--root", str(root)]) == 0


def test_plan_capture_routes_os_domain_and_project_ideas(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--title",
                "Telemetry Adapter",
                "--summary",
                "Capture losmon telemetry into run logs.",
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    os_plan = Path(result["target"])
    assert os_plan.is_file()
    assert "Capture losmon telemetry into run logs." in os_plan.read_text(encoding="utf-8")
    assert "future-ideas/telemetry-adapter.md" in (
        root / "shared_factory" / "05-knowledge" / "plans" / "README.md"
    ).read_text(encoding="utf-8")

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--kind",
                "domain",
                "--domain",
                "los",
                "--title",
                "CI failure clustering",
                "--summary",
                "Group related CI failures before triage.",
            ]
        )
        == 0
    )
    raw_ideas = (root / "los" / "01-inbox" / "raw-ideas.md").read_text(encoding="utf-8")
    assert "CI failure clustering" in raw_ideas

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--kind",
                "customer",
                "--domain",
                "los",
                "--project",
                "losmon_replacement",
                "--title",
                "Customer-safe deploy brief",
                "--summary",
                "Create reusable customer deploy planning notes.",
            ]
        )
        == 0
    )
    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "Customer-safe deploy brief" in project_status


def test_workflow_check_reports_readiness_findings(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["workflow", "check", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)

    severities = {finding["severity"] for finding in packet["findings"]}
    assert severities <= {"blocker", "fix-soon", "cleanup", "observation"}
    assert "fix-soon" in severities

    runbook = root / "los" / "03-workflows" / "engineering" / "feature_dev" / "runbook.md"
    runbook.write_text(runbook.read_text(encoding="utf-8").replace("## After Running", "## Finish"), encoding="utf-8")

    assert main(["workflow", "check", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert {
        "severity": "blocker",
        "path": str(runbook),
        "message": "missing required section: After Running",
    } in packet["findings"]


def test_run_log_close_requires_validation_for_done_and_rejects_invalid_status(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_id = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev")).name

    assert main(["run-log", "close", "los", run_id, "--status", "done", "--root", str(root)]) == 2
    with pytest.raises(SystemExit) as exc:
        main(["run-log", "close", "los", run_id, "--status", "finished", "--root", str(root)])
    assert exc.value.code == 2


def test_run_log_close_records_closeout_and_activity_updates(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_dir = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev"))

    assert (
        main(
            [
                "run-log",
                "close",
                "los",
                run_dir.name,
                "--status",
                "done",
                "--summary",
                "Built and verified the workflow closeout command.",
                "--validation",
                "uv run --extra dev pytest -q passed",
                "--artifact",
                "run-log.md",
                "--approval",
                "No external approval gate encountered.",
                "--next-action",
                "Promote to the next feature.",
                "--learning",
                "Closeout needs validation evidence before done.",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["status"] == "done"

    run_log = run_dir / "run-log.md"
    content = run_log.read_text(encoding="utf-8")
    assert "| Status | `done` |" in content
    assert "## Closeout" in content
    assert "uv run --extra dev pytest -q passed" in content
    assert "Promote to the next feature." in content

    activity_log = (root / "los" / "06-runs-and-logs" / "activity-log.md").read_text(encoding="utf-8")
    assert run_dir.name in activity_log
    progress = (root / "los" / "03-workflows" / "engineering" / "feature_dev" / "progress.md").read_text(
        encoding="utf-8"
    )
    assert run_dir.name in progress
    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "## Run Closeout" in project_status
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
