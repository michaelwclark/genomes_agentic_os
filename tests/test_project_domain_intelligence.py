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
    assert (root / "harness/shared_factory/04-workflows/project-domain-architecture-analysis.md").is_file()
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
