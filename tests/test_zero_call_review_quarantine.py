"""Invalid derived authority stays unusable without buying a second review."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from genomes_agentic_os.review_coordination import (
    ReviewBudgetExceeded, ReviewCoordinationError, ReviewCoordinator,
    assert_exact_head_review_receipt, load_review_receipt,
)
from test_review_parent_resolution_protocol import (
    PARENT_IDS, advice, legacy_delta, legacy_recovery_receipt,
    parent_review, response, subject,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    coordinator = ReviewCoordinator(tmp_path / "reviews")
    parent = parent_review(coordinator)
    rows = advice()
    text = response(rows)
    delta = legacy_delta(coordinator, parent, text)
    # Reproduce the older producer's loss of inherited rows, using its actual
    # immutable derivation format rather than relaxing the current loader.
    child = legacy_recovery_receipt(coordinator, delta, text, rows, [])
    payload = json.loads(child.read_bytes())
    index = {field: payload[field] for field in (
        "key", "family_key", "chain_key", "mode", "outcome", "subject",
    )}
    index.update(schema="auto-dev-review-index/v1", budget_consumed=False, receipt_ref=str(child))
    (coordinator.index / child.name).write_text(json.dumps(index))
    binding = {
        "key": child.stem, "receipt_sha256": _digest(child),
        "family_key": delta.receipt["family_key"], "source_key": delta.key,
        "source_receipt_sha256": _digest(delta.receipt_path),
    }
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({
        "schema": "auto-dev-zero-call-quarantine-approval/v1",
        "approved": True, "reason": "Preserve invalid zero-call derivation", **binding,
    }))
    arguments = {k: v for k, v in binding.items() if k != "family_key"}
    arguments.update(approval_path=approval, approval_sha256=_digest(approval))
    return coordinator, parent, delta, child, arguments


@pytest.mark.parametrize("prequarantined", [False, True])
def test_native_quarantine_preserves_paid_history_and_blocks_bad_key(tmp_path, prequarantined):
    coordinator, parent, delta, child, arguments = _fixture(tmp_path)
    original = {p: p.read_bytes() for p in (parent.receipt_path, delta.receipt_path, child)}
    with pytest.raises(ReviewCoordinationError, match="unresolved inherited"):
        load_review_receipt(child)
    if prequarantined:
        for _ in range(2):
            with pytest.raises(ReviewCoordinationError, match="budget accounting failed closed"):
                coordinator.execute(subject("3" * 40), lambda: pytest.fail("No paid call"))
    metadata_path = coordinator.quarantine_invalid_advisory_derivative(**arguments)
    first_metadata = metadata_path.read_bytes()
    metadata = json.loads(first_metadata)
    assert metadata["budget_consumed"] is False and metadata["mode"] == "advisory_recovery"
    assert Path(metadata["quarantine_ref"]).read_bytes() == original[child]
    assert not child.exists()
    assert all(path.read_bytes() == raw for path, raw in original.items() if path != child)
    assert coordinator.quarantine_invalid_advisory_derivative(**arguments) == metadata_path
    assert metadata_path.read_bytes() == first_metadata
    with pytest.raises(ReviewCoordinationError):
        assert_exact_head_review_receipt(child, head_sha=subject("2" * 40).head_sha)
    with pytest.raises(ReviewCoordinationError):
        load_review_receipt(metadata["quarantine_ref"])
    # Genuine parent-resolution evidence is still necessary for the next delta.
    next_review = coordinator.execute(
        subject("3" * 40), lambda: {"outcome": "clean", "resolution_refs": list(PARENT_IDS)},
        mode="delta", parent_key=delta.key,
    )
    assert next_review.receipt["budget"]["full_reviews_used"] == 1
    assert next_review.receipt["budget"]["delta_reviews_used"] == 2
    last = coordinator.execute(subject("4" * 40), lambda: {"outcome": "clean"},
                               mode="delta", parent_key=next_review.key)
    with pytest.raises(ReviewBudgetExceeded, match="delta-review budget"):
        coordinator.execute(subject("5" * 40), lambda: pytest.fail("No paid call"),
                            mode="delta", parent_key=last.key)
    evidence = tmp_path / "original-response.md"
    evidence.write_text(response(advice()))
    with pytest.raises(ReviewCoordinationError, match="unresolved"):
        coordinator.derive_same_head_advisory_clean(
            delta.receipt_path, evidence_path=evidence, findings=advice(),
        )


@pytest.mark.parametrize("changed", [
    "key", "receipt_sha256", "source_key", "source_receipt_sha256", "approval_sha256",
    "approval-family", "approval-denied", "approval-empty-reason",
    "index-paid", "index-mode", "index-subject", "missing-index",
    "wrong-derivation", "wrong-response", "missing-recovery", "missing-review",
])
def test_neutral_classification_refuses_unproven_or_changed_authority(tmp_path, changed):
    coordinator, parent, delta, child, arguments = _fixture(tmp_path)
    if changed in arguments:
        arguments[changed] = "f" * 64
    elif changed.startswith("approval-"):
        path = arguments["approval_path"]
        data = json.loads(path.read_bytes())
        field, value = {
            "approval-family": ("family_key", "f" * 64),
            "approval-denied": ("approved", False),
            "approval-empty-reason": ("reason", ""),
        }[changed]
        data[field] = value
        path.write_text(json.dumps(data))
        arguments["approval_sha256"] = _digest(path)
    elif "index" in changed:
        path = coordinator.index / child.name
        if changed == "missing-index":
            path.unlink()
        else:
            data = json.loads(path.read_bytes())
            field, value = {
                "index-paid": ("budget_consumed", True), "index-mode": ("mode", "delta"),
                "index-subject": ("subject", {**data["subject"], "repository": "acme/other"}),
            }[changed]
            data[field] = value
            path.write_text(json.dumps(data))
    else:
        data = json.loads(child.read_bytes())
        if changed == "wrong-derivation":
            data["recovery"]["evidence_sha256"] = "f" * 64
        elif changed == "wrong-response":
            data["review"]["response"] += "changed"
        else:
            data.pop("recovery" if changed == "missing-recovery" else "review")
        child.write_text(json.dumps(data))
        arguments["receipt_sha256"] = _digest(child)
        path = arguments["approval_path"]
        approved = json.loads(path.read_bytes())
        approved["receipt_sha256"] = arguments["receipt_sha256"]
        path.write_text(json.dumps(approved))
        arguments["approval_sha256"] = _digest(path)
    before = {p: p.read_bytes() for p in coordinator.root.rglob("*.json")}
    with pytest.raises(ReviewCoordinationError):
        coordinator.quarantine_invalid_advisory_derivative(**arguments)
    assert {p: p.read_bytes() for p in coordinator.root.rglob("*.json")} == before


def test_concurrent_neutral_admission_is_idempotent_and_unrelated_unknown_stays_blocked(tmp_path):
    coordinator, _, _, child, arguments = _fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(
            lambda _: ReviewCoordinator(coordinator.root).quarantine_invalid_advisory_derivative(**arguments),
            range(2),
        ))
    assert paths[0] == paths[1]
    assert len(list(coordinator.quarantine.glob("*.meta.json"))) == 1
    unknown = coordinator.receipts / ("f" * 64 + ".json")
    unknown.write_text("unidentified corrupt record")
    for _ in range(2):
        with pytest.raises(ReviewCoordinationError, match="unidentified|quarantined"):
            coordinator.execute(subject("3" * 40), lambda: pytest.fail("No paid call"),
                                mode="delta", parent_key=arguments["source_key"])


@pytest.mark.parametrize("paid", [False, True])
def test_valid_advice_and_paid_receipts_cannot_be_reclassified(tmp_path, paid):
    coordinator = ReviewCoordinator(tmp_path / "reviews")
    text = response(advice())
    original = coordinator.execute(subject(), lambda: {"outcome": "findings", "response": text})
    evidence = tmp_path / "response.md"
    evidence.write_text(text)
    valid = coordinator.derive_same_head_advisory_clean(
        original.receipt_path, evidence_path=evidence, findings=advice(),
    )
    selected = original if paid else valid
    binding = {
        "key": selected.key, "receipt_sha256": _digest(selected.receipt_path),
        "family_key": original.receipt["family_key"], "source_key": original.key,
        "source_receipt_sha256": _digest(original.receipt_path),
    }
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({
        "schema": "auto-dev-zero-call-quarantine-approval/v1",
        "approved": True, "reason": "Cannot authorize this reclassification", **binding,
    }))
    arguments = {k: v for k, v in binding.items() if k != "family_key"}
    before = {p: p.read_bytes() for p in coordinator.root.rglob("*.json")}
    with pytest.raises(ReviewCoordinationError, match="unpaid advisory|invalid inherited"):
        coordinator.quarantine_invalid_advisory_derivative(
            **arguments, approval_path=approval, approval_sha256=_digest(approval),
        )
    assert {p: p.read_bytes() for p in coordinator.root.rglob("*.json")} == before


def test_classification_refuses_conflicting_approval_and_preserves_first_proof(tmp_path):
    coordinator, _, _, _, arguments = _fixture(tmp_path)
    metadata = coordinator.quarantine_invalid_advisory_derivative(**arguments)
    before = metadata.read_bytes()
    approval = arguments["approval_path"]
    data = json.loads(approval.read_bytes())
    data["reason"] += " Changed approval"
    approval.write_text(json.dumps(data))
    arguments["approval_sha256"] = _digest(approval)
    with pytest.raises(ReviewCoordinationError, match="conflicts"):
        coordinator.quarantine_invalid_advisory_derivative(**arguments)
    assert metadata.read_bytes() == before


@pytest.mark.parametrize("changed", [{"outcome": "unknown"}, {"mode": "unknown", "outcome": "unavailable"}])
def test_known_family_unknown_quarantine_identity_remains_blocked_on_repeated_admission(tmp_path, changed):
    coordinator, _, delta, _, arguments = _fixture(tmp_path)
    coordinator.quarantine_invalid_advisory_derivative(**arguments)
    unknown = coordinator.receipts / ("f" * 64 + ".json")
    payload = {**delta.receipt, **changed, "key": "f" * 64}
    unknown.write_text(json.dumps(payload))
    for _ in range(2):
        with pytest.raises(ReviewCoordinationError, match="budget accounting failed closed"):
            ReviewCoordinator(coordinator.root).execute(
                subject("3" * 40), lambda: pytest.fail("No paid call"),
                mode="delta", parent_key=delta.key,
            )
