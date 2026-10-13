"""Legacy task-bound validation identity and item-owned artifact regressions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_validation_refresh as refresh
from test_development_validation_refresh import _fixture, _refresh


def test_genuinely_recorded_legacy_shape_refreshes_without_rewriting_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, legacy=True)
    before = fixture["task"].read()
    original = fixture["predecessor"].read_bytes()

    result = _refresh(fixture)
    after = result["task"]

    assert fixture["predecessor"].read_bytes() == original
    assert after["receipts"][:-1] == before["receipts"]
    assert after["state"] == before["state"]
    assert after["subject_revision"] is None
    assert after["validation_head_sha"] == fixture["head"]
    authority = after["validation_refreshes"][-1]["predecessor_identity_attestation"]
    assert authority["schema"] == "development-validation-predecessor-attestation/v1"
    assert authority["kind"] == "task_bound_legacy_identity"
    assert authority["predecessor_sha256"] == before["receipts"][-1]["sha256"]
    assert _refresh(fixture)["replayed"] is True


def test_only_configured_registered_item_artifacts_are_admitted(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ticket = fixture["task"].read()["ticket"]
    artifact = fixture["worktree"] / ".features" / ticket / "checks" / "watch-state.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"status":"success"}\n')
    original = artifact.read_bytes()

    assert _refresh(fixture)["task"]["validation_head_sha"] == fixture["head"]
    assert artifact.read_bytes() == original

