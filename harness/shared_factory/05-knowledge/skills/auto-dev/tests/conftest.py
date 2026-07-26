"""Keep every auto-dev test away from the real harness/state/agentic_os.db.

The RunStore flag defaults to sqlite (Phase 1 default-on), so without this
guard the pre-existing tests would dual-write fixture rows into the live DB.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolated_auto_dev_db() -> Iterator[None]:
    with tempfile.TemporaryDirectory(prefix="auto-dev-test-db-") as tmp:
        previous = os.environ.get("AUTO_DEV_DB")
        os.environ["AUTO_DEV_DB"] = os.path.join(tmp, "agentic_os.db")
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("AUTO_DEV_DB", None)
            else:
                os.environ["AUTO_DEV_DB"] = previous
