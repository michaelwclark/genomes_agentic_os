"""Minimal Notion API client using stdlib urllib only.

Injectable transport seam (``fetcher`` kwarg) mirrors the pattern in
``source_providers.py`` so tests can pass a fake without network access.

Token safety rules:
- The token is resolved from an environment variable at call time.
- The token value MUST NOT appear in any dict returned by this module,
  in any log line, or in any exception message.
- Callers pass the *env-var name* (e.g. ``"GENOMES_NOTION_PAT"``), never
  the token value itself.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_API_VERSION = "2022-06-28"
_DEFAULT_TOKEN_ENV = "GENOMES_NOTION_PAT"

# ---------------------------------------------------------------------------
# Injectable transport (same shape as source_providers._default_fetcher)
# ---------------------------------------------------------------------------

def _default_fetcher(req: urllib.request.Request) -> Any:
    """Default HTTP transport — wraps urllib.request.urlopen."""
    return urllib.request.urlopen(req, timeout=20)  # noqa: S310


def _json_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    fetcher: Callable[[urllib.request.Request], Any],
) -> Any:
    """Send *method* request to *url*; parse and return JSON body.

    Raises ``RuntimeError`` on transport/API failures. The token value in
    *headers* never appears in raised exceptions.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = fetcher(req)
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "(unreadable)"
        raise RuntimeError(
            f"Notion API {method} {url} returned HTTP {exc.code}: {err_body}"
        ) from None
    raw = response.read() if hasattr(response, "read") else response
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _auth_headers(token: str, notion_version: str = _NOTION_API_VERSION) -> dict[str, str]:
    """Build request headers. The token value is embedded here and must not
    leave this scope as a plain string in any return value."""
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

def resolve_token(token_env: str = _DEFAULT_TOKEN_ENV) -> str | None:
    """Return the token value from *token_env* env var, or None if unset/empty.

    The returned value must be treated as a secret — never store it in dicts,
    manifests, or log strings.
    """
    return os.environ.get(token_env) or None


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def get_bot_workspace(
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Return the ``workspace_name`` for the bot associated with the token.

    Used for live workspace verification. Raises ``RuntimeError`` on failure.
    Token value never appears in the return value.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    data = _json_request("GET", f"{_NOTION_API_BASE}/users/me", _auth_headers(token), None, fetcher)
    workspace_name = (data.get("bot") or {}).get("workspace_name") or data.get("workspace_name")
    if not workspace_name:
        raise RuntimeError("Notion /users/me did not return a workspace_name")
    return str(workspace_name)


def search_child_pages(
    parent_page_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Return child pages (type=child_page) under *parent_page_id*.

    Returns a list of dicts with ``id`` (no dashes), ``id_dashed``, and
    ``title`` keys — no raw API payloads.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_NOTION_API_BASE}/blocks/{parent_page_id}/children?page_size=100"
    data = _json_request("GET", url, _auth_headers(token), None, fetcher)
    results = data.get("results") or []
    pages = []
    for block in results:
        if block.get("type") != "child_page":
            continue
        title = (block.get("child_page") or {}).get("title") or ""
        pages.append({"id": block["id"].replace("-", ""), "id_dashed": block["id"], "title": title})
    return pages


def _page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties") or {}
    for value in properties.values():
        if not isinstance(value, dict) or value.get("type") != "title":
            continue
        title_items = value.get("title") or []
        return "".join(str(item.get("plain_text") or "") for item in title_items if isinstance(item, dict))
    return ""


def search_pages(
    query: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    page_size: int = 25,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Search accessible pages by title/query and return safe summaries."""
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "query": query,
        "filter": {"value": "page", "property": "object"},
        "page_size": max(1, min(page_size, 100)),
    }
    data = _json_request("POST", f"{_NOTION_API_BASE}/search", _auth_headers(token), body, fetcher)
    pages = []
    for page in data.get("results") or []:
        if not isinstance(page, dict) or page.get("object") != "page":
            continue
        title = _page_title(page)
        pages.append(
            {
                "id": str(page.get("id") or "").replace("-", ""),
                "id_dashed": page.get("id"),
                "title": title,
                "url": page.get("url"),
            }
        )
    return pages


def append_block_children(
    block_id: str,
    children: list[dict[str, Any]],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Append children blocks to a page/block in chunks of 100."""
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    for index in range(0, len(children), 100):
        chunk = children[index : index + 100]
        body = {"children": chunk}
        _json_request(
            "PATCH",
            f"{_NOTION_API_BASE}/blocks/{block_id}/children",
            _auth_headers(token),
            body,
            fetcher,
        )


def search_child_databases(
    parent_page_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Return child databases under *parent_page_id*.

    Returns a list of dicts with ``id`` (no dashes), ``id_dashed``, and
    ``title`` keys.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_NOTION_API_BASE}/blocks/{parent_page_id}/children?page_size=100"
    data = _json_request("GET", url, _auth_headers(token), None, fetcher)
    results = data.get("results") or []
    databases = []
    for block in results:
        if block.get("type") != "child_database":
            continue
        title = (block.get("child_database") or {}).get("title") or ""
        databases.append({"id": block["id"].replace("-", ""), "id_dashed": block["id"], "title": title})
    return databases


def create_page(
    parent_page_id: str,
    title: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a child page under *parent_page_id* with *title*.

    Returns the new page id (no dashes).
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
    }
    data = _json_request("POST", f"{_NOTION_API_BASE}/pages", _auth_headers(token), body, fetcher)
    return data["id"].replace("-", "")


def create_database(
    parent_page_id: str,
    title: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a database as a child of *parent_page_id*.

    *properties* is the Notion properties schema dict (name → type spec).
    Returns the new database id (no dashes).
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
        "is_inline": True,
    }
    data = _json_request("POST", f"{_NOTION_API_BASE}/databases", _auth_headers(token), body, fetcher)
    return data["id"].replace("-", "")


def query_database_by_key(
    database_id: str,
    key_value: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str | None:
    """Query *database_id* for a page whose "Key" rich_text equals *key_value*.

    Returns the page id (no dashes) if found, else None.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "filter": {
            "property": "Key",
            "rich_text": {"equals": key_value},
        }
    }
    url = f"{_NOTION_API_BASE}/databases/{database_id}/query"
    data = _json_request("POST", url, _auth_headers(token), body, fetcher)
    results = data.get("results") or []
    if results:
        return results[0]["id"].replace("-", "")
    return None


def query_database_by_rich_text_property(
    database_id: str,
    property_name: str,
    value: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Query *database_id* for pages whose rich-text property equals *value*.

    Returns the sanitized Notion page payloads from the response. Callers use
    this for databases whose idempotency key is not named ``Key``.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "filter": {
            "property": property_name,
            "rich_text": {"equals": value},
        }
    }
    url = f"{_NOTION_API_BASE}/databases/{database_id}/query"
    data = _json_request("POST", url, _auth_headers(token), body, fetcher)
    return list(data.get("results") or [])


def get_database_property_types(
    database_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> dict[str, str]:
    """Return a mapping of *database_id* property name -> Notion property type.

    Lets callers send only properties that actually exist on a database that
    may have been provisioned out-of-band. Raises ``RuntimeError`` on failure.
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_NOTION_API_BASE}/databases/{database_id}"
    data = _json_request("GET", url, _auth_headers(token), None, fetcher)
    properties = data.get("properties") or {}
    return {name: str((spec or {}).get("type") or "") for name, spec in properties.items()}


def create_database_page(
    database_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    children: list[dict[str, Any]] | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a new page in *database_id* with *properties*.

    Returns the new page id (no dashes).
    """
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "parent": {"type": "database_id", "database_id": database_id},
        "properties": properties,
    }
    if children:
        body["children"] = children
    data = _json_request("POST", f"{_NOTION_API_BASE}/pages", _auth_headers(token), body, fetcher)
    return data["id"].replace("-", "")


def query_database(
    database_id: str,
    filter_body: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Query *database_id* with a caller-supplied Notion filter body."""
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"filter": filter_body}
    url = f"{_NOTION_API_BASE}/databases/{database_id}/query"
    data = _json_request("POST", url, _auth_headers(token), body, fetcher)
    return list(data.get("results") or [])


def update_database_page(
    page_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Update properties on an existing database page *page_id*."""
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"properties": properties}
    _json_request("PATCH", f"{_NOTION_API_BASE}/pages/{page_id}", _auth_headers(token), body, fetcher)


def update_database_schema(
    database_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Add or update database property schemas on *database_id*."""
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"properties": properties}
    _json_request("PATCH", f"{_NOTION_API_BASE}/databases/{database_id}", _auth_headers(token), body, fetcher)


def _query_collection(
    endpoint: str,
    body: dict[str, Any],
    token_env: str,
    notion_version: str,
    fetcher: Callable[[urllib.request.Request], Any],
) -> list[dict[str, Any]]:
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    data = _json_request("POST", endpoint, _auth_headers(token, notion_version), body, fetcher)
    return [row for row in data.get("results") or [] if isinstance(row, dict)]


def query_database_pages(
    database_id: str,
    *,
    token_env: str = _DEFAULT_TOKEN_ENV,
    page_size: int = 100,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Query a legacy Notion database and return safe page summaries."""
    body = {"page_size": max(1, min(page_size, 100))}
    rows = _query_collection(
        f"{_NOTION_API_BASE}/databases/{database_id}/query",
        body,
        token_env,
        _NOTION_API_VERSION,
        fetcher,
    )
    return [notion_page_summary(row) for row in rows]


def query_data_source_pages(
    data_source_id: str,
    *,
    token_env: str = _DEFAULT_TOKEN_ENV,
    page_size: int = 100,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Query a Notion data source and return safe page summaries."""
    body = {"page_size": max(1, min(page_size, 100))}
    rows = _query_collection(
        f"{_NOTION_API_BASE}/data_sources/{data_source_id}/query",
        body,
        token_env,
        "2025-09-03",
        fetcher,
    )
    return [notion_page_summary(row) for row in rows]


def plain_property_value(property_value: dict[str, Any]) -> Any:
    """Convert a Notion page property value into a compact scalar."""
    prop_type = property_value.get("type")
    value = property_value.get(prop_type) if prop_type else None
    if prop_type in {"title", "rich_text"} and isinstance(value, list):
        return "".join(str(part.get("plain_text") or "") for part in value if isinstance(part, dict))
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
        return [item.get("name") or item.get("id") for item in value if isinstance(item, dict)]
    if prop_type == "formula" and isinstance(value, dict):
        nested_type = value.get("type")
        if nested_type:
            return plain_property_value({"type": nested_type, nested_type: value.get(nested_type)})
    return None


def notion_page_summary(page: dict[str, Any]) -> dict[str, Any]:
    """Return a safe, trimmed summary for a Notion page/database row."""
    properties = page.get("properties") or {}
    return {
        "id": str(page.get("id") or "").replace("-", ""),
        "id_dashed": page.get("id"),
        "last_edited_time": page.get("last_edited_time"),
        "url": page.get("url"),
        "properties": {
            name: plain_property_value(value)
            for name, value in properties.items()
            if isinstance(value, dict)
        },
    }


# ---------------------------------------------------------------------------
# Property builders — produce Notion property value shapes
# ---------------------------------------------------------------------------

def _title_prop(value: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def _rich_text_prop(value: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def _select_prop(value: str) -> dict[str, Any]:
    return {"select": {"name": value[:100]}}


def _date_prop(iso_string: str) -> dict[str, Any]:
    return {"date": {"start": iso_string}}


def _checkbox_prop(value: bool) -> dict[str, Any]:
    return {"checkbox": value}


def build_record_properties(record: dict[str, Any], updated_at: str) -> dict[str, Any]:
    """Build a Notion properties dict for a runtime tracking record.

    Every database has at minimum: Name (title), Key (rich_text),
    Kind (select), Status (select), Updated (date).
    """
    kind = record.get("kind", "unknown")
    return {
        "Name": _title_prop(record.get("title") or record.get("key") or ""),
        "Key": _rich_text_prop(record.get("record_key") or ""),
        "Kind": _select_prop(kind),
        "Status": _select_prop(record.get("action") or "create-or-update"),
        "Updated": _date_prop(updated_at),
    }


# ---------------------------------------------------------------------------
# Database property schemas (used when creating the 7 runtime databases)
# ---------------------------------------------------------------------------

def _base_db_properties() -> dict[str, Any]:
    """Minimal shared property schema for all runtime tracking databases."""
    return {
        "Name": {"title": {}},
        "Key": {"rich_text": {}},
        "Kind": {"select": {}},
        "Status": {"select": {}},
        "Updated": {"date": {}},
    }


DATABASE_PROPERTY_SCHEMAS: dict[str, dict[str, Any]] = {
    "Integrations": {
        **_base_db_properties(),
        "Provider": {"rich_text": {}},
        "Credential State": {"select": {}},
        "Approval Gate": {"checkbox": {}},
        "Last Health Check": {"date": {}},
    },
    "Execution Targets": {
        **_base_db_properties(),
        "Type": {"select": {}},
        "Owner": {"rich_text": {}},
        "Health Check": {"date": {}},
        "Approval Required For": {"rich_text": {}},
    },
    "Heartbeats": {
        **_base_db_properties(),
        "Cadence": {"rich_text": {}},
        "Enabled": {"checkbox": {}},
        "Integration": {"rich_text": {}},
        "Execution Target": {"rich_text": {}},
        "Last Status": {"select": {}},
        "Last Run": {"date": {}},
        "Next Due": {"date": {}},
    },
    "Schedules": {
        **_base_db_properties(),
        "Cadence": {"rich_text": {}},
        "Timezone": {"rich_text": {}},
        "Command": {"rich_text": {}},
        "Enabled": {"checkbox": {}},
        "Last Queued": {"date": {}},
        "Next Due": {"date": {}},
    },
    "Run Queue": {
        **_base_db_properties(),
        "Approval State": {"select": {}},
        "Due At": {"date": {}},
        "Idempotency Key": {"rich_text": {}},
        "Log Path": {"rich_text": {}},
    },
    "Approvals": {
        **_base_db_properties(),
        "Queue Item": {"rich_text": {}},
        "Approval State": {"select": {}},
        "Required Gate": {"rich_text": {}},
        "Owner": {"rich_text": {}},
        "Decision At": {"date": {}},
    },
    "Runs": {
        **_base_db_properties(),
        "Started At": {"date": {}},
        "Finished At": {"date": {}},
        "Dry Run": {"checkbox": {}},
        "Log Path": {"rich_text": {}},
        "Linked Runtime Object": {"rich_text": {}},
    },
}
