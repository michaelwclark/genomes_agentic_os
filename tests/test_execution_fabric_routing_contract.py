from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from genomes_agentic_os.execution_fabric_remote import validate_task_route
from genomes_agentic_os.runtime_ops import runtime_init
from genomes_agentic_os.scaffold import (
    domain_router,
    domain_rules,
    domain_tools,
    project_router,
    project_rules,
    project_tools,
    root_router,
    root_rules,
    root_tools,
)


SOURCE_ROOT = Path(__file__).parents[1]


def test_generated_root_contract_routes_managed_execution_to_one_program() -> None:
    router = root_router()
    rules = root_rules()
    tools = root_tools()

    assert "Queue admission, worker capacity" in router
    assert "harness/shared_factory/00-programs/execution_fabric/" in router
    assert "folder counts, detached" in rules
    assert "admission, assignment, attempt, effect, and terminal run receipts" in rules
    assert "| `execution-fabric` |" in tools
    assert "| `agentic-os runtime snapshot` |" in tools
    assert "runtime config status/validate/reconcile" in tools


def test_generated_domain_and_project_contracts_inherit_fabric_authority() -> None:
    domain_documents = "\n".join(
        (domain_router("engineering"), domain_rules("engineering"), domain_tools("engineering"))
    )
    project_documents = "\n".join(
        (
            project_router("engineering", "example"),
            project_rules("engineering", "example"),
            project_tools("engineering", "example"),
        )
    )

    assert "shared Execution Fabric program" in domain_documents
    assert "do not create" in domain_documents
    assert "terminal receipts" in domain_documents
    assert "shared Execution Fabric program" in project_documents
    assert "Never use folder counts as a concurrency semaphore" in project_documents
    assert "Project config references task types/queues but does not copy" in project_documents


def test_installed_agent_config_template_carries_the_same_queue_contract() -> None:
    router = (SOURCE_ROOT / "templates/agent-config/ROUTER.md").read_text(encoding="utf-8")
    rules = (SOURCE_ROOT / "templates/agent-config/RULES.md").read_text(encoding="utf-8")
    tools = (SOURCE_ROOT / "templates/agent-config/TOOLS.md").read_text(encoding="utf-8")

    assert "Execution Fabric" in router
    assert "Folder counts, detached launches" in rules
    assert "terminal run receipts" in rules
    assert "| `execution-fabric` |" in tools
    assert "runtime config status/validate/reconcile" in tools


def test_cross_repo_task_route_fixtures_match_closed_canonical_policy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentic_os"
    runtime_init(root)
    fixture_path = SOURCE_ROOT / "tests/fixtures/execution_fabric_task_routes.json"
    expected_digest = (
        SOURCE_ROOT / "tests/fixtures/execution_fabric_task_routes.sha256"
    ).read_text(encoding="utf-8").split()[0]
    assert sha256(fixture_path.read_bytes()).hexdigest() == expected_digest
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for row in fixture["fixtures"]:
        route = validate_task_route(
            root,
            row["queue"],
            row["task_type"],
            payload=row["payload"],
            remote=True,
        )
        assert route["required_capability"] == row["required_capability"]
        assert route["domain_worker"] == row["domain_worker"]
        assert route["allowed_effect_types"] == row["allowed_effect_types"]
