"""Optional MongoDB driver contract used by the AGE-152 adapter."""

from __future__ import annotations

import pytest


def test_pymongo_exposes_the_construction_and_index_surface() -> None:
    pymongo = pytest.importorskip("pymongo")

    assert callable(pymongo.MongoClient)
    assert hasattr(pymongo, "ASCENDING")
