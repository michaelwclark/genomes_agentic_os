from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.runtime_ops import runtime_init
from genomes_agentic_os.scaffold import create_workflow, init_os
from genomes_agentic_os.workflow_engine import (
    DEFINITION_FILE,
    INSTANCE_FILE,
    create_workflow_definition,
    get_workflow_resource,
    publish_workflow,
    query_workflow_resources,
    rollback_workflow_action,
    update_workflow_definition,
    validate_workflow_definition,
    workflow_run_now,
)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    init_os(root)
    runtime_init(root)
    return root


def _definition(**changes) -> dict:
    value = {
        "schema_version": 1,
        "resource_kind": "workflow_definition",
        "id": "release_review",
        "domain": "work",
        "lane": "engineering",
        "name": "Release Review",
        "summary": "Review a release with explicit evidence and approval gates.",
        "owner": "OS Owner",
        "availability": "active",
        "health": "healthy",
        "version": "1.0.0",
        "inputs": {"release": {"type": "string"}},
        "outputs": {"decision": {"type": "string"}},
        "approvals": [],
        "retry": {"max_attempts": 1, "backoff_seconds": 0},
        "failure_policy": "stop",
        "prompts": ["Review verified release evidence."],
        "agents": ["release_reviewer"],
        "models": ["routed"],
        "linked_capabilities": [{"kind": "skill", "id": "pull_request"}],
        "publish": {"allowed": True},
        "future_extension": {"keep": True},
        "steps": [
            {
                "id": "collect_evidence",
                "name": "Collect evidence",
                "summary": "Collect bounded release evidence.",
                "order": 1,
                "kind": "skill",
                "depends_on": [],
                "skills": ["pull_request"],
                "inputs": {},
                "outputs": {"evidence": {}},
                "approvals": [],
                "retry": {"max_attempts": 2, "backoff_seconds": 5},
                "failure_policy": "stop",
                "future_step_extension": "preserve",
            },
            {
                "id": "approve_release",
                "name": "Approve release",
                "summary": "Record the guarded release decision.",
                "order": 2,
                "kind": "approval",
                "depends_on": ["collect_evidence"],
                "inputs": {"evidence": {}},
                "outputs": {"decision": {}},
                "approvals": ["release_owner"],
                "retry": {"max_attempts": 1, "backoff_seconds": 0},
                "failure_policy": "require_approval",
            },
        ],
    }
    value.update(changes)
    return value


def _create(root: Path) -> dict:
    planned = create_workflow_definition(root, _definition())
    return create_workflow_definition(
        root,
        _definition(),
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )


def _publish(root: Path) -> dict:
    planned = publish_workflow(root, "release_review", domain="work", lane="engineering")
    return publish_workflow(
        root,
        "release_review",
        domain="work",
        lane="engineering",
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )


def test_legacy_workflow_projects_as_partial_without_fabricating_steps(tmp_path: Path) -> None:
    root = _root(tmp_path)
    create_workflow(root, "work", "engineering", "legacy_review")
    create_workflow(root, "work", "engineering", "malformed_review")
    (root / "work/03-workflows/engineering/malformed_review" / DEFINITION_FILE).write_text("steps: [\n", encoding="utf-8")

    result = query_workflow_resources(root, "definition", domain="work", lane="engineering")
    legacy = next(item for item in result["items"] if item["id"] == "legacy_review")
    malformed = next(item for item in result["items"] if item["id"] == "malformed_review")

    assert legacy["source_state"] == "partial"
    assert legacy["managed"] is False
    assert legacy["editable"] is False
    assert legacy["steps"] == []
    assert legacy["partial_sources"] == [DEFINITION_FILE]
    assert malformed["source_state"] == "invalid"
    assert malformed["validation"]["findings"][0]["code"] == "definition_parse_error"
    assert result["source_health"] == {
        "status": "invalid",
        "partial_count": 1,
        "invalid_count": 1,
    }


def test_validation_maps_invalid_order_dependency_and_cycle_to_steps(tmp_path: Path) -> None:
    root = _root(tmp_path)
    invalid = _definition()
    invalid["steps"][0]["order"] = 2
    invalid["steps"][0]["depends_on"] = ["approve_release"]
    invalid["steps"][1]["order"] = 1
    invalid["steps"][1]["depends_on"] = ["collect_evidence", "missing_step"]

    result = validate_workflow_definition(root, invalid)
    codes = {item["code"] for item in result["findings"]}

    assert result["ok"] is False
    assert {"invalid_step_order", "dependency_not_prior", "unknown_step_dependency", "step_dependency_cycle"}.issubset(codes)
    assert all(item["path"].startswith("$") for item in result["findings"])
    assert any(item.get("step_id") == "approve_release" for item in result["findings"])


def test_create_is_dry_run_first_and_reads_back_distinct_definition_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    planned = create_workflow_definition(root, _definition())
    workflow_root = root / "work/03-workflows/engineering/release_review"

    assert planned["status"] == "planned"
    assert not workflow_root.exists()
    with pytest.raises(ValueError, match="expected-drift-hash"):
        create_workflow_definition(root, _definition(), dry_run=False)

    applied = create_workflow_definition(
        root,
        _definition(),
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )

    assert applied["readback"]["ok"] is True
    assert (workflow_root / DEFINITION_FILE).is_file()
    fetched = get_workflow_resource(root, "definition", "release_review", domain="work", lane="engineering")["resource"]
    assert fetched["definition_id"] == "workflow_definition:work:engineering:release_review"
    assert fetched["relationships"]["instance_id"] is None
    assert fetched["source_state"] == "complete"


def test_update_preserves_unknown_fields_rejects_loss_and_stale_bases(tmp_path: Path) -> None:
    root = _root(tmp_path)
    created = _create(root)
    changes = {
        "summary": "Updated summary.",
        "steps": [
            {"id": "collect_evidence", "summary": "Updated evidence summary.", "order": 1},
            {"id": "approve_release", "order": 2},
        ],
    }
    planned = update_workflow_definition(root, "release_review", changes, domain="work", lane="engineering")
    applied = update_workflow_definition(
        root,
        "release_review",
        changes,
        domain="work",
        lane="engineering",
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )

    readback = applied["readback"]["definition"]
    assert readback["future_extension"] == {"keep": True}
    assert readback["steps"][0]["future_step_extension"] == "preserve"
    assert readback["steps"][0]["summary"] == "Updated evidence summary."

    with pytest.raises(ValueError, match="destructively remove steps"):
        update_workflow_definition(
            root,
            "release_review",
            {"steps": [deepcopy(readback["steps"][0])]},
            domain="work",
            lane="engineering",
        )

    definition_path = root / "work/03-workflows/engineering/release_review" / DEFINITION_FILE
    definition_path.write_text(definition_path.read_text() + "\nexternal_edit: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale workflow plan"):
        update_workflow_definition(
            root,
            "release_review",
            {"summary": "Stale update."},
            domain="work",
            lane="engineering",
            expected_drift_hash=created["drift"]["after"],
            dry_run=False,
        )


def test_publish_creates_immutable_version_and_separate_instance(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _create(root)
    published = _publish(root)

    version = published["readback"]["version"]
    instance = published["readback"]["instance"]
    assert version["resource_kind"] == "workflow_version"
    assert instance["resource_kind"] == "workflow_instance"
    assert version["id"] != instance["id"]
    assert instance["version_id"] == version["id"]
    assert (root / "work/03-workflows/engineering/release_review" / INSTANCE_FILE).is_file()

    versions = query_workflow_resources(root, "version", workflow="release_review")["items"]
    instances = query_workflow_resources(root, "instance", workflow="release_review")["items"]
    assert [item["id"] for item in versions] == [version["id"]]
    assert [item["id"] for item in instances] == [instance["id"]]

    repeat_plan = publish_workflow(root, "release_review", domain="work", lane="engineering")
    repeated = publish_workflow(
        root,
        "release_review",
        domain="work",
        lane="engineering",
        expected_drift_hash=repeat_plan["drift"]["before"],
        dry_run=False,
    )
    assert repeated["version_created"] is False
    assert repeated["readback"]["version"]["id"] == version["id"]

    update_plan = update_workflow_definition(
        root,
        "release_review",
        {"summary": "Changed without a version bump."},
        domain="work",
        lane="engineering",
    )
    update_workflow_definition(
        root,
        "release_review",
        {"summary": "Changed without a version bump."},
        domain="work",
        lane="engineering",
        expected_drift_hash=update_plan["drift"]["before"],
        dry_run=False,
    )
    with pytest.raises(ValueError, match="immutable"):
        publish_workflow(root, "release_review", domain="work", lane="engineering")


def test_denied_publish_is_blocked_by_definition_policy(tmp_path: Path) -> None:
    root = _root(tmp_path)
    definition = _definition(publish={"allowed": False})
    planned = create_workflow_definition(root, definition)
    create_workflow_definition(root, definition, expected_drift_hash=planned["drift"]["before"], dry_run=False)

    with pytest.raises(ValueError, match="denied"):
        publish_workflow(root, "release_review", domain="work", lane="engineering")


def test_run_now_is_idempotent_queue_only_and_never_claims_execution(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    _create(root)
    _publish(root)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("workflow run-now must not launch a process")

    monkeypatch.setattr("subprocess.run", forbidden)
    planned = workflow_run_now(
        root,
        "release_review",
        domain="work",
        lane="engineering",
        idempotency_key="cc311:queue:test",
    )
    assert planned["dispatch_performed"] is False
    assert planned["run"]["execution_status"] == "not_started"

    first = workflow_run_now(
        root,
        "release_review",
        domain="work",
        lane="engineering",
        idempotency_key="cc311:queue:test",
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )
    second = workflow_run_now(
        root,
        "release_review",
        domain="work",
        lane="engineering",
        idempotency_key="cc311:queue:test",
        expected_drift_hash=planned["drift"]["before"],
        dry_run=False,
    )

    assert first["queue_created"] is True
    assert second["queue_created"] is False
    assert first["readback"]["queue_item"]["dispatch_performed"] is False
    assert "command" not in first["readback"]["queue_item"]
    run_id = first["run"]["id"]
    run = get_workflow_resource(root, "run", run_id)["resource"]
    assert run["status"] == "queued"
    assert run["execution_contract"] == "harness_worker_required"


def test_run_now_uses_only_governed_harness_routes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    definition = _definition(execution={"harness": "claude"})
    plan = create_workflow_definition(root, definition)
    create_workflow_definition(
        root,
        definition,
        expected_drift_hash=plan["drift"]["before"],
        dry_run=False,
    )
    _publish(root)

    run_plan = workflow_run_now(root, "release_review", domain="work", lane="engineering")
    assert run_plan["queue_item"]["execution_target"] == "claude_harness"
    assert run_plan["run"]["execution_target"] == "claude_harness"

    invalid = _definition(execution={"harness": "arbitrary_remote_shell"})
    validation = validate_workflow_definition(root, invalid)
    assert validation["ok"] is False
    assert any(finding["path"] == "$.execution.harness" for finding in validation["findings"])


def test_rollback_restores_exact_definition_and_rejects_newer_state(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _create(root)
    before = get_workflow_resource(root, "definition", "release_review", domain="work", lane="engineering")["resource"]
    plan = update_workflow_definition(
        root,
        "release_review",
        {"summary": "Temporary change."},
        domain="work",
        lane="engineering",
    )
    changed = update_workflow_definition(
        root,
        "release_review",
        {"summary": "Temporary change."},
        domain="work",
        lane="engineering",
        expected_drift_hash=plan["drift"]["before"],
        dry_run=False,
    )
    rollback_plan = rollback_workflow_action(root, changed["receipt_id"])
    rolled_back = rollback_workflow_action(
        root,
        changed["receipt_id"],
        expected_drift_hash=rollback_plan["drift"]["before"],
        dry_run=False,
    )
    after = get_workflow_resource(root, "definition", "release_review", domain="work", lane="engineering")["resource"]
    assert rolled_back["readback"] == {"ok": True, "restored": True}
    assert after["summary"] == before["summary"]

    with pytest.raises(ValueError, match="changed after"):
        rollback_workflow_action(root, changed["receipt_id"])


def test_publish_rollback_removes_new_version_and_instance_pointer(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _create(root)
    published = _publish(root)
    version_id = published["readback"]["version"]["id"]
    instance_path = root / "work/03-workflows/engineering/release_review" / INSTANCE_FILE

    assert instance_path.is_file()
    assert get_workflow_resource(root, "version", version_id)["resource"]["id"] == version_id

    rollback_plan = rollback_workflow_action(root, published["receipt_id"])
    rolled_back = rollback_workflow_action(
        root,
        published["receipt_id"],
        expected_drift_hash=rollback_plan["drift"]["before"],
        dry_run=False,
    )

    assert rolled_back["readback"] == {"ok": True, "restored": True}
    assert not instance_path.exists()
    with pytest.raises(ValueError, match="unknown workflow version"):
        get_workflow_resource(root, "version", version_id)


def test_cli_contract_returns_json_and_apply_requires_plan_hash(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    definition_file = tmp_path / "workflow.yml"
    definition_file.write_text(yaml.safe_dump(_definition(), sort_keys=False), encoding="utf-8")

    assert main(["workflow", "validate", "--definition-file", str(definition_file), "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["api_version"] == "workflow-engine/v1"

    assert main(["workflow", "create", "--definition-file", str(definition_file), "--root", str(root), "--json"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert main(
        [
            "workflow",
            "create",
            "--definition-file",
            str(definition_file),
            "--expected-drift-hash",
            planned["drift"]["before"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["readback"]["ok"] is True

    assert main(["workflow", "query", "definition", "--domain", "work", "--root", str(root), "--json"]) == 0
    queried = json.loads(capsys.readouterr().out)
    assert queried["items"][0]["definition_id"].startswith("workflow_definition:")


@pytest.mark.parametrize("invalid_id", ["../escape", "has-hyphen", "UPPER", "has space"])
def test_fixed_routing_rejects_invalid_identity(tmp_path: Path, invalid_id: str) -> None:
    root = _root(tmp_path)
    definition = _definition(id=invalid_id)
    with pytest.raises(ValueError, match="lowercase letters"):
        create_workflow_definition(root, definition)
