"""Conformance coverage for the AGE-152 provider-neutral evidence port."""

from __future__ import annotations

import ast
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from genomes_agentic_os.run_evidence import (
    EvidenceRecord,
    InMemoryRunLogStore,
    RunLogStoreConfigurationError,
    UnknownHostError,
    build_configured_run_log_store,
    build_run_log_store,
    load_run_log_store_config,
)


REPO = Path(__file__).parents[1]


def _store() -> InMemoryRunLogStore:
    config = replace(load_run_log_store_config(REPO), backend="memory")
    store = build_configured_run_log_store(REPO, config=config)
    assert isinstance(store, InMemoryRunLogStore)
    assert store.get_host("bigmac")["aliases"] == ["bigmac.local"]  # type: ignore[index]
    return store


def _record(**overrides: object) -> EvidenceRecord:
    values: dict[str, object] = {
        "model_key": "run_log",
        "host_id": "bigmac",
        "source": "tests",
        "classification": "durable_evidence",
        "payload": {"result": "success"},
        "payload_metadata": {"format": "json"},
        "occurred_at": "2026-08-08T00:00:00Z",
        "schema_version": 1,
        "correlation_id": "age-152",
        "run_id": "run-152",
        "work_item_id": "AGE-152",
    }
    values.update(overrides)
    return EvidenceRecord(**values)  # type: ignore[arg-type]


def test_memory_fake_satisfies_append_search_aggregate_and_idempotency_contract() -> None:
    store = _store()
    first = store.append(_record())
    duplicate = store.import_idempotently([_record()])[0]

    assert duplicate["id"] == first["id"]
    assert store.get("run_log", first["id"])["host_id"] == "bigmac"  # type: ignore[index]
    assert [item["id"] for item in store.search("run_log", correlation_id="age-152")] == [first["id"]]
    assert store.aggregate("run_log", "host_id") == {"bigmac": 1}
    assert store.health()["ready"] is True


def test_memory_idempotency_canonicalizes_reordered_nested_payloads() -> None:
    store = _store()
    first = store.append(_record(payload={"result": "success", "nested": {"one": 1, "two": 2}}))
    duplicate = store.import_idempotently(
        [_record(id="reordered", payload={"nested": {"two": 2, "one": 1}, "result": "success"})]
    )[0]

    assert duplicate["id"] == first["id"]
    assert duplicate["content_hash"] == first["content_hash"]


def test_store_rejects_unknown_hosts_and_wrong_model_schema() -> None:
    store = _store()
    with pytest.raises(UnknownHostError, match="unknown evidence host"):
        store.append(_record(host_id="unknown"))
    with pytest.raises(Exception, match="schema version"):
        store.append(_record(schema_version=99))


def test_batch_validation_happens_before_any_fake_mutation() -> None:
    store = _store()
    with pytest.raises(UnknownHostError):
        store.append_many([_record(id="first"), _record(id="invalid", host_id="missing")])
    assert store.get("run_log", "first") is None


def test_retention_obeys_registry_age_and_count_limits() -> None:
    store = _store()
    store.append(_record(id="old", occurred_at="2020-01-01T00:00:00Z", content_hash="a" * 64))
    assert store.apply_retention("run_log", now=datetime(2026, 8, 8, tzinfo=UTC)) == 1


def test_mongodb_is_selected_only_at_the_composition_root() -> None:
    config = load_run_log_store_config(REPO)
    fake_client = {config.database: object()}
    store = build_run_log_store(config, client=fake_client)
    assert store.backend == "mongodb"

    with pytest.raises(RunLogStoreConfigurationError, match="AGENTIC_OS_MONGODB_URI"):
        build_run_log_store(config)


def test_port_does_not_import_driver_or_concrete_adapter() -> None:
    port_path = REPO / "src" / "genomes_agentic_os" / "run_evidence" / "store.py"
    tree = ast.parse(port_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "pymongo" not in imports


@pytest.mark.skipif(not os.environ.get("AGENTIC_OS_MONGODB_INTEGRATION_URI"), reason="MongoDB integration profile is opt-in")
def test_mongodb_integration_profile_can_ping_selected_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run only with a least-privilege disposable integration URI."""
    config = load_run_log_store_config(REPO)
    monkeypatch.setenv(config.uri_env, os.environ["AGENTIC_OS_MONGODB_INTEGRATION_URI"])
    store = build_run_log_store(config)
    assert store.health()["ready"] is True
