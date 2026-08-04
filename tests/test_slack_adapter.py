"""Offline tests for the reusable Slack channel-history port."""

from __future__ import annotations

import json
from typing import Any

import pytest

from genomes_agentic_os.slack_adapter import SlackApiError, SlackClient


def _fetcher(payload: Any):
    def fetch(request):
        del request
        return json.dumps(payload).encode("utf-8")

    return fetch


def test_client_trims_messages_and_keeps_stable_source_metadata() -> None:
    client = SlackClient(
        "secret",
        _fetcher(
            {
                "ok": True,
                "messages": [
                    {
                        "ts": "1717200000.000001",
                        "text": "X" * 700,
                        "files": [{"id": "F1", "name": "evidence.txt", "filetype": "text"}],
                    }
                ],
            }
        ),
    )

    messages = client.channel_history("C01TEST")

    assert messages == [
        {
            "ts": "1717200000.000001",
            "text": "X" * 500,
            "files": [{"id": "F1", "name": "evidence.txt", "filetype": "text"}],
            "_provider": "slack",
            "_event_type": "message",
            "_idempotency_key": "slack:message:C01TEST:1717200000.000001",
        }
    ]
    assert "secret" not in json.dumps(messages)


def test_client_exposes_safe_provider_error() -> None:
    client = SlackClient("secret", _fetcher({"ok": False, "error": "channel_not_found"}))

    with pytest.raises(SlackApiError, match="Slack API error: channel_not_found"):
        client.channel_history("C01TEST")
