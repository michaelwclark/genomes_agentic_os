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

    notion_api.replace_block_children(
        "target", children, approved_parent_page_id="parent"
    )

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
    assert bridge.calls[-1]["args"] == {"blockId": "target", "children": children}


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

    page_id = notion_api.create_database_page(
        "database", properties, approved_parent_page_id="parent"
    )

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


def test_update_page_uses_separate_approved_root(monkeypatch) -> None:
    bridge = _Bridge({"updatePage": [{"id": "target"}]})
    _install(monkeypatch, bridge)

    notion_api.update_database_page(
        "target",
        {"Status": {"select": {"name": "ready"}}},
        approved_parent_page_id="approved-root",
    )

    assert bridge.calls == [
        {
            "operation": "updatePage",
            "args": {
                "pageId": "target",
                "input": {"properties": {"Status": {"select": {"name": "ready"}}}},
            },
            "mutation": True,
            "identity": {
                "workspaceName": "Genome's Notion",
                "parentPageId": "approved-root",
            },
        }
    ]


def test_mutation_without_separate_root_fails_before_bridge_call(monkeypatch) -> None:
    bridge = _Bridge({"updatePage": [{"id": "target"}]})
    _install(monkeypatch, bridge)

    try:
        notion_api.update_database_page("target", {})
    except RuntimeError as exc:
        assert "approved_parent_page_id" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("mutation self-authorized its target page")
    assert bridge.calls == []


def test_create_refuses_parent_outside_separately_approved_root(monkeypatch) -> None:
    bridge = _Bridge({"createPage": [{"id": "unexpected"}]})
    _install(monkeypatch, bridge)

    try:
        notion_api.create_page(
            "stale-target", "Unsafe", approved_parent_page_id="approved-root"
        )
    except RuntimeError as exc:
        assert "differs from the approved mutation root" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("create self-authorized a stale target")
    assert bridge.calls == []


def test_create_page_uses_json_stable_reconciliation_marker(monkeypatch) -> None:
    bridge = _Bridge({"createPage": [{"id": "new-page"}]})
    _install(monkeypatch, bridge)

    page_id = notion_api.create_page(
        "parent",
        'Quarterly "Review"\nAGE-132',
        approved_parent_page_id="parent",
    )

    assert page_id == "newpage"
    assert bridge.calls[-1]["args"]["input"]["reconciliation"]["marker"] == "Quarterly"


def test_create_page_rejects_title_without_stable_marker_before_mutation(monkeypatch) -> None:
    bridge = _Bridge({"createPage": [{"id": "unexpected"}]})
    _install(monkeypatch, bridge)

    try:
        notion_api.create_page('parent', '"\\\n', approved_parent_page_id="parent")
    except RuntimeError as exc:
        assert "JSON-stable reconciliation marker" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("create accepted an unreconcilable title")
    assert bridge.calls == []


def test_reconciliation_marker_preserves_short_and_symbol_titles() -> None:
    assert notion_api._reconciliation_marker("Q1") == "Q1"
    assert notion_api._reconciliation_marker("🧬") == "🧬"


def test_direct_default_transport_is_disabled() -> None:
    try:
        notion_api._default_fetcher(object())  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "shared bridge" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("direct Notion transport unexpectedly remained enabled")
