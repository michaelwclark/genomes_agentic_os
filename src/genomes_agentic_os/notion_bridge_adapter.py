"""Legacy-shape read adapters backed by the shared Notion bridge.

The bridge owns provider transport, pagination, deadlines, retries, and safe
errors. This module performs only the small shape conversion required by
existing Agentic OS automation consumers during the bounded cutover.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .notion_bridge import NotionBridgeClient, NotionBridgeError, client_from_environment


def plain_property_value(property_value: Mapping[str, Any]) -> Any:
    """Convert one provider property value into the existing compact scalar."""
    prop_type = property_value.get("type")
    value = property_value.get(prop_type) if isinstance(prop_type, str) else None
    if prop_type in {"title", "rich_text"} and isinstance(value, list):
        return "".join(
            str(part.get("plain_text") or "")
            for part in value
            if isinstance(part, dict)
        )
    if prop_type in {"select", "status"} and isinstance(value, dict):
        return value.get("name")
    if prop_type == "checkbox":
        return bool(value)
    if prop_type in {"number", "url", "email", "phone_number"}:
        return value
    if prop_type == "date" and isinstance(value, dict):
        return value.get("start")
    if prop_type == "multi_select" and isinstance(value, list):
        return [item.get("name") for item in value if isinstance(item, dict)]
    if prop_type == "people" and isinstance(value, list):
        return [
            item.get("name") or item.get("id")
            for item in value
            if isinstance(item, dict)
        ]
    if prop_type == "formula" and isinstance(value, dict):
        nested_type = value.get("type")
        if isinstance(nested_type, str):
            return plain_property_value(
                {"type": nested_type, nested_type: value.get(nested_type)}
            )
    return None


def notion_page_summary(page: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a normalized bridge page into the established safe row shape."""
    properties = page.get("properties")
    raw_properties = properties if isinstance(properties, dict) else {}
    page_id = str(page.get("id") or "")
    return {
        "id": page_id.replace("-", ""),
        "id_dashed": page_id or None,
        "last_edited_time": page.get("updatedAt"),
        "url": page.get("url"),
        "properties": {
            str(name): plain_property_value(value)
            for name, value in raw_properties.items()
            if isinstance(value, dict)
        },
    }


def _client(token_env: str, client: NotionBridgeClient | None) -> NotionBridgeClient:
    if client is not None:
        return client
    token = os.environ.get(token_env, "").strip()
    if not token:
        raise NotionBridgeError(
            "CONFIGURATION_ERROR", f"Notion token env var {token_env!r} is not set"
        )
    return client_from_environment(token=token)


def _complete_pages(
    operation: str,
    object_id_name: str,
    object_id: str,
    *,
    token_env: str,
    client: NotionBridgeClient | None,
) -> list[dict[str, Any]]:
    result = _client(token_env, client).request(operation, {object_id_name: object_id})
    if not isinstance(result, dict) or result.get("complete") is not True:
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE",
            "Notion bridge returned an incomplete collection without a caller limit",
        )
    values = result.get("values")
    if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Notion bridge returned invalid page rows"
        )
    return [notion_page_summary(row) for row in values]


def query_database_pages(
    database_id: str,
    *,
    token_env: str = "GENOMES_NOTION_PAT",
    client: NotionBridgeClient | None = None,
) -> list[dict[str, Any]]:
    """Query every current data source under a database via API 2026-03-11."""
    return _complete_pages(
        "queryDatabase",
        "databaseId",
        database_id,
        token_env=token_env,
        client=client,
    )


def query_data_source_pages(
    data_source_id: str,
    *,
    token_env: str = "GENOMES_NOTION_PAT",
    client: NotionBridgeClient | None = None,
) -> list[dict[str, Any]]:
    """Query a data source to exhaustion through the shared bridge."""
    return _complete_pages(
        "queryDataSource",
        "dataSourceId",
        data_source_id,
        token_env=token_env,
        client=client,
    )
