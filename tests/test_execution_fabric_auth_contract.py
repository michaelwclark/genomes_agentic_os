from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/execution_fabric_auth_contract.json"
CHECKSUM = ROOT / "tests/fixtures/execution_fabric_auth_contract.sha256"


def test_cross_language_auth_contract_is_closed_and_session_bound() -> None:
    raw = FIXTURE.read_bytes()
    expected_digest, expected_name = CHECKSUM.read_text(encoding="utf-8").split()
    assert expected_name == FIXTURE.name
    assert hashlib.sha256(raw).hexdigest() == expected_digest
    contract = json.loads(raw)
    assert contract["schema_version"] == "execution-fabric-auth-contract/v2"
    assert set(contract["static_credentials"]) == {
        "submit",
        "worker_bootstrap",
        "observer",
        "admin",
        "effect_consumer",
        "alarm_dispatcher",
    }
    assert (
        contract["static_credentials"]["submit"]["endpoints"]
        == ["POST /api/v1/tasks"]
    )
    assert (
        contract["static_credentials"]["worker_bootstrap"]["endpoints"]
        == ["POST /api/v1/workers/register"]
    )
    assert contract["static_credentials"]["worker_bootstrap"]["bound_fields"] == [
        "bootstrapId",
        "workerId",
        "hostId",
        "queues",
        "capabilities",
        "maxConcurrency",
    ]
    assert all(
        endpoint.startswith("GET ")
        for endpoint in contract["static_credentials"]["observer"]["endpoints"]
    )
    assert contract["static_credentials"]["effect_consumer"]["bound_fields"] == [
        "consumerId",
        "source",
        "effectTypes",
    ]
    assert contract["static_credentials"]["alarm_dispatcher"]["bound_fields"] == [
        "consumerId",
        "source",
    ]
    for session in contract["session_credentials"].values():
        assert session["bearer_and_body_must_match"] is True
    assert contract["session_credentials"]["lease_token"]["bound_fields"] == [
        "attemptId",
        "workerId",
        "fabricEpoch",
    ]
    assert contract["response_contracts"]["no_assignment"] == {
        "status": 204,
        "body": None,
    }
    assert contract["source_credentials"]["reliability_observation"] == {
        "source_token_map_file_environment": (
            "FABRIC_RELIABILITY_SOURCE_TOKENS_FILE"
        ),
        "endpoint": "POST /api/v1/reliability/observations",
        "body_source_must_match_token_scope": True,
    }
