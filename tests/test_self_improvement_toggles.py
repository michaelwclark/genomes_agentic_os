"""Tests for the self-improvement auto-implement lane and per-improvement toggles.

Coverage:
- ``auto_implement`` is disabled by default: nothing is implemented even when a
  proposal's class matches the toggle map.
- Enabled lane with a true class toggle writes the auto_dev worker prompt,
  appends a directly leased run-queue item, records the durable intake-ledger entry,
  and creates a toggle-ledger entry (status queued).
- A false/absent class toggle keeps the proposal un-implemented.
- ``auto_implement.max_per_night`` caps the lane independently of auto_approve.
- The intake ledger dedupes: a proposal already queued as ``auto_dev`` is
  reported under ``skipped_implement`` and never re-queued.
- Dry-run reports ``implement_candidates`` without writing anything.
- Toggle off/on round-trip parks and restores registered artifacts; toggling to
  the current state is a ``changed: false`` no-op.
- Artifact paths outside the OS root are refused and left untouched.
- The morning report renders the "Added To The System (Last 24h)" section from
  nightly-apply receipts + toggle entries, with an explicit empty state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from genomes_agentic_os import self_improvement as si


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _seed_root(
    tmp_path: Path,
    *,
    enable_nightly: bool = False,
    auto_implement: dict[str, Any] | None = None,
) -> Path:
    """Create a minimal installed root; optionally arm nightly-apply + auto_implement."""
    from genomes_agentic_os.cli import main

    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    config = si._load_yaml(root / si.CONFIG_PATH)
    nightly = dict(config.get("nightly_apply") or {})
    if enable_nightly:
        nightly["enabled"] = True
    if auto_implement is not None:
        nightly["auto_implement"] = auto_implement
    config["nightly_apply"] = nightly
    (root / si.CONFIG_PATH).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


def _make_proposal(root: Path, *, finding_type: str, total_score: int, slug: str) -> dict[str, Any]:
    """Build a valid proposal via the module's own construction path."""
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
        "summary": f"TEST-FIXTURE: Recurring signal {slug} needs attention.",
        "evidence": f"TEST-FIXTURE: validation failed repeatedly for {slug}",
        "score": score,
    }
    proposal = si._proposal_from_finding(root, [], finding)
    proposal["dedupe_key"] = si._sha256(f"{finding_type}|{slug}")
    proposal["proposal_id"] = "si-" + si._digest(proposal["dedupe_key"], 12)
    proposal["title"] = f"Finding {slug}"
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


def _run_queue_ids(root: Path) -> list[str]:
    path = root / si.RUN_QUEUE_PATH
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(item.get("id")) for item in data.get("items") or []]


def _doctor_class_on() -> dict[str, Any]:
    return {"enabled": True, "classes": {"doctor-check-draft": True}, "max_per_night": 2}


def _stub_successful_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        si,
        "_project_nightly_row_to_intake",
        lambda proposal, *args, **kwargs: {
            "projected": True,
            "page_id": f"page-{proposal['proposal_id']}",
            "url": f"https://www.notion.so/page-{proposal['proposal_id']}",
        },
    )


@pytest.fixture(autouse=True)
def _no_notion_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(si.NOTION_TOKEN_ENV, raising=False)
    monkeypatch.delenv("GENOMES_NOTION_CONNECTOR", raising=False)


# ---------------------------------------------------------------------------
# Auto-implement lane
# ---------------------------------------------------------------------------


def test_auto_implement_disabled_by_default_nothing_implemented(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True)
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert result["approved"], "auto_approve lane still runs"
    assert result["implemented"] == []
    assert result["implement_candidates"] == []
    assert not si._si_toggles_path(root).exists()


def test_auto_implement_enabled_false_with_true_class_is_noop(tmp_path: Path) -> None:
    root = _seed_root(
        tmp_path,
        enable_nightly=True,
        auto_implement={"enabled": False, "classes": {"doctor-check-draft": True}, "max_per_night": 2},
    )
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert result["implemented"] == []
    assert result["implement_candidates"] == []


def test_enabled_class_true_queues_worker_ledger_and_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_successful_intake(monkeypatch)
    root = _seed_root(tmp_path, enable_nightly=True, auto_implement=_doctor_class_on())
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    proposal_id = doctor["proposal_id"]

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert len(result["implemented"]) == 1
    row = result["implemented"][0]
    assert row["proposal_id"] == proposal_id
    assert row["target"] == "doctor-check-draft"
    # The durable prompt remains on disk; execution is a directly leased Codex
    # worker rather than a detached shell script.
    prompt_path = root / row["prompt"]
    assert prompt_path.is_file()
    assert row["execution_target"] == "codex_harness"
    assert "script" not in row
    # The prompt instructs artifact registration into the toggle ledger.
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert si.SI_TOGGLES_PATH in prompt_text
    assert "additive and reversible" in prompt_text
    # Run-queue item appended.
    assert row["queue_id"] in _run_queue_ids(root)
    # Durable intake-ledger record for the auto_dev action.
    ledger = si._read_intake_ledger(root)
    assert f"{proposal_id}:auto_dev" in ledger["actions"]
    assert ledger["actions"][f"{proposal_id}:auto_dev"]["queue_id"] == row["queue_id"]
    # Toggle-ledger entry with status queued and no artifacts yet.
    toggles = si._read_si_toggles(root)["toggles"]
    assert toggles[proposal_id]["enabled"] is True
    assert toggles[proposal_id]["status"] == "queued"
    assert toggles[proposal_id]["target"] == "doctor-check-draft"
    assert toggles[proposal_id]["artifacts"] == []
    assert toggles[proposal_id]["disabled_at"] is None
    # Receipt captures the implemented row.
    receipt = json.loads((root / result["receipt"]).read_text(encoding="utf-8"))
    assert [item["proposal_id"] for item in receipt["implemented"]] == [proposal_id]


def test_class_toggle_false_or_absent_not_implemented(tmp_path: Path) -> None:
    root = _seed_root(
        tmp_path,
        enable_nightly=True,
        auto_implement={"enabled": True, "classes": {"doctor-check-draft": False}, "max_per_night": 2},
    )
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())
    assert result["approved"], "auto_approve still runs"
    assert result["implemented"] == []

    root_absent = _seed_root(
        tmp_path / "absent",
        enable_nightly=True,
        auto_implement={"enabled": True, "classes": {}, "max_per_night": 2},
    )
    doctor_absent = _make_proposal(root_absent, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root_absent, [doctor_absent])

    result_absent = si.nightly_apply_self_improvement(root_absent, dry_run=False, notifier=_RecordingNotifier())
    assert result_absent["implemented"] == []


def test_max_per_night_caps_the_implement_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_successful_intake(monkeypatch)
    root = _seed_root(tmp_path, enable_nightly=True, auto_implement=_doctor_class_on())
    proposals = [
        _make_proposal(root, finding_type="recurring_failure", total_score=20, slug=f"d{i}") for i in range(3)
    ]
    _persist(root, proposals)

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert len(result["approved"]) == 3  # auto_approve default cap
    assert len(result["implemented"]) == 2  # auto_implement cap
    skipped = [item for item in result["skipped_implement"] if item["reason"] == "over_auto_implement_max_per_night"]
    assert len(skipped) == 1


def test_intake_ledger_dedupes_auto_dev_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_successful_intake(monkeypatch)
    root = _seed_root(tmp_path, enable_nightly=True, auto_implement=_doctor_class_on())
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    proposal_id = doctor["proposal_id"]
    # A prior tick (Notion action watcher or an earlier nightly run) already
    # queued this proposal's auto_dev action.
    ledger = si._read_intake_ledger(root)
    ledger["actions"][f"{proposal_id}:auto_dev"] = {
        "queue_id": "queue_prior",
        "page_id": "page_prior",
        "queued_at": si._now(),
    }
    si._write_intake_ledger(root, ledger)

    result = si.nightly_apply_self_improvement(root, dry_run=False, notifier=_RecordingNotifier())

    assert result["implemented"] == []
    skipped = [item for item in result["skipped_implement"] if item["reason"] == "already_processed_ledger"]
    assert skipped and skipped[0]["proposal_id"] == proposal_id
    assert skipped[0]["queue_item_id"] == "queue_prior"
    assert "queue_prior" not in _run_queue_ids(root)


def test_dry_run_reports_candidates_and_writes_nothing(tmp_path: Path) -> None:
    root = _seed_root(tmp_path, enable_nightly=True, auto_implement=_doctor_class_on())
    doctor = _make_proposal(root, finding_type="recurring_failure", total_score=20, slug="doctor")
    _persist(root, [doctor])
    queue_before = _run_queue_ids(root)

    result = si.nightly_apply_self_improvement(root, dry_run=True, notifier=_RecordingNotifier())

    assert result["implement_candidates"] == [
        {"proposal_id": doctor["proposal_id"], "target": "doctor-check-draft"}
    ]
    assert result["implemented"] == []
    assert not (root / si.NIGHTLY_APPLY_ROOT).exists()
    assert not si._si_toggles_path(root).exists()
    assert _run_queue_ids(root) == queue_before
    config = si._load_yaml(root / si.CONFIG_PATH)
    status = si._read_yaml(si._proposal_file(root, config, doctor["proposal_id"])).get("promotion_status")
    assert status == "proposed"


# ---------------------------------------------------------------------------
# Per-improvement toggle on/off mechanics
# ---------------------------------------------------------------------------


def _seed_toggle(root: Path, proposal_id: str, artifacts: list[str], *, enabled: bool = True) -> None:
    si._write_si_toggles(
        root,
        {
            "schema_version": 1,
            "toggles": {
                proposal_id: {
                    "enabled": enabled,
                    "status": "queued",
                    "target": "skill-draft",
                    "title": "Test improvement",
                    "queued_at": si._now(),
                    "artifacts": artifacts,
                    "disabled_at": None,
                }
            },
        },
    )


def test_toggle_off_on_round_trip_moves_and_restores_artifacts(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    artifact_rel = "harness/skills/test-improvement/SKILL.md"
    artifact = root / artifact_rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# test improvement\n", encoding="utf-8")
    _seed_toggle(root, "si-roundtrip", [artifact_rel])

    off = si.set_self_improvement_toggle(root, "si-roundtrip", enabled=False)
    assert off["changed"] is True
    assert not artifact.exists()
    assert len(off["moved"]) == 1
    parked = root / off["moved"][0]["to"]
    assert parked.is_file()
    assert str(parked).startswith(str(root / si.SI_DISABLED_ROOT / "si-roundtrip"))
    entry = si._read_si_toggles(root)["toggles"]["si-roundtrip"]
    assert entry["enabled"] is False
    assert entry["disabled_at"]
    assert entry["moved"] == off["moved"]

    # Toggling to the current state is a no-op.
    off_again = si.set_self_improvement_toggle(root, "si-roundtrip", enabled=False)
    assert off_again["changed"] is False
    assert parked.is_file()

    on = si.set_self_improvement_toggle(root, "si-roundtrip", enabled=True)
    assert on["changed"] is True
    assert artifact.is_file()
    assert artifact.read_text(encoding="utf-8") == "# test improvement\n"
    assert not parked.exists()
    entry = si._read_si_toggles(root)["toggles"]["si-roundtrip"]
    assert entry["enabled"] is True
    assert entry["disabled_at"] is None
    assert entry["moved"] == []

    on_again = si.set_self_improvement_toggle(root, "si-roundtrip", enabled=True)
    assert on_again["changed"] is False


def test_toggle_off_refuses_artifacts_outside_os_root(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch\n", encoding="utf-8")
    _seed_toggle(root, "si-outside", ["../outside.txt"])

    result = si.set_self_improvement_toggle(root, "si-outside", enabled=False)

    refused = [item for item in result["refused"] if item["reason"] == "outside_os_root"]
    assert refused and refused[0]["path"] == "../outside.txt"
    assert outside.is_file(), "file outside the OS root must never be moved"
    assert result["moved"] == []


def test_toggle_unknown_proposal_raises(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    with pytest.raises(ValueError, match="unknown self-improvement toggle"):
        si.set_self_improvement_toggle(root, "si-missing", enabled=False)


# ---------------------------------------------------------------------------
# Morning report: Added To The System (Last 24h)
# ---------------------------------------------------------------------------


def _write_fake_receipt(root: Path, proposal_id: str) -> None:
    receipts_dir = root / si.NIGHTLY_APPLY_ROOT
    receipts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "action": "nightly-apply",
        "generated_at": si._now(),
        "approved": [{"proposal_id": proposal_id, "approval_id": "approval-test"}],
        "queued": [{"proposal_id": proposal_id, "target": "skill-draft", "draft_paths": []}],
        "implemented": [{"proposal_id": proposal_id, "target": "skill-draft", "queue_id": "queue_test"}],
    }
    (receipts_dir / "20990101-000000.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_morning_report_lists_added_to_system(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    proposal_id = "si-added24h0001"
    _write_fake_receipt(root, proposal_id)
    _seed_toggle(root, proposal_id, ["harness/skills/added/SKILL.md"])

    result = si.run_self_improvement_morning_report(root, dry_run=True)

    added = result["added_to_system"]
    kinds = {item["kind"] for item in added["items"]}
    assert {"approved", "queued", "implemented"} <= kinds
    assert added["toggles"] and added["toggles"][0]["proposal_id"] == proposal_id
    assert added["toggles"][0]["enabled"] is True
    assert added["toggles"][0]["artifacts"] == ["harness/skills/added/SKILL.md"]

    markdown = si._morning_report_markdown(root, result)
    assert "## Added To The System (Last 24h)" in markdown
    assert proposal_id in markdown
    assert "agentic-os self-improvement toggle <proposal-id> --off --root <root>" in markdown

    blocks_text = json.dumps(si._morning_report_notion_blocks(result))
    assert "Added To The System (Last 24h)" in blocks_text
    assert proposal_id in blocks_text


def test_morning_report_added_to_system_empty_state(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)

    result = si.run_self_improvement_morning_report(root, dry_run=True)

    assert result["added_to_system"]["items"] == []
    assert result["added_to_system"]["toggles"] == []
    markdown = si._morning_report_markdown(root, result)
    assert "## Added To The System (Last 24h)" in markdown
    assert "Nothing was auto-applied overnight." in markdown
    blocks_text = json.dumps(si._morning_report_notion_blocks(result))
    assert "Nothing was auto-applied overnight." in blocks_text
