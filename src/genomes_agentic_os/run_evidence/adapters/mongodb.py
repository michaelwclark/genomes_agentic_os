"""MongoDB implementation of the RunLogStore port.

The driver import is intentionally local to construction so importing the
application port never makes MongoDB a transitive dependency for callers.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ..store import EvidenceRecord, RunLogStoreConfig, RunLogStoreConfigurationError, RunLogStoreError, UnknownHostError, _timestamp, _validate_record


def _document(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = dict(value)
    mongo_id = result.pop("_id", None)
    if mongo_id is not None:
        result.setdefault("id", str(mongo_id))
    return result


class MongoDBRunLogStore:
    """MongoDB adapter; construction is limited to ``build_run_log_store``."""

    backend = "mongodb"

    def __init__(self, config: RunLogStoreConfig, database: Any):
        self.config = config
        self.database = database

    @classmethod
    def from_config(cls, config: RunLogStoreConfig, *, client: Any | None = None) -> "MongoDBRunLogStore":
        if client is None:
            uri = os.environ.get(config.uri_env)
            if not uri:
                raise RunLogStoreConfigurationError(
                    f"{config.uri_env} is required for the mongodb RunLogStore backend; deliver it only through the environment"
                )
            try:
                from pymongo import MongoClient
            except ImportError as error:  # pragma: no cover - exercised by package installation, not a fake driver.
                raise RunLogStoreConfigurationError(
                    "mongodb backend requires the optional 'mongodb' package extra (pymongo)"
                ) from error
            client = MongoClient(uri, serverSelectionTimeoutMS=250)
        return cls(config, client[config.database])

    def _collection(self, model_key: str) -> Any:
        try:
            collection = self.config.models[model_key]["collection"]
        except KeyError as error:
            raise RunLogStoreError(f"unknown run-evidence model: {model_key}") from error
        return self.database[collection]

    def upsert_host(self, host: Mapping[str, Any]) -> dict[str, Any]:
        host_id = host.get("host_id")
        if not isinstance(host_id, str) or not host_id:
            raise RunLogStoreError("host_id is required")
        now = _timestamp()
        hosts = self.database["hosts"]
        hosts.update_one(
            {"host_id": host_id},
            {"$set": {**dict(host), "host_id": host_id, "last_seen_at": now}, "$setOnInsert": {"first_seen_at": now}},
            upsert=True,
        )
        stored = _document(hosts.find_one({"host_id": host_id}))
        assert stored is not None
        return stored

    def get_host(self, host_id: str) -> dict[str, Any] | None:
        return _document(self.database["hosts"].find_one({"host_id": host_id}))

    def append(self, record: EvidenceRecord) -> dict[str, Any]:
        document = _validate_record(record, self.config, self.get_host(record.host_id) is not None)
        collection = self._collection(record.model_key)
        existing = _document(collection.find_one({"content_hash": document["content_hash"]}))
        if existing is not None:
            return existing
        try:
            collection.insert_one(document)
        except Exception as error:
            # Do not expose a driver exception or a URI.  A concurrent writer
            # may have won the configured unique idempotency index.
            existing = _document(collection.find_one({"content_hash": document["content_hash"]}))
            if existing is not None:
                return existing
            raise RunLogStoreError("mongodb evidence append failed") from error
        return document

    def append_many(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]:
        # Prevalidate the complete batch before the first write.  The adapter
        # keeps individual idempotency behavior consistent with retrying ingress.
        for record in records:
            _validate_record(record, self.config, self.get_host(record.host_id) is not None)
        return [self.append(record) for record in records]

    def import_idempotently(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]:
        return self.append_many(records)

    def get(self, model_key: str, record_id: str) -> dict[str, Any] | None:
        return _document(self._collection(model_key).find_one({"id": record_id}))

    def search(
        self,
        model_key: str,
        *,
        host_id: str | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {key: value for key, value in {"host_id": host_id, "correlation_id": correlation_id, "run_id": run_id}.items() if value is not None}
        if since is not None or until is not None:
            query["occurred_at"] = {**({"$gte": since} if since is not None else {}), **({"$lte": until} if until is not None else {})}
        cursor = self._collection(model_key).find(query).sort([("occurred_at", -1), ("id", -1)]).skip(max(0, offset)).limit(max(0, limit))
        return [_document(value) for value in cursor if _document(value) is not None]  # type: ignore[misc]

    def aggregate(self, model_key: str, field_name: str) -> dict[str, int]:
        rows = self._collection(model_key).aggregate([{"$group": {"_id": f"${field_name}", "count": {"$sum": 1}}}])
        return {str(row["_id"]): int(row["count"]) for row in rows}

    def apply_retention(self, model_key: str, *, now: datetime | None = None) -> int:
        model = self.config.models[model_key]
        retention = model["retention"]
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(days=int(retention["max_age_days"]))).isoformat().replace("+00:00", "Z")
        collection = self._collection(model_key)
        age_result = collection.delete_many({"occurred_at": {"$lt": cutoff}})
        overflow = list(collection.find({}, {"id": 1}).sort([("occurred_at", -1), ("id", -1)]).skip(int(retention["max_objects"])))
        overflow_ids = [row["id"] for row in overflow]
        count_result = collection.delete_many({"id": {"$in": overflow_ids}}) if overflow_ids else None
        return int(age_result.deleted_count) + (int(count_result.deleted_count) if count_result else 0)

    def ensure_indexes(self) -> dict[str, list[str]]:
        created: dict[str, list[str]] = {}
        hosts = self.database["hosts"]
        hosts.create_index([("host_id", 1)], unique=True, name="host_id_unique")
        hosts.create_index([("aliases", 1)], name="aliases_lookup")
        created["hosts"] = ["host_id_unique", "aliases_lookup"]
        for key, model in self.config.models.items():
            collection = self._collection(key)
            names = ["content_hash_unique"]
            collection.create_index([("content_hash", 1)], unique=True, name=names[0])
            for fields in model["indexes"]:
                name = "_".join(fields)
                collection.create_index([(field, 1) for field in fields], name=name)
                names.append(name)
            created[key] = names
        return created

    def health(self) -> dict[str, Any]:
        try:
            self.database.command("ping")
        except Exception as error:
            raise RunLogStoreError("mongodb RunLogStore health check failed") from error
        return {"ready": True, "backend": self.backend, "database": self.config.database}
