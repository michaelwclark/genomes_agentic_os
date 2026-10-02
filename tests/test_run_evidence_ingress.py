"""Producer, durability and shutdown contracts using synthetic evidence."""

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from threading import Event
import time

import pytest

from genomes_agentic_os.run_evidence.ingress import (
    BufferedEvidenceWriter, IngressError, IngressPolicy, build_evidence_writer,
)
from genomes_agentic_os.run_evidence.outbox import FilesystemOutbox, OutboxFull, OutboxPolicy
from genomes_agentic_os.run_evidence.store import (
    EvidenceRecord, InMemoryRunLogStore, load_run_log_store_config,
)

REPO = Path(__file__).parents[1]


def record(n=1, **overrides):
    data = dict(model_key="run_log", host_id="bigmac", source="test",
                classification="durable_evidence", payload={"n": n},
                occurred_at="2026-10-02T00:00:00Z", schema_version=1,
                correlation_id="c", work_item_id="AGE-153")
    return EvidenceRecord(**(data | overrides))


class Provider(InMemoryRunLogStore):
    def __init__(self, config):
        super().__init__(config)
        self.upsert_host({"host_id": "bigmac"})
        self.batches = []
        self.deadlines = []

    @contextmanager
    def write_deadline(self, seconds):
        self.deadlines.append(seconds)
        yield

    def append_many(self, records):
        self.batches.append(len(records))
        return super().append_many(records)


def setup_writer(tmp_path, *, provider_class=Provider, overflow="outbox", **overrides):
    config = replace(load_run_log_store_config(REPO), backend="memory")
    provider = provider_class(config)
    outbox = FilesystemOutbox(tmp_path / "outbox", OutboxPolicy(
        max_items=16, max_bytes=200_000, max_record_bytes=10_000))
    values = dict(queue_capacity=4, batch_size=2, flush_interval_ms=10,
                  write_timeout_ms=25, overflow_policy=overflow, max_record_bytes=10_000)
    writer = BufferedEvidenceWriter(provider, outbox, config,
                                   IngressPolicy(**(values | overrides)),
                                   host_ids=frozenset({"bigmac"}))
    return writer, provider, outbox


def test_healthy_batch_flushes_with_provider_readback_and_no_files(tmp_path):
    writer, provider, outbox = setup_writer(tmp_path)
    writer.start()
    receipts = [writer.submit(record(i)) for i in range(3)]
    assert writer.close(timeout_seconds=1) == {"drained": True, "pending": 0, "dropped": 0}
    assert all(r.durable and r.status == "persisted" for r in receipts)
    assert sum(provider.batches) == 3 and max(provider.batches) <= 2
    assert provider.deadlines and set(provider.deadlines) == {.025}
    assert outbox.status()["count"] == 0
    status = writer.status()
    assert status["persisted"] == status["accepted"] == 3
    assert status["last_successful_write"] is not None


class BlockedProvider(Provider):
    def __init__(self, config):
        super().__init__(config)
        self.entered, self.release = Event(), Event()

    def append_many(self, records):
        self.entered.set()
        assert self.release.wait(2)
        return super().append_many(records)


def test_producer_never_waits_for_database_and_close_reports_pending(tmp_path):
    writer, provider, outbox = setup_writer(tmp_path, provider_class=BlockedProvider, batch_size=1)
    writer.start()
    first = writer.submit(record())
    assert provider.entered.wait(1)
    try:
        start = time.monotonic()
        second = writer.submit(record(2))
        assert time.monotonic() - start < .2
        assert not first.durable and not second.durable
        result = writer.close(timeout_seconds=.01)
        assert result["drained"] is False and result["pending"] == 2
        assert outbox.status()["count"] == 0
    finally:
        provider.release.set()
        assert writer.close(timeout_seconds=1)["drained"]
    assert first.durable and second.durable


@pytest.mark.parametrize("overflow", ["outbox", "reject"])
def test_saturation_has_explicit_backpressure_and_bounded_queue(tmp_path, overflow):
    writer, provider, outbox = setup_writer(tmp_path, provider_class=BlockedProvider,
                                          overflow=overflow, queue_capacity=1, batch_size=1)
    writer.start()
    writer.submit(record())
    assert provider.entered.wait(1)
    try:
        writer.submit(record(2))
        if overflow == "outbox":
            third = writer.submit(record(3))
            assert third.durable and third.status == "outboxed"
            assert outbox.status()["pending"] == 1
        else:
            with pytest.raises(IngressError, match="queue full"):
                writer.submit(record(3))
            assert outbox.status()["count"] == 0
        assert writer.status()["queue_depth"] == 1
    finally:
        provider.release.set()
        assert writer.close(timeout_seconds=1)["drained"]


def test_unavailable_ingress_returns_durable_fallback_and_closed_rejects_when_configured(tmp_path):
    writer, _, outbox = setup_writer(tmp_path)
    receipt = writer.submit(record())
    assert receipt.durable and receipt.status == "outboxed"
    assert outbox.status()["pending"] == 1
    writer.close(timeout_seconds=0)
    assert writer.submit(record(2)).durable
    rejecting, _, _ = setup_writer(tmp_path / "reject", overflow="reject")
    with pytest.raises(IngressError):
        rejecting.submit(record())


class PartialProvider(Provider):
    def append_many(self, records):
        self.append(records[0])
        raise TimeoutError("sensitive driver diagnostics")


def test_partial_timeout_retains_whole_batch_and_replay_converges(tmp_path):
    writer, provider, outbox = setup_writer(tmp_path, provider_class=PartialProvider)
    writer.start()
    receipts = [writer.submit(record(i)) for i in range(2)]
    assert writer.close(timeout_seconds=1)["drained"]
    assert all(r.status == "outboxed" and r.durable for r in receipts)
    assert outbox.status()["pending"] == 2
    assert outbox.replay(provider, limit=2)["persisted"] == 2
    assert outbox.replay(provider, limit=2)["persisted"] == 0
    assert len(provider.search("run_log")) == 2


@pytest.mark.parametrize("failure", [PermissionError(), OSError("disk full"), OutboxFull("quota")])
def test_failed_local_fallback_is_visible_and_not_durable(tmp_path, monkeypatch, failure):
    writer, _, outbox = setup_writer(tmp_path)
    def fail(_):
        raise failure
    monkeypatch.setattr(outbox, "put", fail)
    receipt = writer.submit(record())
    assert receipt.wait(0) and not receipt.durable
    assert receipt.status == "dropped" and receipt.error_code == "outbox_unavailable"
    assert writer.status()["dropped"] == 1


@pytest.mark.parametrize("changes", [
    {"host_id": "unknown"}, {"schema_version": 2}, {"model_key": "unknown"},
    {"classification": "scratch"}, {"payload": {"v": object()}},
    {"payload": {"v": float("nan")}}, {"payload": {"v": "a" * 20_000}},
])
def test_validation_precedes_acceptance_and_serialization_is_bounded(tmp_path, changes):
    writer, provider, outbox = setup_writer(tmp_path)
    with pytest.raises(IngressError):
        writer.submit(record(**changes))
    assert writer.status()["accepted"] == 0
    assert provider.batches == [] and outbox.status()["count"] == 0


def test_submission_freezes_identity_and_mutable_payload(tmp_path):
    writer, provider, _ = setup_writer(tmp_path, flush_interval_ms=100)
    writer.start()
    original = record(payload={"nested": [1]})
    receipt = writer.submit(original)
    original.payload["nested"].append(2)
    assert writer.close(timeout_seconds=1)["drained"]
    saved = provider.get("run_log", receipt.record_id)
    assert saved["payload"] == {"nested": [1]}
    assert saved["content_hash"] == receipt.content_hash


def test_stress_rejects_without_spawning_or_unbounded_retention(tmp_path):
    writer, provider, _ = setup_writer(tmp_path, provider_class=BlockedProvider,
                                      overflow="reject", queue_capacity=2, batch_size=1)
    writer.start()
    worker = writer._thread
    writer.submit(record())
    assert provider.entered.wait(1)
    try:
        for i in range(1000):
            try:
                writer.submit(record(i + 10))
            except IngressError:
                pass
        status = writer.status()
        assert status["queue_depth"] == 2 and status["inflight"] == 1
        assert status["dropped"] == 998
        writer.start()
        assert writer._thread is worker
    finally:
        provider.release.set()
        assert writer.close(timeout_seconds=1)["drained"]


def test_readback_mismatch_goes_to_outbox(tmp_path):
    class Mismatch(Provider):
        def get(self, *args):
            return None
    writer, _, outbox = setup_writer(tmp_path, provider_class=Mismatch)
    writer.start()
    receipt = writer.submit(record())
    assert writer.close(timeout_seconds=1)["drained"]
    assert receipt.durable and receipt.status == "outboxed"
    assert outbox.status()["pending"] == 1


def test_recovery_metrics_and_provider_deadline(tmp_path):
    writer, provider, outbox = setup_writer(tmp_path)
    receipt = writer.submit(record())
    assert receipt.durable and receipt.status == "outboxed"
    assert writer.replay(limit=1) == {"persisted": 1, "retry": 0}
    status = writer.status()
    assert status["replayed"] == 1 and status["retries"] == 0
    assert provider.deadlines == [.025]
    assert outbox.status()["count"] == 0


def test_mongo_deadline_is_owned_by_adapter(monkeypatch):
    import sys
    from types import ModuleType
    from genomes_agentic_os.run_evidence.adapters.mongodb import MongoDBRunLogStore
    fake = ModuleType("pymongo")
    entered = []
    @contextmanager
    def timeout(seconds):
        entered.append(seconds)
        yield
    fake.timeout = timeout
    monkeypatch.setitem(sys.modules, "pymongo", fake)
    provider = MongoDBRunLogStore(load_run_log_store_config(REPO), None)
    with provider.write_deadline(.25):
        assert entered == [.25]


def test_composition_uses_canonical_configuration_and_selected_root(tmp_path):
    import yaml
    (tmp_path / "harness/config").mkdir(parents=True)
    config = yaml.safe_load((REPO / "harness/config/run-evidence.yml").read_text())
    config["ingress"]["outbox_root"] = "buffer"
    (tmp_path / "harness/config/run-evidence.yml").write_text(yaml.safe_dump(config))
    provider = Provider(load_run_log_store_config(REPO))
    writer = build_evidence_writer(tmp_path, provider, host_ids=frozenset({"bigmac"}))
    receipt = writer.submit(record())
    assert writer.close(timeout_seconds=1)["drained"]
    assert receipt.durable and writer.outbox.root == tmp_path / "buffer"


@pytest.mark.parametrize("changes", [{"queue_capacity": 0}, {"batch_size": 10},
                                   {"write_timeout_ms": True}, {"overflow_policy": "drop"}])
def test_invalid_policy_fails_before_worker_start(tmp_path, changes):
    with pytest.raises(ValueError):
        setup_writer(tmp_path, **changes)
