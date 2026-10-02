"""Bounded durable recovery buffer behind the RunLogStore application port.

This module is deliberately not wired to producers yet. A durable acknowledgement
means both the envelope and its directory entry were fsynced. Replay never holds
the filesystem lock during provider I/O; fencing tokens reject stale workers.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import fcntl
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Iterator
from uuid import uuid4

from .store import EvidenceRecord, RunLogStore, RunLogStoreError


class OutboxError(RunLogStoreError):
    """Visible local durability or envelope failure."""


class OutboxFull(OutboxError):
    """The configured count or byte limit would be exceeded."""


class OutboxBusy(OutboxError):
    """Another local owner holds the lock; callers must not wait indefinitely."""


class ClaimLost(OutboxError):
    """The replay lease expired or was replaced by another worker."""


@dataclass(frozen=True)
class OutboxPolicy:
    max_items: int
    max_bytes: int
    max_record_bytes: int
    lease_seconds: float = 30
    max_attempts: int = 5
    retry_seconds: float = 1
    max_retry_seconds: float = 60
    max_replay_items: int = 100

    def __post_init__(self) -> None:
        for name in ("max_items", "max_bytes", "max_record_bytes", "max_attempts", "max_replay_items"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("lease_seconds", "retry_seconds", "max_retry_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.max_record_bytes > self.max_bytes:
            raise ValueError("max_record_bytes exceeds max_bytes")
        if self.max_items < 2 or self.max_bytes < 2 * self.max_record_bytes:
            raise ValueError("outbox must reserve one slot and one record for atomic replacement")


@dataclass(frozen=True)
class OutboxClaim:
    key: str
    token: str
    record: EvidenceRecord


class FilesystemOutbox:
    """One quota covers pending, claimed, quarantined and interrupted temp files.

    One item slot and max_record_bytes of the quota are reserved for atomic
    updates, so a full buffer can still claim and retry existing evidence.
    Use an item-owned local directory, not a network filesystem. Advisory flock
    ownership is released by the OS on process death. No host-wide cleanup or
    implicit deletion of poison evidence occurs here.
    """

    def __init__(self, root: Path, policy: OutboxPolicy):
        self.root = Path(root)
        self.policy = policy
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OutboxBusy("outbox metadata lock is busy") from None
            yield
        finally:
            os.close(fd)

    def _files(self) -> list[Path]:
        files = []
        for path in self.root.iterdir():
            if path.name == ".lock":
                continue
            if path.is_symlink() or not path.is_file():
                raise OutboxError("unexpected outbox entry")
            files.append(path)
            if len(files) > self.policy.max_items:
                raise OutboxFull("outbox item limit exceeded")
        return files

    def _sync_directory(self) -> None:
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise OutboxError("invalid envelope identity")
        return self.root / f"{key}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        if path.is_symlink() or path.stat().st_size > self.policy.max_record_bytes:
            raise OutboxError("invalid envelope file")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["schema"] != "run-evidence-outbox/v1" or value["state"] not in {"pending", "claimed", "quarantined"}:
                raise ValueError
            EvidenceRecord(**value["record"])
            if self._key(value["record"]) != path.stem:
                raise ValueError
            for field in ("created_at", "next_attempt_at"):
                if type(value[field]) not in (int, float) or not math.isfinite(value[field]):
                    raise ValueError
            if type(value["attempts"]) is not int or not 0 <= value["attempts"] <= self.policy.max_attempts:
                raise ValueError
            if value["state"] == "claimed" and (
                not isinstance(value["token"], str)
                or len(value["token"]) != 32
                or type(value["lease_until"]) not in (int, float)
                or not math.isfinite(value["lease_until"])
            ):
                raise ValueError
            return value
        except (ValueError, KeyError, TypeError):
            raise OutboxError("invalid outbox envelope; operator recovery required") from None

    @staticmethod
    def _key(document: dict[str, Any]) -> str:
        return sha256(json.dumps([document["model_key"], document["content_hash"]], separators=(",", ":")).encode()).hexdigest()

    def _write(self, path: Path, value: dict[str, Any]) -> None:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(data) > self.policy.max_record_bytes:
            raise OutboxFull("envelope exceeds record byte limit")
        files = self._files()
        # Reserve space for atomic replacement's temporary second copy, too.
        creating = path not in files
        reserved_count = 2 if creating else 1
        reserved_bytes = self.policy.max_record_bytes if creating else 0
        if len(files) + reserved_count > self.policy.max_items or sum(item.stat().st_size for item in files) + len(data) + reserved_bytes > self.policy.max_bytes:
            raise OutboxFull("outbox count or byte limit reached")
        temporary = self.root / f"{uuid4().hex}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory()
        except OSError:
            # An fsync failure after rename has an uncertain durable outcome.
            # Never acknowledge it, never delete the committed destination.
            raise OutboxError("outbox durable write failed") from None
        finally:
            if temporary.exists():
                temporary.unlink()

    def put(self, record: EvidenceRecord, *, now: float | None = None) -> str:
        """Return the durable envelope key, or raise without acknowledging."""
        now = time.time() if now is None else now
        if type(now) not in (int, float) or not math.isfinite(now):
            raise OutboxError("invalid outbox timestamp")
        try:
            document = json.loads(json.dumps(record.normalized(), allow_nan=False))
        except (TypeError, ValueError):
            raise OutboxError("evidence is not JSON serializable") from None
        key = self._key(document)
        path = self._path(key)
        with self._locked():
            if path.exists():
                existing = self._read(path)["record"]
                fields = set(document) - {"id", "ingested_at"}
                if any(existing.get(field) != document[field] for field in fields):
                    raise OutboxError("content identity conflicts with retained evidence")
                # A prior call may have failed directory fsync after rename.
                self._sync_directory()
                return key
            self._write(path, {
                "schema": "run-evidence-outbox/v1", "state": "pending",
                "record": document, "created_at": now, "attempts": 0,
                "next_attempt_at": now, "token": None, "lease_until": None,
                "error_code": None,
            })
        return key

    def claim(self, *, now: float | None = None) -> OutboxClaim | None:
        """Claim at most one eligible item; expired leases are recoverable."""
        now = time.time() if now is None else now
        with self._locked():
            for path in sorted(self._files()):
                if path.suffix != ".json":
                    continue  # Interrupted temporary writes are never replayed.
                item = self._read(path)
                if item["state"] == "quarantined" or item["next_attempt_at"] > now:
                    continue
                if item["state"] == "claimed" and item["lease_until"] > now:
                    continue
                item.update(state="claimed", token=uuid4().hex, lease_until=now + self.policy.lease_seconds)
                self._write(path, item)
                return OutboxClaim(path.stem, item["token"], EvidenceRecord(**item["record"]))
        return None

    def _owned(self, claim: OutboxClaim, now: float) -> tuple[Path, dict[str, Any]]:
        path = self._path(claim.key)
        if not path.exists():
            raise ClaimLost("outbox claim no longer exists")
        item = self._read(path)
        if item["state"] != "claimed" or item["token"] != claim.token or item["lease_until"] <= now:
            raise ClaimLost("outbox lease is no longer owned")
        return path, item

    def _acknowledge(self, claim: OutboxClaim, *, now: float) -> None:
        with self._locked():
            path, _ = self._owned(claim, now)
            path.unlink()
            self._sync_directory()

    def retry(self, claim: OutboxClaim, *, now: float | None = None, error_code: str = "provider_unavailable") -> None:
        """Retain failed evidence with capped backoff; quarantine after budget."""
        if error_code not in {"provider_unavailable", "readback_mismatch"}:
            raise ValueError("unsupported outbox error code")
        now = time.time() if now is None else now
        with self._locked():
            path, item = self._owned(claim, now)
            attempts = min(item["attempts"] + 1, self.policy.max_attempts)
            delay = min(self.policy.max_retry_seconds, self.policy.retry_seconds * 2 ** min(attempts - 1, 30))
            item.update(attempts=attempts, next_attempt_at=now + delay,
                        state="quarantined" if attempts >= self.policy.max_attempts else "pending",
                        error_code=error_code, token=None, lease_until=None)
            self._write(path, item)

    def replay(self, store: RunLogStore, *, limit: int = 1) -> dict[str, int]:
        """Persist then verify through the port before retiring local evidence."""
        if type(limit) is not int or not 1 <= limit <= self.policy.max_replay_items:
            raise ValueError("replay limit exceeds policy")
        counts = {"persisted": 0, "retry": 0}
        for _ in range(limit):
            claim = self.claim()
            if claim is None:
                break
            code = "provider_unavailable"
            try:
                result = store.append(claim.record)
                readback = store.get(claim.record.model_key, result["id"])
                expected = claim.record.normalized()
                code = "readback_mismatch"
                fields = (
                    "model_key", "host_id", "source", "occurred_at", "schema_version",
                    "classification", "payload", "payload_metadata", "content_hash",
                    "correlation_id", "run_id", "work_item_id",
                )
                if readback is None or any(readback.get(field) != expected[field] for field in fields):
                    raise OutboxError("provider readback mismatch")
            except Exception:
                self.retry(claim, error_code=code)
                counts["retry"] += 1
            else:
                self._acknowledge(claim, now=time.time())
                counts["persisted"] += 1
        return counts

    def status(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._locked():
            files = self._files()
            items = [self._read(path) for path in files if path.suffix == ".json"]
            return {
                "count": len(files), "bytes": sum(path.stat().st_size for path in files),
                "pending": sum(item["state"] == "pending" for item in items),
                "claimed": sum(item["state"] == "claimed" for item in items),
                "quarantined": sum(item["state"] == "quarantined" for item in items),
                "temporary": sum(path.suffix == ".tmp" for path in files),
                "oldest_age_seconds": max((max(0, now - item["created_at"]) for item in items), default=0),
            }
