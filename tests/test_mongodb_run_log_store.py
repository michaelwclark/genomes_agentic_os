"""Fake-driver conformance coverage for the AGE-152 MongoDB adapter."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from genomes_agentic_os.run_evidence import (
    EvidenceRecord,
    RunLogStoreError,
    build_configured_run_log_store,
    load_run_log_store_config,
    seed_configured_host,
)
from genomes_agentic_os.run_evidence.adapters.mongodb import MongoDBRunLogStore


REPO = Path(__file__).parents[1]


class _Cursor:
    """Small Mongo cursor double covering the adapter's query contract."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def sort(self, fields: list[tuple[str, int]]) -> "_Cursor":
        for name, direction in reversed(fields):
            self.rows.sort(key=lambda row: str(row.get(name, "")), reverse=direction < 0)
        return self

    def skip(self, count: int) -> "_Cursor":
        self.rows = self.rows[count:]
        return self

    def limit(self, count: int) -> "_Cursor":
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class _Result:
    """Driver result double exposing the adapter's only consumed field."""

    def __init__(self, deleted_count: int = 0):
        self.deleted_count = deleted_count


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$lt" in expected and not (value < expected["$lt"]):
                return False
            if "$gte" in expected and not (value >= expected["$gte"]):
                return False
            if "$lte" in expected and not (value <= expected["$lte"]):
                return False
        elif value != expected:
            return False
    return True


class _Collection:
    """In-memory Mongo collection double with unique-index conflict injection."""

    def __init__(self, operations: list[str]):
        self.documents: list[dict[str, Any]] = []
        self.index_calls: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []
        self.fail_insert = False
        self.inject_duplicate_once = False
        self.operations = operations

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool) -> _Result:
        self.operations.append("update_one")
        existing = self.find_one(query)
        if existing is None:
            assert upsert
            existing = {**query, **update.get("$setOnInsert", {})}
            self.documents.append(existing)
        existing.update(update.get("$set", {}))
        return _Result()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next((dict(row) for row in self.documents if _matches(row, query)), None)

    def insert_one(self, document: dict[str, Any]) -> _Result:
        self.operations.append("insert_one")
        if self.inject_duplicate_once:
            self.inject_duplicate_once = False
            self.documents.append(dict(document))
            raise RuntimeError("duplicate key")
        if self.fail_insert:
            raise RuntimeError("driver write failure")
        if any(row.get("content_hash") == document.get("content_hash") for row in self.documents):
            raise RuntimeError("duplicate key")
        self.documents.append(dict(document))
        return _Result()

    def find(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> _Cursor:
        rows = [dict(row) for row in self.documents if _matches(row, query)]
        if projection is not None:
            included = {key for key, enabled in projection.items() if enabled}
            rows = [{key: value for key, value in row.items() if key in included} for row in rows]
        return _Cursor(rows)

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        field = pipeline[0]["$group"]["_id"].removeprefix("$")
        counts: dict[str, int] = {}
        for document in self.documents:
            value = str(document.get(field, ""))
            counts[value] = counts.get(value, 0) + 1
        return [{"_id": key, "count": value} for key, value in counts.items()]

    def delete_many(self, query: dict[str, Any]) -> _Result:
        retained = [row for row in self.documents if not _matches(row, query)]
        deleted = len(self.documents) - len(retained)
        self.documents = retained
        return _Result(deleted)

    def create_index(self, fields: list[tuple[str, int]], **kwargs: Any) -> str:
        self.operations.append("create_index")
        self.index_calls.append((fields, kwargs))
        return str(kwargs["name"])


class _Database:
    """Database double shared by adapter construction and direct assertions."""

    def __init__(self):
        self.collections: dict[str, _Collection] = {}
        self.ping_error: Exception | None = None
        self.operations: list[str] = []

    def __getitem__(self, name: str) -> _Collection:
        return self.collections.setdefault(name, _Collection(self.operations))

    def command(self, command: str) -> dict[str, int]:
        assert command == "ping"
        if self.ping_error is not None:
            raise self.ping_error
        return {"ok": 1}


def _record(**overrides: object) -> EvidenceRecord:
    values: dict[str, object] = {
        "model_key": "run_log",
        "host_id": "bigmac",
        "source": "tests",
        "classification": "durable_evidence",
        "payload": {"result": "success"},
        "payload_metadata": {"format": "json"},
        "occurred_at": "2026-08-10T00:00:00Z",
        "schema_version": 1,
        "correlation_id": "age-152",
        "run_id": "run-152",
        "work_item_id": "AGE-152",
    }
    values.update(overrides)
    return EvidenceRecord(**values)  # type: ignore[arg-type]


def _adapter() -> tuple[MongoDBRunLogStore, _Database]:
    config = load_run_log_store_config(REPO)
    database = _Database()
    adapter = MongoDBRunLogStore(config, database)
    seed_configured_host(REPO, adapter, config)
    return adapter, database


def test_configured_mongodb_store_installs_indexes_before_host_seed_and_append() -> None:
    config = load_run_log_store_config(REPO)
    database = _Database()

    store = build_configured_run_log_store(REPO, config=config, client={config.database: database})
    assert isinstance(store, MongoDBRunLogStore)
    store.append(_record())

    assert database.operations.index("create_index") < database.operations.index("update_one")
    assert database.operations.index("create_index") < database.operations.index("insert_one")
    collection = database[config.models["run_log"]["collection"]]
    assert collection.index_calls[0][1] == {"unique": True, "name": "content_hash_unique"}


def test_mongodb_adapter_conforms_without_a_live_database() -> None:
    """Exercise port behavior, indexes, and conflict recovery through a fake driver."""
    adapter, database = _adapter()

    indexes = adapter.ensure_indexes()
    assert indexes["hosts"] == ["host_id_unique", "aliases_lookup"]
    assert database["hosts"].index_calls[0][1] == {"unique": True, "name": "host_id_unique"}

    first = adapter.append(_record(id="first"))
    duplicate = adapter.import_idempotently([_record(id="duplicate")])[0]
    assert duplicate["id"] == first["id"]
    assert adapter.get("run_log", first["id"])["host_id"] == "bigmac"  # type: ignore[index]

    collection = database[adapter.config.models["run_log"]["collection"]]
    collection.inject_duplicate_once = True
    concurrent = adapter.append(_record(id="concurrent", content_hash="c" * 64, payload={"result": "concurrent"}))
    assert concurrent["id"] == "concurrent"

    old = adapter.append(
        _record(id="old", content_hash="o" * 64, payload={"result": "old"}, occurred_at="2020-01-01T00:00:00Z")
    )
    rows = adapter.search("run_log", correlation_id="age-152")
    assert {row["id"] for row in rows} == {first["id"], concurrent["id"], old["id"]}
    assert adapter.aggregate("run_log", "host_id") == {"bigmac": 3}
    assert adapter.apply_retention("run_log", now=datetime(2026, 8, 10, tzinfo=UTC)) == 1
    assert adapter.health() == {"ready": True, "backend": "mongodb", "database": "agentic_os"}


def test_mongodb_adapter_maps_driver_errors_without_leaking_details() -> None:
    adapter, database = _adapter()
    collection = database[adapter.config.models["run_log"]["collection"]]
    collection.fail_insert = True

    with pytest.raises(RunLogStoreError, match="mongodb evidence append failed"):
        adapter.append(_record(content_hash="f" * 64))


def test_mongodb_from_config_uses_environment_and_a_bounded_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_run_log_store_config(REPO)
    database = _Database()
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Client:
        def __init__(self, uri: str, **kwargs: Any):
            calls.append((uri, kwargs))

        def __getitem__(self, name: str) -> _Database:
            assert name == config.database
            return database

    pymongo = ModuleType("pymongo")
    pymongo.MongoClient = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymongo", pymongo)
    monkeypatch.setenv(config.uri_env, "mongodb://integration.example.invalid/agentic_os")

    adapter = MongoDBRunLogStore.from_config(config)
    assert adapter.database is database
    assert calls == [("mongodb://integration.example.invalid/agentic_os", {"serverSelectionTimeoutMS": 250})]


def test_mongodb_adapter_rejects_unknown_hosts_before_any_write() -> None:
    adapter, database = _adapter()
    collection = database[adapter.config.models["run_log"]["collection"]]

    with pytest.raises(Exception, match="unknown evidence host"):
        adapter.append_many([_record(id="valid"), _record(id="missing", host_id="unknown")])

    assert collection.documents == []
