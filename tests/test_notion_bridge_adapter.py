from __future__ import annotations

import json
import subprocess

import pytest

from genomes_agentic_os import notion_api
from genomes_agentic_os.notion_bridge import NotionBridgeClient, NotionBridgeError
from genomes_agentic_os.notion_bridge_adapter import (
    query_database_pages,
    query_data_source_pages,
)


RAW_PAGE = {
    "object": "page",
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "last_edited_time": "2026-07-31T12:00:00.000Z",
    "url": "https://www.notion.so/fixture",
    "properties": {
        "Name": {
            "type": "title",
            "title": [{"plain_text": "Fixture"}],
        },
        "Status": {"type": "status", "status": {"name": "Queue Start"}},
    },
}

BRIDGE_PAGE = {
    "object": "page",
    "id": RAW_PAGE["id"],
    "updatedAt": RAW_PAGE["last_edited_time"],
    "url": RAW_PAGE["url"],
    "properties": RAW_PAGE["properties"],
}


def _client(result: object) -> tuple[NotionBridgeClient, list[dict[str, object]]]:
    requests: list[dict[str, object]] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        requests.append(json.loads(str(kwargs["input"])))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"version": 1, "ok": True, "result": result}),
            stderr="",
        )

    return (
        NotionBridgeClient(
            ["node", "bridge.js"], {"GENOMES_NOTION_PAT": "secret"}, runner=runner
        ),
        requests,
    )


@pytest.mark.parametrize(
    ("function", "operation", "argument"),
    [
        (query_database_pages, "queryDatabase", "databaseId"),
        (query_data_source_pages, "queryDataSource", "dataSourceId"),
    ],
)
def test_bridge_reads_preserve_legacy_safe_summary_shape(
    function, operation: str, argument: str
) -> None:
    client, requests = _client({"values": [BRIDGE_PAGE], "complete": True})

    assert function("object-id", client=client) == [
        notion_api.notion_page_summary(RAW_PAGE)
    ]
    assert requests == [
        {
            "version": 1,
            "operation": operation,
            "args": {argument: "object-id"},
        }
    ]


def test_unlimited_bridge_read_fails_closed_on_partial_collection() -> None:
    client, _ = _client({"values": [], "complete": False, "nextCursor": "cursor"})

    with pytest.raises(NotionBridgeError) as exc:
        query_data_source_pages("source-id", client=client)
    assert exc.value.code == "BRIDGE_INVALID_RESPONSE"
