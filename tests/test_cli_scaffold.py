from __future__ import annotations

from pathlib import Path

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


def test_init_creates_base_tree_and_copies_templates(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    for folder in (
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
    ):
        assert (root / folder).is_dir()
    assert (root / "templates" / "workflow" / "workflow.md").is_file()


def test_domain_create_creates_expected_tree(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["domain", "create", "internal_product", "--root", str(root)]) == 0

    domain_root = root / "domains" / "internal_product"
    assert (domain_root / "README.md").is_file()
    assert (domain_root / "domain.yml").read_text(encoding="utf-8").startswith("id: internal_product")
    assert (domain_root / "context" / "business.md").is_file()
    assert (domain_root / "context" / "systems.md").is_file()
    assert (domain_root / "context" / "stakeholders.md").is_file()
    assert (domain_root / "context" / "access-policy.md").is_file()
    assert (domain_root / "workflows").is_dir()
    assert (domain_root / "automations").is_dir()
    assert (domain_root / "decisions").is_dir()
    assert (domain_root / "notion").is_dir()


def test_workflow_automation_run_log_and_validate(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["workflow", "create", "internal_product", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert (
        root / "domains" / "internal_product" / "workflows" / "engineering" / "feature_dev.md"
    ).is_file()

    assert (
        main(
            [
                "automation",
                "create",
                "internal_product",
                "support",
                "production_thread_intake",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert (
        root / "domains" / "internal_product" / "automations" / "support" / "production_thread_intake.md"
    ).is_file()

    assert main(["run-log", "create", "internal_product", "feature_dev", "--root", str(root)]) == 0
    run_logs = list((root / "runs").glob("*-internal_product-feature_dev*.md"))
    assert len(run_logs) == 1
    assert validate_root(root).ok
    assert main(["validate", "--root", str(root)]) == 0


def test_commands_are_safe_to_rerun(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    command = ["domain", "create", "internal_product", "--root", str(root)]
    assert main(command) == 0
    before = (root / "domains" / "internal_product" / "domain.yml").read_text(encoding="utf-8")
    assert main(command) == 0
    after = (root / "domains" / "internal_product" / "domain.yml").read_text(encoding="utf-8")

    assert before == after
