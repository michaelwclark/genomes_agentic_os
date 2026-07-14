"""Provider adapters for the Spec Engine."""

from .base import SpecAdapter, SpecTransport
from .filesystem import FilesystemSpecAdapter
from .jira import JiraSpecAdapter
from .linear import LinearSpecAdapter

__all__ = [
    "SpecAdapter",
    "SpecTransport",
    "FilesystemSpecAdapter",
    "LinearSpecAdapter",
    "JiraSpecAdapter",
]
