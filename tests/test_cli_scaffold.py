from __future__ import annotations

from pathlib import Path

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


def test_init_creates_domain_first_tree_and_shared_templates(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    for domain in ("personal", "clarks_consulting", "los", "lenders", "shared_factory", "archive"):
        domain_root = root / domain
        assert domain_root.is_dir()
        assert (domain_root / "AGENTS.md").is_file()
        assert (domain_root / "AGENT.md").is_file()
        assert (domain_root / "00-control-plane" / "routing-rules.md").is_file()
        assert (domain_root / "01-inbox" / "triage.md").is_file()
        assert (domain_root / "03-workflows" / "engineering").is_dir()
        assert (domain_root / "04-automations" / "operations").is_dir()
        assert (domain_root / "05-knowledge" / "source-map.md").is_file()
        assert (domain_root / "06-runs-and-logs" / "runs").is_dir()
        assert (domain_root / "08-archive" / "README.md").is_file()

    assert (root / "AGENTS.md").is_file()
    assert (root / "AGENT.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "workflow.md").is_file()
    assert not (root / "domains").exists()


def test_domain_create_creates_expected_top_level_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["domain", "create", "client_delivery", "--root", str(root)]) == 0

    domain_root = root / "client_delivery"
    assert (domain_root / "README.md").is_file()
    assert (domain_root / "AGENTS.md").is_file()
    assert (domain_root / "domain.yml").read_text(encoding="utf-8").startswith("id: client_delivery")
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
    assert (workflow_root / "state-machine.md").is_file()
    assert (workflow_root / "context-pack.md").is_file()
    assert (workflow_root / "approval-rules.md").is_file()
    assert (workflow_root / "output-contract.md").is_file()
    assert (workflow_root / "runbook.md").is_file()
    assert (workflow_root / "examples").is_dir()
    assert (workflow_root / "runs").is_dir()

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
