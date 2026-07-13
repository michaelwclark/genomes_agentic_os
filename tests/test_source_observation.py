from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import yaml

from genomes_agentic_os.source_observation import build_source_observation_snapshot


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, content: str, *, age_days: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    timestamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def _registry(root: Path) -> None:
    path = root / "harness/shared_factory/00-control-plane/watch-sources.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    source = {
        "id": "configured_api",
        "display_name": "Configured API",
        "connected_system": "github_genome",
        "source_type": "github_repo",
        "external_ref": {"owner": "acme", "repo": "api", "token": "must-not-escape"},
        "watch_method": "poll",
        "cadence": "hourly",
        "enabled": True,
    }
    path.write_text(yaml.safe_dump({"watch_sources": [source, {**source, "id": "duplicate_api"}]}), encoding="utf-8")


def test_snapshot_ranks_local_signals_dedupes_configured_and_hides_bodies(tmp_path: Path) -> None:
    _registry(tmp_path)
    slack = tmp_path / "watchers/slack_ingest/data/2026-07-13.jsonl"
    _write(
        slack,
        "\n".join(
            [
                json.dumps({"channel": "C012345678", "channel_name": "eng-leads", "ingest_at": "2026-07-13T10:00:00Z", "text": "RAW_SECRET_BODY https://github.com/hidden/private/pull/1"}),
                json.dumps({"channel": "C012345678", "channel_name": "eng-leads", "ingest_at": "2026-07-13T11:00:00Z", "text": "another private body"}),
            ]
        )
        + "\n",
    )
    conversation = tmp_path / "harness/shared_factory/06-runs-and-logs/conversations/turns.jsonl"
    _write(
        conversation,
        json.dumps({"timestamp": "2026-07-13T09:00:00Z", "message": "Review https://github.com/acme/api/pull/12 and ACME-44 in #eng-leads"}) + "\n",
    )
    work_item = tmp_path / "los/02-projects/django/work-items/02-active/040/WORKLOG.md"
    _write(work_item, "Built https://github.com/acme/django/pull/99 for ACME-44.\n", age_days=10)

    snapshot = build_source_observation_snapshot(tmp_path, now=NOW)

    assert len(snapshot["configured"]) == 1
    assert snapshot["diagnostics"]["configured_duplicates"] == 1
    assert snapshot["configured"][0]["external_ref"] == {"owner": "acme", "repo": "api"}

    observed = {item["source_key"]: item for item in snapshot["observed"]}
    assert observed["slack:id:C012345678"]["score"] == 12.0
    assert observed["slack:id:C012345678"]["signal_count"] == 2
    assert observed["slack:id:C012345678"]["external_ref"]["channel_name"] == "eng-leads"
    assert observed["github:acme/api"]["configured"] is True
    assert observed["github:acme/django"]["score"] == 1.0
    assert observed["jira:ACME"]["score"] == 5.0

    suggestion_keys = {
        item["observation"]["evidence_refs"][0]: item for item in snapshot["suggestions"]
    }
    assert all(item["enabled"] is False for item in snapshot["suggestions"])
    assert not any(item["source_type"] == "github_repo" and item["external_ref"]["repo"] == "api" for item in snapshot["suggestions"])
    assert any(item["source_type"] == "github_repo" and item["external_ref"]["repo"] == "django" for item in snapshot["suggestions"])
    assert suggestion_keys

    rendered = json.dumps(snapshot, sort_keys=True)
    assert "RAW_SECRET_BODY" not in rendered
    assert "must-not-escape" not in rendered
    assert "hidden/private" not in rendered
    assert all("#L" in ref or ref.endswith(".md") for item in snapshot["observed"] for ref in item["evidence_refs"])


def test_snapshot_is_deterministic_bounded_and_graceful_on_malformed_inputs(tmp_path: Path) -> None:
    registry = tmp_path / "harness/shared_factory/00-control-plane/watch-sources.yml"
    _write(registry, "watch_sources: [not: valid")
    newest = tmp_path / "watchers/slack_ingest/data/2026-07-13.jsonl"
    older = tmp_path / "watchers/slack_ingest/data/2026-07-12.jsonl"
    _write(newest, "not-json\n" + json.dumps({"channel": "C999999999", "channel_name": "newest", "ts": "1783958400.0"}) + "\n")
    _write(older, json.dumps({"channel": "C888888888", "channel_name": "older", "ts": "1783872000.0"}) + "\n", age_days=1)

    first = build_source_observation_snapshot(tmp_path, now=NOW, max_files=1)
    second = build_source_observation_snapshot(tmp_path, now=NOW, max_files=1)

    assert first == second
    assert first["configured"] == []
    assert first["diagnostics"]["files_discovered"] == 2
    assert first["diagnostics"]["files_scanned"] == 1
    assert first["diagnostics"]["truncated"] is True
    assert first["diagnostics"]["malformed_records"] == 1
    assert first["diagnostics"]["malformed_files"][0]["path"].endswith("watch-sources.yml")
    assert [item["source_key"] for item in first["observed"]] == ["slack:id:C999999999"]


def test_missing_root_and_file_limit_clamp_are_explicit(tmp_path: Path) -> None:
    missing = build_source_observation_snapshot(tmp_path / "missing", now=NOW, max_files=9999)

    assert missing["configured"] == []
    assert missing["observed"] == []
    assert missing["suggestions"] == []
    assert missing["diagnostics"]["file_limit"] == 500
    assert missing["diagnostics"]["limit_clamped"] is True
    assert missing["diagnostics"]["notices"] == [{"path": ".", "reason": "OS root missing"}]


def test_evidence_and_suggestions_are_ranked_and_bounded(tmp_path: Path) -> None:
    conversation = tmp_path / "harness/shared_factory/06-runs-and-logs/conversations/turns.jsonl"
    rows = []
    for index in range(130):
        rows.append(
            json.dumps(
                {
                    "timestamp": "2026-07-13T09:00:00Z",
                    "message": f"Review https://github.com/acme/repo-{index}/pull/1 and ACME-{index}",
                }
            )
        )
    _write(conversation, "\n".join(rows) + "\n")

    snapshot = build_source_observation_snapshot(tmp_path, now=NOW)
    jira = next(item for item in snapshot["observed"] if item["source_key"] == "jira:ACME")

    assert jira["signal_count"] == 1
    assert jira["evidence_count"] == 1
    assert len(snapshot["suggestions"]) == 100
    assert snapshot["diagnostics"]["suggestion_candidates"] == 131
    assert snapshot["diagnostics"]["suggestions_truncated"] is True
