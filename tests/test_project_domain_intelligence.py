from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


def test_project_domain_intelligence_program_is_installed_and_cross_harness_visible(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    program = root / "harness/shared_factory/00-programs/project_domain_intelligence"
    components = yaml.safe_load((program / "components.yml").read_text(encoding="utf-8"))
    assert components["id"] == "project_domain_intelligence"
    assert components["instances"] == [{"id": "los_django", "path": "instances/los_django"}]
    instance = program / "instances/los_django"
    assert (instance / "program.md").read_text(encoding="utf-8").startswith(
        "# InstanceOSProgram: project_domain_intelligence"
    )
    assert yaml.safe_load((instance / ".agentic-resource.yml").read_text(encoding="utf-8"))["definition_id"] == "project_domain_intelligence"
    schedule = yaml.safe_load((program / "automation/project-domain-refresh.yml").read_text(encoding="utf-8"))
    assert schedule["schedule"]["enabled"] is False
    assert schedule["permissions"]["article_write"] is False
    assert (program / "operator-attention.md").is_file()
    assert (program / "reports/project-domain-refresh-receipt.yml").is_file()
    workflow = root / "harness/shared_factory/04-workflows/project-domain-architecture-analysis"
    assert (workflow / "workflow.md").is_file()
    assert yaml.safe_load((workflow / "workflow.yml").read_text(encoding="utf-8"))["owner"] == "project_domain_intelligence"
    assert (root / "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis/scripts/domain-analysis").is_file()
    assert (root / "harness/shared_factory/05-knowledge/commands/project-domain-investigate.md").is_file()
    assert (root / "harness/shared_factory/05-knowledge/skills/project-domain-investigate/SKILL.md").is_file()

    skills = yaml.safe_load((root / "harness/registries/skills.yml").read_text(encoding="utf-8"))
    assert "project-domain-investigate" in {entry["id"] for entry in skills["skills"]}
    catalog = yaml.safe_load((root / "harness/skills/skill-registry.yml").read_text(encoding="utf-8"))
    entry = next(item for item in catalog["skills"] if item["id"] == "project-domain-investigate")
    assert entry["harness_targets"] == ["codex", "claude"]

    assert main(["capability", "list", "--root", str(root), "--type", "commands"]) == 0
    assert "/project-domain-investigate" in capsys.readouterr().out
    assert validate_root(root).ok


def test_observe_only_refresh_writes_a_deterministic_receipt_without_articles(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    script = (
        Path(__file__).parents[1]
        / "harness/shared_factory/00-programs/project_domain_intelligence/scripts/project-domain-refresh"
    )
    first = project / "receipts/first.yml"
    second = project / "receipts/second.yml"

    for receipt in (first, second):
        completed = subprocess.run(
            [str(script), "--root", str(project), "--receipt", str(receipt)],
            check=True,
            text=True,
            capture_output=True,
        )
        assert completed.stdout == ""

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    receipt = yaml.safe_load(first.read_text(encoding="utf-8"))
    assert receipt["api_version"] == "project-domain-refresh/v1"
    assert receipt["mode"] == "observe"
    assert receipt["article_writes"] is False
    assert not list(project.glob("**/*.md"))


def test_domain_analysis_article_lifecycle_is_recoverable_and_receipt_backed(tmp_path: Path) -> None:
    # Arrange: create a configured project with a stable initial revision.
    project = tmp_path / "project"
    config = project / ".project-domain-analysis/config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """analysis:
  output_dir: docs/domains
  evidence_dir: docs/domain-analysis/evidence
  runs_dir: docs/domain-analysis/runs
  write_mode: propose
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "configure analysis"], check=True)
    script = (
        Path(__file__).parents[1]
        / "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis/scripts/domain-analysis"
    )

    # Act: create, modify, refresh, retrieve, validate, drift, and roll back.
    subprocess.run([str(script), "create", "payments", "--title", "Payments"], cwd=project, check=True)
    article = project / "docs/domains/payments.md"
    assert "## Risks and failures" in article.read_text(encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "add payments article"], check=True)
    article.write_text(article.read_text(encoding="utf-8") + "\nTemporary refresh evidence.\n", encoding="utf-8")
    before_refresh = article.read_text(encoding="utf-8")
    subprocess.run([str(script), "refresh", "payments"], cwd=project, check=True)
    receipt = "docs/domain-analysis/runs/context-payments.yml"
    subprocess.run([str(script), "retrieve", "payments", "--receipt", receipt], cwd=project, check=True)
    subprocess.run([str(script), "validate"], cwd=project, check=True)
    subprocess.run([str(script), "drift", "HEAD"], cwd=project, check=True)
    subprocess.run([str(script), "rollback", "payments"], cwd=project, check=True)

    # Assert: retrieval is deterministic, drift is visible, and rollback restores
    # the exact pre-refresh bytes rather than reconstructing approximate prose.
    context = yaml.safe_load((project / receipt).read_text(encoding="utf-8"))
    assert context["status"] == "context_ready"
    assert context["selected_articles"] == ["docs/domains/payments.md"]
    assert "docs/domains/payments.md" in (
        project / "docs/domain-analysis/runs/drift.md"
    ).read_text(encoding="utf-8")
    assert article.read_text(encoding="utf-8") == before_refresh
