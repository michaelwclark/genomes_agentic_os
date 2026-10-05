from copy import deepcopy

import pytest

from genomes_agentic_os.auto_dev_orchestration import (
    AUTO_DEV_STAGE_ORDER, AutoDevStateError, _stage_row,
    plan_legacy_consumer_migration,
)


def legacy_pair(*, completion="health", status="ready"):
    order = [name for name in AUTO_DEV_STAGE_ORDER if name != "validate_production_release"]
    stages = {name: {**_stage_row(name), "status": "completed", "receipt_refs": [f"artifacts/{name}.json"]} for name in order}
    projection = {
        "schema": "auto-dev-work-item/v1", "work_item_id": "fixture", "canonical_work_id": "acme:app:fixture",
        "domain": "acme", "project": "app", "mode": "single_stage", "start_stage": "groom",
        "completion_stage": completion, "status": status, "current_stage": None, "stage_order": order,
        "stages": stages, "delivery": {"state": "local_validation"}, "compatibility": {},
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
    }
    task = {"auto_dev_mode": "single_stage", "auto_dev_start_stage": "groom",
            "auto_dev_completion_stage": completion, "auto_dev_stage_order": order,
            "state": "local_validation", "stage_receipts": {"develop": "exact-source-receipt"},
            "history": [{"state": "planned"}, {"state": "local_validation"}], "policy_fingerprint": "frozen"}
    return projection, task


def test_missing_execution_stays_pending_and_existing_evidence_is_preserved():
    projection, task = legacy_pair(status="completed")
    projection["custom_operator_field"] = {"preserve": [1, 2]}
    task["custom_operator_field"] = "keep"
    original = deepcopy((projection, task))
    result = plan_legacy_consumer_migration(projection, task)
    migrated, migrated_task = result["projection"], result["task"]
    assert result["new_pending_stages"] == ["validate_production_release"]
    assert migrated["current_stage"] == "validate_production_release" and migrated["status"] == "ready"
    missing = migrated["stages"]["validate_production_release"]
    assert missing["status"] == "not_started"
    assert missing["run_ref"] is None and missing["receipt_refs"] == [] and missing["last_verified_at"] is None
    assert all(migrated["stages"][name] == row for name, row in projection["stages"].items())
    assert migrated["custom_operator_field"] == projection["custom_operator_field"]
    assert migrated_task["history"] == task["history"] and migrated_task["stage_receipts"] == task["stage_receipts"]
    assert migrated_task["state"] == "local_validation" and (projection, task) == original
    assert not result["execution_receipts_created"] and not result["delivery_lifecycle_changed"]


@pytest.mark.parametrize("status", ["blocked", "paused"])
def test_blocked_or_paused_admission_is_preserved(status):
    projection, task = legacy_pair(status=status)
    projection["blocker"] = {"kind": "independent-review-unavailable", "unavailable_policy": "block"}
    result = plan_legacy_consumer_migration(projection, task)
    assert result["projection"]["status"] == status and result["projection"]["blocker"] == projection["blocker"]


def test_new_stage_outside_window_is_out_of_scope_without_receipts():
    projection, task = legacy_pair(completion="develop")
    result = plan_legacy_consumer_migration(projection, task)
    row = result["projection"]["stages"]["validate_production_release"]
    assert row["status"] == "out_of_scope" and row["receipt_refs"] == [] and result["new_pending_stages"] == []


def test_already_current_contract_is_a_pure_noop():
    projection, task = legacy_pair()
    migrated = plan_legacy_consumer_migration(projection, task)
    result = plan_legacy_consumer_migration(migrated["projection"], migrated["task"])
    assert not result["changed"] and result["projection"] == migrated["projection"] and result["task"] == migrated["task"]


def test_existing_required_stage_policy_metadata_and_frozen_gates_are_preserved():
    projection, task = legacy_pair()
    policy = {"applicability": "required", "frozen_policy_ref": "keep", "unavailable_policy": "block", "custom": {"receipt": "exact"}}
    projection["stage_policies"] = {"validate_production_release": deepcopy(policy)}
    task["auto_dev_stage_policies"] = {"validate_production_release": deepcopy(policy)}
    result = plan_legacy_consumer_migration(projection, task)
    assert result["projection"]["stage_policies"]["validate_production_release"] == policy
    assert result["task"]["auto_dev_stage_policies"]["validate_production_release"] == policy
    assert result["task"]["policy_fingerprint"] == task["policy_fingerprint"]


def test_current_order_missing_required_execution_row_is_explicitly_pending():
    projection, task = legacy_pair(status="completed")
    projection["stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    task["auto_dev_stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    result = plan_legacy_consumer_migration(projection, task)
    assert result["changed"] and result["from_contract"] == "auto-dev-stage-order/current-missing-production-release/v1"
    assert result["projection"]["current_stage"] == "validate_production_release"
    assert result["projection"]["status"] == "ready"
    assert result["projection"]["stages"]["validate_production_release"]["receipt_refs"] == []


@pytest.mark.parametrize("row", [None, {}, {"status": "completed"}])
def test_incomplete_present_current_stage_rows_are_refused(row):
    projection, task = legacy_pair(status="completed")
    projection["stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    task["auto_dev_stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    projection["stages"]["validate_production_release"] = row
    with pytest.raises(AutoDevStateError, match="incomplete or malformed"):
        plan_legacy_consumer_migration(projection, task)


@pytest.mark.parametrize("applicability", ["disabled", "contextual", None, "unknown"])
def test_conflicting_required_stage_policy_is_refused(applicability):
    projection, task = legacy_pair()
    task["auto_dev_stage_policies"] = {"validate_production_release": {"applicability": applicability}}
    with pytest.raises(AutoDevStateError, match="conflicts"):
        plan_legacy_consumer_migration(projection, task)


@pytest.mark.parametrize("task_schema", ["development-task/v99", "different-task/v1", None, 99])
def test_explicit_future_or_unknown_task_version_is_refused(task_schema):
    projection, task = legacy_pair(); task["schema"] = task_schema
    with pytest.raises(AutoDevStateError, match="task schema version"):
        plan_legacy_consumer_migration(projection, task)


@pytest.mark.parametrize("versioned", [False, True])
def test_known_task_v1_and_explicit_structural_unversioned_legacy_handling(versioned):
    projection, task = legacy_pair()
    if versioned: task["schema"] = "development-task/v1"
    result = plan_legacy_consumer_migration(projection, task)
    assert result["task_contract"] == ("development-task/v1" if versioned else "development-task/legacy-unversioned")
    assert ("schema" in result["task"]) is versioned



@pytest.mark.parametrize("mutation", ["future-schema", "unknown-stage", "missing-stage", "running", "boundary", "task-order", "divergent-new-stage"])
def test_unknown_or_unsafe_contracts_are_refused(mutation):
    projection, task = legacy_pair()
    if mutation == "future-schema": projection["schema"] = "auto-dev-work-item/v99"
    if mutation == "unknown-stage": projection["stage_order"] = ["unknown"] + projection["stage_order"][1:]
    if mutation == "missing-stage": del projection["stages"]["groom"]
    if mutation == "running": projection["stages"]["develop"]["status"] = "running"
    if mutation == "boundary": task["auto_dev_completion_stage"] = "develop"
    if mutation == "task-order": task["auto_dev_stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    if mutation == "divergent-new-stage": projection["stages"]["validate_production_release"] = _stage_row("validate_production_release")
    with pytest.raises(AutoDevStateError): plan_legacy_consumer_migration(projection, task)
