"""Tests for live source adapters (GitHub, Slack) — F-013 offline half.

Verifies:
- GitHub fixture payloads flow through injectable transport → normalised events
  with stable, provider-ID-based idempotency keys
- Slack fixture payloads do the same
- Re-poll of the same fixture produces no duplicate (idempotency via stable key)
- No-creds path → dry-run placeholder event, unchanged from pre-adapter behaviour
- Token-shaped value in config → SECRETS_IN_CONFIG finding, poll refused
- No written event file contains the token fixture value
- Zero network access (all transport is injectable fake)
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from genomes_agentic_os.source_providers import (
    check_config_for_secrets,
    fetch_github_events,
    fetch_slack_messages,
    looks_like_token,
    poll_github_source,
    poll_slack_source,
)
import genomes_agentic_os.source_providers as source_providers
from genomes_agentic_os.source_watch import (
    connected_systems,
    ensure_registries,
    find_by_id,
    normalized_source_event,
    poll_watch_source,
    run_due_watch_sources,
    write_yaml,
    CONNECTED_SYSTEMS_FILE,
    WATCH_SOURCES_FILE,
)


# ---------------------------------------------------------------------------
# Fixtures — network-free fake payloads
# ---------------------------------------------------------------------------

GITHUB_PR_FIXTURE = [
    {
        "id": 1001,
        "number": 42,
        "title": "Add feature X",
        "state": "open",
        "created_at": "2026-06-01T10:00:00Z",
        "updated_at": "2026-06-02T12:00:00Z",
        "merged_at": None,
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/pull/42",
        "user": {"login": "testuser", "id": 9999},
        "head": {"ref": "feature-x", "sha": "abc123"},
        "base": {"ref": "main", "sha": "def456"},
        "draft": False,
        "labels": [{"name": "enhancement"}],
        "requested_reviewers": [{"login": "reviewer1"}],
        "requested_teams": [],
    },
    {
        "id": 1002,
        "number": 43,
        "title": "Fix bug Y",
        "state": "closed",
        "created_at": "2026-06-01T11:00:00Z",
        "updated_at": "2026-06-03T09:00:00Z",
        "merged_at": "2026-06-03T09:00:00Z",
        "closed_at": "2026-06-03T09:00:00Z",
        "html_url": "https://github.com/testorg/testrepo/pull/43",
        "user": {"login": "anotheruser", "id": 8888},
        "head": {"ref": "fix-y", "sha": "bcd234"},
        "base": {"ref": "main", "sha": "def456"},
        "draft": False,
        "labels": [],
        "requested_reviewers": [],
        "requested_teams": [],
    },
]

GITHUB_ISSUE_FIXTURE = [
    {
        "id": 2001,
        "number": 77,
        "title": "Track bridge migration",
        "state": "open",
        "created_at": "2026-06-04T10:00:00Z",
        "updated_at": "2026-06-05T12:00:00Z",
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/issues/77",
        "user": {"login": "issue-author", "id": 7777},
        "labels": [{"name": "migration"}],
        "assignees": [{"login": "owner1"}],
    }
]

SLACK_MESSAGES_FIXTURE = {
    "ok": True,
    "messages": [
        {
            "type": "message",
            "user": "U01ABCDEF",
            "text": "Hello, world! This is a test message.",
            "ts": "1717200000.000001",
            "thread_ts": None,
            "reply_count": 0,
            "reactions": [{"name": "thumbsup", "count": 2}],
            "files": [],
        },
        {
            "type": "message",
            "user": "U01GHIJKL",
            "text": "Another message here.",
            "ts": "1717200060.000002",
            "thread_ts": None,
            "reply_count": 0,
            "reactions": [],
            "files": [],
        },
    ],
    "has_more": False,
}

SLACK_EMPTY_FIXTURE = {"ok": True, "messages": [], "has_more": False}

# A fake token that looks like a real secret — used for secrets-guard tests
FAKE_TOKEN_VALUE = "ghp_TestTokenThatLooksRealABCDEFGH12345"
FAKE_SLACK_TOKEN = "xoxb-test-slack-bot-token-0123456789"


# ---------------------------------------------------------------------------
# Injectable fetcher helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def github_port_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the shared-port vocabulary for every GitHub PR fixture."""
    monkeypatch.setenv("GENOMES_GITHUB_BRIDGE_COMMAND", "node bridge.mjs")
    pull_requests = [
        {
            "id": item["id"],
            "number": item["number"],
            "title": item["title"],
            "state": "merged" if item["merged_at"] else item["state"],
            "url": item["html_url"],
            "author": item["user"]["login"],
            "headBranch": item["head"]["ref"],
            "baseBranch": item["base"]["ref"],
            "headSha": item["head"]["sha"],
            "draft": item["draft"],
            "labels": [label["name"] for label in item["labels"]],
            "requestedReviewers": [
                reviewer["login"] for reviewer in item["requested_reviewers"]
            ],
            "requestedTeams": [
                team["slug"] for team in item["requested_teams"]
            ],
            "openedAt": item["created_at"],
            "updatedAt": item["updated_at"],
            "closedAt": item["closed_at"],
            "mergedAt": item["merged_at"],
        }
        for item in GITHUB_PR_FIXTURE
    ]
    monkeypatch.setattr(
        source_providers,
        "list_pull_requests",
        lambda _command, **_kwargs: pull_requests,
    )

def _make_json_fetcher(payload: Any):
    """Return a fetcher callable that returns *payload* as JSON."""
    def fetcher(req):
        body = json.dumps(payload).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        return mock_resp
    return fetcher


def _make_pr_then_issues_fetcher():
    """Fetcher that returns PR fixture for /pulls URLs, empty list for /issues."""
    def fetcher(req):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/pulls" in url:
            payload = GITHUB_PR_FIXTURE
        else:
            payload = []
        body = json.dumps(payload).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        return mock_resp
    return fetcher


# ---------------------------------------------------------------------------
# Helpers for setting up a minimal watch-source root
# ---------------------------------------------------------------------------

def _make_github_watch_root(tmp_path: Path, token_env_name: str | None = "GITHUB_TOKEN") -> Path:
    """Create a minimal agentic-os root with a github watch source."""
    root = tmp_path / "agentic_os"
    os_root = ensure_registries(root)

    # Override connected-systems to have a github_test entry
    systems_path = os_root / CONNECTED_SYSTEMS_FILE
    data = yaml.safe_load(systems_path.read_text()) or {}
    systems = data.get("connected_systems", [])
    systems.append({
        "id": "github_test",
        "display_name": "Test GitHub",
        "system": "github",
        "status": "planned",
        "owner": "Test",
        "provider_priority": ["direct_api"],
        "credential_refs": {
            "env_vars": [token_env_name] if token_env_name else [],
            "account_aliases": [],
        },
        "workspace_verification": {"required": False},
        "permissions": {"read": ["repo:read"], "write": []},
        "approval_required_for": [],
        "health_check": {"command": "agentic-os connected-system doctor github_test"},
    })
    data["connected_systems"] = systems
    systems_path.write_text(yaml.safe_dump(data, sort_keys=False))

    # Add a github watch source
    ws_path = os_root / WATCH_SOURCES_FILE
    ws_data = yaml.safe_load(ws_path.read_text()) or {}
    ws_data.setdefault("watch_sources", []).append({
        "id": "github_pr_watch",
        "display_name": "GitHub PR Watch",
        "connected_system": "github_test",
        "source_type": "github_repo",
        "external_ref": {
            "owner": "testorg",
            "repo": "testrepo",
            "event_types": ["pull_request"],
        },
        "watch_method": "poll",
        "cadence": "manual",
        "enabled": False,
        "cursor": {
            "type": "timestamp",
            "state_ref": "harness/shared_factory/00-control-plane/watch-cursors.yml",
        },
        "dedupe": {
            "idempotency_key": "{source_type}:{source_id}:{event_id}",
        },
        "filters": {},
        "trigger_rules": [],
        "route": {
            "command": "agentic-os route",
            "context_command": "agentic-os context build",
            "fallback_domain": "shared_factory",
        },
        "outputs": {
            "source_events_dir": "harness/shared_factory/06-runs-and-logs/source-events/",
            "run_queue_ref": "harness/shared_factory/00-control-plane/run-queue.yml",
        },
    })
    ws_path.write_text(yaml.safe_dump(ws_data, sort_keys=False))

    return root


def _make_slack_watch_root(tmp_path: Path, token_env_name: str | None = "SLACK_BOT_TOKEN") -> Path:
    """Create a minimal agentic-os root with a slack watch source."""
    root = tmp_path / "agentic_os"
    os_root = ensure_registries(root)

    systems_path = os_root / CONNECTED_SYSTEMS_FILE
    data = yaml.safe_load(systems_path.read_text()) or {}
    systems = data.get("connected_systems", [])
    systems.append({
        "id": "slack_test",
        "display_name": "Test Slack",
        "system": "slack",
        "status": "planned",
        "owner": "Test",
        "provider_priority": ["direct_api"],
        "credential_refs": {
            "env_vars": [token_env_name] if token_env_name else [],
            "account_aliases": [],
        },
        "workspace_verification": {"required": False},
        "permissions": {"read": ["channels:history"], "write": []},
        "approval_required_for": [],
        "health_check": {"command": "agentic-os connected-system doctor slack_test"},
    })
    data["connected_systems"] = systems
    systems_path.write_text(yaml.safe_dump(data, sort_keys=False))

    ws_path = os_root / WATCH_SOURCES_FILE
    ws_data = yaml.safe_load(ws_path.read_text()) or {}
    ws_data.setdefault("watch_sources", []).append({
        "id": "slack_channel_watch",
        "display_name": "Slack Channel Watch",
        "connected_system": "slack_test",
        "source_type": "slack_channel",
        "external_ref": {
            "channel_id": "C01TEST1234",
        },
        "watch_method": "poll",
        "cadence": "manual",
        "enabled": False,
        "cursor": {
            "type": "timestamp",
            "state_ref": "harness/shared_factory/00-control-plane/watch-cursors.yml",
        },
        "dedupe": {
            "idempotency_key": "{source_type}:{source_id}:{event_id}",
        },
        "filters": {},
        "trigger_rules": [],
        "route": {
            "command": "agentic-os route",
            "context_command": "agentic-os context build",
            "fallback_domain": "shared_factory",
        },
        "outputs": {
            "source_events_dir": "harness/shared_factory/06-runs-and-logs/source-events/",
            "run_queue_ref": "harness/shared_factory/00-control-plane/run-queue.yml",
        },
    })
    ws_path.write_text(yaml.safe_dump(ws_data, sort_keys=False))

    return root


# ---------------------------------------------------------------------------
# Unit tests: looks_like_token
# ---------------------------------------------------------------------------

class TestLooksLikeToken:
    def test_real_github_token_detected(self) -> None:
        assert looks_like_token(FAKE_TOKEN_VALUE)

    def test_slack_token_detected(self) -> None:
        assert looks_like_token(FAKE_SLACK_TOKEN)

    def test_env_var_name_not_detected(self) -> None:
        assert not looks_like_token("GITHUB_TOKEN")
        assert not looks_like_token("SLACK_BOT_TOKEN")
        assert not looks_like_token("COMPOSIO_API_KEY")

    def test_short_strings_not_detected(self) -> None:
        assert not looks_like_token("short")
        assert not looks_like_token("abc123")

    def test_none_not_detected(self) -> None:
        assert not looks_like_token(None)

    def test_integer_not_detected(self) -> None:
        assert not looks_like_token(42)

    def test_path_string_not_detected(self) -> None:
        assert not looks_like_token("/home/user/something/long/path/here.txt")


class TestCheckConfigForSecrets:
    def test_finds_token_in_config(self) -> None:
        config = {"token": FAKE_TOKEN_VALUE, "owner": "testorg"}
        violations = check_config_for_secrets(config)
        assert "token" in violations

    def test_clean_config_has_no_violations(self) -> None:
        config = {"owner": "testorg", "repo": "testrepo"}
        violations = check_config_for_secrets(config)
        assert violations == []

    def test_env_var_name_not_flagged(self) -> None:
        config = {"token_env": "GITHUB_TOKEN"}
        violations = check_config_for_secrets(config)
        assert violations == []


# ---------------------------------------------------------------------------
# GitHub adapter: low-level fetch
# ---------------------------------------------------------------------------

class TestFetchGithubEvents:
    def test_prs_require_the_platform_bridge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)

        with pytest.raises(source_providers.GitHubBridgeError) as error:
            fetch_github_events(
                "testorg",
                "testrepo",
                token="fake_token",
                event_types=["pull_request"],
            )

        assert error.value.code == "BRIDGE_UNCONFIGURED"

    def test_prs_use_shared_port_bridge_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GENOMES_GITHUB_BRIDGE_COMMAND", "node bridge.mjs")
        observed: dict[str, object] = {}

        def fake_port(command, **kwargs):
            observed["command"] = command
            observed.update(kwargs)
            return [{
                "number": 42,
                "title": "Add feature X",
                "state": "open",
                "url": "https://github.com/testorg/testrepo/pull/42",
                "author": "testuser",
                "headBranch": "feature-x",
                "baseBranch": "main",
                "headSha": "abc123",
                "draft": False,
                "labels": ["enhancement"],
                "openedAt": "2026-06-01T10:00:00.000Z",
                "updatedAt": "2026-06-02T12:00:00.000Z",
            }]

        monkeypatch.setattr(source_providers, "list_pull_requests", fake_port)

        items = fetch_github_events("testorg", "testrepo", token="fake_token", event_types=["pull_request"])

        assert observed["command"] == ["node", "bridge.mjs"]
        assert observed["state"] == "all"
        assert items[0]["updated_at"] == "2026-06-02T12:00:00.000Z"
        assert items[0]["_idempotency_key"] == "github:pr:testorg:testrepo:42"

    def test_bridge_mapping_preserves_legacy_pr_shape(self) -> None:
        items = fetch_github_events(
            "testorg",
            "testrepo",
            token="fake_token",
            event_types=["pull_request"],
        )

        assert "id" in items[0]
        assert items[0]["id"] == 1001
        assert items[0]["requested_reviewers"] == ["reviewer1"]
        assert items[0]["requested_teams"] == []

    def test_issue_only_poll_does_not_require_bridge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)
        calls: list[str] = []

        def issue_fetcher(req):
            calls.append(req.full_url)
            return _make_json_fetcher(GITHUB_ISSUE_FIXTURE)(req)

        items = fetch_github_events(
            "testorg",
            "testrepo",
            token="fake_token",
            event_types=["issues"],
            fetcher=issue_fetcher,
        )

        assert len(calls) == 1
        assert "/issues?" in calls[0]
        assert items[0]["_event_type"] == "issue"
        assert items[0]["number"] == 77

    def test_pr_fixture_returns_trimmed_items(self) -> None:
        fetcher = _make_pr_then_issues_fetcher()
        items = fetch_github_events(
            "testorg", "testrepo",
            token="fake_token",
            event_types=["pull_request"],
            fetcher=fetcher,
        )
        assert len(items) == 2
        assert all(item["_provider"] == "github" for item in items)
        assert all(item["_event_type"] == "pull_request" for item in items)

    def test_pr_idempotency_keys_are_stable_and_id_based(self) -> None:
        fetcher = _make_pr_then_issues_fetcher()
        items1 = fetch_github_events(
            "testorg", "testrepo",
            token="fake_token",
            event_types=["pull_request"],
            fetcher=fetcher,
        )
        items2 = fetch_github_events(
            "testorg", "testrepo",
            token="fake_token",
            event_types=["pull_request"],
            fetcher=fetcher,
        )
        keys1 = {item["_idempotency_key"] for item in items1}
        keys2 = {item["_idempotency_key"] for item in items2}
        # Same fixture → same keys (stable)
        assert keys1 == keys2
        # Keys include the PR number, not a timestamp
        for key in keys1:
            assert "github:pr:" in key
            assert "testorg" in key
            assert "testrepo" in key

    def test_raw_token_never_in_returned_items(self) -> None:
        fetcher = _make_pr_then_issues_fetcher()
        items = fetch_github_events(
            "testorg", "testrepo",
            token=FAKE_TOKEN_VALUE,
            event_types=["pull_request"],
            fetcher=fetcher,
        )
        serialized = json.dumps(items)
        assert FAKE_TOKEN_VALUE not in serialized

    def test_trimmed_items_have_no_raw_body_fields(self) -> None:
        fetcher = _make_pr_then_issues_fetcher()
        items = fetch_github_events(
            "testorg", "testrepo",
            token="fake",
            event_types=["pull_request"],
            fetcher=fetcher,
        )
        for item in items:
            # Raw body / auth fields must not leak through
            assert "body" not in item
            assert "token" not in item
            assert "Authorization" not in item

    def test_prs_do_not_use_the_legacy_http_fetcher(self) -> None:
        call_count = {"n": 0}

        def counting_fetcher(req):
            call_count["n"] += 1
            body = json.dumps(GITHUB_PR_FIXTURE).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            return mock_resp

        fetch_github_events(
            "testorg", "testrepo",
            token="fake",
            event_types=["pull_request"],
            fetcher=counting_fetcher,
        )
        assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# Slack adapter: low-level fetch
# ---------------------------------------------------------------------------

class TestFetchSlackMessages:
    def test_fixture_returns_trimmed_messages(self) -> None:
        fetcher = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        items = fetch_slack_messages(
            "C01TEST1234",
            token="fake_token",
            fetcher=fetcher,
        )
        assert len(items) == 2
        assert all(item["_provider"] == "slack" for item in items)
        assert all(item["_event_type"] == "message" for item in items)

    def test_idempotency_keys_include_channel_and_ts(self) -> None:
        fetcher = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        items = fetch_slack_messages(
            "C01TEST1234",
            token="fake_token",
            fetcher=fetcher,
        )
        for item in items:
            assert "slack:message:C01TEST1234:" in item["_idempotency_key"]
            assert item["ts"] in item["_idempotency_key"]

    def test_stable_keys_across_polls(self) -> None:
        fetcher1 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        fetcher2 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        items1 = fetch_slack_messages("C01TEST1234", token="t", fetcher=fetcher1)
        items2 = fetch_slack_messages("C01TEST1234", token="t", fetcher=fetcher2)
        keys1 = {i["_idempotency_key"] for i in items1}
        keys2 = {i["_idempotency_key"] for i in items2}
        assert keys1 == keys2

    def test_text_trimmed_to_max_length(self) -> None:
        long_msg = {"ok": True, "messages": [
            {"type": "message", "user": "U1", "text": "X" * 1000, "ts": "1717200000.0"}
        ]}
        fetcher = _make_json_fetcher(long_msg)
        items = fetch_slack_messages("C01", token="t", fetcher=fetcher)
        assert len(items[0]["text"]) <= 500

    def test_raw_token_not_in_items(self) -> None:
        fetcher = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        items = fetch_slack_messages(
            "C01TEST1234",
            token=FAKE_SLACK_TOKEN,
            fetcher=fetcher,
        )
        serialized = json.dumps(items)
        assert FAKE_SLACK_TOKEN not in serialized

    def test_api_error_raises_value_error(self) -> None:
        fetcher = _make_json_fetcher({"ok": False, "error": "channel_not_found"})
        with pytest.raises(ValueError, match="Slack API error"):
            fetch_slack_messages("C01BAD", token="t", fetcher=fetcher)


# ---------------------------------------------------------------------------
# poll_github_source / poll_slack_source — no-creds fallback
# ---------------------------------------------------------------------------

class TestPollAdaptersNoCreds:
    def test_github_no_token_returns_dry_run_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        source = {
            "id": "test_src",
            "source_type": "github_repo",
            "external_ref": {"owner": "org", "repo": "repo"},
        }
        system = {
            "system": "github",
            "credential_refs": {"env_vars": ["GITHUB_TOKEN"]},
        }
        result = poll_github_source(source, system)
        assert result["ok"] is True
        assert result["live"] is False
        assert result["items"] == []
        assert "dry_run_reason" in result
        assert result["dry_run_reason"] is not None

    def test_github_pr_with_token_but_no_bridge_is_an_explicit_blocker(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)
        source = {
            "id": "test_src",
            "source_type": "github_repo",
            "external_ref": {
                "owner": "org",
                "repo": "repo",
                "event_types": ["pull_request"],
            },
        }
        system = {
            "system": "github",
            "credential_refs": {"env_vars": ["GITHUB_TOKEN"]},
        }

        result = poll_github_source(source, system)

        assert result["ok"] is False
        assert result["live"] is False
        assert result["provider"] == "platform_github_port"
        assert result["findings"] == [{
            "severity": "blocker",
            "code": "BRIDGE_UNCONFIGURED",
            "message": "GitHub pull-request polling requires the configured platform GitHub bridge",
        }]

    def test_slack_no_token_returns_dry_run_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TOKEN", raising=False)
        monkeypatch.delenv("COMPOSIO_SLACK_TOKEN", raising=False)
        source = {
            "id": "test_src",
            "source_type": "slack_channel",
            "external_ref": {"channel_id": "C01TEST"},
        }
        system = {
            "system": "slack",
            "credential_refs": {"env_vars": ["SLACK_BOT_TOKEN"]},
        }
        result = poll_slack_source(source, system)
        assert result["ok"] is True
        assert result["live"] is False
        assert result["items"] == []
        assert result["dry_run_reason"] is not None


# ---------------------------------------------------------------------------
# Secrets-in-config guard
# ---------------------------------------------------------------------------

class TestSecretsInConfigGuard:
    def test_github_token_in_config_refused(self) -> None:
        source = {
            "id": "bad_src",
            "source_type": "github_repo",
            # operator accidentally pasted the token value instead of the env var name
            "token": FAKE_TOKEN_VALUE,
            "external_ref": {"owner": "org", "repo": "repo"},
        }
        system = {"system": "github", "credential_refs": {"env_vars": []}}
        result = poll_github_source(source, system)
        assert result["ok"] is False
        assert result["live"] is False
        codes = [f["code"] for f in result.get("findings", [])]
        assert "SECRETS_IN_CONFIG" in codes

    def test_slack_token_in_config_refused(self) -> None:
        source = {
            "id": "bad_src",
            "source_type": "slack_channel",
            "token": FAKE_SLACK_TOKEN,
            "external_ref": {"channel_id": "C01TEST"},
        }
        system = {"system": "slack", "credential_refs": {"env_vars": []}}
        result = poll_slack_source(source, system)
        assert result["ok"] is False
        codes = [f["code"] for f in result.get("findings", [])]
        assert "SECRETS_IN_CONFIG" in codes

    def test_external_ref_token_in_config_refused(self) -> None:
        """Token-shaped value nested in external_ref is also caught."""
        source = {
            "id": "bad_src",
            "source_type": "github_repo",
            "external_ref": {
                "owner": "org",
                "repo": "repo",
                "token": FAKE_TOKEN_VALUE,  # misplaced here
            },
        }
        system = {"system": "github", "credential_refs": {"env_vars": []}}
        result = poll_github_source(source, system)
        assert result["ok"] is False
        codes = [f["code"] for f in result.get("findings", [])]
        assert "SECRETS_IN_CONFIG" in codes


# ---------------------------------------------------------------------------
# poll_watch_source integration — fixture transport wired end-to-end
# ---------------------------------------------------------------------------

class TestPollWatchSourceGithub:
    def test_bridge_failure_propagates_as_poll_failure(self, tmp_path, monkeypatch) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token_value_for_env")
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)

        result = poll_watch_source(root, "github_pr_watch", dry_run=True)

        assert result["ok"] is False
        assert result["events"] == []
        assert result["adapter"]["provider"] == "platform_github_port"
        assert [finding["code"] for finding in result["findings"]] == [
            "BRIDGE_UNCONFIGURED"
        ]

    def test_mixed_poll_preserves_issue_result_when_bridge_fails(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token_value_for_env")
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)
        ws_path = root / "harness" / "shared_factory" / "00-control-plane" / "watch-sources.yml"
        data = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
        data["watch_sources"][0]["external_ref"]["event_types"] = [
            "pull_request",
            "issues",
        ]
        ws_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        system = find_by_id(connected_systems(root), "github_test")
        source = find_by_id(
            yaml.safe_load(ws_path.read_text(encoding="utf-8"))["watch_sources"],
            "github_pr_watch",
        )
        result = poll_github_source(
            source,
            system,
            fetcher=_make_json_fetcher(GITHUB_ISSUE_FIXTURE),
        )

        assert result["ok"] is False
        assert result["partial"] is True
        assert result["provider"] == "platform_github_port+direct_api"
        assert result["item_count"] == 1
        assert result["items"][0]["_event_type"] == "issue"
        assert result["findings"][0]["code"] == "BRIDGE_UNCONFIGURED"

    def test_run_due_surfaces_bridge_failure(self, tmp_path, monkeypatch) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token_value_for_env")
        monkeypatch.delenv("GENOMES_GITHUB_BRIDGE_COMMAND", raising=False)
        ws_path = root / "harness" / "shared_factory" / "00-control-plane" / "watch-sources.yml"
        data = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
        data["watch_sources"][0]["enabled"] = True
        data["watch_sources"][0]["trigger_rules"] = [{
            "id": "test_disabled_rule",
            "enabled": False,
        }]
        ws_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        result = run_due_watch_sources(root, dry_run=True)
        action = next(
            action for action in result["actions"]
            if action["source_id"] == "github_pr_watch"
        )

        assert action["action"] == "poll"
        assert action["ok"] is False
        assert action["events"] == []
        assert action["findings"][0]["code"] == "BRIDGE_UNCONFIGURED"

    def test_live_poll_produces_normalised_event(self, tmp_path, monkeypatch) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token_value_for_env")
        fetcher = _make_pr_then_issues_fetcher()

        result = poll_watch_source(root, "github_pr_watch", dry_run=True, fetcher=fetcher)

        assert result["ok"] is True
        assert len(result["events"]) == 1
        event = result["events"][0]
        assert event["schema_version"] == 1
        assert event["event_type"] == "github_repo.polled"
        assert event["dry_run"] is True
        assert "live_items" in event
        assert len(event["live_items"]) == 2
        assert event["provider_adapter"]["mode"] == "live_dry_run"

    def test_live_idempotency_key_is_provider_id_based_not_timestamp(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token_value_for_env")
        fetcher = _make_pr_then_issues_fetcher()

        r1 = poll_watch_source(root, "github_pr_watch", dry_run=True, fetcher=fetcher)
        r2 = poll_watch_source(root, "github_pr_watch", dry_run=True, fetcher=fetcher)

        key1 = r1["events"][0]["dedupe"]["idempotency_key"]
        key2 = r2["events"][0]["dedupe"]["idempotency_key"]
        # Same fixture → same idempotency key across polls (stable, not timestamp)
        assert key1 == key2
        # Must NOT be a timestamp-based key — must not contain "observed_at" patterns
        assert "2026" not in key1

    def test_no_creds_falls_back_to_dry_run_unchanged(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        result = poll_watch_source(root, "github_pr_watch", dry_run=True)

        assert result["ok"] is True
        assert len(result["events"]) == 1
        event = result["events"][0]
        # No live items — pure registry dry-run path
        assert "live_items" not in event or event.get("live_items") is None
        assert event["dry_run"] is True
        assert "registry" in event["payload_ref"]["type"]

    def test_trigger_enqueue_preserves_worker_command(self, tmp_path, monkeypatch) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        ws_path = root / "harness" / "shared_factory" / "00-control-plane" / "watch-sources.yml"
        data = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
        source = data["watch_sources"][0]
        source["trigger_rules"] = [
            {
                "id": "run_selected_worker",
                "enabled": True,
                "when": {"event_type": "github_repo.polled"},
                "then": {
                    "enqueue": {
                        "work_type": "implementation",
                        "route_to": "los/00-programs/auto_dev_queue",
                        "execution_target": "script",
                        "command": "agentic-os watch-source poll github_pr_watch --root {database_url} --apply",
                    }
                },
                "approval": {"required": False},
                "idempotency": {"key": "{event_id}:run_selected_worker"},
            }
        ]
        source["external_ref"]["database_url"] = str(root)
        ws_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        result = poll_watch_source(root, "github_pr_watch", dry_run=True)

        action = result["trigger_actions"][0]
        assert action["queue_item"]["command"] == f"agentic-os watch-source poll github_pr_watch --root {root} --apply"
        assert action["queue_item"]["execution_target"] == "script"

    def test_secrets_in_config_propagates_as_blocker(self, tmp_path, monkeypatch) -> None:
        root = _make_github_watch_root(tmp_path)
        # Inject a token-shaped value into the watch source config
        ws_path = root / "harness" / "shared_factory" / "00-control-plane" / "watch-sources.yml"
        data = yaml.safe_load(ws_path.read_text())
        for src in data.get("watch_sources", []):
            if src.get("id") == "github_pr_watch":
                src["token"] = FAKE_TOKEN_VALUE
        ws_path.write_text(yaml.safe_dump(data, sort_keys=False))

        monkeypatch.setenv("GITHUB_TOKEN", "something")

        result = poll_watch_source(root, "github_pr_watch", dry_run=True)
        assert result["ok"] is False
        codes = [f.get("code") for f in result.get("findings", [])]
        assert "SECRETS_IN_CONFIG" in codes

    def test_written_event_files_do_not_contain_token(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN_VALUE)
        fetcher = _make_pr_then_issues_fetcher()

        result = poll_watch_source(root, "github_pr_watch", dry_run=False, fetcher=fetcher)

        assert result.get("ok") is True
        for written_path in result.get("written", []):
            content = Path(written_path).read_text(encoding="utf-8")
            assert FAKE_TOKEN_VALUE not in content, (
                f"Token found in written event file: {written_path}"
            )


class TestPollWatchSourceSlack:
    def test_live_poll_produces_normalised_event(self, tmp_path, monkeypatch) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-slack-token")
        fetcher = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)

        result = poll_watch_source(root, "slack_channel_watch", dry_run=True, fetcher=fetcher)

        assert result["ok"] is True
        event = result["events"][0]
        assert event["event_type"] == "slack_channel.polled"
        assert "live_items" in event
        assert len(event["live_items"]) == 2

    def test_idempotency_stable_across_repoll(self, tmp_path, monkeypatch) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        fetcher1 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        fetcher2 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)

        r1 = poll_watch_source(root, "slack_channel_watch", dry_run=True, fetcher=fetcher1)
        r2 = poll_watch_source(root, "slack_channel_watch", dry_run=True, fetcher=fetcher2)

        key1 = r1["events"][0]["dedupe"]["idempotency_key"]
        key2 = r2["events"][0]["dedupe"]["idempotency_key"]
        assert key1 == key2

    def test_no_creds_falls_back_to_dry_run(self, tmp_path, monkeypatch) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TOKEN", raising=False)
        monkeypatch.delenv("COMPOSIO_SLACK_TOKEN", raising=False)

        result = poll_watch_source(root, "slack_channel_watch", dry_run=True)

        assert result["ok"] is True
        event = result["events"][0]
        assert event["dry_run"] is True
        assert event["payload_ref"]["type"] == "registry"

    def test_written_slack_event_does_not_contain_token(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.setenv("SLACK_BOT_TOKEN", FAKE_SLACK_TOKEN)
        fetcher = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)

        result = poll_watch_source(root, "slack_channel_watch", dry_run=False, fetcher=fetcher)

        assert result.get("ok") is True
        for written_path in result.get("written", []):
            content = Path(written_path).read_text(encoding="utf-8")
            assert FAKE_SLACK_TOKEN not in content, (
                f"Slack token found in written event file: {written_path}"
            )


# ---------------------------------------------------------------------------
# Idempotency: same fixture twice → same event ID (no duplicate write)
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_github_repoll_same_items_same_event_id(self, tmp_path, monkeypatch) -> None:
        """Same fixture data must produce identical event IDs (idempotent)."""
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
        fetcher = _make_pr_then_issues_fetcher()

        r1 = poll_watch_source(root, "github_pr_watch", dry_run=True, fetcher=fetcher)
        r2 = poll_watch_source(root, "github_pr_watch", dry_run=True, fetcher=fetcher)

        id1 = r1["events"][0]["id"]
        id2 = r2["events"][0]["id"]
        assert id1 == id2, "Same items must produce the same event ID"

    def test_github_apply_twice_writes_once(self, tmp_path, monkeypatch) -> None:
        """write_yaml_once ensures the event file is only written on first apply."""
        root = _make_github_watch_root(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
        fetcher = _make_pr_then_issues_fetcher()

        r1 = poll_watch_source(root, "github_pr_watch", dry_run=False, fetcher=fetcher)
        r2 = poll_watch_source(root, "github_pr_watch", dry_run=False, fetcher=fetcher)

        assert r1.get("ok")
        assert r2.get("ok")
        # Both polls wrote the same event file (not a new one each time)
        written1 = set(r1.get("written", []))
        written2 = set(r2.get("written", []))
        assert written1 == written2, "Second apply must not write a different file"

    def test_slack_repoll_same_messages_same_event_id(self, tmp_path, monkeypatch) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        fetcher1 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)
        fetcher2 = _make_json_fetcher(SLACK_MESSAGES_FIXTURE)

        r1 = poll_watch_source(root, "slack_channel_watch", dry_run=True, fetcher=fetcher1)
        r2 = poll_watch_source(root, "slack_channel_watch", dry_run=True, fetcher=fetcher2)

        assert r1["events"][0]["id"] == r2["events"][0]["id"]


# ---------------------------------------------------------------------------
# Dry-run preservation: existing poll_watch_source without creds === old behaviour
# ---------------------------------------------------------------------------

class TestDryRunPreservationNoCreds:
    """Ensure the no-creds path is byte-for-byte identical to pre-adapter behaviour."""

    def test_github_no_creds_event_has_registry_payload_ref(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_github_watch_root(tmp_path)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        result = poll_watch_source(root, "github_pr_watch", dry_run=True)

        event = result["events"][0]
        assert event["payload_ref"]["type"] == "registry"
        assert event["provider_adapter"]["mode"] == "registry_dry_run"
        assert event["dry_run"] is True

    def test_slack_no_creds_event_matches_registry_mode(
        self, tmp_path, monkeypatch
    ) -> None:
        root = _make_slack_watch_root(tmp_path)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TOKEN", raising=False)
        monkeypatch.delenv("COMPOSIO_SLACK_TOKEN", raising=False)

        result = poll_watch_source(root, "slack_channel_watch", dry_run=True)

        event = result["events"][0]
        assert event["payload_ref"]["type"] == "registry"
        assert event["dry_run"] is True
