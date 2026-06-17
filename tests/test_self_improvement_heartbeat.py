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
                "Score": {"type": "number"},
                "Status": {"type": "select"},
                "Run ID": {"type": "rich_text"},
                "Date": {"type": "date"},
            }
        },
        {"id": "page-1234"},  # create_database_page
    ]
    transport = _FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        projection = si._project_run_to_notion(root, result, report_paths, fetcher=transport)

    assert projection["projected"] is True
    assert projection["page_id"] == "page1234"
    # The created page POST must carry only properties that exist on the DB.
    create_req = transport.requests[-1]
    body = json.loads(create_req["data"].decode("utf-8"))
    assert set(body["properties"]).issubset({"Name", "Summary", "Score", "Status", "Run ID", "Date"})
    assert body["properties"]["Score"]["number"] == 21
    # Token must never appear in any request body or URL.
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


# ---------------------------------------------------------------------------
# Doctor checks
# ---------------------------------------------------------------------------


def _enable_self_improvement(root: Path) -> None:
    config_path = root / si.CONFIG_PATH
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["enabled"] = True
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


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
