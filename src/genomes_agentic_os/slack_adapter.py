"""Generic, injectable Slack channel-history client.

The source-watch workflow imports this port, but does not own its HTTP or
normalization rules.  That keeps Slack reusable without pulling a
workflow-specific Bolt implementation into Agentic OS.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


_SLACK_API_BASE = "https://slack.com/api"
_SLACK_MSG_KEEP = frozenset(
    {"ts", "type", "user", "text", "thread_ts", "reply_count", "reactions", "files", "subtype", "bot_id", "app_id"}
)
_SLACK_TEXT_MAX = 500

Fetcher = Callable[[urllib.request.Request], Any]


class SlackApiError(ValueError):
    """A safe, stable error from Slack's API envelope."""


def _default_fetcher(request: urllib.request.Request) -> Any:
    return urllib.request.urlopen(request, timeout=15)  # noqa: S310


def _trim_message(message: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key in _SLACK_MSG_KEEP:
        if key not in message:
            continue
        value = message[key]
        if key == "text" and isinstance(value, str):
            value = value[:_SLACK_TEXT_MAX]
        elif key == "reactions" and isinstance(value, list):
            value = [
                {"name": reaction.get("name"), "count": reaction.get("count")}
                for reaction in value
                if isinstance(reaction, dict)
            ]
        elif key == "files" and isinstance(value, list):
            value = [
                {"id": file.get("id"), "name": file.get("name"), "filetype": file.get("filetype")}
                for file in value
                if isinstance(file, dict)
            ]
        trimmed[key] = value
    return trimmed


@dataclass(frozen=True)
class SlackClient:
    """Read-only Slack history port with injectable transport for tests."""

    token: str
    fetcher: Fetcher = _default_fetcher

    def channel_history(
        self, channel_id: str, *, oldest: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return trimmed channel messages with stable source-watch metadata."""
        query: dict[str, str | int] = {"channel": channel_id, "limit": limit}
        if oldest:
            query["oldest"] = oldest
        request = urllib.request.Request(
            f"{_SLACK_API_BASE}/conversations.history?{urlencode(query)}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "genomes-agentic-os/source-watcher",
            },
        )
        response = self.fetcher(request)
        body = response.read() if hasattr(response, "read") else response
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict) or not data.get("ok"):
            error = data.get("error", "invalid_response") if isinstance(data, dict) else "invalid_response"
            raise SlackApiError(f"Slack API error: {error}")
        messages = data.get("messages") or []
        results: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            item = _trim_message(message)
            timestamp = str(message.get("ts") or "")
            item.update(
                {
                    "_provider": "slack",
                    "_event_type": "message",
                    "_idempotency_key": f"slack:message:{channel_id}:{timestamp}",
                }
            )
            results.append(item)
        return results


def fetch_slack_messages(
    channel_id: str,
    *,
    token: str,
    oldest: str | None = None,
    limit: int = 50,
    fetcher: Fetcher = _default_fetcher,
) -> list[dict[str, Any]]:
    """Compatibility function for existing source-watch callers."""
    return SlackClient(token, fetcher).channel_history(channel_id, oldest=oldest, limit=limit)
