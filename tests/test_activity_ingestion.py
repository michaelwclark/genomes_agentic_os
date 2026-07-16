from pathlib import Path

import yaml
from genomes_agentic_os.cli import main

from genomes_agentic_os.activity_ingestion import (
    CURSORS,
    EVENTS,
    HEALTH,
    METRICS,
    REGISTRY,
    event_envelope,
    collect_local_activity,
    discover_local_activity,
    ingest_fixture,
    ingest_pages,
    validate_sources,
)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def setup_root(root: Path) -> None:
    write(
        root / METRICS,
        {"metrics": [{"id": "messages"}, {"id": "tool_runs"}, {"id": "errors"}]},
    )
    write(
        root / REGISTRY,
        {
            "schema_version": 1,
            "activity_sources": [
                {
                    "id": "slack_los",
                    "provider": "slack",
                    "enabled": True,
                    "opt_in": True,
                    "scope": {"domain": "los", "project": "los_app"},
                    "dimensions": {"harness": "agentic_os"},
                    "metric_bindings": {"slack.message.sent": "messages"},
                    "limits": {"max_pages_per_run": 10},
                },
                {
                    "id": "github_cc",
                    "provider": "github",
                    "enabled": True,
                    "opt_in": True,
                    "scope": {
                        "domain": "clarks_consulting",
                        "project": "agentic_harness",
                    },
                    "dimensions": {"repository": "genomes_agentic_harness"},
                    "metric_bindings": {"github.pull_request.opened": "tool_runs"},
                },
            ],
        },
    )


def test_privacy_envelope_uses_configured_scope_and_allowlisted_metadata(
    tmp_path: Path,
) -> None:
    setup_root(tmp_path)
    source = yaml.safe_load((tmp_path / REGISTRY).read_text())["activity_sources"][0]
    item = {
        "id": "m-1",
        "event_type": "message.sent",
        "status": "posted",
        "body": "private body",
        "token": "xoxb-secret",
        "customer_name": "Acme",
        "url": "https://private.invalid/thread",
        "occurred_at": "secret body smuggled as time",
        "domain": "attacker-domain",
        "project": "attacker-project",
    }
    event = event_envelope(source, item)
    rendered = yaml.safe_dump(event)
    assert event["scope"] == {"domain": "los", "project": "los_app"}
    assert event["metric"]["id"] == "messages"
    assert event["attributes"] == {"status": "posted"}
    assert "private body" not in rendered
    assert "xoxb-secret" not in rendered
    assert "Acme" not in rendered
    assert "private.invalid" not in rendered
    assert "smuggled" not in rendered
    assert event["privacy"] == {
        "classification": "metadata_only",
        "contains_body": False,
        "contains_secret": False,
        "contains_customer_data": False,
        "contains_private_link": False,
    }


def test_pagination_cursor_and_idempotent_apply(tmp_path: Path) -> None:
    setup_root(tmp_path)
    pages = [
        {
            "items": [{"id": "m-1", "event_type": "message.sent"}],
            "next_cursor": "c1",
            "rate_limit_remaining": 9,
        },
        {
            "items": [{"id": "m-2", "event_type": "message.sent"}],
            "next_cursor": "c2",
            "rate_limit_remaining": 8,
        },
    ]
    first = ingest_pages(tmp_path, "slack_los", pages, apply=True)
    second = ingest_pages(tmp_path, "slack_los", pages, apply=True)
    assert first["emitted"] == 2 and first["cursor"] == "c2"
    assert second["emitted"] == 0 and second["duplicates"] == 2
    assert len(list((tmp_path / EVENTS).glob("*.yml"))) == 2
    assert (
        yaml.safe_load((tmp_path / CURSORS).read_text())["sources"]["slack_los"][
            "cursor"
        ]
        == "c2"
    )


def test_rate_limit_preserves_cursor_and_health(tmp_path: Path) -> None:
    setup_root(tmp_path)
    result = ingest_pages(
        tmp_path,
        "github_cc",
        [
            {
                "items": [{"id": "pr-1", "event_type": "pull_request.opened"}],
                "next_cursor": "page-2",
                "rate_limit_remaining": 0,
            },
            {"items": [{"id": "pr-2", "event_type": "pull_request.opened"}]},
        ],
        apply=True,
    )
    assert result["status"] == "rate_limited"
    assert result["emitted"] == 1
    health = yaml.safe_load((tmp_path / HEALTH).read_text())["sources"]["github_cc"]
    assert health["freshness"] == "stale" and health["completeness"] == "partial"


def test_partial_failure_does_not_block_other_sources(tmp_path: Path) -> None:
    setup_root(tmp_path)
    fixture = tmp_path / "fixture.yml"
    write(
        fixture,
        {
            "sources": [
                {"id": "slack_los", "pages": [{"error": "provider unavailable"}]},
                {
                    "id": "github_cc",
                    "pages": [
                        {"items": [{"id": "pr-1", "event_type": "pull_request.opened"}]}
                    ],
                },
            ]
        },
    )
    result = ingest_fixture(tmp_path, fixture, apply=True)
    assert result["partial"] is True
    assert result["results"][0]["status"] == "unavailable"
    assert result["results"][1]["emitted"] == 1


def test_metric_binding_and_opt_in_validation(tmp_path: Path) -> None:
    setup_root(tmp_path)
    registry = yaml.safe_load((tmp_path / REGISTRY).read_text())
    registry["activity_sources"][0]["opt_in"] = False
    registry["activity_sources"][1]["metric_bindings"]["github.pull_request.closed"] = (
        "unknown_metric"
    )
    write(tmp_path / REGISTRY, registry)
    result = validate_sources(tmp_path)
    assert result["ok"] is False
    assert {finding["message"] for finding in result["findings"]} == {
        "enabled source requires explicit opt_in: true",
        "github.pull_request.closed binds unknown metric unknown_metric",
    }


def test_dry_run_does_not_write_cursor_health_or_events(tmp_path: Path) -> None:
    setup_root(tmp_path)
    result = ingest_pages(
        tmp_path,
        "slack_los",
        [{"items": [{"id": "m-1", "event_type": "message.sent"}]}],
    )
    assert result["emitted"] == 1
    assert not (tmp_path / CURSORS).exists()
    assert not (tmp_path / HEALTH).exists()
    assert not list((tmp_path / EVENTS).glob("*.yml"))


def test_rejects_unbound_event_and_unsafe_configured_dimension(tmp_path: Path) -> None:
    setup_root(tmp_path)
    registry = yaml.safe_load((tmp_path / REGISTRY).read_text())
    registry["activity_sources"][0]["dimensions"] = {"url": "https://private.invalid"}
    write(tmp_path / REGISTRY, registry)
    assert validate_sources(tmp_path)["ok"] is False
    source = registry["activity_sources"][1]
    try:
        event_envelope(source, {"id": "pr-1", "event_type": "pull_request.closed"})
    except ValueError as exc:
        assert "no analytics metric binding" in str(exc)
    else:
        raise AssertionError("unbound event was accepted")


def test_all_supported_provider_families_normalize_without_credentials(
    tmp_path: Path,
) -> None:
    setup_root(tmp_path)
    for provider in ("slack", "github", "jira", "linear", "agentic_os"):
        canonical_provider = "os" if provider == "agentic_os" else provider
        source = {
            "id": f"{provider}_source",
            "provider": provider,
            "scope": {"domain": "d", "project": "p"},
            "metric_bindings": {f"{canonical_provider}.observed": "tool_runs"},
        }
        event = event_envelope(source, {"id": f"{provider}-1", "type": "observed"})
        assert event["type"] == f"{canonical_provider}.observed"
        assert event["source"]["provider"] == provider


def test_provider_aliases_cover_operator_activity_families() -> None:
    cases = (
        ("slack", "message_created", "slack.message.sent"),
        ("github", "pr_merged", "github.pull_request.merged"),
        ("github", "action_failed", "github.workflow_run.failed"),
        ("jira", "transitioned", "jira.issue.transitioned"),
        ("linear", "completed", "linear.issue.completed"),
        ("agentic_os", "tool_ran", "os.tool.ran"),
        ("agentic_os", "automation_ran", "os.automation.ran"),
        ("agentic_os", "error", "os.error.recorded"),
    )
    for provider, raw_type, canonical in cases:
        source = {
            "id": f"{provider}_source",
            "provider": provider,
            "scope": {"domain": "d", "project": "p"},
            "metric_bindings": {canonical: "tool_runs"},
        }
        event = event_envelope(source, {"id": "stable-1", "type": raw_type})
        assert event["type"] == canonical


def setup_local_source(root: Path) -> None:
    write(
        root / METRICS,
        {
            "metrics": [
                {"id": "messages"},
                {"id": "tool_runs"},
                {"id": "automation_runs"},
                {"id": "errors"},
            ]
        },
    )
    write(
        root / REGISTRY,
        {
            "schema_version": 1,
            "activity_sources": [
                {
                    "id": "agentic_os_local",
                    "provider": "agentic_os",
                    "enabled": True,
                    "opt_in": True,
                    "scope": {
                        "domain": "clarks_consulting",
                        "project": "genomes_agentic_os",
                    },
                    "dimensions": {"host_class": "workstation"},
                    "metric_bindings": {
                        "os.tool.ran": "tool_runs",
                        "os.conversation.message": "messages",
                        "os.automation.ran": "automation_runs",
                        "os.error.recorded": "errors",
                    },
                }
            ],
        },
    )


def write_local_evidence(root: Path) -> None:
    write(
        root / "harness/shared_factory/06-runs-and-logs/events/evt_message.yml",
        {
            "id": "evt_message",
            "type": "os.conversation.message",
            "occurred_at": "2026-07-16T00:00:00Z",
            "text": "private conversation body",
            "url": "https://private.invalid/thread",
        },
    )
    write(
        root / "harness/shared_factory/06-runs-and-logs/runs/run-1/run-log.yml",
        {
            "run_id": "run-1",
            "kind": "runtime_dispatch",
            "status": "done",
            "provider": "customer_name",
            "finished_at": "2026-07-16T00:01:00Z",
            "command": "print a secret",
            "evidence": {"stdout": "customer body", "token": "xoxb-secret"},
        },
    )


def test_local_collector_dry_run_is_metadata_only_and_read_only(tmp_path: Path) -> None:
    setup_local_source(tmp_path)
    write_local_evidence(tmp_path)
    result = collect_local_activity(tmp_path, "agentic_os_local", limit=10)
    rendered = yaml.safe_dump(result)
    assert result["emitted"] == 2
    assert {event["type"] for event in result["events"]} == {
        "os.conversation.message",
        "os.automation.ran",
    }
    assert "private conversation body" not in rendered
    assert "private.invalid" not in rendered
    assert "print a secret" not in rendered
    assert "customer body" not in rendered
    assert "xoxb-secret" not in rendered
    assert "customer_name" not in rendered
    assert not (tmp_path / CURSORS).exists()
    assert not (tmp_path / HEALTH).exists()
    assert not list((tmp_path / EVENTS).glob("*.yml"))


def test_local_collector_apply_advances_cursor_and_replay_is_empty(
    tmp_path: Path,
) -> None:
    setup_local_source(tmp_path)
    write_local_evidence(tmp_path)
    first = collect_local_activity(tmp_path, "agentic_os_local", limit=10, apply=True)
    second = collect_local_activity(tmp_path, "agentic_os_local", limit=10, apply=True)
    assert first["emitted"] == 2
    assert first["cursor"]
    assert second["emitted"] == 0
    assert len(list((tmp_path / EVENTS).glob("*.yml"))) == 2
    cursor = yaml.safe_load((tmp_path / CURSORS).read_text())["sources"][
        "agentic_os_local"
    ]
    assert cursor["cursor"] == first["cursor"]


def test_local_discovery_is_bounded_and_reports_unsupported(tmp_path: Path) -> None:
    events = tmp_path / "harness/shared_factory/06-runs-and-logs/events"
    for index in range(3):
        write(
            events / f"evt_{index}.yml",
            {"id": f"evt_{index}", "type": "unmapped.event"},
        )
    result = discover_local_activity(tmp_path, limit=2)
    assert result["scanned"] == 2
    assert result["unsupported"] == 2
    assert result["items"] == []


def test_local_collector_malformed_evidence_is_degraded_and_recoverable(
    tmp_path: Path,
) -> None:
    setup_local_source(tmp_path)
    events = tmp_path / "harness/shared_factory/06-runs-and-logs/events"
    events.mkdir(parents=True)
    (events / "evt_bad.yml").write_text("bad: [yaml", encoding="utf-8")
    result = collect_local_activity(tmp_path, "agentic_os_local", apply=True)
    assert result["ok"] is True
    assert result["status"] == "degraded"
    assert result["collector"]["malformed"] == 1
    health = yaml.safe_load((tmp_path / HEALTH).read_text())["sources"][
        "agentic_os_local"
    ]
    assert health["status"] == "degraded"
    assert "1 malformed" in health["last_error"]


def test_local_collector_missing_evidence_does_not_advance_cursor(
    tmp_path: Path,
) -> None:
    setup_local_source(tmp_path)
    result = collect_local_activity(tmp_path, "agentic_os_local", apply=True)
    assert result["ok"] is False
    assert result["status"] == "unavailable"
    cursor_data = yaml.safe_load((tmp_path / CURSORS).read_text())
    assert cursor_data["sources"] == {}


def test_local_collector_rejects_external_provider_source(tmp_path: Path) -> None:
    setup_root(tmp_path)
    try:
        collect_local_activity(tmp_path, "slack_los")
    except ValueError as exc:
        assert "requires an agentic_os" in str(exc)
    else:
        raise AssertionError("external provider source was accepted")


def test_local_collector_maps_tool_and_error_receipts(tmp_path: Path) -> None:
    setup_local_source(tmp_path)
    write(
        tmp_path / "harness/shared_factory/06-runs-and-logs/runs/tool/run-log.yml",
        {
            "run_id": "tool-1",
            "kind": "tool_call",
            "status": "done",
            "finished_at": "2026-07-16T00:00:00Z",
        },
    )
    write(
        tmp_path / "harness/shared_factory/06-runs-and-logs/events/evt_error.yml",
        {
            "id": "evt_error",
            "type": "os.doctor.regression",
            "occurred_at": "2026-07-16T00:01:00Z",
        },
    )
    result = collect_local_activity(tmp_path, "agentic_os_local")
    assert {event["type"] for event in result["events"]} == {
        "os.tool.ran",
        "os.error.recorded",
    }


def test_collect_local_cli_dry_run(tmp_path: Path, capsys) -> None:
    setup_local_source(tmp_path)
    write_local_evidence(tmp_path)
    assert (
        main(
            [
                "activity",
                "collect-local",
                "agentic_os_local",
                "--root",
                str(tmp_path),
                "--limit",
                "1",
                "--dry-run",
            ]
        )
        == 0
    )
    output = yaml.safe_load(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["collector"]["scanned"] == 1


def test_local_collector_rejects_nonpositive_limit(tmp_path: Path) -> None:
    setup_local_source(tmp_path)
    try:
        collect_local_activity(tmp_path, "agentic_os_local", limit=0)
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("nonpositive limit was accepted")
