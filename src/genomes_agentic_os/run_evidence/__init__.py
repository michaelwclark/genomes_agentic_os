"""Provider-neutral storage for append-oriented run evidence."""

from .store import (
    EvidenceRecord,
    InMemoryRunLogStore,
    RunLogStore,
    RunLogStoreConfig,
    RunLogStoreConfigurationError,
    RunLogStoreError,
    UnknownHostError,
    build_configured_run_log_store,
    build_run_log_store,
    load_run_log_store_config,
    seed_configured_host,
)

__all__ = [
    "EvidenceRecord",
    "InMemoryRunLogStore",
    "RunLogStore",
    "RunLogStoreConfig",
    "RunLogStoreConfigurationError",
    "RunLogStoreError",
    "UnknownHostError",
    "build_configured_run_log_store",
    "build_run_log_store",
    "load_run_log_store_config",
    "seed_configured_host",
]
