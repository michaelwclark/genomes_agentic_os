from pathlib import Path

from genomes_agentic_os.customer import scaffold_customer_brief
from genomes_agentic_os.lifecycle import project_domain, root_project_dirs
from genomes_agentic_os.scaffold import domain_path, installed_domain_names


def test_conventional_domains_are_preferred_and_discovered(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "domains/los"
    project = domain / "projects/django"
    project.mkdir(parents=True)
    (domain / "domain.yml").write_text("name: los\n", encoding="utf-8")

    assert domain_path(root, "los") == domain
    assert installed_domain_names(root) == ["los"]
    assert root_project_dirs(root) == [project]
    assert root_project_dirs(root, domain="los", project="django") == [project]
    assert project_domain(project) == "los"


def test_legacy_domain_path_remains_compatible(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "los"
    domain.mkdir(parents=True)
    (domain / "domain.yml").write_text("name: los\n", encoding="utf-8")
    assert domain_path(root, "los") == domain
    assert installed_domain_names(root) == ["los"]


def test_customer_brief_uses_conventional_domain_path(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "domains/consulting"
    domain.mkdir(parents=True)
    (domain / "domain.yml").write_text("name: consulting\n", encoding="utf-8")

    result = scaffold_customer_brief(root, "consulting", "intake_review")

    assert result["created"] is True
    assert Path(result["path"]).parent == domain / "01-intake"
