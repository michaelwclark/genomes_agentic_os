"""Compatibility facade for the shared, guarded Notion bridge.

Default/live calls cross the versioned TypeScript bridge.  The injectable
``fetcher`` seam remains only for deterministic legacy fixtures: it targets a
synthetic host, carries no credential headers, and cannot perform live I/O.

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

from .notion_bridge import (
    DEFAULT_WORKSPACE,
    NotionBridgeClient,
    NotionBridgeError,
    client_from_environment,
)

_FIXTURE_API_BASE = "https://notion-fixture.invalid/v1"
_NOTION_API_VERSION = "2022-06-28"
_DEFAULT_TOKEN_ENV = "GENOMES_NOTION_PAT"

# ---------------------------------------------------------------------------
# Injectable transport (same shape as source_providers._default_fetcher)
# ---------------------------------------------------------------------------

def _default_fetcher(req: urllib.request.Request) -> Any:
    """Live direct transport is disabled; default calls must use the bridge."""
    del req
    raise RuntimeError("direct Notion transport is disabled; use the shared bridge")


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
    """Return credential-free headers for the injected fixture seam."""
    del token, notion_version
    return {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

def resolve_token(token_env: str = _DEFAULT_TOKEN_ENV) -> str | None:
    """Return the token value from *token_env* env var, or None if unset/empty.

    The returned value must be treated as a secret — never store it in dicts,
    manifests, or log strings.
    """
    return os.environ.get(token_env) or None


def _bridge_client(token_env: str) -> NotionBridgeClient:
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    return client_from_environment(token=token)


def _bridge_identity(parent_page_id: str) -> dict[str, str]:
    return {
        "workspaceName": os.environ.get("GENOMES_NOTION_WORKSPACE", "").strip()
        or DEFAULT_WORKSPACE,
        "parentPageId": parent_page_id,
    }


def _mutation_identity(
    client: NotionBridgeClient, approved_parent_page_id: str | None
) -> dict[str, str]:
    """Resolve a separately approved mutation root; never infer it from a target."""
    if approved_parent_page_id:
        identity = dict(client.identity or {})
        identity.update(_bridge_identity(approved_parent_page_id))
        return identity
    if client.identity is not None:
        return dict(client.identity)
    raise RuntimeError(
        "GENOMES_NOTION_PARENT_PAGE_ID or approved_parent_page_id is required "
        "for Notion mutations"
    )


def _same_notion_id(left: Any, right: Any) -> bool:
    return str(left or "").replace("-", "") == str(right or "").replace("-", "")


def _bridge_collection(
    result: Any, *, require_complete: bool = True
) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or (
        require_complete and result.get("complete") is not True
    ):
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Notion bridge returned an incomplete collection"
        )
    values = result.get("values")
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Notion bridge returned invalid collection values"
        )
    return values


def _legacy_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = str(block.get("type") or "")
    return {
        "object": "block",
        "id": block.get("id"),
        "type": block_type,
        block_type: block.get("value") or {},
        "has_children": block.get("hasChildren") is True,
        "in_trash": block.get("inTrash") is True,
        "parent": block.get("parent") or {},
        "last_edited_time": block.get("updatedAt"),
    }


def _reconciliation_marker(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        runs: list[str] = []
        current: list[str] = []
        for character in value.strip():
            if character.isalnum() or character in " ._:/-":
                current.append(character)
            elif current:
                runs.append("".join(current).strip())
                current = []
        if current:
            runs.append("".join(current).strip())
        stable = [run for run in runs if len(run) >= 3]
        return max(stable, key=len, default="")
    if isinstance(value, dict):
        for key in ("content", "plain_text", "name"):
            marker = _reconciliation_marker(value.get(key))
            if marker:
                return marker
        for key, child in value.items():
            if key in {"type", "object", "href"}:
                continue
            marker = _reconciliation_marker(child)
            if marker:
                return marker
    if isinstance(value, list):
        for child in value:
            marker = _reconciliation_marker(child)
            if marker:
                return marker
    return ""


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def get_bot_workspace(
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Return the ``workspace_name`` for the bot associated with the token.

    Used for live workspace verification. Raises ``RuntimeError`` on failure.
    Token value never appears in the return value.
    """
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _bridge_identity(parent_page_id) if parent_page_id else client.identity
        if identity is None:
            raise RuntimeError("GENOMES_NOTION_PARENT_PAGE_ID is required for workspace verification")
        result = client.request("preflightIdentity", identity)
        if not isinstance(result, dict) or not result.get("workspaceName"):
            raise RuntimeError("Notion bridge did not return a workspace name")
        return str(result["workspaceName"])
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    data = _json_request("GET", f"{_FIXTURE_API_BASE}/users/me", _auth_headers(token), None, fetcher)
    workspace_name = (data.get("bot") or {}).get("workspace_name") or data.get("workspace_name")
    if not workspace_name:
        raise RuntimeError("Notion /users/me did not return a workspace_name")
    return str(workspace_name)


def get_database_parent_page_id(
    database_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Return the page parent used to anchor guarded database operations."""
    if fetcher is _default_fetcher:
        database = _bridge_client(token_env).request(
            "getDatabase", {"databaseId": database_id}
        )
    else:
        token = resolve_token(token_env)
        if not token:
            raise RuntimeError(f"Notion token env var {token_env!r} is not set")
        database = _json_request(
            "GET",
            f"{_FIXTURE_API_BASE}/databases/{database_id}",
            _auth_headers(token),
            None,
            fetcher,
        )
    if not isinstance(database, dict):
        raise RuntimeError("Notion database was not found")
    parent = database.get("parent") or {}
    parent_page_id = parent.get("id") or parent.get("page_id")
    if parent.get("type") != "page_id" or not parent_page_id:
        raise RuntimeError("Notion database is not under a page parent")
    return str(parent_page_id)


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
    if fetcher is _default_fetcher:
        blocks = _bridge_collection(
            _bridge_client(token_env).request(
                "listBlockChildren", {"blockId": parent_page_id}
            )
        )
        return [
            {
                "id": str(block["id"]).replace("-", ""),
                "id_dashed": block["id"],
                "title": str((block.get("value") or {}).get("title") or ""),
            }
            for block in blocks
            if block.get("type") == "child_page"
        ]
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_FIXTURE_API_BASE}/blocks/{parent_page_id}/children?page_size=100"
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
    if fetcher is _default_fetcher:
        result = _bridge_collection(
            _bridge_client(token_env).request(
                "search",
                {
                    "query": query,
                    "filter": {"value": "page", "property": "object"},
                    "limit": max(1, min(page_size, 100)),
                },
            ),
            require_complete=False,
        )
        return [
            {
                "id": str(page.get("id") or "").replace("-", ""),
                "id_dashed": page.get("id"),
                "title": _page_title(page),
                "url": page.get("url"),
            }
            for page in result
            if page.get("object") == "page"
        ]
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "query": query,
        "filter": {"value": "page", "property": "object"},
        "page_size": max(1, min(page_size, 100)),
    }
    data = _json_request("POST", f"{_FIXTURE_API_BASE}/search", _auth_headers(token), body, fetcher)
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
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Append children blocks to a page/block in chunks of 100."""
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        client.request(
            "appendBlockChildren",
            {"blockId": block_id, "children": children},
            mutation=True,
            identity=_mutation_identity(client, approved_parent_page_id),
        )
        return
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    for index in range(0, len(children), 100):
        chunk = children[index : index + 100]
        body = {"children": chunk}
        _json_request(
            "PATCH",
            f"{_FIXTURE_API_BASE}/blocks/{block_id}/children",
            _auth_headers(token),
            body,
            fetcher,
        )


def list_block_children(
    block_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Return all first-level children for *block_id* with pagination."""
    if fetcher is _default_fetcher:
        return [
            _legacy_block(block)
            for block in _bridge_collection(
                _bridge_client(token_env).request(
                    "listBlockChildren", {"blockId": block_id}
                )
            )
        ]
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    headers = _auth_headers(token)
    cursor: str | None = None
    results: list[dict[str, Any]] = []
    while True:
        suffix = f"&start_cursor={cursor}" if cursor else ""
        data = _json_request(
            "GET",
            f"{_FIXTURE_API_BASE}/blocks/{block_id}/children?page_size=100{suffix}",
            headers,
            None,
            fetcher,
        )
        results.extend(item for item in data.get("results") or [] if isinstance(item, dict))
        if not data.get("has_more") or not data.get("next_cursor"):
            return results
        cursor = str(data["next_cursor"])


def archive_block(
    block_id: str,
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Archive one block without exposing token or payload data."""
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        client.request(
            "trashBlock",
            {"blockId": block_id},
            mutation=True,
            identity=_mutation_identity(client, approved_parent_page_id),
        )
        return
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    _json_request(
        "DELETE",
        f"{_FIXTURE_API_BASE}/blocks/{block_id}",
        _auth_headers(token),
        None,
        fetcher,
    )


def replace_block_children(
    block_id: str,
    children: list[dict[str, Any]],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Replace a page's first-level content while preserving child pages/databases."""
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _mutation_identity(client, approved_parent_page_id)
        existing = [
            _legacy_block(block)
            for block in _bridge_collection(
                client.request("listBlockChildren", {"blockId": block_id})
            )
        ]
        for child in existing:
            if child.get("type") in {"child_page", "child_database"}:
                continue
            client.request(
                "trashBlock",
                {"blockId": str(child["id"])},
                mutation=True,
                identity=identity,
            )
        client.request(
            "appendBlockChildren",
            {"blockId": block_id, "children": children},
            mutation=True,
            identity=identity,
        )
        return
    existing = list_block_children(block_id, token_env, fetcher=fetcher)
    for child in existing:
        if child.get("type") in {"child_page", "child_database"}:
            continue
        archive_block(
            str(child["id"]),
            token_env,
            approved_parent_page_id=approved_parent_page_id,
            fetcher=fetcher,
        )
    append_block_children(
        block_id,
        children,
        token_env,
        approved_parent_page_id=approved_parent_page_id,
        fetcher=fetcher,
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
    if fetcher is _default_fetcher:
        blocks = _bridge_collection(
            _bridge_client(token_env).request(
                "listBlockChildren", {"blockId": parent_page_id}
            )
        )
        return [
            {
                "id": str(block["id"]).replace("-", ""),
                "id_dashed": block["id"],
                "title": str((block.get("value") or {}).get("title") or ""),
            }
            for block in blocks
            if block.get("type") == "child_database"
        ]
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_FIXTURE_API_BASE}/blocks/{parent_page_id}/children?page_size=100"
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
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a child page under *parent_page_id* with *title*.

    Returns the new page id (no dashes).
    """
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _mutation_identity(client, approved_parent_page_id)
        if not _same_notion_id(parent_page_id, identity["parentPageId"]):
            raise RuntimeError("Notion page parent differs from the approved mutation root")
        marker = _reconciliation_marker(title)
        if not marker:
            raise RuntimeError("Notion page title requires a JSON-stable reconciliation marker")
        result = client.request(
            "createPage",
            {
                "input": {
                    "parent": {"type": "page_id", "id": parent_page_id},
                    "properties": {
                        "title": {
                            "title": [
                                {"type": "text", "text": {"content": title}}
                            ]
                        }
                    },
                    "reconciliation": {
                        "parentPageId": identity["parentPageId"],
                        "marker": marker,
                    },
                }
            },
            mutation=True,
            identity=identity,
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError("Notion bridge did not return a created page ID")
        return str(result["id"]).replace("-", "")
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
    data = _json_request("POST", f"{_FIXTURE_API_BASE}/pages", _auth_headers(token), body, fetcher)
    return data["id"].replace("-", "")


def create_database(
    parent_page_id: str,
    title: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a database as a child of *parent_page_id*.

    *properties* is the Notion properties schema dict (name → type spec).
    Returns the new database id (no dashes).
    """
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _mutation_identity(client, approved_parent_page_id)
        if not _same_notion_id(parent_page_id, identity["parentPageId"]):
            raise RuntimeError(
                "Notion database parent differs from the approved mutation root"
            )
        title_payload = [{"type": "text", "text": {"content": title}}]
        marker = _reconciliation_marker(title)
        if not marker:
            raise RuntimeError(
                "Notion database title requires a JSON-stable reconciliation marker"
            )
        result = client.request(
            "createDatabase",
            {
                "input": {
                    "parentPageId": parent_page_id,
                    "title": title_payload,
                    "initialDataSource": {"properties": properties},
                    "isInline": True,
                    "reconciliation": {
                        "parentPageId": identity["parentPageId"],
                        "marker": marker,
                    },
                }
            },
            mutation=True,
            identity=identity,
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError("Notion bridge did not return a created database ID")
        return str(result["id"]).replace("-", "")
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
        "is_inline": True,
    }
    data = _json_request("POST", f"{_FIXTURE_API_BASE}/databases", _auth_headers(token), body, fetcher)
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
    if fetcher is _default_fetcher:
        rows = _bridge_collection(
            _bridge_client(token_env).request(
                "queryDatabase",
                {
                    "databaseId": database_id,
                    "filter": {
                        "property": "Key",
                        "rich_text": {"equals": key_value},
                    },
                },
            )
        )
        return str(rows[0]["id"]).replace("-", "") if rows else None
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "filter": {
            "property": "Key",
            "rich_text": {"equals": key_value},
        }
    }
    url = f"{_FIXTURE_API_BASE}/databases/{database_id}/query"
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
    if fetcher is _default_fetcher:
        return _bridge_collection(
            _bridge_client(token_env).request(
                "queryDatabase",
                {
                    "databaseId": database_id,
                    "filter": {
                        "property": property_name,
                        "rich_text": {"equals": value},
                    },
                },
            )
        )
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "filter": {
            "property": property_name,
            "rich_text": {"equals": value},
        }
    }
    url = f"{_FIXTURE_API_BASE}/databases/{database_id}/query"
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
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        database = client.request("getDatabase", {"databaseId": database_id})
        if not isinstance(database, dict):
            raise RuntimeError("Notion database was not found")
        properties: dict[str, str] = {}
        for data_source_id in database.get("dataSourceIds") or []:
            source = client.request(
                "getDataSource", {"dataSourceId": str(data_source_id)}
            )
            if not isinstance(source, dict):
                continue
            for name, spec in (source.get("properties") or {}).items():
                if isinstance(spec, dict):
                    properties[str(name)] = str(spec.get("type") or "")
        return properties
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    url = f"{_FIXTURE_API_BASE}/databases/{database_id}"
    data = _json_request("GET", url, _auth_headers(token), None, fetcher)
    properties = data.get("properties") or {}
    return {name: str((spec or {}).get("type") or "") for name, spec in properties.items()}


def create_database_page(
    database_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    children: list[dict[str, Any]] | None = None,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> str:
    """Create a new page in *database_id* with *properties*.

    Returns the new page id (no dashes).
    """
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _mutation_identity(client, approved_parent_page_id)
        database = client.request("getDatabase", {"databaseId": database_id})
        if not isinstance(database, dict):
            raise RuntimeError("Notion database was not found")
        parent = database.get("parent") or {}
        if parent.get("type") != "page_id" or not parent.get("id"):
            raise RuntimeError("Notion database is not under a page parent")
        if not _same_notion_id(parent["id"], identity["parentPageId"]):
            raise RuntimeError(
                "Notion database is outside the approved mutation root"
            )
        marker = _reconciliation_marker(properties)
        if not marker:
            raise RuntimeError("Notion database page requires a reconciliation marker")
        result = client.request(
            "createPage",
            {
                "input": {
                    "parent": {"type": "database_id", "id": database_id},
                    "properties": properties,
                    **({"children": children} if children else {}),
                    "reconciliation": {
                        "parentPageId": identity["parentPageId"],
                        "marker": marker,
                    },
                }
            },
            mutation=True,
            identity=identity,
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError("Notion bridge did not return a created database page ID")
        return str(result["id"]).replace("-", "")
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {
        "parent": {"type": "database_id", "database_id": database_id},
        "properties": properties,
    }
    if children:
        body["children"] = children
    data = _json_request("POST", f"{_FIXTURE_API_BASE}/pages", _auth_headers(token), body, fetcher)
    return data["id"].replace("-", "")


def query_database(
    database_id: str,
    filter_body: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Query *database_id* with a caller-supplied Notion filter body."""
    if fetcher is _default_fetcher:
        return _bridge_collection(
            _bridge_client(token_env).request(
                "queryDatabase",
                {"databaseId": database_id, "filter": filter_body},
            )
        )
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"filter": filter_body}
    url = f"{_FIXTURE_API_BASE}/databases/{database_id}/query"
    data = _json_request("POST", url, _auth_headers(token), body, fetcher)
    return list(data.get("results") or [])


def update_database_page(
    page_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Update properties on an existing database page *page_id*."""
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        client.request(
            "updatePage",
            {"pageId": page_id, "input": {"properties": properties}},
            mutation=True,
            identity=_mutation_identity(client, approved_parent_page_id),
        )
        return
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"properties": properties}
    _json_request("PATCH", f"{_FIXTURE_API_BASE}/pages/{page_id}", _auth_headers(token), body, fetcher)


def update_database_schema(
    database_id: str,
    properties: dict[str, Any],
    token_env: str = _DEFAULT_TOKEN_ENV,
    *,
    approved_parent_page_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> None:
    """Add or update database property schemas on *database_id*."""
    if fetcher is _default_fetcher:
        client = _bridge_client(token_env)
        identity = _mutation_identity(client, approved_parent_page_id)
        database = client.request("getDatabase", {"databaseId": database_id})
        if not isinstance(database, dict):
            raise RuntimeError("Notion database was not found")
        source_ids = database.get("dataSourceIds") or []
        if len(source_ids) != 1:
            raise RuntimeError(
                "Notion database schema update requires exactly one data source"
            )
        parent = database.get("parent") or {}
        if parent.get("type") != "page_id" or not parent.get("id"):
            raise RuntimeError("Notion database is not under a page parent")
        client.request(
            "updateDataSource",
            {
                "dataSourceId": str(source_ids[0]),
                "input": {"properties": properties},
            },
            mutation=True,
            identity=identity,
        )
        return
    token = resolve_token(token_env)
    if not token:
        raise RuntimeError(f"Notion token env var {token_env!r} is not set")
    body: dict[str, Any] = {"properties": properties}
    _json_request("PATCH", f"{_FIXTURE_API_BASE}/databases/{database_id}", _auth_headers(token), body, fetcher)


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
    if fetcher is _default_fetcher:
        rows = _bridge_collection(
            _bridge_client(token_env).request(
                "queryDatabase", {"databaseId": database_id}
            )
        )
        return [notion_page_summary(row) for row in rows]
    body = {"page_size": max(1, min(page_size, 100))}
    rows = _query_collection(
        f"{_FIXTURE_API_BASE}/databases/{database_id}/query",
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
    if fetcher is _default_fetcher:
        rows = _bridge_collection(
            _bridge_client(token_env).request(
                "queryDataSource", {"dataSourceId": data_source_id}
            )
        )
        return [notion_page_summary(row) for row in rows]
    body = {"page_size": max(1, min(page_size, 100))}
    rows = _query_collection(
        f"{_FIXTURE_API_BASE}/data_sources/{data_source_id}/query",
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
        "last_edited_time": page.get("last_edited_time") or page.get("updatedAt"),
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
