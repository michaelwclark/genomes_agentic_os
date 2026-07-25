from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/execution_fabric_reliability_observation.json"
CHECKSUM = ROOT / "tests/fixtures/execution_fabric_reliability_observation.sha256"


def test_reliability_observation_contract_is_source_scoped_closed_and_stable() -> None:
    raw = FIXTURE.read_bytes()
    expected_digest, expected_name = CHECKSUM.read_text(encoding="utf-8").split()
    assert expected_name == FIXTURE.name
    assert hashlib.sha256(raw).hexdigest() == expected_digest

    contract = json.loads(raw)
    assert (
        contract["schema_version"]
        == "execution-fabric-reliability-observation-contract/v1"
    )
    assert contract["endpoint"] == "POST /api/v1/reliability/observations"
    assert contract["authentication"] == {
        "type": "bearer",
        "scope": "reliability-source:<source>",
        "source_body_must_match_credential": True,
    }
    assert contract["request"]["additional_properties"] is False
    example = contract["request"]["example"]
    assert set(example) == set(contract["request"]["required"])
    assert example["source"] == "team-pr-runner"
    assert example["active"] is True
    assert example["affected"]["id"] == "a" * 32
    assert set(contract["forbidden_request_fields"]) >= {
        "command",
        "repair",
        "alertRoute",
        "notificationTarget",
    }
    assert contract["idempotency"] == {
        "key_fields": ["source", "incidentKey", "revision"],
        "same_content_status": 200,
        "new_revision_status": 201,
        "same_revision_different_content_status": 409,
        "stale_revision_status": 409,
        "recovery_requires_higher_revision": True,
    }
    recovery = contract["request"]["recovery_example"]
    assert set(recovery) == set(contract["request"]["required"])
    assert recovery["active"] is False
    assert recovery["severity"] == "warning"
    assert contract["recovery"] == {
        "active": False,
        "severity_must_remain": ["warning", "critical"],
        "finding_status": "resolved",
        "alarm_status": "resolved_awaiting_ack",
        "repair_status": "cancelled",
        "operator_ack_required": True,
    }
