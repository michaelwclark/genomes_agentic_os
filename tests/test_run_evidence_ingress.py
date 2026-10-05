"""Producer, durability and shutdown contracts using synthetic evidence."""

from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import socket
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
    assert all(r.persisted_id == r.record_id for r in receipts)
    assert all(r.outbox_key is None for r in receipts)
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
        assert first.persisted_id is None and second.persisted_id is None
        assert first.outbox_key is None and second.outbox_key is None
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
    assert all(r.persisted_id is None for r in receipts)
    assert all(r.outbox_key is not None for r in receipts)
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
    assert receipt.persisted_id is None
    assert receipt.outbox_key is None
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


@pytest.mark.parametrize("batch_size", [1, 2])
def test_duplicate_receipt_exposes_verified_persisted_identity(tmp_path, batch_size):
    writer, provider, outbox = setup_writer(tmp_path, batch_size=batch_size)
    writer.start()
    first = writer.submit(record(id="first"))
    duplicate = writer.submit(record(id="second"))
    assert writer.close(timeout_seconds=1)["drained"]
    assert first.wait(0) and duplicate.wait(0)
    assert first.status == duplicate.status == "persisted"
    assert first.durable and duplicate.durable
    assert duplicate.record_id == "second"
    assert first.persisted_id == duplicate.persisted_id == "first"
    assert provider.get("run_log", duplicate.record_id) is None
    saved = provider.get("run_log", duplicate.persisted_id)
    assert saved["content_hash"] == duplicate.content_hash
    assert len(provider.search("run_log")) == 1
    assert writer.status()["duplicated"] == 1
    assert outbox.status()["count"] == 0


def test_duplicate_outboxed_receipt_identifies_retained_envelope(tmp_path, monkeypatch):
    writer, provider, outbox = setup_writer(tmp_path)
    first = writer.submit(record(id="first"))
    duplicate = writer.submit(record(id="second"))
    assert first.durable and duplicate.durable
    assert first.status == duplicate.status == "outboxed"
    assert duplicate.record_id == "second"
    assert first.persisted_id is duplicate.persisted_id is None
    assert first.outbox_key == duplicate.outbox_key
    assert duplicate.outbox_key is not None
    assert outbox.status()["count"] == 1
    now = time.time()
    claim = outbox.claim(now=now)
    assert claim.key == duplicate.outbox_key and claim.record.id == "first"
    outbox.retry(claim, now=now)
    monkeypatch.setattr("genomes_agentic_os.run_evidence.outbox.time.time", lambda: now + 2)
    assert writer.replay(limit=1)["persisted"] == 1
    assert provider.get("run_log", "first")["content_hash"] == duplicate.content_hash
    assert writer.replay(limit=1)["persisted"] == 0
    assert outbox.status()["count"] == 0
    assert len(provider.search("run_log")) == 1


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
    assert receipt.persisted_id is None
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


def test_oversized_input_is_rejected_before_identity_copy_or_hash(tmp_path, monkeypatch):
    writer, _, outbox = setup_writer(tmp_path)
    monkeypatch.setattr(EvidenceRecord, "normalized", lambda _: pytest.fail("unbounded normalization"))
    with pytest.raises(IngressError, match="record byte limit"):
        writer.submit(record(payload={"large": "x" * 100_000}))
    assert writer.status()["accepted"] == 0 and outbox.status()["count"] == 0


def test_cyclic_input_and_boolean_schema_are_rejected_before_acceptance(tmp_path):
    writer, _, outbox = setup_writer(tmp_path)
    payload = {}
    payload["cycle"] = payload
    for invalid in (record(payload=payload), record(schema_version=True)):
        with pytest.raises(IngressError):
            writer.submit(invalid)
    assert writer.status()["accepted"] == 0 and outbox.status()["count"] == 0


def test_model_payload_limit_is_checked_before_outboxing(tmp_path):
    writer, _, outbox = setup_writer(tmp_path)
    models = {key: dict(value) for key, value in writer.config.models.items()}
    models["run_log"]["max_payload_bytes"] = 20
    writer.config = replace(writer.config, models=models)
    with pytest.raises(IngressError, match="model payload byte limit"):
        writer.submit(record(payload={"message": "x" * 30}))
    assert writer.status()["accepted"] == 0 and outbox.status()["count"] == 0


def configured_root(root, **ingress_changes):
    import yaml
    folder = root / "harness/config"
    folder.mkdir(parents=True)
    document = yaml.safe_load((REPO / "harness/config/run-evidence.yml").read_text())
    document["ingress"].update(ingress_changes)
    (folder / "run-evidence.yml").write_text(yaml.safe_dump(document))
    return document


@pytest.mark.parametrize("relative", ["../outside", "/outside", ".", "linked/buffer"])
def test_composition_rejects_escaping_outbox_before_filesystem_mutation(tmp_path, relative):
    root, outside = tmp_path / "selected", tmp_path / "outside"
    configured_root(root, outbox_root=relative)
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(IngressError, match="outbox_root"):
        build_evidence_writer(root, Provider(load_run_log_store_config(REPO)),
                              host_ids=frozenset({"bigmac"}))
    assert not list(outside.iterdir())


def test_legacy_configuration_loads_but_requires_explicit_ingress_upgrade(tmp_path):
    import yaml
    from genomes_agentic_os.run_evidence_config import load_run_evidence_config
    document = configured_root(tmp_path)
    for key in ("overflow_policy", "max_record_bytes", "max_outbox_items", "max_outbox_bytes"):
        document["ingress"].pop(key)
    (tmp_path / "harness/config/run-evidence.yml").write_text(yaml.safe_dump(document))
    assert load_run_evidence_config(tmp_path)["models"] == document["models"]
    provider = Provider(load_run_log_store_config(tmp_path))
    assert provider.append(record())["host_id"] == "bigmac"
    with pytest.raises(IngressError, match="explicit overflow and outbox bounds"):
        build_evidence_writer(tmp_path, provider, host_ids=frozenset({"bigmac"}))
    assert not (tmp_path / document["ingress"]["outbox_root"]).exists()


@pytest.mark.parametrize("background_outage", [False, True])
def test_abrupt_ingress_exit_keeps_every_durable_acknowledgement(tmp_path, background_outage):
    code = r'''
import json, os, sys
from pathlib import Path
from genomes_agentic_os.run_evidence.ingress import BufferedEvidenceWriter, IngressPolicy
from genomes_agentic_os.run_evidence.outbox import FilesystemOutbox, OutboxPolicy
from genomes_agentic_os.run_evidence.store import EvidenceRecord, InMemoryRunLogStore, load_run_log_store_config
class Outage(InMemoryRunLogStore):
    def append_many(self, records):
        raise TimeoutError("simulated outage")
config = load_run_log_store_config(Path(sys.argv[1]))
box = FilesystemOutbox(Path(sys.argv[2]), OutboxPolicy(16, 200000, 10000))
writer = BufferedEvidenceWriter(Outage(config), box, config,
    IngressPolicy(4, 1, 1, 25, "outbox", 10000), host_ids=frozenset({"bigmac"}))
if sys.argv[3] == "True":
    writer.start()
ack = writer.submit(EvidenceRecord("run_log", "bigmac", "crash-test", "durable_evidence",
    {"message": "retained"}, "2026-10-04T00:00:00Z", 1, correlation_id="crash-correlation"))
assert ack.wait(1) and ack.durable and ack.status == "outboxed"
print(json.dumps({"id": ack.record_id, "hash": ack.content_hash}), flush=True)
os._exit(0)
'''
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AGENTIC_OS_", "EXECUTION_FABRIC_"))}
    environment["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run([sys.executable, "-c", code, str(REPO), str(tmp_path / "outbox"),
                             str(background_outage)], env=environment, check=True,
                            capture_output=True, text=True, timeout=5)
    acknowledgement = json.loads(result.stdout)
    writer, provider, outbox = setup_writer(tmp_path)
    assert writer.replay(limit=2) == {"persisted": 1, "retry": 0}
    saved = provider.get("run_log", acknowledgement["id"])
    assert saved["content_hash"] == acknowledgement["hash"]
    assert saved["correlation_id"] == "crash-correlation"
    assert outbox.status()["count"] == 0
    assert writer.replay(limit=2)["persisted"] == 0


def test_real_mongodb_unavailability_respects_batch_deadline_and_durable_fallback(tmp_path):
    pymongo = pytest.importorskip("pymongo")
    from genomes_agentic_os.run_evidence.adapters.mongodb import MongoDBRunLogStore
    writer, _, outbox = setup_writer(tmp_path, write_timeout_ms=50, batch_size=1)
    # Bind without listening: this endpoint cannot be another local datastore.
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        client = pymongo.MongoClient("127.0.0.1", endpoint.getsockname()[1],
                                     serverSelectionTimeoutMS=5000, connect=False)
        writer.store = MongoDBRunLogStore(writer.config, client["age153_disposable_deadline"])
        try:
            writer.start()
            started = time.monotonic()
            acknowledgement = writer.submit(record())
            assert time.monotonic() - started < .2
            assert acknowledgement.wait(1)
            assert time.monotonic() - started < 1
            assert acknowledgement.durable and acknowledgement.status == "outboxed"
            assert outbox.status()["pending"] == 1
        finally:
            assert writer.close(timeout_seconds=1)["drained"]
            client.close()
