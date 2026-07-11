from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import yaml
import pytest

from genomes_agentic_os.adaptive_observation_projection import (
    ObservationProjectionError,
    append_report_entry,
    routing_health,
)
from genomes_agentic_os.adaptive_observation_runner import run_observation_report
from genomes_agentic_os.adaptive_observation_reports import append_observation_event
from genomes_agentic_os.task_assessment import assess_task


SESSION_ID = "019f49a2-e800-7253-966e-2164d765584f"
NOW = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)


def _root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "agentic_os"
    control = root / "harness/shared_factory/00-control-plane"
    control.mkdir(parents=True)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    config = {
        "version": 1,
        "enabled": True,
        "mode": "observe",
        "session_roots": [str(sessions)],
        "observation_ledger": "harness/shared_factory/06-runs-and-logs/adaptive-routing/observations.jsonl",
        "report_root": "harness/shared_factory/06-runs-and-logs/adaptive-routing/observation-reports",
        "pricing_catalog": "harness/shared_factory/00-control-plane/adaptive-routing-pricing.yml",
        "privacy": {
            "persist_task_text": False,
            "persist_conversation_text": False,
            "persist_tool_arguments": False,
        },
        "notion": {"apply": False, "append_only": True},
    }
    (control / "adaptive-routing-observation-report.yml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    (control / "adaptive-routing-pricing.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "currency": "USD",
                "models": {
                    "gpt-5.6-luna": {
                        "input_per_million": 1,
                        "cached_input_per_million": 0.1,
                        "output_per_million": 4,
                    },
                    "gpt-5.6-sol": {
                        "input_per_million": 4,
                        "cached_input_per_million": 0.4,
                        "output_per_million": 16,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root, sessions


def test_runner_correlates_real_session_shape_and_writes_artifacts(tmp_path: Path) -> None:
    root, sessions = _root(tmp_path)
    ledger = root / "harness/shared_factory/06-runs-and-logs/adaptive-routing/observations.jsonl"
    operation = {
        "operation_status": "ready",
        "execution_plan": {
            "policy_version": 1,
            "status": "ready",
            "model_tier": "economy",
            "model_id": "gpt-5.6-luna",
            "reasoning_effort": "medium",
            "assessment": assess_task("Update one Jira label").as_dict(),
        },
    }
    append_observation_event(
        ledger,
        operation,
        correlation_id=SESSION_ID,
        policy_fingerprint="a" * 64,
        timestamp="2026-07-10T11:01:30Z",
    )
    rollout = sessions / f"rollout-{SESSION_ID}.jsonl"
    records = [
        {"timestamp": "2026-07-10T10:59:00Z", "type": "session_meta", "payload": {"id": SESSION_ID}},
        {
            "timestamp": "2026-07-10T11:01:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Update one Jira label"}],
            },
        },
        {
            "timestamp": "2026-07-10T11:01:10Z",
            "type": "turn_context",
            "payload": {
                "model": "fallback",
                "collaboration_mode": {
                    "settings": {"model": "gpt-5.6-sol", "reasoning_effort": "high"}
                },
            },
        },
        {
            "timestamp": "2026-07-10T11:02:00Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 500,
                        "output_tokens": 100,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 1100,
                    }
                },
            },
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    timestamp = NOW.timestamp()
    rollout.touch()
    # The runner prefilters by mtime; align the fixture with the deterministic window.
    import os

    os.utime(rollout, (timestamp, timestamp))

    result = run_observation_report(root, hours=12, now=NOW)
    repeated = run_observation_report(root, hours=12, now=NOW)

    assert result["coverage"]["matched_sessions"] == 1
    assert repeated["run_id"] == result["run_id"]
    assert result["routing_health"]["route_mismatch"] == 1
    assert result["classification_field_agreement"]["ratio"] == 1.0
    assert Path(result["artifacts"]["json"]).is_file()
    assert result["notion"] == {"status": "not_requested"}


class FakeNotion:
    def __init__(self) -> None:
        self.created = False

    def request(self, method: str, path: str, body=None):
        if path == "/users/me":
            return {"bot": {"workspace_name": "Genome's Notion"}}
        if path == "/databases/db":
            return {"parent": {"type": "page_id", "page_id": "parent"}}
        if path == "/pages/parent":
            return {"properties": {"Name": {"type": "title", "title": [{"plain_text": "Adaptive Model and Orchestration Router"}]}}}
        if path == "/databases/db/query":
            return {"results": []}
        if path == "/pages" and method == "POST":
            self.created = True
            assert body["parent"] == {"database_id": "db"}
            return {"id": "page", "url": "https://notion.test/page"}
        if path == "/pages/page":
            return {"id": "page"}
        raise AssertionError((method, path, body))


def test_projection_is_guarded_append_only_and_aggregate_only(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-07-10T12:00:00Z",
        "coverage": {
            "observations": 2,
            "matched_sessions": 2,
            "matched_turns": 2,
            "usage_ratio": 1.0,
            "cost_ratio": 0.5,
        },
        "classification_field_agreement": {"ratio": 0.75, "compared": 8},
        "cost_totals": {
            "actual_estimated": 1.0,
            "projected_routed_model": 0.5,
            "estimated_savings": 0.5,
        },
        "policy": {"fingerprints": ["a" * 64]},
        "assumptions": ["Estimate only."],
    }
    client = FakeNotion()
    result = append_report_entry(
        report,
        notion={
            "workspace_expected": "Genome's Notion",
            "parent_page_id": "parent",
            "database_id": "db",
            "append_only": True,
        },
        run_id="20260710T120000Z",
        window_start="2026-07-10T00:00:00Z",
        window_end="2026-07-10T12:00:00Z",
        receipt_path=tmp_path / "receipt.json",
        client=client,
    )

    assert routing_health(report) == "working"
    assert result["status"] == "projected"
    assert client.created
    assert json.loads((tmp_path / "receipt.json").read_text())["page_id"] == "page"


def test_projection_requires_positive_workspace_identity(tmp_path: Path) -> None:
    client = FakeNotion()
    original = client.request

    def missing_workspace(method: str, path: str, body=None):
        if path == "/users/me":
            return {"bot": {}}
        return original(method, path, body)

    client.request = missing_workspace  # type: ignore[method-assign]
    with pytest.raises(ObservationProjectionError, match="workspace verification"):
        append_report_entry(
            {
                "generated_at": "2026-07-10T12:00:00Z",
                "coverage": {"observations": 0, "matched_sessions": 0, "matched_turns": 0},
                "classification_field_agreement": {"ratio": None, "compared": 0},
                "cost_totals": {},
                "policy": {"fingerprints": []},
                "assumptions": [],
            },
            notion={
                "workspace_expected": "Genome's Notion",
                "parent_page_id": "parent",
                "database_id": "db",
                "append_only": True,
            },
            run_id="20260710T120000Z-empty",
            window_start="2026-07-10T00:00:00Z",
            window_end="2026-07-10T12:00:00Z",
            receipt_path=tmp_path / "blocked.json",
            client=client,
        )
