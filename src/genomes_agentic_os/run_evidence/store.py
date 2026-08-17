"""The RunLogStore port and its composition-root configuration.

Application services import this module only.  Concrete provider modules stay
behind :func:`build_run_log_store`, which is the sole construction edge.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from genomes_agentic_os.run_evidence_config import load_run_evidence_config


class RunLogStoreError(RuntimeError):
    """Base error raised by the evidence storage boundary."""


class RunLogStoreConfigurationError(RunLogStoreError, ValueError):
    """Raised when the selected run-evidence backend is not usable."""


class UnknownHostError(RunLogStoreError):
    """Raised when an evidence record cannot be attributed to a known host."""


def _timestamp(value: str | None = None) -> str:
    if value is not None:
        return value
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EvidenceRecord:
    """Model-neutral durable evidence required by the AGE-151 registry."""

    model_key: str
    host_id: str
    source: str
    classification: str
    payload: Mapping[str, Any]
    occurred_at: str
    schema_version: int
    content_hash: str | None = None
    payload_metadata: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    run_id: str | None = None
    work_item_id: str | None = None
    id: str | None = None
    ingested_at: str | None = None

    def normalized(self) -> dict[str, Any]:
        """Return the persistence representation with deterministic identity."""
        document = asdict(self)
        payload = dict(self.payload)
        document["payload"] = payload
        document["payload_metadata"] = dict(self.payload_metadata)
        document["id"] = self.id or str(uuid4())
        document["ingested_at"] = _timestamp(self.ingested_at)
        identity = {
            "host_id": self.host_id,
            "model_key": self.model_key,
            "occurred_at": self.occurred_at,
            "payload": payload,
            "source": self.source,
        }
        document["content_hash"] = self.content_hash or sha256(
            json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return document


class RunLogStore(Protocol):
    """Business-facing evidence operations; no provider types cross this port."""

    backend: str

    def upsert_host(self, host: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_host(self, host_id: str) -> dict[str, Any] | None: ...

    def append(self, record: EvidenceRecord) -> dict[str, Any]: ...

    def append_many(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]: ...

    def get(self, model_key: str, record_id: str) -> dict[str, Any] | None: ...

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
    ) -> list[dict[str, Any]]: ...

    def aggregate(self, model_key: str, field_name: str) -> dict[str, int]: ...

    def apply_retention(self, model_key: str, *, now: datetime | None = None) -> int: ...

    def ensure_indexes(self) -> dict[str, list[str]]: ...

    def health(self) -> dict[str, Any]: ...

    def import_idempotently(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RunLogStoreConfig:
    """Portable explicit input to the sole evidence-store composition root."""

    backend: str
    database: str
    uri_env: str
    models: Mapping[str, Mapping[str, Any]]
    initial_host: str
    host_registry_source: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RunLogStoreConfig":
        backend = value.get("backend")
        datastores = value.get("datastores")
        models = value.get("models")
        host_registry = value.get("host_registry")
        if not isinstance(backend, str):
            raise RunLogStoreConfigurationError("run_evidence.backend must be a string")
        if not isinstance(datastores, Mapping) or not isinstance(datastores.get("mongodb"), Mapping):
            raise RunLogStoreConfigurationError("run_evidence.datastores.mongodb is required")
        if not isinstance(models, Mapping) or not models:
            raise RunLogStoreConfigurationError("run_evidence.models is required")
        if not isinstance(host_registry, Mapping) or not isinstance(host_registry.get("initial_host"), str):
            raise RunLogStoreConfigurationError("run_evidence.host_registry.initial_host is required")
        mongodb = datastores["mongodb"]
        uri_env = mongodb.get("uri_env")
        database = mongodb.get("database")
        if not isinstance(uri_env, str) or not uri_env:
            raise RunLogStoreConfigurationError("run_evidence.datastores.mongodb.uri_env is required")
        if not isinstance(database, str) or not database:
            raise RunLogStoreConfigurationError("run_evidence.datastores.mongodb.database is required")
        source = host_registry.get("source")
        if not isinstance(source, str) or not source:
            raise RunLogStoreConfigurationError("run_evidence.host_registry.source is required")
        return cls(backend.lower(), database, uri_env, models, host_registry["initial_host"], source)


def load_run_log_store_config(root: Path) -> RunLogStoreConfig:
    """Load the one canonical backend choice from the AGE-151 registry."""
    return RunLogStoreConfig.from_mapping(load_run_evidence_config(root))


def seed_configured_host(root: Path, store: RunLogStore, config: RunLogStoreConfig | None = None) -> dict[str, Any]:
    """Idempotently seed the configured initial host and read it back."""
    config = config or load_run_log_store_config(root)
    source = root / config.host_registry_source
    if not source.is_file():
        raise RunLogStoreConfigurationError(f"host registry is missing: {source}")
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    hosts = document.get("hosts") if isinstance(document, Mapping) else None
    if not isinstance(hosts, list):
        raise RunLogStoreConfigurationError("host registry hosts must be a list")
    host = next((item for item in hosts if isinstance(item, Mapping) and item.get("host_id") == config.initial_host), None)
    if host is None:
        raise RunLogStoreConfigurationError(f"initial host is missing from registry: {config.initial_host}")
    store.upsert_host(host)
    readback = store.get_host(config.initial_host)
    if readback is None:
        raise RunLogStoreError(f"configured initial host was not persisted: {config.initial_host}")
    return readback


def _validate_record(record: EvidenceRecord, config: RunLogStoreConfig, known_host: bool) -> dict[str, Any]:
    if record.model_key not in config.models:
        raise RunLogStoreError(f"unknown run-evidence model: {record.model_key}")
    if not known_host:
        raise UnknownHostError(f"unknown evidence host: {record.host_id}")
    if not record.source or not record.classification:
        raise RunLogStoreError("evidence source and classification are required")
    if not isinstance(record.payload, Mapping) or not isinstance(record.payload_metadata, Mapping):
        raise RunLogStoreError("evidence payload and payload_metadata must be mappings")
    model = config.models[record.model_key]
    if record.schema_version != model.get("schema_version"):
        raise RunLogStoreError(f"schema version does not match model {record.model_key}")
    if record.classification != model.get("classification"):
        raise RunLogStoreError(f"classification does not match model {record.model_key}")
    return record.normalized()


class InMemoryRunLogStore:
    """Contract fake used by tests; it is not a production persistence backend."""

    backend = "memory"

    def __init__(self, config: RunLogStoreConfig):
        self.config = config
        self._hosts: dict[str, dict[str, Any]] = {}
        self._records: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in config.models}
        self._content_hashes: dict[str, dict[str, str]] = {key: {} for key in config.models}

    def upsert_host(self, host: Mapping[str, Any]) -> dict[str, Any]:
        host_id = host.get("host_id")
        if not isinstance(host_id, str) or not host_id:
            raise RunLogStoreError("host_id is required")
        now = _timestamp()
        existing = self._hosts.get(host_id, {})
        stored = {**existing, **dict(host), "host_id": host_id, "first_seen_at": existing.get("first_seen_at", now), "last_seen_at": now}
        self._hosts[host_id] = stored
        return dict(stored)

    def get_host(self, host_id: str) -> dict[str, Any] | None:
        host = self._hosts.get(host_id)
        return None if host is None else dict(host)

    def append(self, record: EvidenceRecord) -> dict[str, Any]:
        document = _validate_record(record, self.config, self.get_host(record.host_id) is not None)
        hashes = self._content_hashes[record.model_key]
        existing_id = hashes.get(document["content_hash"])
        if existing_id is not None:
            return dict(self._records[record.model_key][existing_id])
        self._records[record.model_key][document["id"]] = document
        hashes[document["content_hash"]] = document["id"]
        return dict(document)

    def append_many(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]:
        # Validate the complete batch before mutating the fake to preserve the port's atomic boundary.
        for record in records:
            _validate_record(record, self.config, self.get_host(record.host_id) is not None)
        return [self.append(record) for record in records]

    def import_idempotently(self, records: Sequence[EvidenceRecord]) -> list[dict[str, Any]]:
        return self.append_many(records)

    def get(self, model_key: str, record_id: str) -> dict[str, Any] | None:
        document = self._records.get(model_key, {}).get(record_id)
        return None if document is None else dict(document)

    def search(self, model_key: str, **filters: Any) -> list[dict[str, Any]]:
        if model_key not in self._records:
            raise RunLogStoreError(f"unknown run-evidence model: {model_key}")
        limit, offset = int(filters.pop("limit", 100)), int(filters.pop("offset", 0))
        since, until = filters.pop("since", None), filters.pop("until", None)
        documents = list(self._records[model_key].values())
        for field_name, value in filters.items():
            if value is not None:
                documents = [document for document in documents if document.get(field_name) == value]
        if since is not None:
            documents = [document for document in documents if document["occurred_at"] >= since]
        if until is not None:
            documents = [document for document in documents if document["occurred_at"] <= until]
        documents.sort(key=lambda document: (document["occurred_at"], document["id"]), reverse=True)
        return [dict(document) for document in documents[offset : offset + max(0, limit)]]

    def aggregate(self, model_key: str, field_name: str) -> dict[str, int]:
        return dict(Counter(str(record.get(field_name, "")) for record in self._records[model_key].values()))

    def apply_retention(self, model_key: str, *, now: datetime | None = None) -> int:
        model = self.config.models[model_key]
        retention = model["retention"]
        now = now or datetime.now(UTC)
        age_cutoff = (now - timedelta(days=int(retention["max_age_days"]))).isoformat().replace("+00:00", "Z")
        records = self._records[model_key]
        ordered = sorted(records.values(), key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
        keep_ids = {item["id"] for item in ordered[: int(retention["max_objects"])] if item["occurred_at"] >= age_cutoff}
        removed = [record_id for record_id in records if record_id not in keep_ids]
        for record_id in removed:
            self._content_hashes[model_key].pop(records[record_id]["content_hash"], None)
            del records[record_id]
        return len(removed)

    def ensure_indexes(self) -> dict[str, list[str]]:
        return {key: ["content_hash_unique", *["_".join(index) for index in value["indexes"]]] for key, value in self.config.models.items()}

    def health(self) -> dict[str, Any]:
        return {"ready": True, "backend": self.backend, "hosts": len(self._hosts)}


def build_run_log_store(config: RunLogStoreConfig, *, client: Any | None = None) -> RunLogStore:
    """Build exactly one selected adapter at the composition root.

    ``memory`` exists only as an explicit contract-test backend.  Filesystem
    evidence remains an ingress/outbox concern until a conformant adapter is
    delivered; callers never silently fall back to it.
    """
    if config.backend == "memory":
        return InMemoryRunLogStore(config)
    if config.backend == "mongodb":
        from .adapters.mongodb import MongoDBRunLogStore

        return MongoDBRunLogStore.from_config(config, client=client)
    if config.backend == "filesystem":
        raise RunLogStoreConfigurationError("filesystem RunLogStore is not implemented; use the bounded outbox ingress")
    raise RunLogStoreConfigurationError(f"unsupported run-evidence backend: {config.backend}")


def build_configured_run_log_store(
    root: Path, *, config: RunLogStoreConfig | None = None, client: Any | None = None
) -> RunLogStore:
    """Construct the selected adapter, install indexes, then seed its initial host."""
    config = config or load_run_log_store_config(root)
    store = build_run_log_store(config, client=client)
    # The Mongo adapter relies on its unique content-hash index to make the
    # duplicate-key recovery path safe for concurrent first appends.  Install
    # the configured indexes before this composition root performs any write.
    store.ensure_indexes()
    seed_configured_host(root, store, config)
    return store
