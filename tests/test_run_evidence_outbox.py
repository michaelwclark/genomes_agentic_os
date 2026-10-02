"""Durability, fencing and recovery checks using only temporary outboxes."""
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from genomes_agentic_os.run_evidence import EvidenceRecord, InMemoryRunLogStore, load_run_log_store_config
from genomes_agentic_os.run_evidence.outbox import (
    ClaimLost, FilesystemOutbox, OutboxBusy, OutboxError, OutboxFull, OutboxPolicy,
)

REPO = Path(__file__).parents[1]


def record(**changes):
    values = dict(model_key="run_log", host_id="bigmac", source="tests",
                  classification="durable_evidence", payload={"result": "ok"},
                  occurred_at="2026-10-02T00:00:00Z", schema_version=1,
                  correlation_id="correlation", run_id="run", work_item_id="AGE-153")
    values.update(changes)
    return EvidenceRecord(**values)


def box(tmp_path, **changes):
    values = dict(max_items=10, max_bytes=100_000, max_record_bytes=10_000,
                  lease_seconds=10, max_attempts=2, retry_seconds=.01)
    values.update(changes)
    return FilesystemOutbox(tmp_path / "outbox", OutboxPolicy(**values))


def store():
    result = InMemoryRunLogStore(replace(load_run_log_store_config(REPO), backend="memory"))
    result.upsert_host({"host_id": "bigmac"})
    return result


def test_restart_replay_preserves_identity_metadata_and_durable_evidence(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record(id="original", ingested_at="2026-10-02T00:00:01Z"))
    restarted = box(tmp_path)
    provider = store()
    assert restarted.replay(provider) == {"persisted": 1, "retry": 0}
    saved = provider.get("run_log", "original")
    assert saved["correlation_id"] == "correlation"
    assert saved["ingested_at"] == "2026-10-02T00:00:01Z"
    assert saved["work_item_id"] == "AGE-153"
    assert not (outbox.root / f"{key}.json").exists()


def test_duplicate_after_provider_success_before_ack_is_idempotent(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record())
    claim = outbox.claim(now=time.time())
    provider = store()
    saved = provider.append(claim.record)
    # Expire the lease in the persisted envelope to simulate a stopped worker.
    document = json.loads((outbox.root / f"{key}.json").read_text())
    document["lease_until"] = 0
    (outbox.root / f"{key}.json").write_text(json.dumps(document))
    assert outbox.replay(provider)["persisted"] == 1
    assert provider.search("run_log") == [saved]


def test_duplicate_put_reuses_frozen_record_and_rejects_hash_conflict(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record())
    assert outbox.put(record()) == key
    frozen = json.loads((outbox.root / f"{key}.json").read_text())["record"]
    with pytest.raises(OutboxError, match="conflicts"):
        outbox.put(record(content_hash=frozen["content_hash"], payload={"other": "data"}))
    assert outbox.status()["pending"] == 1


def test_stale_claim_cannot_remove_new_owners_evidence(tmp_path):
    outbox = box(tmp_path)
    outbox.put(record(), now=0)
    first = outbox.claim(now=0)
    assert outbox.claim(now=1) is None
    second = outbox.claim(now=11)
    assert second.token != first.token
    with pytest.raises(ClaimLost):
        outbox._acknowledge(first, now=12)
    assert outbox.status(now=12)["claimed"] == 1
    outbox._acknowledge(second, now=12)


def test_count_limit_reserves_atomic_update_slot(tmp_path):
    outbox = box(tmp_path, max_items=2)
    outbox.put(record(), now=0)
    with pytest.raises(OutboxFull):
        outbox.put(record(payload={"result": "second"}), now=0)
    claim = outbox.claim(now=0)
    outbox.retry(claim, now=0)
    assert outbox.status(now=0)["pending"] == 1


def test_failed_fsync_never_acknowledges_or_replays_temporary_file(tmp_path, monkeypatch):
    outbox = box(tmp_path)
    monkeypatch.setattr(os, "fsync", lambda _: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OutboxError, match="durable write failed"):
        outbox.put(record())
    assert outbox.status()["count"] == 0


def test_directory_fsync_failure_keeps_unacknowledged_record(tmp_path, monkeypatch):
    outbox = box(tmp_path)
    real_fsync = os.fsync
    calls = []
    def fail_second(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("directory unavailable")
        real_fsync(fd)
    monkeypatch.setattr(os, "fsync", fail_second)
    with pytest.raises(OutboxError):
        outbox.put(record())
    assert outbox.status()["pending"] == 1
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert outbox.put(record())
    assert outbox.status()["pending"] == 1


def test_lock_contention_returns_without_waiting(tmp_path):
    outbox = box(tmp_path)
    fd = os.open(outbox.root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(OutboxBusy):
            outbox.put(record())
        assert time.monotonic() - started < .5
    finally:
        os.close(fd)


def test_readback_failure_keeps_evidence_and_quarantines_at_retry_budget(tmp_path):
    outbox = box(tmp_path, retry_seconds=.001)
    outbox.put(record())
    provider = store()
    provider.get = lambda *args: None
    assert outbox.replay(provider) == {"persisted": 0, "retry": 1}
    time.sleep(.005)
    assert outbox.replay(provider) == {"persisted": 0, "retry": 1}
    assert outbox.status()["quarantined"] == 1
    assert outbox.claim() is None


def test_provider_exception_is_sanitized_and_retained(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record())
    class Offline:
        def append(self, record):
            raise RuntimeError("credential-shaped-private-provider-details")
    assert outbox.replay(Offline())["retry"] == 1
    text = (outbox.root / f"{key}.json").read_text()
    assert "credential-shaped" not in text
    assert "provider_unavailable" in text


def test_invalid_payload_and_record_byte_limit_fail_before_ack(tmp_path):
    outbox = box(tmp_path)
    with pytest.raises(OutboxError):
        outbox.put(record(payload={"invalid": object()}))
    with pytest.raises(OutboxFull):
        outbox.put(record(payload={"huge": "x" * 20_000}))
    assert outbox.status()["count"] == 0


def test_interrupted_temp_file_is_never_replayed_and_counts_toward_quota(tmp_path):
    outbox = box(tmp_path)
    (outbox.root / "interrupted.tmp").write_text("incomplete")
    assert outbox.claim() is None
    assert outbox.status()["temporary"] == 1
    assert outbox.status()["bytes"] == len("incomplete")


def test_two_instances_do_not_claim_the_same_item(tmp_path):
    first = box(tmp_path)
    second = box(tmp_path)
    first.put(record(), now=0)
    assert first.claim(now=0) is not None
    assert second.claim(now=1) is None


@pytest.mark.parametrize("changes", [{"lease_seconds": float("nan")}, {"max_items": True}, {"max_items": 1}, {"max_bytes": 10}])
def test_invalid_policy_is_rejected_before_use(tmp_path, changes):
    with pytest.raises(ValueError):
        box(tmp_path, **changes)


def test_private_envelope_permissions_and_bounded_replay(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record())
    assert (outbox.root / f"{key}.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        outbox.replay(store(), limit=101)


def test_process_exit_releases_lock_and_durable_claim_is_recoverable(tmp_path):
    outbox = box(tmp_path)
    outbox.put(record(), now=0)
    code = '''
import os, sys
from pathlib import Path
from genomes_agentic_os.run_evidence.outbox import FilesystemOutbox, OutboxPolicy
box = FilesystemOutbox(Path(sys.argv[1]), OutboxPolicy(10, 100000, 10000, lease_seconds=10))
assert box.claim(now=0) is not None
with box._locked():
    os._exit(0)
'''
    result = subprocess.run([sys.executable, "-c", code, str(outbox.root)], timeout=10, check=False)
    assert result.returncode == 0
    assert outbox.claim(now=1) is None
    assert outbox.claim(now=11) is not None


def test_concurrent_processes_preserve_count_bound(tmp_path):
    outbox = box(tmp_path, max_items=2)
    code = '''
import sys
from pathlib import Path
from genomes_agentic_os.run_evidence import EvidenceRecord
from genomes_agentic_os.run_evidence.outbox import FilesystemOutbox, OutboxPolicy, OutboxFull, OutboxBusy
box = FilesystemOutbox(Path(sys.argv[1]), OutboxPolicy(2, 100000, 10000))
record = EvidenceRecord("run_log", "bigmac", "test", "durable_evidence", {"n": sys.argv[2]}, "2026-10-02T00:00:00Z", 1)
try:
    box.put(record)
except (OutboxFull, OutboxBusy):
    sys.exit(2)
'''
    children = [subprocess.Popen([sys.executable, "-c", code, str(outbox.root), str(n)]) for n in range(3)]
    try:
        results = [child.wait(timeout=10) for child in children]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
    assert results.count(0) == 1
    assert results.count(2) == 2
    assert outbox.status()["count"] == 1


def test_corrupt_envelope_fails_visibly_and_is_preserved(tmp_path):
    outbox = box(tmp_path)
    key = outbox.put(record())
    path = outbox.root / f"{key}.json"
    path.write_text('{"schema":"unsupported"}')
    with pytest.raises(OutboxError, match="invalid outbox envelope"):
        outbox.claim()
    assert path.exists()


def test_nan_timestamp_fails_before_durable_write(tmp_path):
    outbox = box(tmp_path)
    with pytest.raises(OutboxError):
        outbox.put(record(), now=float("nan"))
    assert outbox.status()["count"] == 0
