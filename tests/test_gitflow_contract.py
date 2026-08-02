"""Regression coverage for the four-repository GitFlow policy."""

from pathlib import Path


CONTRACT = Path(__file__).parents[1] / "docs/gitflow-contract.md"
RELEASE_CONTRACT = Path(__file__).parents[1] / "docs/release-contract.md"


def test_gitflow_contract_has_exactly_the_four_in_scope_repositories() -> None:
    content = CONTRACT.read_text(encoding="utf-8")

    repositories = {
        "genomes_agentic_os",
        "genomes_agentic_harness",
        "genomes_agentic_lib",
        "genomes_agentic_brain",
    }
    assert all(f"`{repository}`" in content for repository in repositories)
    assert "`genomes_agentic_platform` is not part of this contract." in content


def test_gitflow_contract_requires_reviewed_promotion_and_forward_ports() -> None:
    content = CONTRACT.read_text(encoding="utf-8")

    assert "Normal feature and fix\npull requests target `develop`." in content
    assert "`release/vX.Y.Z`" in content
    assert "`hotfix/vX.Y.Z`" in content
    assert "forward-port the exact fix to\n`develop`" in content
    assert "provider readback" in content


def test_release_contract_defers_branch_topology_to_gitflow_contract() -> None:
    content = RELEASE_CONTRACT.read_text(encoding="utf-8")

    assert "[GitFlow contract](gitflow-contract.md)" in content
    assert "`integration_ref` is therefore `develop`" in content
    assert "`release_ref` is `main`" in content
