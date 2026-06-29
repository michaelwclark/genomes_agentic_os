"""Tests for the self-improvement documentation heartbeat.

Coverage:
- Per-root evidence cap reaches every configured root, including a small
  conversation root that would otherwise be starved by a large runs tree.
- A persist run renders ``latest-report.md`` (and an archived copy) with the
  expected human-readable sections.
- The runtime doctor flags the new self-improvement health conditions.
- The Notion projection degrades to a draft (never raises) when the manifest,
  credential, or workspace gate is absent, and lands a row via a fake transport
  when the gate passes — without leaking the token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os import self_improvement as si
from genomes_agentic_os import runtime_ops
from genomes_agentic_os.runtime_ops import runtime_doctor


SENTINEL_TOKEN = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _shared_factory(root: Path) -> Path:
    return root / "harness" / "shared_factory"


def _self_improvement_root(root: Path) -> Path:
    return _shared_factory(root) / "06-runs-and-logs" / "self-improvement"


def _seed_runs_noise(root: Path, count: int) -> None:
    runs_dir = _shared_factory(root) / "06-runs-and-logs" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (runs_dir / f"noise-{index:03d}.md").write_text(
            "Validation failed after repeated manual command sequence.\n"
            "Validation failed after repeated manual command sequence.\n",
            encoding="utf-8",
        )


def _seed_conversation(root: Path, name: str, body: str) -> Path:
    conv_dir = root / "harness" / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    path = conv_dir / name
    path.write_text(body, encoding="utf-8")
    return path


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


# ---------------------------------------------------------------------------
# Evidence reach
# ---------------------------------------------------------------------------


def test_per_root_cap_reaches_conversation_root_despite_large_runs_tree(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    # A runs tree far larger than the per-root cap.
    _seed_runs_noise(root, si.MAX_EVIDENCE_FILES_PER_ROOT * 3)
    conv = _seed_conversation(
        root,
        "2026-06-17-session.md",
        "Manual command workaround should become a shared workflow.\n",
    )

    config = si._load_yaml(root / si.CONFIG_PATH)
    evidence_roots = si._configured_evidence_roots(root, config)
    records = si._collect_evidence(evidence_roots)

    locators = {si._record_locator(root, record) for record in records}
    # The conversation file must be sampled even though the runs tree is huge.
    assert conv.relative_to(root).as_posix() in locators
    # The runs root must not exceed the per-root cap of distinct files.
    runs_sampled = [loc for loc in locators if "06-runs-and-logs/runs/" in loc]
    assert len(runs_sampled) <= si.MAX_EVIDENCE_FILES_PER_ROOT


def test_evidence_files_orders_newest_first(tmp_path: Path) -> None:
    folder = tmp_path / "evidence"
    folder.mkdir()
    older = folder / "old.md"
    newer = folder / "new.md"
    older.write_text("older entry\n", encoding="utf-8")
    newer.write_text("newer entry\n", encoding="utf-8")
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    ordered = si._evidence_files(folder)
    assert ordered[0] == newer
    assert ordered[1] == older


def test_repeated_evidence_filters_structured_noise_and_semantic_dedupe(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    actionable = "Operator handoff is blocked because unsupported local script command needs a runtime adapter."
    records_a = [
        si.EvidenceRecord(
            path=root / "run-a.yml",
            text="",
            redacted_text="\n".join(
                [
                    "created_at: 2026-06-28T00:00:00Z",
                    "idempotency_key: schedule:automation_control_tick:2026-06-28T00:00:00Z",
                    actionable,
                ]
            ),
            redactions=0,
        ),
        si.EvidenceRecord(
            path=root / "run-b.yml",
            text="",
            redacted_text=f"queue_id: queue_deadbeef1234\n{actionable}\n",
            redactions=0,
        ),
    ]
    findings = si._findings(root, records_a)
    repeated = next(finding for finding in findings if finding["type"] == "repeated_evidence")

    assert "unsupported local script command" in repeated["evidence"]
    assert "created_at" not in repeated["evidence"]

    proposal_a = si._proposal_from_finding(root, records_a, repeated)
    records_b = [
        si.EvidenceRecord(path=root / "other-a.yml", text="", redacted_text=actionable, redactions=0),
        si.EvidenceRecord(path=root / "other-b.yml", text="", redacted_text=actionable, redactions=0),
    ]
    proposal_b = si._proposal_from_finding(root, records_b, repeated)
    assert proposal_a["dedupe_key"] == proposal_b["dedupe_key"]


def test_candidate_evidence_prefers_actionable_lines_over_metadata(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    record = si.EvidenceRecord(
        path=root / "run.yml",
        text="",
        redacted_text=(
            "created_at: 2026-06-28T00:00:00Z\n"
            "status: queued\n"
            "Manual review is repeatedly blocked because the proposal report lacks owner next action.\n"
        ),
        redactions=0,
    )
    evidence = si._candidate_evidence(
        root,
        [record],
        {
            "type": "repeated_evidence",
            "evidence": "manual review is repeatedly blocked because the proposal report lacks owner next action.",
        },
    )

    assert evidence
    assert evidence[0]["excerpt"].startswith("Manual review")


# ---------------------------------------------------------------------------
# Daily report renderer
# ---------------------------------------------------------------------------


def test_persist_run_writes_latest_report_with_sections(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    _seed_conversation(
        root,
        "session.md",
        "\n".join(
            [
                "Validation failed after repeated manual command sequence.",
                "Validation failed after repeated manual command sequence.",
                "Manual command workaround should become a shared workflow.",
            ]
        )
        + "\n",
    )

    # No GENOMES_NOTION_PAT in the environment -> Notion degrades to a draft.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        result = si.run_self_improvement(root, dry_run=False)

    report_path = _self_improvement_root(root) / "latest-report.md"
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("# Self-Improvement Daily Report")
    assert "## Findings" in text
    assert "## Proposals" in text
    assert "## Recommended next actions" in text
    assert "Counts: evidence files scanned =" in text

    archives = sorted((_self_improvement_root(root) / "reports").glob("*.md"))
    # An archived report plus a notion-draft were written.
    assert any(p.name == "latest-report.md" for p in [report_path])
    assert any(not p.name.endswith("-notion-draft.md") for p in archives)
    assert result["report"]["latest"].endswith("latest-report.md")


def test_dry_run_writes_no_report(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    result = si.run_self_improvement(root, dry_run=True)
    assert "report" not in result
    assert not (_self_improvement_root(root) / "latest-report.md").exists()


def test_morning_report_dry_run_writes_no_morning_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    result = si.run_self_improvement_morning_report(root, dry_run=True)

    assert result["action"] == "morning-report"
    assert result["mode"] == "dry-run"
    assert not (_self_improvement_root(root) / "morning-reports").exists()


def test_morning_report_apply_writes_filesystem_report_and_logs(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        result = si.run_self_improvement_morning_report(root, dry_run=False)

    report = root / result["morning_report"]["report"]
    logs = root / result["morning_report"]["logs"]
    receipt = root / result["morning_report"]["receipt"]
    assert report.is_file()
    assert logs.is_file()
    assert receipt.is_file()
    text = report.read_text(encoding="utf-8")
    assert "## What Was Analyzed" in text
    assert "## What Was Found" in text
    assert "## What Was Updated" in text
    assert result["notion_page_projection"]["projected"] is False
    assert "notion token" in result["notion_page_projection"]["reason"]


def test_runtime_dispatch_supports_morning_report_command(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        execution = runtime_ops._run_local_script(
            root,
            f"agentic-os self-improvement morning-report --root {root} --apply",
        )

    assert execution["supported"] is True
    assert execution["ok"] is True
    assert execution["report_path"].endswith("report.md")
    assert execution["logs_path"].endswith("logs.yml")


def test_repair_validation_drift_creates_work_item_placeholders_and_json_backup(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    work_item = root / "domain" / "02-projects" / "project" / "work-items" / "01-intake" / "001_missing"
    work_item.mkdir(parents=True)
    (work_item / "work.yml").write_text(
        yaml.safe_dump({"title": "Missing Packet", "summary": "Needs structural repair."}),
        encoding="utf-8",
    )
    bad_json = root / "artifacts" / "broken.json"
    bad_json.parent.mkdir()
    bad_json.write_text("{not json", encoding="utf-8")
    validation = {
        "errors": [
            f"work item 001_missing status 'captured' missing required file: {work_item / 'IDEA.md'}",
            f"invalid JSON: {bad_json}: Expecting property name enclosed in double quotes",
        ],
        "warnings": [],
    }

    repair = si._repair_validation_drift(root, validation, apply=True)

    assert repair["applied_count"] == 2
    assert (work_item / "IDEA.md").is_file()
    repaired = json.loads(bad_json.read_text(encoding="utf-8"))
    assert repaired["status"] == "repaired_invalid_json_placeholder"
    assert list(bad_json.parent.glob("broken.json.invalid-*"))


# ---------------------------------------------------------------------------
# Notion projection
# ---------------------------------------------------------------------------


def _write_manifest(root: Path, *, live: bool, with_db: bool, workspace: str = "Genome's Notion") -> None:
    manifest: dict[str, Any] = {"live": live, "workspace": workspace}
    if with_db:
        manifest["database_ids"] = {"Self Improvement": "f1f0a4c71b724a9689bb504cf1a6bf4f"}
    path = root / si.NOTION_RUNTIME_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def test_notion_projection_degrades_when_no_manifest(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    report_paths = {"latest": "report.md"}
    result = {"findings": [], "proposal_candidates": [], "evidence_files": 0, "run_id": "r1"}

    projection = si._project_run_to_notion(root, result, report_paths)
    assert projection["projected"] is False
    assert "not live" in projection["reason"]
    assert Path(root / projection["draft"]).is_file()


def test_notion_projection_degrades_when_token_absent(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    _write_manifest(root, live=True, with_db=True)
    report_paths = {"latest": "report.md"}
    result = {"findings": [], "proposal_candidates": [], "evidence_files": 0, "run_id": "r1"}

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        projection = si._project_run_to_notion(root, result, report_paths)
    assert projection["projected"] is False
    assert "token" in projection["reason"]
    assert Path(root / projection["draft"]).is_file()


def test_notion_projection_lands_row_with_fake_transport(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    _write_manifest(root, live=True, with_db=True)
    report_paths = {"latest": "harness/.../latest-report.md"}
    result = {
        "findings": [{"score": {"total": 21}}],
        "proposal_candidates": [{"proposal_id": "si-abc"}],
        "evidence_files": 12,
        "run_id": "20260617T000000Z-deadbeef",
    }

    responses = [
        {"bot": {"workspace_name": "Genome's Notion"}},  # get_bot_workspace
        {  # get_database_property_types
            "properties": {
                "Name": {"type": "title"},
                "Summary": {"type": "rich_text"},
                "Proposed Spec": {"type": "rich_text"},
                "Score": {"type": "number"},
                "Status": {"type": "select"},
                "Evidence Path": {"type": "rich_text"},
                "Run ID": {"type": "rich_text"},
                "Date": {"type": "date"},
                "Updated": {"type": "date"},
                "Type": {"type": "select"},
                "Proposal ID": {"type": "rich_text"},
                "Parent Run ID": {"type": "rich_text"},
                "Recommended Artifact": {"type": "rich_text"},
                "Action Status": {"type": "select"},
                "Action Log": {"type": "rich_text"},
                "Auto Groom": {"type": "checkbox"},
                "Run Grooming": {"type": "checkbox"},
                "Auto-dev Implementation": {"type": "checkbox"},
            }
        },
        {"id": "page-1234"},  # create summary database page
        {"id": "page-5678"},  # create suggestion database page
    ]
    transport = _FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        projection = si._project_run_to_notion(root, result, report_paths, fetcher=transport)

    assert projection["projected"] is True
    assert projection["page_id"] == "page1234"
    assert projection["suggestion_count"] == 1
    # The created page POST must carry only properties that exist on the DB.
    create_req = next(req for req in transport.requests if req["method"] == "POST" and req["url"].endswith("/pages"))
    body = json.loads(create_req["data"].decode("utf-8"))
    assert set(body["properties"]).issubset(
        {
            "Name",
            "Summary",
            "Proposed Spec",
            "Score",
            "Status",
            "Evidence Path",
            "Run ID",
            "Date",
            "Updated",
            "Type",
            "Proposal ID",
            "Parent Run ID",
            "Recommended Artifact",
            "Action Status",
            "Action Log",
            "Auto Groom",
            "Run Grooming",
            "Auto-dev Implementation",
        }
    )
    assert body["properties"]["Score"]["number"] == 21
    assert body["properties"]["Type"]["select"]["name"] == "Daily Summary"
    assert body["children"]
    # Token must never appear in any request body or URL.
    for req in transport.requests:
        payload = (req["data"] or b"").decode("utf-8", errors="replace")
        assert SENTINEL_TOKEN not in payload
        assert SENTINEL_TOKEN not in req["url"]


def test_morning_report_notion_page_projection_creates_report_and_logs_pages(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    result = si.run_self_improvement_morning_report(root, dry_run=True)
    result["morning_report"] = {"report": "local-report.md", "logs": "local-logs.yml", "receipt": "receipt.yml"}

    responses = [
        {"bot": {"workspace_name": "Genome's Notion"}},
        {
            "results": [
                {
                    "object": "page",
                    "id": "parent-page-id",
                    "url": "https://notion.test/parent",
                    "properties": {
                        "title": {
                            "type": "title",
                            "title": [{"plain_text": "Genome's Agentic OS"}],
                        }
                    },
                }
            ]
        },
        {"results": []},  # no Self Improvement Reports child page
        {"id": "reports-page-id"},
        {},  # append intro blocks
        {"results": []},  # no daily page
        {"id": "daily-page-id"},
        {"id": "logs-page-id"},
        {},  # append daily blocks
        {},  # append log blocks
    ]
    transport = _FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        projection = si._project_morning_report_to_notion(root, result, fetcher=transport)

    assert projection["projected"] is True
    assert projection["report_page_id"] == "dailypageid"
    assert projection["logs_page_id"] == "logspageid"
    methods = [request["method"] for request in transport.requests]
    assert methods.count("POST") == 4
    assert methods.count("PATCH") == 3
    for req in transport.requests:
        payload = (req["data"] or b"").decode("utf-8", errors="replace")
        assert SENTINEL_TOKEN not in payload
        assert SENTINEL_TOKEN not in req["url"]


def test_notion_projection_degrades_on_workspace_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    _write_manifest(root, live=True, with_db=True, workspace="Genome's Notion")
    report_paths = {"latest": "report.md"}
    result = {"findings": [], "proposal_candidates": [], "evidence_files": 0, "run_id": "r1"}

    responses = [{"bot": {"workspace_name": "Some Other Workspace"}}]
    transport = _FakeTransport(responses)
    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        projection = si._project_run_to_notion(root, result, report_paths, fetcher=transport)
    assert projection["projected"] is False
    assert "does not match" in projection["reason"]


def test_process_actions_queues_checked_grooming_page(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    _write_manifest(root, live=True, with_db=True)
    proposal_dir = _self_improvement_root(root) / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    proposal = {
        "schema_version": 1,
        "proposal_id": "si-action123",
        "created_at": "2026-06-27T00:00:00Z",
        "updated_at": "2026-06-27T00:00:00Z",
        "opportunity_type": "missing_harness_capability",
        "title": "Actionable suggestion",
        "summary": "Improve the action flow.",
        "scope": "installed_os",
        "evidence": [{"locator": "harness/logs/session.md", "excerpt": "needs action", "signal_type": "test", "redactions": 0}],
        "deterministic_findings": [],
        "model_recommendation": None,
        "score": {"frequency": 3, "severity": 3, "reuse": 3, "confidence": 3, "blast_radius": 3, "staleness": 3, "total": 18},
        "dedupe_key": "test-action",
        "cooldown_until": None,
        "recommended_artifact": "feature-spec",
        "approval_requirement": "operator_required",
        "validation_plan": ["Run focused tests."],
        "reference_migration_plan": [],
        "redaction_status": "clean",
        "promotion_status": "proposed",
        "approval_record_id": None,
    }
    proposal["content_hash"] = si._proposal_content_hash(proposal)
    (proposal_dir / "si-action123.yml").write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    responses = [
        {"bot": {"workspace_name": "Genome's Notion"}},
        {
            "properties": {
                "Name": {"type": "title"},
                "Summary": {"type": "rich_text"},
                "Proposed Spec": {"type": "rich_text"},
                "Score": {"type": "number"},
                "Status": {"type": "select"},
                "Evidence Path": {"type": "rich_text"},
                "Run ID": {"type": "rich_text"},
                "Date": {"type": "date"},
                "Updated": {"type": "date"},
                "Type": {"type": "select"},
                "Proposal ID": {"type": "rich_text"},
                "Parent Run ID": {"type": "rich_text"},
                "Recommended Artifact": {"type": "rich_text"},
                "Action Status": {"type": "select"},
                "Action Log": {"type": "rich_text"},
                "Auto Groom": {"type": "checkbox"},
                "Run Grooming": {"type": "checkbox"},
                "Auto-dev Implementation": {"type": "checkbox"},
            }
        },
        {
            "results": [
                {
                    "id": "page-action-1",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Actionable suggestion"}]},
                        "Type": {"type": "select", "select": {"name": "Suggestion"}},
                        "Proposal ID": {"type": "rich_text", "rich_text": [{"plain_text": "si-action123"}]},
                        "Action Status": {"type": "select", "select": {"name": "ready"}},
                        "Auto Groom": {"type": "checkbox", "checkbox": True},
                        "Run Grooming": {"type": "checkbox", "checkbox": False},
                        "Auto-dev Implementation": {"type": "checkbox", "checkbox": False},
                    },
                }
            ]
        },
        {"id": "page-action-1"},
    ]
    transport = _FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        result = si.process_self_improvement_actions(root, dry_run=False, fetcher=transport)

    assert result["status"] == "processed"
    assert len(result["queued"]) == 1
    queued = result["queued"][0]
    assert queued["kind"] == "self_improvement_action"
    assert queued["work_type"] == "self_improvement_groom"
    assert "agentic-os-quiet-run start" in queued["command"]
    queue_path = _shared_factory(root) / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert queue["run_queue"][0]["id"] == queued["id"]
    update_req = transport.requests[-1]
    update_body = json.loads(update_req["data"].decode("utf-8"))
    assert update_body["properties"]["Auto Groom"]["checkbox"] is False
    assert update_body["properties"]["Run Grooming"]["checkbox"] is False
    assert update_body["properties"]["Action Status"]["select"]["name"] == "queued"


# ---------------------------------------------------------------------------
# Doctor checks
# ---------------------------------------------------------------------------


def _enable_self_improvement(root: Path) -> None:
    config_path = root / si.CONFIG_PATH
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["enabled"] = True
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _write_successful_self_improvement_run(root: Path, *, completed_at: str = "2026-06-28T12:00:00Z") -> None:
    runs_dir = _self_improvement_root(root) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "20260628T120000Z-test"
    (runs_dir / f"{run_id}.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "run_id": run_id,
                "started_at": "2026-06-28T11:59:00Z",
                "completed_at": completed_at,
                "mode": "apply",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_stale_self_improvement_queue(root: Path) -> None:
    queue_path = _shared_factory(root) / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_self_improvement_old",
        "kind": "schedule",
        "ref": "self_improvement_review",
        "status": "queued",
        "approval_state": "not_required",
        "dry_run": False,
        "due_at": "2000-01-01T00:00:00Z",
        "idempotency_key": "schedule:self_improvement_review:2000-01-01T00:00:00Z",
        "execution_target": "script",
        "command": "agentic-os self-improvement run --root <root> --apply",
    }
    queue["items"] = [item]
    queue["run_queue"] = [item]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")


def test_doctor_flags_enabled_but_never_ran(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _enable_self_improvement(root)

    report = runtime_doctor(root)
    messages = [f["message"] for f in report["findings"]]
    assert any("enabled but has never produced a run record" in m for m in messages)
    # Advisory only: never a blocker.
    si_findings = [f for f in report["findings"] if "self-improvement" in f["message"]]
    assert all(f["severity"] != "blocker" for f in si_findings)


def test_status_reports_stale_self_improvement_queue_item(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _enable_self_improvement(root)
    _write_successful_self_improvement_run(root)
    _write_stale_self_improvement_queue(root)

    result = si.self_improvement_status(root)
    assert result["queue_health"]["status"] == "stale"
    assert result["queue_health"]["stale_items"][0]["id"] == "queue_self_improvement_old"

    formatted = si.format_self_improvement_result(result)
    assert "queue_health:" in formatted
    assert "queue_self_improvement_old" in formatted


def test_doctor_flags_stale_self_improvement_queue_item(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _enable_self_improvement(root)
    _write_successful_self_improvement_run(root)
    _write_stale_self_improvement_queue(root)

    report = runtime_doctor(root)
    messages = [f["message"] for f in report["findings"]]
    assert any("self-improvement review queue item is stale: queue_self_improvement_old" in m for m in messages)
    assert report["ok"] is True


def test_apply_run_reconciles_covered_self_improvement_queue_item(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _enable_self_improvement(root)
    _write_stale_self_improvement_queue(root)
    _seed_conversation(
        root,
        "session.md",
        "Validation failed after repeated manual command sequence.\n"
        "Validation failed after repeated manual command sequence.\n",
    )

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        result = si.run_self_improvement(root, dry_run=False)

    assert result["queue_reconciliation"]["reconciled"][0]["id"] == "queue_self_improvement_old"
    queue = yaml.safe_load((_shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    item = queue["run_queue"][0]
    assert item["status"] == "done"
    assert item["reconcile_reason"] == "covered_by_later_self_improvement_run"
    assert item["covered_by_run_id"] == result["run_id"]


def test_reconcile_queue_cli_applies_covered_self_improvement_queue_item(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _enable_self_improvement(root)
    _write_successful_self_improvement_run(root)
    _write_stale_self_improvement_queue(root)

    assert main(["self-improvement", "reconcile-queue", "--root", str(root), "--apply"]) == 0

    queue = yaml.safe_load((_shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    item = queue["run_queue"][0]
    assert item["status"] == "done"
    assert item["covered_by_run_id"] == "20260628T120000Z-test"


def test_doctor_flags_missing_conversation_root(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    # The clarks_consulting conversation root does not exist in a fresh init.
    report = runtime_doctor(root)
    messages = [f["message"] for f in report["findings"]]
    assert any("conversation evidence root is missing" in m for m in messages)


def test_doctor_flags_missing_self_improvement_db_id(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    _write_manifest(root, live=True, with_db=False)

    report = runtime_doctor(root)
    messages = [f["message"] for f in report["findings"]]
    assert any("'Self Improvement' database id" in m for m in messages)


def test_doctor_silent_on_fresh_disabled_install(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    report = runtime_doctor(root)
    # Self-improvement is disabled by default; no enabled-but-never-ran/stale findings.
    messages = [f["message"] for f in report["findings"]]
    assert not any("enabled but has never produced" in m for m in messages)
    assert not any("latest-report.md" in m for m in messages)
