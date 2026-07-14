from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_obsolete_top_level_lifecycle_and_example_folders_are_absent() -> None:
    for name in ("SPECS", "examples", "skills"):
        assert not (REPO_ROOT / name).exists(), f"obsolete top-level folder returned: {name}"

    assert (REPO_ROOT / "docs" / "examples" / "README.md").is_file()


def test_meaningful_repository_boundaries_have_navigation_readmes() -> None:
    expected = (
        "config/README.md",
        "customer_profiles/README.md",
        "docs/README.md",
        "docs/architecture/README.md",
        "docs/assets/README.md",
        "docs/design-notes/README.md",
        "docs/examples/README.md",
        "docs/qa/README.md",
        "docs/tutorials/README.md",
        "harness/README.md",
        "harness/commands/README.md",
        "harness/registries/README.md",
        "harness/shared_factory/README.md",
        "harness/shared_factory/00-programs/README.md",
        "harness/shared_factory/00-programs/spec_grooming/README.md",
        "installers/README.md",
        "operating-manual/README.md",
        "schemas/README.md",
        "src/README.md",
        "src/genomes_agentic_os/README.md",
        "src/genomes_agentic_os/cli/README.md",
        "src/genomes_agentic_os/spec_adapters/README.md",
        "src/genomes_agentic_os/state/README.md",
        "system/README.md",
        "templates/README.md",
        "tests/README.md",
    )
    missing = [path for path in expected if not (REPO_ROOT / path).is_file()]
    assert not missing, f"missing navigation README files: {missing}"


def test_command_readme_lists_every_command_document() -> None:
    command_root = REPO_ROOT / "harness" / "commands"
    content = (command_root / "README.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in sorted(command_root.glob("*.md"))
        if path.name != "README.md" and f"({path.name})" not in content
    ]
    assert not missing, f"command README is missing: {missing}"


def test_registry_readme_lists_every_direct_registry_file() -> None:
    registry_root = REPO_ROOT / "harness" / "registries"
    content = (registry_root / "README.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in sorted(registry_root.iterdir())
        if path.is_file() and path.name != "README.md" and f"({path.name})" not in content
    ]
    assert not missing, f"registry README is missing: {missing}"
