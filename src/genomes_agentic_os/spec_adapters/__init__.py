"""Provider adapters for the Spec Engine."""

from .base import SpecAdapter, SpecTransport
from .filesystem import FilesystemSpecAdapter
from .jira import (
    JiraBridgeSpecTransport,
    JiraSpecAdapter,
    transport_from_environment as jira_transport_from_environment,
)
from .linear import (
    LinearBridgeSpecTransport,
    LinearSpecAdapter,
    transport_from_environment as linear_transport_from_environment,
)

# Preserve the AGE-131 public import while exposing both provider factories.
transport_from_environment = jira_transport_from_environment

__all__ = [
    "FilesystemSpecAdapter",
    "JiraBridgeSpecTransport",
    "JiraSpecAdapter",
    "LinearBridgeSpecTransport",
    "LinearSpecAdapter",
    "SpecAdapter",
    "SpecTransport",
    "jira_transport_from_environment",
    "linear_transport_from_environment",
    "transport_from_environment",
]
