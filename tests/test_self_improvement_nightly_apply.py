"""Tests for the guarded self-improvement nightly-apply lane.

Coverage:
- Selection honors the auto_approve policy (class + min_score) against the
  ``proposed`` set only; feature-spec (score 19) and wrong-class items are
  excluded, doctor-check-draft (score 20) is selected.
- Dry-run writes nothing and mutates no proposal state.
- Apply approves + promotes selected proposals (reusing the existing mechanics),
  flips them out of ``proposed`` so a re-run is idempotent, and writes a receipt.
- ``max_per_night`` and the ``--limit`` override cap the number approved.
- Notion projection is best-effort: it lands an OS Work Intake row via a fake
  transport (Auto Mode unchecked, token never leaked), degrades without failing
  when the token is absent, and records a Notion error without failing the run.
- Stale ``proposed`` items outside the policy surface as ``stale_triage``.
- A disabled policy is a no-op, and exactly one summary notification is emitted.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from genomes_agentic_os import self_improvement as si


SENTINEL_TOKEN = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeTransport:
    """Records every request; returns canned JSON responses in order."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any) -> _FakeResponse:
        self.requests.append({"method": req.method, "url": req.full_url, "data": req.data})
        if not self._responses:
            raise AssertionError(f"FakeTransport ran out of responses for {req.method} {req.full_url}")
        return _FakeResponse(json.dumps(self._responses.pop(0)).encode("utf-8"))


class _RaisingTransport:
    def __call__(self, req: Any) -> _FakeResponse:  # noqa: D401 - test double
        raise RuntimeError("notion boom")


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _seed_root(tmp_path: Path, *, enable_nightly: bool = False) -> Path:
    """Create a minimal installed root with a self-improvement config.

    The scaffolded template ships ``nightly_apply.enabled: false`` (safe by
    default); pass ``enable_nightly=True`` to arm the lane for apply-path tests.
    """
    from genomes_agentic_os.cli import main

    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    if enable_nightly:
        config = si._load_yaml(root / si.CONFIG_PATH)
        nightly = dict(config.get("nightly_apply") or {})
        nightly["enabled"] = True
        config["nightly_apply"] = nightly
        (root / si.CONFIG_PATH).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


def _make_proposal(
    root: Path,
    *,
    finding_type: str,
    total_score: int,
    slug: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a valid proposal via the module's own construction path.

    Using ``_proposal_from_finding`` keeps content_hash and required fields
    consistent with what the approve/promote validators expect.
    """
    # Distribute the desired total across the score components deterministically.
    base, remainder = divmod(total_score, 6)
    components = [base] * 6
    components[0] += remainder
    score = si._score(
        frequency=components[0],
        severity=components[1],
        reuse=components[2],
        confidence=components[3],
        blast_radius=components[4],
        staleness=components[5],
    )
    finding = {
        "type": finding_type,
        "title": f"Finding {slug}",
        "summary": f"Recurring signal {slug} needs attention.",
        "evidence": f"validation failed repeatedly for {slug}",
        "score": score,
    }
    proposal = si._proposal_from_finding(root, [], finding)
    # Force a unique dedupe key + id per slug so seeded proposals never collide.
    proposal["dedupe_key"] = si._sha256(f"{finding_type}|{slug}")
    proposal["proposal_id"] = "si-" + si._digest(proposal["dedupe_key"], 12)
    proposal["title"] = f"Finding {slug}"
    if created_at is not None:
        proposal["created_at"] = created_at
    proposal["content_hash"] = si._proposal_content_hash(proposal)
    assert proposal["score"]["total"] == total_score
    return proposal


def _persist(root: Path, proposals: list[dict[str, Any]]) -> None:
    config = si._load_yaml(root / si.CONFIG_PATH)
    proposals_dir = si._output_path(root, config, "proposals")
    si._ensure_safe_dir(root, proposals_dir)
    for proposal in proposals:
        path = si._proposal_file(root, config, proposal["proposal_id"])
        si._atomic_write_yaml(root, path, proposal)


def _status_of(root: Path, proposal_id: str) -> str:
    config = si._load_yaml(root / si.CONFIG_PATH)
    return str(si._read_yaml(si._proposal_file(root, config, proposal_id)).get("promotion_status"))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_dry_run_selects_only_matching_class_and_score(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    feature = _make_proposal(root, finding_type="repeated_evidence", total_score=19, slug="feature")
    low = _make_proposal(root, finding_type="recurring_failure", total_score=18, slug="lowscore")
    _persist(root, [doctor, feature, low])

    result = si.nightly_apply_self_improvement(root, dry_run=True, notifier=_RecordingNotifier())

    assert result["mode"] == "dry-run"
    assert result["selected"] == [doctor["proposal_id"]]
    assert result["eligible"] == [doctor["proposal_id"]]
    # Dry-run mutates nothing.
    assert _status_of(root, doctor["proposal_id"]) == "proposed"
    assert not (root / si.NIGHTLY_APPLY_ROOT).exists()


def test_apply_approves_promotes_and_is_idempotent(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])

    result = si.nightly_apply_self_improvement(
        root, dry_run=False, notifier=_RecordingNotifier()
    )

    assert result["mode"] == "apply"
    assert [row["proposal_id"] for row in result["queued"]] == [doctor["proposal_id"]]
    assert len(result["approved"]) == 1
    assert _status_of(root, doctor["proposal_id"]) == "drafted"
    # Receipt written under the nightly-apply run root.
    assert result["receipt"].endswith(".json")
    assert (root / result["receipt"]).is_file()
    # Draft artifacts landed.
    assert result["queued"][0]["draft_paths"]

    # Re-running selects nothing because the item left the ``proposed`` set.
    rerun = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())
    assert rerun["selected"] == []
    assert rerun["approved"] == []


def test_max_per_night_and_limit_cap_selection(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    proposals = [
        _make_proposal(root, finding_type="recurring_failure", total_score=20, slug=f"d{i}")
        for i in range(5)
    ]
    _persist(root, proposals)

    capped = si.nightly_apply_self_improvement(root, dry_run=True, notifier=_RecordingNotifier())
    assert len(capped["selected"]) == 3  # max_per_night default
    assert len(capped["deferred_over_cap"]) == 2

    limited = si.nightly_apply_self_improvement(
        root, dry_run=True, limit=1, notifier=_RecordingNotifier()
    )
    assert len(limited["selected"]) == 1


# ---------------------------------------------------------------------------
# Notion projection (best-effort)
# ---------------------------------------------------------------------------


def test_apply_lands_intake_row_via_fake_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    monkeypatch.setenv(si.NOTION_TOKEN_ENV, SENTINEL_TOKEN)

    transport = _FakeTransport(
        [
            {  # GET database property types
                "properties": {
                    "Name": {"type": "title"},
                    "Type": {"type": "select"},
                    "Project": {"type": "select"},
                    "Status": {"type": "select"},
                    "Priority": {"type": "select"},
                    "Source": {"type": "select"},
                    "Harness": {"type": "select"},
                    "Auto Mode": {"type": "checkbox"},
                }
            },
            {"id": "intake-page-1234"},  # POST create page
        ]
    )
    result = si.nightly_apply_self_improvement(
        root, dry_run=False, fetcher=transport, notifier=_RecordingNotifier()
    )

    projection = result["queued"][0]["notion"]
    assert projection["projected"] is True
    # notion_api strips dashes from returned page ids.
    assert projection["page_id"] == "intakepage1234"
    assert result["notion_failures"] == []

    # The create-page request targeted the OS Work Intake database, left Auto Mode
    # unchecked, and never carried the raw token in the body.
    create = [r for r in transport.requests if r["method"] == "POST"][0]
    body = json.loads(create["data"].decode("utf-8"))
    assert body["parent"]["database_id"] == si.WORK_INTAKE_DB_ID
    assert body["properties"]["Auto Mode"]["checkbox"] is False
    assert body["properties"]["Status"]["select"]["name"] == "queued"
    assert body["properties"]["Name"]["title"][0]["text"]["content"].startswith("SI: ")
    assert SENTINEL_TOKEN not in create["data"].decode("utf-8")


def test_projection_degrades_when_token_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    monkeypatch.delenv(si.NOTION_TOKEN_ENV, raising=False)

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    # The proposal is still approved + promoted; only the projection degrades.
    assert _status_of(root, doctor["proposal_id"]) == "drafted"
    assert result["queued"][0]["notion"]["projected"] is False
    assert result["queued"][0]["notion"]["reason"] == "notion_token_missing"


def test_notion_error_does_not_fail_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    monkeypatch.setenv(si.NOTION_TOKEN_ENV, SENTINEL_TOKEN)

    result = si.nightly_apply_self_improvement(
        root, dry_run=False, fetcher=_RaisingTransport(), notifier=_RecordingNotifier()
    )

    assert result["ok"] is True
    assert _status_of(root, doctor["proposal_id"]) == "drafted"
    assert result["queued"][0]["notion"]["projected"] is False
    assert result["notion_failures"] and "notion_error" in result["notion_failures"][0]["reason"]


# ---------------------------------------------------------------------------
# Stale triage, disabled policy, notification
# ---------------------------------------------------------------------------


def test_stale_proposed_items_surface_as_stale_triage(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # feature-spec is outside the policy; being 30 days old makes it stale_triage.
    stale = _make_proposal(
        root, finding_type="repeated_evidence", total_score=19, slug="stale", created_at=old
    )
    _persist(root, [stale])

    result = si.nightly_apply_self_improvement(root, dry_run=True, notifier=_RecordingNotifier())

    assert result["selected"] == []
    ids = [item["proposal_id"] for item in result["stale_triage"]]
    assert stale["proposal_id"] in ids


def test_disabled_policy_is_a_noop(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    config = si._load_yaml(root / si.CONFIG_PATH)
    config["nightly_apply"] = {"enabled": False, "auto_approve": {"classes": ["doctor-check-draft"], "min_score": 20, "max_per_night": 3}}
    (root / si.CONFIG_PATH).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert result["skipped_reason"] == "nightly_apply_disabled"
    assert result["approved"] == []
    assert _status_of(root, doctor["proposal_id"]) == "proposed"


def test_one_summary_notification_is_emitted(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    notifier = _RecordingNotifier()

    si.nightly_apply_self_improvement(root, dry_run=True, notifier=notifier)

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["source"] == "automation.self_improvement"
    assert call["level"] == "info"
    assert "approved" in call["message"] and "queued" in call["message"]
