"""Bounded producer ingress; provider I/O belongs to one background worker.

Queued is an in-memory acknowledgement, never a durable acknowledgement. A
submission becomes durable only after provider readback or an fsynced outbox
write. Callers needing durability must inspect the returned completion receipt.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from threading import Condition, Event, Thread
import time
from typing import Any, Protocol

from genomes_agentic_os.run_evidence_config import load_run_evidence_config
from .outbox import FilesystemOutbox, OutboxPolicy
from .store import EvidenceRecord, RunLogStore, RunLogStoreConfig, RunLogStoreError


class IngressError(RunLogStoreError):
    """Submission was rejected before acceptance."""


@dataclass(frozen=True)
class IngressPolicy:
    queue_capacity: int
    batch_size: int
    flush_interval_ms: int
    write_timeout_ms: int
    overflow_policy: str
    max_record_bytes: int

    def __post_init__(self) -> None:
        for name in ("queue_capacity", "batch_size", "flush_interval_ms", "write_timeout_ms", "max_record_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.batch_size > self.queue_capacity:
            raise ValueError("batch_size must not exceed queue_capacity")
        if self.max_record_bytes < 2048:
            raise ValueError("max_record_bytes must reserve envelope metadata")
        if self.overflow_policy not in {"outbox", "reject"}:
            raise ValueError("overflow_policy must be outbox or reject")


@dataclass
class Submission:
    """Caller-owned bounded completion receipt, containing no payload."""

    record_id: str
    content_hash: str
    status: str = "queued"
    error_code: str | None = None
    persisted_id: str | None = None
    outbox_key: str | None = None
    _done: Event = field(default_factory=Event, repr=False)

    @property
    def durable(self) -> bool:
        return self._done.is_set() and self.status in {"persisted", "outboxed"}

    def wait(self, timeout_seconds: float) -> bool:
        """Wait at most the caller's finite bound; false means still pending."""
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout_seconds must be finite and nonnegative")
        return self._done.wait(timeout_seconds)


class EvidenceWriter(Protocol):
    """The injected producer application port; construction does no submission."""

    def submit(self, record: EvidenceRecord) -> Submission: ...


class BufferedEvidenceWriter:
    """One bounded queue, one bounded in-flight batch, and one worker thread."""

    def __init__(self, store: RunLogStore, outbox: FilesystemOutbox,
                 config: RunLogStoreConfig, policy: IngressPolicy,
                 *, host_ids: frozenset[str]):
        self.store, self.outbox, self.config, self.policy = store, outbox, config, policy
        self.host_ids = host_ids
        self._condition = Condition()
        self._queue: deque[tuple[EvidenceRecord, Submission]] = deque()
        self._closing = False
        self._inflight = 0
        self._metrics: Counter[str] = Counter()
        self._last_success: float | None = None
        self._batch_latency = 0.0
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start once explicitly; never create a thread per submission."""
        with self._condition:
            if self._closing:
                raise IngressError("ingress is closed")
            if self._thread is None:
                self._thread = Thread(target=self._run, name="run-evidence-ingress", daemon=True)
                self._thread.start()

    def _freeze(self, record: EvidenceRecord) -> EvidenceRecord:
        """Validate locally and isolate caller-owned mutable mappings."""
        model = self.config.models.get(record.model_key)
        if (model is None or record.host_id not in self.host_ids or not record.source
                or record.classification != model.get("classification")
                or type(record.schema_version) is not int
                or record.schema_version != model.get("schema_version")
                or not isinstance(record.payload, Mapping)
                or not isinstance(record.payload_metadata, Mapping)):
            raise IngressError("invalid evidence model, host, schema or classification")
        try:
            # Check bounds before normalized() deep-copies and hashes the input.
            # An oversized/cyclic caller mapping must never reach that path.
            document = {name: getattr(record, name) for name in record.__dataclass_fields__}
            document["payload"] = dict(record.payload)
            document["payload_metadata"] = dict(record.payload_metadata)
            frozen = EvidenceRecord(**json.loads(self._bounded_json(document)))
            payload_limit = model.get("max_payload_bytes", self.policy.max_record_bytes)
            if len(self._bounded_json(frozen.payload).encode("utf-8")) > payload_limit:
                raise IngressError("evidence exceeds model payload byte limit")
            return EvidenceRecord(**json.loads(self._bounded_json(frozen.normalized())))
        except (TypeError, ValueError, RecursionError):
            raise IngressError("evidence is not bounded JSON") from None

    def _bounded_json(self, document: Any) -> str:
        chunks: list[str] = []
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False).iterencode(document):
            # Avoid allocating a second oversized byte string for a large chunk.
            if len(chunk) > self.policy.max_record_bytes - 1024:
                raise IngressError("evidence exceeds record byte limit")
            size += len(chunk.encode("utf-8"))
            if size > self.policy.max_record_bytes - 1024:
                raise IngressError("evidence exceeds record byte limit")
            chunks.append(chunk)
        return "".join(chunks)

    def submit(self, record: EvidenceRecord) -> Submission:
        """Enqueue without provider I/O; overflow may use explicit local fallback."""
        frozen = self._freeze(record)
        receipt = Submission(str(frozen.id), str(frozen.content_hash))
        with self._condition:
            available = not self._closing and self._thread is not None and self._thread.is_alive()
            if available and len(self._queue) < self.policy.queue_capacity:
                self._queue.append((frozen, receipt))
                self._metrics["accepted"] += 1
                self._condition.notify()
                return receipt
            if self.policy.overflow_policy == "reject":
                self._metrics["dropped"] += 1
                raise IngressError("ingress unavailable or queue full")
            self._metrics["accepted"] += 1
        # Never hold the queue lock while touching the filesystem.
        self._fallback(frozen, receipt)
        return receipt

    def _finish(self, receipt: Submission, status: str, error: str | None = None,
                *, persisted_id: str | None = None, outbox_key: str | None = None) -> None:
        receipt.status, receipt.error_code, receipt.persisted_id = status, error, persisted_id
        receipt.outbox_key = outbox_key
        with self._condition:
            self._metrics[status] += 1
            if status == "persisted":
                self._last_success = time.time()
        receipt._done.set()

    def _fallback(self, record: EvidenceRecord, receipt: Submission) -> None:
        try:
            key = self.outbox.put(record)
        except (OSError, RunLogStoreError):
            self._finish(receipt, "dropped", "outbox_unavailable")
        else:
            self._finish(receipt, "outboxed", outbox_key=key)

    def _persist(self, batch: list[tuple[EvidenceRecord, Submission]]) -> None:
        started = time.monotonic()
        try:
            # The adapter enforces one total operation deadline, including
            # validation queries, partial writes and each provider readback.
            with self.store.write_deadline(self.policy.write_timeout_ms / 1000):
                saved = self.store.append_many([record for record, _ in batch])
                if len(saved) != len(batch):
                    raise RunLogStoreError("partial batch result")
                for (record, _), result in zip(batch, saved):
                    readback = self.store.get(record.model_key, result["id"])
                    expected = record.normalized()
                    fields = set(expected) - {"id", "ingested_at"}
                    if readback is None or any(readback.get(key) != expected[key] for key in fields):
                        raise RunLogStoreError("batch readback mismatch")
        except Exception:
            # The complete uncertain batch is retained: successful partial
            # writes converge through the provider's idempotency contract.
            for record, receipt in batch:
                self._fallback(record, receipt)
        else:
            for (record, receipt), result in zip(batch, saved):
                if result["id"] != record.id:
                    with self._condition:
                        self._metrics["duplicated"] += 1
                self._finish(receipt, "persisted", persisted_id=result["id"])
        finally:
            with self._condition:
                self._batch_latency = time.monotonic() - started

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closing or bool(self._queue))
                if not self._queue and self._closing:
                    return
                until = time.monotonic() + self.policy.flush_interval_ms / 1000
                while len(self._queue) < self.policy.batch_size and not self._closing:
                    remaining = until - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                batch = [self._queue.popleft() for _ in range(min(len(self._queue), self.policy.batch_size))]
                self._inflight = len(batch)
            self._persist(batch)
            with self._condition:
                self._inflight = 0

    def close(self, *, timeout_seconds: float) -> dict[str, Any]:
        """Flush within a caller bound; a timed-out close never claims durability."""
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout_seconds must be finite and nonnegative")
        with self._condition:
            self._closing = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
        with self._condition:
            pending = len(self._queue) + self._inflight
            return {"drained": pending == 0 and (thread is None or not thread.is_alive()),
                    "pending": pending, "dropped": self._metrics["dropped"]}

    def status(self) -> dict[str, Any]:
        """Snapshot bounded counters; outbox I/O never holds the producer lock."""
        with self._condition:
            result = {key: self._metrics[key] for key in ("accepted", "persisted", "outboxed", "duplicated", "dropped", "replayed", "retries")}
            result.update(queue_depth=len(self._queue), inflight=self._inflight,
                          batch_latency_seconds=self._batch_latency,
                          last_successful_write=self._last_success)
        try:
            result["outbox"] = self.outbox.status()
        except (OSError, RunLogStoreError):
            result["outbox_error"] = "outbox_unavailable"
        return result

    def replay(self, *, limit: int = 1) -> dict[str, int]:
        """Explicit bounded recovery; never schedule or replay at construction."""
        with self.store.write_deadline(self.policy.write_timeout_ms / 1000):
            counts = self.outbox.replay(self.store, limit=limit)
        with self._condition:
            self._metrics["replayed"] += counts["persisted"]
            self._metrics["retries"] += counts["retry"]
            if counts["persisted"]:
                self._last_success = time.time()
        return counts


def build_evidence_writer(root: Path, store: RunLogStore, *, host_ids: frozenset[str]) -> BufferedEvidenceWriter:
    """Bind canonical configuration at the composition root, then start ingress."""
    document = load_run_evidence_config(root)
    ingress = document["ingress"]
    required = set(IngressPolicy.__dataclass_fields__) | {"max_outbox_items", "max_outbox_bytes"}
    if required - ingress.keys():
        raise IngressError("ingress requires explicit overflow and outbox bounds in canonical configuration")
    policy = IngressPolicy(**{key: ingress[key] for key in IngressPolicy.__dataclass_fields__})
    relative = Path(ingress["outbox_root"])
    if relative.is_absolute() or ".." in relative.parts:
        raise IngressError("outbox_root must be relative to the selected root")
    selected_root, outbox_root = root.resolve(), (root / relative).resolve()
    if outbox_root == selected_root or not outbox_root.is_relative_to(selected_root):
        raise IngressError("outbox_root must stay inside the selected root")
    outbox = FilesystemOutbox(outbox_root, OutboxPolicy(
        max_items=ingress["max_outbox_items"], max_bytes=ingress["max_outbox_bytes"],
        max_record_bytes=policy.max_record_bytes,
        lease_seconds=max(30, 2 * policy.write_timeout_ms / 1000)))
    writer = BufferedEvidenceWriter(store, outbox, RunLogStoreConfig.from_mapping(document),
                                    policy, host_ids=host_ids)
    writer.start()
    return writer
