from pathlib import Path

import yaml

from genomes_agentic_os.activity_ingestion import (
    CURSORS,
    EVENTS,
    HEALTH,
    METRICS,
    REGISTRY,
    event_envelope,
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
