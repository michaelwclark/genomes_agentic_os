from __future__ import annotations

from typing import Any

from genomes_agentic_os import notion_api


class _Bridge:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.identity = None
        self.responses = {name: list(values) for name, values in responses.items()}
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        operation: str,
        args: dict[str, Any],
        *,
        mutation: bool = False,
        identity: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "operation": operation,
                "args": args,
                "mutation": mutation,
                "identity": identity,
            }
        )
        return self.responses[operation].pop(0)


def _install(monkeypatch, bridge: _Bridge) -> None:
    monkeypatch.setattr(notion_api, "_bridge_client", lambda token_env: bridge)


def test_default_database_query_uses_bridge_and_normalizes_rows(monkeypatch) -> None:
    bridge = _Bridge(
        {
            "queryDatabase": [
                {
                    "complete": True,
                    "values": [
                        {
                            "id": "aaaa-bbbb",
                            "updatedAt": "2026-07-31T12:00:00Z",
                            "url": "https://notion.example/row",
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "AGE-132"}],
                                }
                            },
                        }
                    ],
                }
            ]
        }
    )
    _install(monkeypatch, bridge)

    rows = notion_api.query_database_pages("database")

    assert rows == [
        {
            "id": "aaaabbbb",
            "id_dashed": "aaaa-bbbb",
            "last_edited_time": "2026-07-31T12:00:00Z",
            "url": "https://notion.example/row",
            "properties": {"Name": "AGE-132"},
        }
    ]
    assert bridge.calls == [
        {
            "operation": "queryDatabase",
            "args": {"databaseId": "database"},
            "mutation": False,
            "identity": None,
        }
    ]


def test_default_replace_preserves_child_collections_and_guards_mutations(monkeypatch) -> None:
    bridge = _Bridge(
        {
            "listBlockChildren": [
                {
                    "complete": True,
                    "values": [
                        {"id": "keep", "type": "child_page", "value": {}},
                        {"id": "trash", "type": "paragraph", "value": {}},
                    ],
                }
            ],
            "trashBlock": [{"id": "trash"}],
            "appendBlockChildren": [[]],
        }
    )
    _install(monkeypatch, bridge)
    children = [{"object": "block", "type": "paragraph", "paragraph": {}}]

    notion_api.replace_block_children("parent", children)

    mutation_calls = [call for call in bridge.calls if call["mutation"]]
    assert [call["operation"] for call in mutation_calls] == [
        "trashBlock",
        "appendBlockChildren",
    ]
    assert all(
        call["identity"]
        == {"workspaceName": "Genome's Notion", "parentPageId": "parent"}
        for call in mutation_calls
    )
    assert bridge.calls[-1]["args"] == {"blockId": "parent", "children": children}


def test_default_database_page_create_reconciles_against_database_parent(monkeypatch) -> None:
    bridge = _Bridge(
        {
            "getDatabase": [
                {"id": "database", "parent": {"type": "page_id", "id": "parent"}}
            ],
            "createPage": [{"id": "new-page"}],
        }
    )
    _install(monkeypatch, bridge)
    properties = {
        "Name": {
            "title": [{"type": "text", "text": {"content": "AGE-132"}}]
        }
    }

    page_id = notion_api.create_database_page("database", properties)

    assert page_id == "newpage"
    create = bridge.calls[-1]
    assert create["operation"] == "createPage"
    assert create["mutation"] is True
    assert create["identity"] == {
        "workspaceName": "Genome's Notion",
        "parentPageId": "parent",
    }
    assert create["args"]["input"]["reconciliation"] == {
        "parentPageId": "parent",
        "marker": "AGE-132",
    }


def test_default_workspace_preflight_uses_explicit_parent(monkeypatch) -> None:
    bridge = _Bridge(
        {
            "preflightIdentity": [
                {"workspaceName": "Genome's Notion", "parentPageId": "parent"}
            ]
        }
    )
    _install(monkeypatch, bridge)

    assert (
        notion_api.get_bot_workspace("TOKEN", parent_page_id="parent")
        == "Genome's Notion"
    )
    assert bridge.calls[0]["args"] == {
        "workspaceName": "Genome's Notion",
        "parentPageId": "parent",
    }


def test_direct_default_transport_is_disabled() -> None:
    try:
        notion_api._default_fetcher(object())  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "shared bridge" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("direct Notion transport unexpectedly remained enabled")
