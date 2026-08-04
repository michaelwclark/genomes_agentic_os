from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.context_contracts import load_context_manifest, path_is_excluded, resolve_context_contract
from genomes_agentic_os.routing import _nearest_contract_target, build_context


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_resolve_inherits_parent_contracts_and_central_provider_routes(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "domains" / "acme"
    target = domain / "03-workflows" / "engineering" / "ship_release"
    write(root / "AGENTS.md", "# Root agent\n")
    write(root / "RULES.md", "# Shared safe rule\n")
    write(domain / "RULES.md", "# Shared safe rule\n")
    write(domain / "TOOLS.md", "# Domain tools\n")
    write(target / "workflow.md", "# Workflow\n")
    write(target / "runbook.md", "# Runbook\n")
    write(
        target / "context-contract.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "workflow",
                "inherits": ["parent"],
                "read": {
                    "first": ["workflow.md"],
                    "deferred": ["runbook.md"],
                    "exclude": ["runs/**"],
                },
                "capabilities": ["ship-release"],
                "providers": {"github": ["github_mcp", "github_cli"]},
                "overrides": {"rules": ["require-green-ci"]},
            },
            sort_keys=False,
        ),
    )
    write(
        root / "harness/registries/composio-tools.yml",
        yaml.safe_dump(
            {
                "composio_tools": [
                    {"id": "jira_genome", "provider_priority": ["atlassian_cli", "jira_mcp"]}
                ]
            }
        ),
    )

    resolved = resolve_context_contract(target, root=root)

    assert resolved.ok
    assert not resolved.legacy_fallback
    assert any(source.path == root / "AGENTS.md" for source in resolved.read_first)
    assert any(source.path == target / "workflow.md" for source in resolved.read_first)
    assert any(source.path == target / "runbook.md" for source in resolved.deferred)
    assert resolved.capabilities["ship-release"]["declared_by"].endswith("context-contract.yml")
    assert resolved.providers["jira_genome"]["source"] == "central_registry"
    assert resolved.providers["github"]["source"] == "manifest_override"
    assert resolved.skipped_duplicates[0]["path"].endswith("acme/RULES.md")
    assert "runs/**" in resolved.excluded


def test_legacy_sources_are_preserved_when_manifest_is_absent(tmp_path: Path) -> None:
    target = tmp_path / "workflow"
    source = write(target / "quick-reference.md", "# Start\n")

    resolved = resolve_context_contract(target, root=tmp_path, legacy_sources=[source])

    assert resolved.ok
    assert resolved.legacy_fallback
    assert [item.path for item in resolved.read_first] == [source]
    assert resolved.diagnostics[0].code == "legacy_fallback"


def test_nearest_contract_target_does_not_walk_above_the_installed_root(tmp_path: Path) -> None:
    root = tmp_path / "os"
    linked_feature = tmp_path / "source-package" / "features" / "ticket"
    linked_feature.mkdir(parents=True)

    assert _nearest_contract_target(linked_feature, root) == root


def test_manifest_rejects_unsafe_relative_paths(tmp_path: Path) -> None:
    target = tmp_path / "workflow"
    write(
        target / "context-contract.yml",
        "schema_version: 1\nkind: workflow\ninherits: []\nread:\n  first: [../secret]\n",
    )

    with pytest.raises(ValueError, match="safe relative paths"):
        load_context_manifest(target)


def test_default_search_exclusions_cover_high_volume_evidence() -> None:
    assert path_is_excluded("los/worktrees/old/src.py")
    assert path_is_excluded("los/06-runs-and-logs/runs/123/run-log.md")
    assert path_is_excluded("project/artifacts/large.json")
    assert not path_is_excluded("los/03-workflows/engineering/ship/workflow.md")


def test_role_tagged_holdout_is_excluded_at_the_packet_load_chokepoint(tmp_path: Path) -> None:
    root = tmp_path / "os"
    workflow = root / "domains" / "acme" / "03-workflows" / "engineering" / "ship_release"
    workflow_file = write(workflow / "workflow.md", "# Workflow\n")
    always_excluded = write(workflow / "private.md", "# Never load\n")
    holdout = write(workflow / "holdout.md", "# Private holdout\n")
    write(
        workflow / "context-contract.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "workflow",
                "inherits": [],
                "read": {
                    "first": ["workflow.md", "private.md", "holdout.md"],
                    "exclude": ["private.md", "role:implementation:holdout.md"],
                },
            },
            sort_keys=False,
        ),
    )

    default_packet = build_context(root, domain="acme", workflow="ship_release", lane="engineering")
    implementation_packet = build_context(
        root,
        domain="acme",
        workflow="ship_release",
        lane="engineering",
        role="implementation",
    )

    assert workflow_file in default_packet.sources_to_load
    assert always_excluded not in default_packet.sources_to_load
    assert holdout in default_packet.sources_to_load
    assert workflow_file in implementation_packet.sources_to_load
    assert always_excluded not in implementation_packet.sources_to_load
    assert holdout not in implementation_packet.sources_to_load


def test_domain_contract_excludes_an_inbox_source_at_the_final_packet_target(tmp_path: Path) -> None:
    root = tmp_path / "os"
    domain = root / "domains" / "acme"
    raw_ideas = write(domain / "01-inbox" / "raw-ideas.md", "# Private intake\n")
    write(
        domain / "context-contract.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "domain",
                "inherits": [],
                "read": {"exclude": ["01-inbox/raw-ideas.md"]},
            },
            sort_keys=False,
        ),
    )

    packet = build_context(root, domain="acme", inbox=True)

    assert raw_ideas not in packet.sources_to_load


def test_project_contract_excludes_a_selected_work_item_holdout(tmp_path: Path) -> None:
    root = tmp_path / "os"
    project = root / "domains" / "acme" / "02-projects" / "app"
    work_item = project / "work-items" / "ticket"
    holdout = write(work_item / "HOLDOUT_QA.md", "# Holdout\n")
    write(work_item / "SPEC.md", "# Spec\n")
    write(work_item / "PLAN.md", "# Plan\n")
    write(work_item / "WORKLOG.md", "# Worklog\n")
    write(work_item / "NEXT.md", "# Next\n")
    write(work_item / "work.yml", "id: ticket\ntitle: Ticket\nstatus: validating\n")
    write(
        project / "context-contract.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "project",
                "inherits": [],
                "read": {"exclude": ["work-items/ticket/HOLDOUT_QA.md"]},
            },
            sort_keys=False,
        ),
    )

    packet = build_context(root, domain="acme", project="app", work_item="ticket")

    assert holdout not in packet.sources_to_load
