"""Provider-neutral payload boundaries through the actual store consumers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from genomes_agentic_os.run_evidence import EvidenceRecord, InMemoryRunLogStore, RunLogStoreConfig
from genomes_agentic_os.run_evidence.adapters.mongodb import MongoDBRunLogStore
from genomes_agentic_os.run_evidence.store import PayloadValidationError, RunLogStoreConfigurationError, validate_payload
from test_mongodb_run_log_store import _Database


def _record(payload: Any, **overrides: Any) -> EvidenceRecord:
    return EvidenceRecord(
        model_key="run_log", host_id="fixture-host", source="synthetic-test",
        classification="durable_evidence", payload=payload,
        occurred_at="2026-10-05T00:00:00Z", schema_version=1, **overrides,
    )


def _store(backend: str, limit: Any) -> tuple[Any, _Database | None]:
    config = RunLogStoreConfig(
        backend=backend, database="disposable", uri_env="UNUSED_SYNTHETIC_URI",
        models={"run_log": {
            "schema_version": 1, "classification": "durable_evidence",
            "collection": "run_log", "max_payload_bytes": limit,
        }}, initial_host="fixture-host", host_registry_source="unused.yml",
    )
    database = _Database() if backend == "mongodb" else None
    store = MongoDBRunLogStore(config, database) if database is not None else InMemoryRunLogStore(config)
    store.upsert_host({"host_id": "fixture-host"})
    return store, database


def _write(store: Any, method: str, record: EvidenceRecord) -> dict[str, Any]:
    return store.append(record) if method == "append" else getattr(store, method)([record])[0]


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
@pytest.mark.parametrize("method", ["append", "append_many", "import_idempotently"])
@pytest.mark.parametrize("payload,encoded", [
    ({"x": "abc"}, b'{"x": "abc"}'),
    ({"x": "\u00e9"}, b'{"x": "\\u00e9"}'),
    ({"x": "\U0001f600"}, b'{"x": "\\ud83d\\ude00"}'),
    ({"x": "\n\"\\"}, b'{"x": "\\n\\\"\\\\"}'),
    ({"a": [1, 2], "b": {"c": True}}, b'{"a": [1, 2], "b": {"c": true}}'),
])
def test_actual_stores_accept_equality_and_reject_one_byte_over(
    backend: str, method: str, payload: dict[str, Any], encoded: bytes,
) -> None:
    store, _ = _store(backend, len(encoded))
    assert _write(store, method, _record(payload))["payload"] == payload
    too_small, database = _store(backend, len(encoded) - 1)
    initial_operations = list(database.operations) if database is not None else []
    with pytest.raises(PayloadValidationError) as rejected:
        _write(too_small, method, _record(payload))
    assert rejected.value.error_code == "payload_too_large"
    assert rejected.value.retryable is False
    assert too_small.search("run_log") == []
    if database is not None:
        assert database.operations == initial_operations


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
def test_envelope_and_payload_metadata_are_excluded(backend: str) -> None:
    store, _ = _store(backend, 2)
    metadata = {"large": "synthetic" * 1000}
    record = _record({}, payload_metadata=metadata, correlation_id="fixture" * 1000)
    stored = store.append(record)
    assert stored["payload"] == {}
    assert stored["payload_metadata"] == metadata
    assert stored["correlation_id"] == record.correlation_id


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
@pytest.mark.parametrize("method", ["append_many", "import_idempotently"])
def test_later_invalid_payload_prevents_every_batch_provider_mutation(backend: str, method: str) -> None:
    store, database = _store(backend, 20)
    initial_operations = list(database.operations) if database is not None else []
    with pytest.raises(PayloadValidationError):
        getattr(store, method)([
            _record({"ok": True}, id="first"),
            _record({"secret": "synthetic-private-value"}, id="invalid"),
        ])
    assert store.search("run_log") == []
    if database is not None:
        assert database.operations == initial_operations


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
@pytest.mark.parametrize("method", ["append_many", "import_idempotently"])
def test_batch_uses_frozen_snapshots_after_validation(
    backend: str, method: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _store(backend, 30)
    later_payload = {"nested": {"value": "ok"}}
    original = store._append_document

    def mutate_caller_then_persist(model_key: str, document: dict[str, Any]) -> dict[str, Any]:
        later_payload["nested"]["value"] = "unexpected" * 1000
        return original(model_key, document)

    monkeypatch.setattr(store, "_append_document", mutate_caller_then_persist)
    records = getattr(store, method)([
        _record({"first": True}, id="first"), _record(later_payload, id="later"),
    ])
    assert records[1]["payload"] == {"nested": {"value": "ok"}}
    assert store.get("run_log", "later")["payload"] == {"nested": {"value": "ok"}}


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
def test_idempotency_does_not_bypass_payload_validation(backend: str) -> None:
    store, _ = _store(backend, 20)
    store.append(_record({"ok": True}, content_hash="same"))
    with pytest.raises(PayloadValidationError):
        store.import_idempotently([_record({"secret": "synthetic-private-value"}, content_hash="same")])
    assert len(store.search("run_log")) == 1


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
@pytest.mark.parametrize("limit", [None, 0, -1, True, "20"])
def test_legacy_manual_configuration_without_a_positive_limit_fails_closed(backend: str, limit: Any) -> None:
    store, database = _store(backend, limit)
    if limit is None:
        store.config = replace(store.config, models={"run_log": {
            key: value for key, value in store.config.models["run_log"].items() if key != "max_payload_bytes"
        }})
    with pytest.raises(RunLogStoreConfigurationError, match="max_payload_bytes must be a positive integer"):
        store.append(_record({}))
    assert store.search("run_log") == []
    if database is not None:
        assert "insert_one" not in database.operations


@pytest.mark.parametrize("backend", ["memory", "mongodb"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), b"synthetic-private-value", object()])
def test_invalid_json_has_a_sanitized_permanent_failure(backend: str, invalid: Any) -> None:
    store, database = _store(backend, 1024)
    with pytest.raises(PayloadValidationError) as rejected:
        store.append(_record({"secret": invalid}))
    assert rejected.value.error_code == "invalid_payload_json"
    assert rejected.value.retryable is False
    assert "secret" not in str(rejected.value)
    assert "synthetic-private-value" not in str(rejected.value)
    assert rejected.value.__cause__ is None
    if database is not None:
        assert "insert_one" not in database.operations


def test_cycles_and_key_coercion_collisions_cannot_drop_fields() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    for payload in (cyclic, {"nested": {1: "one", "1": "different"}}):
        with pytest.raises(PayloadValidationError, match="finite JSON"):
            validate_payload(payload, max_payload_bytes=1024)


def test_single_append_freezes_nested_payload_from_caller_mutation() -> None:
    store, _ = _store("memory", 100)
    payload = {"nested": {"value": "before"}}
    stored = store.append(_record(payload))
    payload["nested"]["value"] = "after"
    assert stored["payload"] == {"nested": {"value": "before"}}
