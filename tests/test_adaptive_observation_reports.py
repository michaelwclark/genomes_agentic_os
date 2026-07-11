from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomes_agentic_os.adaptive_observation_reports import (
    DuplicateCorrelationError,
    ObservationError,
    append_observation_event,
    build_observation_report,
    load_pricing_catalog,
    parse_codex_rollout,
    read_observation_events,
    write_observation_report,
)
from genomes_agentic_os.task_assessment import assess_task


CORRELATION = "019f49a2-e800-7253-966e-2164d765584f"
FINGERPRINT = "a" * 64
NOW = "2026-07-10T12:00:00Z"


def _operation(model: str = "gpt-5.4-mini") -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "adaptive-routing-plan",
        "operation_status": "ready",
        "execution_plan": {
            "schema_version": 1,
            "policy_version": 3,
            "status": "ready",
            "model_tier": "economy",
            "model_id": model,
            "reasoning_effort": "medium",
            "assessment": assess_task("Fix a small unit test and run pytest").as_dict(),
        },
    }


def _pricing(path: Path) -> dict[str, object]:
    path.write_text(
        """\
schema_version: 1
currency: USD
models:
  gpt-5.5:
    relative_cost_index: 4.0
    input_per_million: 2.0
    cached_input_per_million: 0.2
    output_per_million: 8.0
  gpt-5.4-mini:
    relative_cost_index: 1.0
    per_million:
      input: 1.0
      cached_input: 0.1
      output: 4.0
""",
        encoding="utf-8",
    )
    return load_pricing_catalog(path)


def test_append_read_duplicate_and_privacy(tmp_path: Path) -> None:
    ledger = tmp_path / "observations.jsonl"
    event = append_observation_event(
        ledger,
        _operation(),
        correlation_id=CORRELATION,
        policy_fingerprint=FINGERPRINT,
        timestamp=NOW,
    )

    assert read_observation_events(ledger) == [event]
    assert "Fix a small" not in ledger.read_text(encoding="utf-8")
    with pytest.raises(DuplicateCorrelationError):
        append_observation_event(
            ledger,
            _operation(),
            correlation_id=CORRELATION,
            policy_fingerprint=FINGERPRINT,
            timestamp=NOW,
        )
    unsafe = _operation()
    unsafe["task"] = "private task"
    with pytest.raises(ObservationError, match="privacy-sensitive"):
        append_observation_event(
            ledger,
            unsafe,
            correlation_id="019f49a2-e800-7253-966e-2164d7655850",
            policy_fingerprint=FINGERPRINT,
            timestamp=NOW,
        )


def test_read_skips_malformed_duplicate_and_unsupported(tmp_path: Path) -> None:
    ledger = tmp_path / "observations.jsonl"
    event = append_observation_event(
        ledger,
        _operation(),
        correlation_id=CORRELATION,
        policy_fingerprint=FINGERPRINT,
        timestamp=NOW,
    )
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write(json.dumps(event) + "\n")
        handle.write(json.dumps({**event, "schema_version": 99}) + "\n")

    assert read_observation_events(ledger) == [event]
    with pytest.raises(ObservationError):
        read_observation_events(ledger, strict=True)


def test_parse_codex_rollout_extracts_metadata_usage_and_assessment_only(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = [
        {
            "timestamp": "2026-07-10T12:00:00.000Z",
            "type": "session_meta",
            "payload": {"id": CORRELATION},
        },
        {
            "timestamp": "2026-07-10T12:00:01.000Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5", "effort": "high"},
        },
        {
            "timestamp": "2026-07-10T12:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Diagnose production and write a report"}
                ],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "019f49a2-e800-7253-966e-2164d7655851"
                },
            },
        },
        {
            "timestamp": "2026-07-10T12:00:03.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 1_000_000,
                        "cached_input_tokens": 500_000,
                        "output_tokens": 100_000,
                        "reasoning_output_tokens": 20_000,
                        "total_tokens": 1_100_000,
                    }
                },
            },
        },
    ]
    rollout.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n{bad\n",
        encoding="utf-8",
    )

    parsed = parse_codex_rollout(rollout)

    assert parsed["session_id"] == CORRELATION
    assert parsed["model"] == "gpt-5.5"
    assert parsed["reasoning_effort"] == "high"
    assert parsed["usage"]["reasoning_output_tokens"] == 20_000
    assert parsed["retrospective_assessment"]["task_family"] == "general_task"
    assert parsed["diagnostics"] == {"malformed_lines": 1}
    serialized = json.dumps(parsed)
    assert "Diagnose production" not in serialized
    assert "task_text" not in serialized


def test_report_uses_exact_turn_usage_not_session_lifetime(tmp_path: Path) -> None:
    rollout = tmp_path / f"rollout-{CORRELATION}.jsonl"
    records = [
        {"timestamp": "2026-07-10T10:00:00Z", "type": "session_meta", "payload": {"id": CORRELATION}},
        {"timestamp": "2026-07-10T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Update Jira status"}]}},
        {"timestamp": "2026-07-10T10:00:02Z", "type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "medium"}},
        {"timestamp": "2026-07-10T10:00:03Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 10, "reasoning_output_tokens": 1, "total_tokens": 110}}}},
        {"timestamp": "2026-07-10T11:00:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Refactor the monolith across modules"}]}},
        {"timestamp": "2026-07-10T11:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.4-mini", "effort": "high"}},
        {"timestamp": "2026-07-10T11:00:02Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 500, "output_tokens": 100, "reasoning_output_tokens": 10, "total_tokens": 1100}}}},
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    session = parse_codex_rollout(rollout)
    observation = append_observation_event(
        tmp_path / "turn.jsonl",
        _operation(),
        correlation_id=CORRELATION,
        policy_fingerprint=FINGERPRINT,
        timestamp="2026-07-10T11:00:01Z",
    )
    report = build_observation_report(
        [observation], [session], _pricing(tmp_path / "pricing.yml"), generated_at=NOW
    )

    assert report["records"][0]["actual"]["usage"]["total_tokens"] == 1100
    assert report["records"][0]["actual"]["model"] == "gpt-5.4-mini"


def test_complete_report_cost_health_agreement_and_artifacts(tmp_path: Path) -> None:
    ledger = tmp_path / "observations.jsonl"
    observation = append_observation_event(
        ledger,
        _operation(),
        correlation_id=CORRELATION,
        policy_fingerprint=FINGERPRINT,
        timestamp=NOW,
    )
    assessment = observation["assessment"]
    session = {
        "session_id": CORRELATION,
        "thread_id": CORRELATION,
        "correlation_ids": [CORRELATION],
        "model": "gpt-5.5",
        "reasoning_effort": "medium",
        "usage": {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 500_000,
            "output_tokens": 100_000,
            "reasoning_output_tokens": 20_000,
            "total_tokens": 1_100_000,
        },
        "retrospective_assessment": assessment,
    }
    report = build_observation_report(
        [observation], [session], _pricing(tmp_path / "pricing.yml"), generated_at=NOW
    )

    record = report["records"][0]
    assert record["cost"]["actual_estimated"] == 1.9
    assert record["cost"]["projected_routed_model"] == 0.95
    assert record["cost"]["estimated_savings"] == 0.95
    assert record["cost"]["relative_direction"] == "premium"
    assert record["routing_health"] == "route_mismatch"
    assert report["coverage"] == {
        "observations": 1,
        "matched_sessions": 1,
        "session_ratio": 1.0,
        "matched_turns": 1,
        "turn_ratio": 1.0,
        "usage_records": 1,
        "usage_ratio": 1.0,
        "paired_cost_records": 1,
        "cost_ratio": 1.0,
    }
    assert report["classification_field_agreement"]["ratio"] == 1.0

    paths = write_observation_report(tmp_path / "reports", report)
    assert paths["run_dir"].name == "20260710T120000Z"
    assert json.loads(paths["json"].read_text(encoding="utf-8")) == report
    assert "Estimated savings: 0.95" in paths["markdown"].read_text(encoding="utf-8")


def test_empty_unknown_partial_and_mixed_policy_remain_explicitly_unknown(
    tmp_path: Path,
) -> None:
    catalog = _pricing(tmp_path / "pricing.yml")
    empty = build_observation_report([], [], catalog, generated_at=NOW)
    assert empty["coverage"]["session_ratio"] is None
    assert empty["cost_totals"]["actual_estimated"] is None

    first = append_observation_event(
        tmp_path / "one.jsonl",
        _operation("unknown-model"),
        correlation_id=CORRELATION,
        policy_fingerprint=FINGERPRINT,
        timestamp=NOW,
    )
    second = append_observation_event(
        tmp_path / "two.jsonl",
        _operation(),
        correlation_id="019f49a2-e800-7253-966e-2164d7655852",
        policy_fingerprint="b" * 64,
        timestamp=NOW,
    )
    report = build_observation_report(
        [first, second],
        [{"session_id": CORRELATION, "model": None, "usage": None}],
        catalog,
        generated_at=NOW,
    )
    assert report["policy"]["mixed_policy"] is True
    assert report["coverage"]["session_ratio"] == 0.5
    assert report["cost_totals"]["actual_estimated"] is None
    assert all(record["cost"]["actual_estimated"] is None for record in report["records"])
    assert report["routing_health"]["unknown"] == 2

    operator_catalog = tmp_path / "operator-pricing.yml"
    operator_catalog.write_text(
        """\
version: 1
currency: USD
models:
  gpt-5.6-luna:
    relative_cost_index: 1.0
    input_per_million: null
    cached_input_per_million: null
    output_per_million: null
""",
        encoding="utf-8",
    )
    loaded = load_pricing_catalog(operator_catalog)
    assert loaded["models"]["gpt-5.6-luna"]["input"] is None
