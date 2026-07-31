"""Compatibility name for the provider-neutral offline tracker fixture."""

from __future__ import annotations

from pathlib import Path

try:
    from .base import StructuredFixtureAdapter, load_fixture
except ImportError:  # pragma: no cover
    from base import StructuredFixtureAdapter, load_fixture


class LinearFixtureAdapter(StructuredFixtureAdapter):
    """Legacy import retained without owning Linear provider behavior."""

    def __init__(self, payload: dict):
        super().__init__(payload, kind="linear")

    @classmethod
    def from_file(cls, path: Path) -> "LinearFixtureAdapter":
        return cls(load_fixture(path))
