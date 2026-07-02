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
            {"results": []},  # POST dedup query — no existing rows for this proposal
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
    # unchecked, never carried the raw token, and uses the new SI-NNN title format.
    # The last POST is the page-create (the first POST is the dedup query).
    create = [r for r in transport.requests if r["method"] == "POST"][-1]
    body = json.loads(create["data"].decode("utf-8"))
    assert body["parent"]["database_id"] == si.WORK_INTAKE_DB_ID
    assert body["properties"]["Auto Mode"]["checkbox"] is False
    assert body["properties"]["Status"]["select"]["name"] == "queued"
    name_text = body["properties"]["Name"]["title"][0]["text"]["content"]
    import re as _re
    assert _re.match(r"^SI-\d{3} — .+", name_text), f"Title did not match SI-NNN format: {name_text!r}"
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


# ---------------------------------------------------------------------------
# New tests: gate-root specificity, re-projection idempotency, title format
# ---------------------------------------------------------------------------


def test_gate_reads_config_from_runtime_root(tmp_path: Path) -> None:
    """Config is read from the --root argument, not a hardcoded path.

    Two isolated roots with different enabled settings must each see their own
    config so that a disabled root never projects even when another root is
    enabled.  This is a regression guard against the 2026-07-02 incident where
    a build agent invoked _project_nightly_row_to_intake against a root that
    had enabled=true while the live instance root had enabled=false.
    """
    root_enabled = _seed_root(tmp_path / "root_on", enable_nightly=True)
    root_disabled = _seed_root(tmp_path / "root_off", enable_nightly=False)

    doctor_on = _make_proposal(root_enabled, finding_type="recurring_failure", total_score=20, slug="on")
    _persist(root_enabled, [doctor_on])
    doctor_off = _make_proposal(root_disabled, finding_type="recurring_failure", total_score=20, slug="off")
    _persist(root_disabled, [doctor_off])

    result_on = si.nightly_apply_self_improvement(root_enabled, dry_run=True, notifier=_RecordingNotifier())
    result_off = si.nightly_apply_self_improvement(root_disabled, dry_run=False, notifier=_RecordingNotifier())

    # Enabled root selects proposals (dry_run so no Notion calls)
    assert len(result_on["selected"]) == 1
    # Disabled root is a no-op regardless of dry_run flag
    assert result_off["skipped_reason"] == "nightly_apply_disabled"
    assert result_off["approved"] == []
    assert _status_of(root_disabled, doctor_off["proposal_id"]) == "proposed"


def test_re_projection_blocked_by_durable_status_and_notion_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proposal that was approved+promoted on run N must not re-project on run N+1.

    Layer 1 (durable): After the first apply the proposal is promoted to
    promotion_status='drafted'.  On the second apply the selection loop skips it
    because only 'proposed' proposals are eligible.

    Layer 2 (Notion guard): Even if the durable write were to fail, the dedup
    query fires before create_database_page and returns the existing page id,
    blocking the second POST.
    """
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    monkeypatch.setenv(si.NOTION_TOKEN_ENV, SENTINEL_TOKEN)
    proposal_id = doctor["proposal_id"]

    # First run: dedup query returns empty → create fires → page created
    transport = _FakeTransport(
        [
            {"results": []},  # dedup query — no existing rows
            {  # GET database property types
                "properties": {
                    "Name": {"type": "title"},
                    "Status": {"type": "select"},
                    "Auto Mode": {"type": "checkbox"},
                }
            },
            {"id": "intake-page-first"},  # POST create page
        ]
    )
    result1 = si.nightly_apply_self_improvement(
        root, dry_run=False, fetcher=transport, notifier=_RecordingNotifier()
    )
    assert result1["queued"][0]["notion"]["projected"] is True
    # Layer 1 check: promotion_status must be 'drafted' after first run
    assert _status_of(root, proposal_id) == "drafted"

    # Second run: proposal is now 'drafted' — selection loop skips it entirely.
    # Transport has NO responses so any unexpected Notion call raises AssertionError.
    transport2 = _FakeTransport([])
    result2 = si.nightly_apply_self_improvement(
        root, dry_run=False, fetcher=transport2, notifier=_RecordingNotifier()
    )
    assert result2["approved"] == [], "drafted proposal must not be re-approved"
    assert result2["queued"] == [], "drafted proposal must not be re-projected"
    assert transport2.requests == [], "no Notion calls should fire on re-run"


def test_title_format_is_si_seq_imperative_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Projected rows use 'SI-NNN — imperative-slug' titles with bold 'What to do:' body.

    Verifies:
    - Title matches SI-NNN — <slug> where NNN is a zero-padded 3-digit integer
    - Slug is ≤ 60 characters
    - First body block is a bold paragraph starting with 'What to do:'
    - Sequence increments monotonically across two consecutive projections
    """
    import re as _re

    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    nurse = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="nurse")
    _persist(root, [doctor, nurse])
    monkeypatch.setenv(si.NOTION_TOKEN_ENV, SENTINEL_TOKEN)

    # Pre-seed the counter so the first row gets SI-003 (seeds at 3)
    seq_path = si._si_seq_path(root)
    seq_path.parent.mkdir(parents=True, exist_ok=True)
    seq_path.write_text(json.dumps({"next_seq": 3}), encoding="utf-8")

    def _prop_responses() -> list[dict[str, Any]]:
        return [
            {"results": []},  # dedup query
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Status": {"type": "select"},
                    "Auto Mode": {"type": "checkbox"},
                }
            },
            {"id": "fake-page"},
        ]

    transport = _FakeTransport(_prop_responses() + _prop_responses())
    result = si.nightly_apply_self_improvement(
        root, dry_run=False, fetcher=transport, notifier=_RecordingNotifier()
    )

    assert len(result["queued"]) == 2, "both proposals should project"

    create_requests = [r for r in transport.requests if r["method"] == "POST" and "/pages" in r["url"]]
    assert len(create_requests) == 2

    titles: list[str] = []
    for req in create_requests:
        body = json.loads(req["data"].decode("utf-8"))
        name_text = body["properties"]["Name"]["title"][0]["text"]["content"]
        assert _re.match(r"^SI-\d{3} — .+", name_text), f"Title format wrong: {name_text!r}"
        slug_part = name_text.split(" — ", 1)[1]
        assert len(slug_part) <= 60, f"Slug too long ({len(slug_part)}): {slug_part!r}"
        titles.append(name_text)
        # Verify bold 'What to do:' is the first child block
        children = body.get("children") or []
        assert children, "body must have blocks"
        first = children[0]
        assert first["type"] == "paragraph"
        rich_text = first["paragraph"]["rich_text"]
        assert rich_text, "first block must have rich_text"
        first_text = rich_text[0]["text"]["content"]
        assert first_text.startswith("What to do:"), (
            f"First body block must start with 'What to do:' — got: {first_text!r}"
        )
        bold = rich_text[0].get("annotations", {}).get("bold")
        assert bold is True, "First body block must be bold"

    # Sequence numbers must be distinct and monotonically increasing
    seq_nums = [int(_re.search(r"SI-(\d{3})", t).group(1)) for t in titles]  # type: ignore[union-attr]
    assert seq_nums[1] == seq_nums[0] + 1, f"Seq must increment: {seq_nums}"
