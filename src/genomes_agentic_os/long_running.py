"""Reusable durability primitives for cooperative long-running operations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import time
from typing import Any


PROGRESS_SCHEMA = "agentic-os-long-running-progress/v1"
TERMINAL_RECEIPT_SCHEMA = "agentic-os-long-running-terminal-receipt/v1"


class RunInterrupted(BaseException):
    """Raised by signal handlers so a cooperative operation can recover safely."""


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


class DurableRunProgress:
    """Atomic progress snapshot plus fsynced append-only semantic journal."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        operation: str,
        items_total: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.path = path
        self.journal_path = path.with_name("journal.jsonl")
        now = utc_now()
        self.payload: dict[str, Any] = {
            "schema": PROGRESS_SCHEMA,
            "run_id": run_id,
            "operation": operation,
            "pid": os.getpid(),
            "status": "running",
            "phase": "preflight",
            "started_at": now,
            "updated_at": now,
            "last_semantic_progress_at": now,
            "items_total": items_total,
            "items_completed": 0,
            "files_total": 0,
            "files_completed": 0,
            "bytes_total": 0,
            "bytes_completed": 0,
            "current_path": None,
            **(metadata or {}),
        }
        self._last_write = 0.0
        self.write(force=True)
        self.event("run_started", phase="preflight")

    def update(self, *, force: bool = False, **values: Any) -> None:
        semantic = any(
            key in values
            for key in (
                "phase",
                "items_completed",
                "files_completed",
                "bytes_completed",
                "status",
            )
        )
        self.payload.update(values)
        self.payload["updated_at"] = utc_now()
        if semantic:
            self.payload["last_semantic_progress_at"] = self.payload["updated_at"]
        self.write(force=force)

    def write(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_write >= 1.0:
            atomic_json(self.path, self.payload)
            self._last_write = now

    def event(self, event: str, **values: Any) -> None:
        payload = {
            "at": utc_now(),
            "run_id": self.payload["run_id"],
            "event": event,
            **values,
        }
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class MutationLock:
    """Exclusive mutation lock with deterministic orphan recovery."""

    def __init__(self, path: Path, *, run_id: str, operation: str) -> None:
        self.path = path
        self.run_id = run_id
        self.operation = operation

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "operation": self.operation,
            "pid": os.getpid(),
            "created_at": utc_now(),
        }
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                try:
                    existing = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(existing.get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = 0
                if pid and self._pid_is_live(pid):
                    raise RuntimeError(
                        f"{self.operation} lock is held by live PID {pid}"
                    )
                stale = self.path.with_name(
                    f"{self.path.name}.stale-{int(time.time())}"
                )
                try:
                    self.path.replace(stale)
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, sort_keys=True) + "\n")
            return
        raise RuntimeError(f"could not acquire {self.operation} lock")

    def release(self) -> None:
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if existing.get("run_id") == self.run_id:
            self.path.unlink(missing_ok=True)


class SignalGuard:
    """Translate SIGINT/SIGTERM into a recoverable BaseException."""

    def __init__(self) -> None:
        self.previous: dict[int, Any] = {}

    @staticmethod
    def _handle(signum: int, _frame: Any) -> None:
        raise RunInterrupted(f"received signal {signal.Signals(signum).name}")

    def __enter__(self) -> "SignalGuard":
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self.previous[signum] = signal.signal(signum, self._handle)
            except ValueError:
                pass
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)
