from pathlib import Path

from genomes_agentic_os.customer import scaffold_customer_brief
from genomes_agentic_os.lifecycle import project_domain, root_project_dirs
from genomes_agentic_os.scaffold import domain_path, init_os, installed_domain_names
from genomes_agentic_os.validate import validate_root


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


def test_domains_parent_prevents_writes_to_a_stray_legacy_domain(tmp_path: Path) -> None:
    root = tmp_path / "os"
    (root / "domains").mkdir(parents=True)
    legacy = root / "los"
    legacy.mkdir()
    (legacy / "domain.yml").write_text("name: los\n", encoding="utf-8")

    assert domain_path(root, "los") == root / "domains/los"


def test_customer_brief_uses_conventional_domain_path(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "domains/consulting"
    domain.mkdir(parents=True)
    (domain / "domain.yml").write_text("name: consulting\n", encoding="utf-8")

    result = scaffold_customer_brief(root, "consulting", "intake_review")

    assert result["created"] is True
    assert Path(result["path"]).parent == domain / "01-intake"


def test_init_creates_only_the_canonical_domain_directory(tmp_path: Path) -> None:
    root = tmp_path / "os"

    init_os(root, domains=("acme",))

    assert (root / "domains/acme/domain.yml").is_file()
    assert not (root / "acme").exists()
    assert not (root / "acme").is_symlink()


def test_validate_rejects_root_domain_compatibility_alias(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root, domains=("acme",))
    (root / "acme").symlink_to(Path("domains/acme"), target_is_directory=True)

    result = validate_root(root)

    assert any("non-canonical root domain entry" in error for error in result.errors)
