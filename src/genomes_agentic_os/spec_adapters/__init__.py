"""Provider adapters for the Spec Engine."""

from .base import SpecAdapter, SpecTransport
from .filesystem import FilesystemSpecAdapter
from .jira import JiraBridgeSpecTransport, JiraSpecAdapter, transport_from_environment
from .linear import LinearSpecAdapter

__all__ = [
    "FilesystemSpecAdapter",
    "JiraBridgeSpecTransport",
    "JiraSpecAdapter",
    "LinearSpecAdapter",
    "SpecAdapter",
    "SpecTransport",
    "transport_from_environment",
]
