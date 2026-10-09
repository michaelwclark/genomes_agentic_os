"""The fixed recovery canary validates data in memory and cannot dispatch work."""
import copy
from uuid import uuid4

import pytest

from genomes_agentic_os.execution_fabric_cold_canary import (
    CANARY_CAPABILITY, CANARY_HANDLER, CANARY_NAMESPACE, CANARY_QUEUE,
    CANARY_TASK_TYPE, canary_result, cold_canary_worker, validate_canary_payload,
)


@pytest.fixture
def inert_assignment():
    payload = {"schema_version": "execution-fabric-cold-canary/v1", "recovery_id": str(uuid4()),
               "cluster_id": "isolated", "epoch": 7, "generation": 3}
    task = {"id": str(uuid4()), "taskType": CANARY_TASK_TYPE, "queue": CANARY_QUEUE,
            "namespace": CANARY_NAMESPACE, "payload": payload, "requiredCapabilities": [CANARY_CAPABILITY]}
    route = {"domain_worker": CANARY_HANDLER, "command_template": None, "allowed_effect_types": []}
    return {"fabricEpoch": 7, "task": task}, route


def test_fixed_canary_returns_only_exact_binding(inert_assignment):
    assignment, route = inert_assignment
    original = copy.deepcopy(assignment)
    result = cold_canary_worker(None, assignment, assignment["task"], route)
    assert result == {"result": canary_result(assignment["task"]["payload"], assignment["task"]["id"]), "effects": [], "artifacts": []}
    assert assignment == original


@pytest.mark.parametrize("change", [{"command": "never"}, {"instruction": "never"}, {"url": "https://never.invalid"},
                                    {"epoch": True}, {"generation": 0}, {"recovery_id": "missing"}, {"cluster_id": ""}])
def test_fixed_canary_refuses_open_or_invalid_payload(inert_assignment, change):
    assignment, route = inert_assignment
    assignment["task"]["payload"].update(change)
    with pytest.raises(ValueError):
        cold_canary_worker(None, assignment, assignment["task"], route)


@pytest.mark.parametrize("field,value", [("taskType", "llm.claude"), ("queue", "codex"), ("namespace", "ordinary"),
                                        ("requiredCapabilities", [])])
def test_fixed_canary_refuses_foreign_task(inert_assignment, field, value):
    assignment, route = inert_assignment
    assignment["task"][field] = value
    with pytest.raises(ValueError, match="fixed inert"):
        cold_canary_worker(None, assignment, assignment["task"], route)


def test_fixed_canary_refuses_stale_epoch_and_route(inert_assignment):
    assignment, route = inert_assignment
    assignment["fabricEpoch"] = 6
    with pytest.raises(ValueError, match="signed recovery binding"):
        cold_canary_worker(None, assignment, assignment["task"], route)
    assignment["fabricEpoch"] = 7
    route["command_template"] = ["never"]
    with pytest.raises(ValueError, match="fixed inert"):
        cold_canary_worker(None, assignment, assignment["task"], route)


def test_fixed_canary_signed_plan_binding(inert_assignment):
    assignment, _ = inert_assignment
    with pytest.raises(ValueError, match="signed recovery binding"):
        validate_canary_payload(assignment["task"]["payload"], generation=4)
