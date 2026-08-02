"""Provider-neutral control-plane store boundary.

The legacy approval and artifact-reference facts remain available from this
module for compatibility, while event-ledger and cursor operations are exposed
through an explicit store port.  The port does not migrate queue, lease,
work-item, replay, or runtime behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .control_plane_facts import (
    APPROVAL_STATUSES,
    CLASSIFICATIONS,
    DECISIONS,
    ControlPlaneError,
    control_plane_projection,
    decide_approval,
    expire_approvals,
    get_approval,
    get_artifact_reference,
    record_artifact_reference,
    request_approval,
    validate_change_linkage,
)


class ControlPlaneConfigurationError(ValueError):
    """Raised when a control-plane backend configuration is invalid."""


class UnsupportedControlPlaneBackend(ControlPlaneConfigurationError):
    """Raised for a declared backend which has no verified adapter yet."""


class ControlPlaneStore(Protocol):
    """Application-facing event and cursor operations for this first slice."""

    backend: str

    def append_event(self, event_type: str, **fields: Any) -> dict[str, Any]: ...

    def get_event(self, event_id: str) -> dict[str, Any] | None: ...

    def query_events(
        self,
        *,
        event_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        correlation_id: str | None = None,
        domain: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def set_cursor(
        self,
        name: str,
        *,
        cursor_type: str | None = None,
        last_value: str | None = None,
        last_idempotency_key: str | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]: ...

    def get_cursor(self, name: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ControlPlaneStoreConfig:
    """Explicit composition input for one control-plane store instance."""

    backend: str
    sqlite_path: Path | str | None = None
    sqlite_busy_timeout_ms: int = 5000

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ControlPlaneStoreConfig":
        """Parse the portable ``control_plane`` config shape without I/O."""
        backend = value.get("backend", "sqlite")
        sqlite = value.get("sqlite", {})
        if not isinstance(backend, str):
            raise ControlPlaneConfigurationError("control_plane.backend must be a string")
        if not isinstance(sqlite, Mapping):
            raise ControlPlaneConfigurationError("control_plane.sqlite must be a mapping")
        timeout = sqlite.get("busy_timeout_ms", 5000)
        if not isinstance(timeout, int) or timeout < 1:
            raise ControlPlaneConfigurationError("control_plane.sqlite.busy_timeout_ms must be a positive integer")
        return cls(
            backend=backend,
            sqlite_path=sqlite.get("path"),
            sqlite_busy_timeout_ms=timeout,
        )


def build_control_plane_store(config: ControlPlaneStoreConfig) -> ControlPlaneStore:
    """Build the selected backend at the composition edge."""
    backend = config.backend.strip().lower()
    if backend == "sqlite":
        if config.sqlite_path is None:
            raise ControlPlaneConfigurationError("control_plane.sqlite.path is required for the sqlite backend")
        from .adapters.sqlite import SQLiteControlPlaneStore

        return SQLiteControlPlaneStore(config.sqlite_path, busy_timeout_ms=config.sqlite_busy_timeout_ms)
    if backend == "postgres":
        raise UnsupportedControlPlaneBackend(
            "postgres backend is not implemented: it requires a driver, migrations, and passed lease/idempotency conformance tests"
        )
    raise UnsupportedControlPlaneBackend(f"unsupported control_plane.backend: {config.backend}")
