"""Tests for the live Notion adapter for runtime tracking.

All tests use a fake transport — zero network access. The fake records every
request made and returns canned responses.

Coverage:
- No config → local path unchanged + live: false
- Live path → creates cockpit + 7 databases + real ids in manifest
- Second apply with manifest present → zero creates, upserts only
- Live API workspace mismatch → refusal error, nothing created
- Token value absent from manifest, result dict, and exception text
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Sentinel token used across all tests — we assert this value never leaks.
# ---------------------------------------------------------------------------

SENTINEL_TOKEN = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ---------------------------------------------------------------------------
# Fake transport helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class FakeTransport:
    """Records every urllib.request.Request object; returns canned responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any) -> _FakeResponse:
        self.requests.append({"method": req.method, "url": req.full_url, "data": req.data})
        if not self._responses:
            raise AssertionError(f"FakeTransport ran out of canned responses for {req.method} {req.full_url}")
        response = self._responses.pop(0)
        body = json.dumps(response).encode("utf-8")
        return _FakeResponse(body)

    def assert_no_requests(self) -> None:
        assert not self.requests, f"Expected no requests but got: {self.requests}"

    def assert_token_not_leaked(self) -> None:
        for req in self.requests:
            # Check Authorization header — present as str in headers dict
            # urllib.request stores headers internally; we check the raw data
            data_str = (req.get("data") or b"").decode("utf-8", errors="replace")
            assert SENTINEL_TOKEN not in data_str, (
                f"Sentinel token leaked into request body: {data_str[:200]}"
            )
            # URL must not contain token
            assert SENTINEL_TOKEN not in req["url"], f"Sentinel token leaked into URL: {req['url']}"


# ---------------------------------------------------------------------------
# Notion API response fixtures
# ---------------------------------------------------------------------------

def _users_me_response(workspace_name: str = "Genome's Notion") -> dict[str, Any]:
    return {
        "object": "user",
        "type": "bot",
        "bot": {"workspace_name": workspace_name},
    }


def _children_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"object": "list", "results": items}


def _page_response(page_id: str, title: str = "") -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "type": "child_page",
        "child_page": {"title": title},
        "properties": {},
    }


def _database_response(db_id: str, title: str = "") -> dict[str, Any]:
    return {
        "object": "database",
        "id": db_id,
        "title": [{"plain_text": title}],
    }


def _query_response(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"object": "list", "results": results}


def _db_page_response(page_id: str) -> dict[str, Any]:
    return {"object": "page", "id": page_id}


# ---------------------------------------------------------------------------
# Install helpers
# ---------------------------------------------------------------------------

def _installed_root(tmp_path: Path) -> Path:
    """Create a minimal installed root with runtime-registry so plan works."""
    from genomes_agentic_os.cli import main
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    return root


def _set_notion_tracking_config(root: Path, *, parent_page_id: str, token_env: str = "GENOMES_NOTION_PAT") -> None:
    """Write a notion-tracking.yml with a live parent_page_id into the installed root."""
    from genomes_agentic_os.scaffold import shared_factory_path
    config_path = shared_factory_path(root, "00-control-plane", "notion-tracking.yml")
    config = {
        "workspace": "Genome's Notion",
        "parent_page_id": parent_page_id,
        "token_env": token_env,
        "cockpit_page_title": "Runtime Control Plane",
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _notion_tracking_config_path(root: Path) -> Path:
    from genomes_agentic_os.scaffold import shared_factory_path
    return shared_factory_path(root, "00-control-plane", "notion-tracking.yml")


# ---------------------------------------------------------------------------
# Test: no config → local path unchanged, live: false
# ---------------------------------------------------------------------------

def test_no_config_stays_local(tmp_path: Path) -> None:
    """When no notion-tracking.yml is present, apply_runtime_tracking uses local path."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking

    root = _installed_root(tmp_path)
    # Ensure notion-tracking.yml does NOT exist or has empty parent_page_id
    config_path = _notion_tracking_config_path(root)
    if config_path.exists():
        config_path.unlink()

    transport = FakeTransport([])
    result = apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    # No network calls made
    transport.assert_no_requests()

    # live: false in result
    assert result.get("live") is False

    # manifest written
    manifest_path = root / ".notion-runtime-tracking" / "manifest.yml"
    assert manifest_path.is_file()
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest.get("live") is False

    # all database IDs are local synthetic
    for db_name, db_id in manifest["database_ids"].items():
        assert db_id.startswith("local-"), f"Expected local id for {db_name}, got {db_id!r}"
    assert manifest["record_scope"]["run_queue_item_limit"] > 0


def test_no_config_local_path_token_env_unset(tmp_path: Path) -> None:
    """Config with non-empty parent_page_id but no token → local path."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking

    root = _installed_root(tmp_path)
    _set_notion_tracking_config(root, parent_page_id="aabbccdd11223344aabbccdd11223344")

    transport = FakeTransport([])
    # Ensure the token env is absent
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        result = apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    transport.assert_no_requests()
    assert result.get("live") is False


def test_runtime_tracking_plan_bounds_run_queue_projection(tmp_path: Path) -> None:
    """Notion runtime tracking should not upsert unbounded historical queue rows."""
    from genomes_agentic_os.runtime_ops import (
        RUNTIME_TRACKING_RUN_QUEUE_LIMIT,
        build_runtime_tracking_plan,
    )
    from genomes_agentic_os.scaffold import shared_factory_path

    root = _installed_root(tmp_path)
    queue_path = shared_factory_path(root, "00-control-plane", "run-queue.yml")
    items = [
        {
            "id": f"done_{idx:03d}",
            "status": "done",
            "approval_state": "not_required",
            "created_at": f"2026-01-{(idx % 28) + 1:02d}T00:00:00+00:00",
            "ref": f"done-{idx:03d}",
        }
        for idx in range(RUNTIME_TRACKING_RUN_QUEUE_LIMIT + 30)
    ]
    items.extend(
        [
            {
                "id": "queued_current",
                "status": "queued",
                "approval_state": "not_required",
                "created_at": "2026-07-04T20:30:00+00:00",
                "ref": "queued-current",
            },
            {
                "id": "running_current",
                "status": "running",
                "approval_state": "not_required",
                "created_at": "2026-07-04T20:35:00+00:00",
                "ref": "running-current",
            },
        ]
    )
    queue_path.write_text(yaml.safe_dump({"items": items}, sort_keys=False), encoding="utf-8")

    plan = build_runtime_tracking_plan(str(root))
    queue_records = [record for record in plan["records"] if record["kind"] == "run_queue_item"]
    queue_keys = {record["key"] for record in queue_records}

    assert len(queue_records) == RUNTIME_TRACKING_RUN_QUEUE_LIMIT
    assert {"queued_current", "running_current"} <= queue_keys
    assert "done_000" not in queue_keys
    assert plan["record_scope"]["run_queue_total_items"] == len(items)
    assert plan["record_scope"]["run_queue_projected_items"] == RUNTIME_TRACKING_RUN_QUEUE_LIMIT
    assert plan["record_scope"]["run_queue_omitted_items"] == len(items) - RUNTIME_TRACKING_RUN_QUEUE_LIMIT


def test_default_bridge_runtime_tracking_accepts_verified_manifest_bindings(
    tmp_path: Path, monkeypatch
) -> None:
    from genomes_agentic_os import notion_api
    from genomes_agentic_os.runtime_ops import _apply_runtime_tracking_live

    monkeypatch.setattr(notion_api, "get_bot_workspace", lambda *args, **kwargs: "Genome's Notion")
    monkeypatch.setattr(
        notion_api,
        "search_child_pages",
        lambda *args, **kwargs: [{"id": "cockpit", "title": "Runtime Control Plane"}],
    )
    monkeypatch.setattr(
        notion_api,
        "search_child_databases",
        lambda *args, **kwargs: [{"id": "database", "title": "Integrations"}],
    )
    manifest_path = tmp_path / "manifest.yml"

    result = _apply_runtime_tracking_live(
        os_root=tmp_path,
        workspace="Genome's Notion",
        plan={"databases": ["Integrations"], "records": []},
        manifest_path=manifest_path,
        existing_manifest={
            "live": True,
            "workspace": "Genome's Notion",
            "parent_page_id": "parent",
            "cockpit_page_id": "cockpit",
            "database_ids": {"Integrations": "database"},
        },
        parent_page_id="parent",
        token_env="GENOMES_NOTION_PAT",
        cockpit_title="Runtime Control Plane",
        fetcher=notion_api._default_fetcher,
    )

    assert result["database_ids"] == {"Integrations": "database"}
    assert yaml.safe_load(manifest_path.read_text())["cockpit_page_id"] == "cockpit"


def test_default_bridge_runtime_tracking_rejects_unbound_manifest_ids(
    tmp_path: Path, monkeypatch
) -> None:
    from genomes_agentic_os import notion_api
    from genomes_agentic_os.runtime_ops import _apply_runtime_tracking_live

    monkeypatch.setattr(notion_api, "get_bot_workspace", lambda *args, **kwargs: "Genome's Notion")
    monkeypatch.setattr(notion_api, "search_child_pages", lambda *args, **kwargs: [])
    monkeypatch.setattr(notion_api, "search_child_databases", lambda *args, **kwargs: [])
    common = {
        "os_root": tmp_path,
        "workspace": "Genome's Notion",
        "plan": {"databases": ["Integrations"], "records": []},
        "manifest_path": tmp_path / "manifest.yml",
        "parent_page_id": "parent",
        "token_env": "GENOMES_NOTION_PAT",
        "cockpit_title": "Runtime Control Plane",
        "fetcher": notion_api._default_fetcher,
    }

    with pytest.raises(ValueError, match="not the expected child"):
        _apply_runtime_tracking_live(
            **common,
            existing_manifest={
                "live": True,
                "workspace": "Genome's Notion",
                "parent_page_id": "parent",
                "cockpit_page_id": "cockpit",
                "database_ids": {},
            },
        )

    monkeypatch.setattr(
        notion_api,
        "search_child_pages",
        lambda *args, **kwargs: [{"id": "cockpit", "title": "Runtime Control Plane"}],
    )
    monkeypatch.setattr(
        notion_api,
        "search_child_databases",
        lambda *args, **kwargs: [{"id": "live-database", "title": "Integrations"}],
    )
    with pytest.raises(ValueError, match="outside the approved cockpit"):
        _apply_runtime_tracking_live(
            **common,
            existing_manifest={
                "live": True,
                "workspace": "Genome's Notion",
                "parent_page_id": "parent",
                "cockpit_page_id": "cockpit",
                "database_ids": {"Integrations": "manifest-database"},
            },
        )


def test_local_manifest_transitions_to_live_without_reusing_synthetic_ids(
    tmp_path: Path, monkeypatch
) -> None:
    from genomes_agentic_os import notion_api
    from genomes_agentic_os.runtime_ops import _apply_runtime_tracking_live

    monkeypatch.setattr(
        notion_api, "get_bot_workspace", lambda *args, **kwargs: "Genome's Notion"
    )
    monkeypatch.setattr(
        notion_api,
        "search_child_pages",
        lambda *args, **kwargs: [{"id": "live-cockpit", "title": "Runtime Control Plane"}],
    )
    monkeypatch.setattr(
        notion_api,
        "search_child_databases",
        lambda *args, **kwargs: [{"id": "live-database", "title": "Integrations"}],
    )

    result = _apply_runtime_tracking_live(
        os_root=tmp_path,
        workspace="Genome's Notion",
        plan={"databases": ["Integrations"], "records": []},
        manifest_path=tmp_path / "manifest.yml",
        existing_manifest={
            "live": False,
            "workspace": "Genome's Notion",
            "cockpit_page_id": "local-cockpit",
            "database_ids": {"Integrations": "local-database"},
        },
        parent_page_id="parent",
        token_env="GENOMES_NOTION_PAT",
        cockpit_title="Runtime Control Plane",
        fetcher=notion_api._default_fetcher,
    )

    assert result["cockpit_page_id"] == "live-cockpit"
    assert result["database_ids"] == {"Integrations": "live-database"}
    assert result["databases_reused"] == 1


# ---------------------------------------------------------------------------
# Test: live path creates cockpit + 7 databases + real ids
# ---------------------------------------------------------------------------

PARENT_PAGE_ID = "aabbccdd11223344aabbccdd11223344"
COCKPIT_PAGE_ID = "cccccccc11111111cccccccc11111111"

DB_NAMES = ["Integrations", "Execution Targets", "Heartbeats", "Schedules", "Run Queue", "Approvals", "Runs"]
DB_IDS = {name: f"db{''.join(c for c in name if c.isalpha())[:8].lower()}1111111111111111111111" for name in DB_NAMES}


def _build_live_responses(
    *,
    child_pages: list[dict[str, Any]] | None = None,
    child_dbs: list[dict[str, Any]] | None = None,
    create_cockpit: bool = True,
    db_query_existing: dict[str, str | None] | None = None,
    records_count: int = 0,
) -> list[dict[str, Any]]:
    """Build the ordered canned response list for a full live apply.

    Order matches the sequence of API calls made by _apply_runtime_tracking_live.
    """
    responses: list[dict[str, Any]] = []

    # 1. /users/me
    responses.append(_users_me_response())

    # 2. GET children of parent_page_id (to find cockpit page)
    if child_pages is not None:
        responses.append(_children_response(child_pages))
    else:
        responses.append(_children_response([]))

    # 3. POST /pages (create cockpit) — only if cockpit not found
    if create_cockpit:
        responses.append(_page_response(COCKPIT_PAGE_ID, "Runtime Control Plane"))

    # 4. GET children of cockpit_id (to find existing databases)
    if child_dbs is not None:
        responses.append(_children_response(child_dbs))
    else:
        responses.append(_children_response([]))

    # 5–11. POST /databases for each of 7 databases
    for db_name in DB_NAMES:
        if child_dbs and any(db["child_database"]["title"] == db_name for db in child_dbs):
            continue  # reused — no create call
        responses.append(_database_response(DB_IDS[db_name], db_name))

    # 6. For each record: query + create/update
    db_query_existing = db_query_existing or {}
    for _ in range(records_count):
        existing_id = db_query_existing.get(str(_))
        responses.append(_query_response([{"id": existing_id}] if existing_id else []))
        if existing_id:
            responses.append({"object": "page", "id": existing_id})  # PATCH response
        else:
            new_id = f"newpage{'0' * 24}{_}"[:32]
            responses.append(_db_page_response(new_id))

    return responses


def test_live_path_creates_cockpit_and_7_databases(tmp_path: Path) -> None:
    """Full live path: creates cockpit page + 7 databases + real ids in manifest."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking

    root = _installed_root(tmp_path)
    _set_notion_tracking_config(root, parent_page_id=PARENT_PAGE_ID)

    # Build responses — no existing children, will create everything
    # We need to account for records from the plan; get the plan first
    from genomes_agentic_os.runtime_ops import build_runtime_tracking_plan
    plan = build_runtime_tracking_plan(str(root))
    record_count = len(plan["records"])

    # Build responses: users/me + parent children (empty) + create cockpit +
    # cockpit children (empty) + 7 db creates + record_count * (query + create)
    responses: list[dict[str, Any]] = [
        _users_me_response(),
        _children_response([]),                              # parent children
        _page_response(COCKPIT_PAGE_ID, "Runtime Control Plane"),  # create cockpit
        _children_response([]),                              # cockpit children (no DBs)
    ]
    # 7 database creates
    for db_name in DB_NAMES:
        responses.append(_database_response(DB_IDS[db_name], db_name))

    # records: query (empty) + create for each
    for i in range(record_count):
        responses.append(_query_response([]))  # not found
        new_page_id = f"newpage{i:024d}"[:32]
        responses.append(_db_page_response(new_page_id))

    transport = FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        result = apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    assert result.get("live") is True
    assert result.get("cockpit_created") is True
    assert result.get("databases_created") == 7
    assert result.get("databases_reused") == 0

    # Manifest written with real IDs
    manifest_path = root / ".notion-runtime-tracking" / "manifest.yml"
    assert manifest_path.is_file()
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest.get("live") is True
    assert manifest.get("cockpit_page_id") == COCKPIT_PAGE_ID

    for db_name in DB_NAMES:
        assert manifest["database_ids"][db_name] == DB_IDS[db_name], (
            f"Database {db_name} id mismatch"
        )

    # Token must not appear anywhere in manifest
    manifest_text = manifest_path.read_text()
    assert SENTINEL_TOKEN not in manifest_text, "Sentinel token leaked into manifest file"

    # Token must not appear in result dict (serialized)
    result_text = yaml.safe_dump(result)
    assert SENTINEL_TOKEN not in result_text, "Sentinel token leaked into result dict"

    # Token must not appear in any request data or URL
    transport.assert_token_not_leaked()


# ---------------------------------------------------------------------------
# Test: second apply → zero creates, upserts only
# ---------------------------------------------------------------------------

def test_second_apply_is_idempotent(tmp_path: Path) -> None:
    """Re-apply with manifest present → zero new databases/pages, upserts only."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking, build_runtime_tracking_plan

    root = _installed_root(tmp_path)
    _set_notion_tracking_config(root, parent_page_id=PARENT_PAGE_ID)

    plan = build_runtime_tracking_plan(str(root))
    record_count = len(plan["records"])

    # --- First apply: write a manifest with real database IDs ---
    # Pre-populate manifest so the second apply sees existing IDs
    manifest_path = root / ".notion-runtime-tracking" / "manifest.yml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump({
            "live": True,
            "workspace": "Genome's Notion",
            "parent_page_id": PARENT_PAGE_ID,
            "cockpit_page_id": COCKPIT_PAGE_ID,
            "updated_at": "2026-01-01T00:00:00+00:00",
            "databases": DB_NAMES,
            "database_ids": DB_IDS,
            "records": [],
        }, sort_keys=False),
        encoding="utf-8",
    )

    # Second apply responses: users/me + parent children (cockpit present) +
    # cockpit children (all 7 DBs present) + record_count * (query existing + patch)
    cockpit_block = {
        "id": COCKPIT_PAGE_ID,
        "type": "child_page",
        "child_page": {"title": "Runtime Control Plane"},
    }
    db_blocks = [
        {
            "id": DB_IDS[name],
            "type": "child_database",
            "child_database": {"title": name},
        }
        for name in DB_NAMES
    ]

    # The manifest already has cockpit_page_id so search_child_pages is skipped.
    # Call order: users/me → search_child_databases(cockpit_id) →
    #   (no db creates, all reused from manifest) →
    #   for each record: query_database_by_key → update_database_page (PATCH)
    responses: list[dict[str, Any]] = [
        _users_me_response(),
        # No search_child_pages (cockpit_page_id already in manifest)
        _children_response(db_blocks),  # search_child_databases(cockpit_id)
        # No create databases (all reused from existing_manifest database_ids)
    ]
    EXISTING_PAGE_ID = "existingpage" + "0" * 20
    for _ in range(record_count):
        responses.append(_query_response([{"id": EXISTING_PAGE_ID}]))  # found
        # update_database_page does PATCH and ignores the response body
        responses.append({"object": "page", "id": EXISTING_PAGE_ID})   # PATCH response

    transport = FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        result = apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    assert result.get("live") is True
    assert result.get("cockpit_created") is False
    assert result.get("databases_created") == 0
    assert result.get("databases_reused") == 7
    assert result.get("records_created") == 0
    assert result.get("records_updated") == record_count

    transport.assert_token_not_leaked()


# ---------------------------------------------------------------------------
# Test: workspace mismatch → refusal, nothing created
# ---------------------------------------------------------------------------

def test_live_api_workspace_mismatch_refuses(tmp_path: Path) -> None:
    """If /users/me workspace_name differs from expected, refuse and create nothing."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking

    root = _installed_root(tmp_path)
    _set_notion_tracking_config(root, parent_page_id=PARENT_PAGE_ID)

    # /users/me returns wrong workspace
    responses = [_users_me_response(workspace_name="Wrong Workspace")]
    transport = FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        with pytest.raises((ValueError, RuntimeError)) as exc_info:
            apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    error_message = str(exc_info.value)
    # Must mention the mismatch
    assert "workspace" in error_message.lower() or "mismatch" in error_message.lower()
    # Token must NOT appear in error message
    assert SENTINEL_TOKEN not in error_message, "Sentinel token leaked into exception message"

    # No manifest written (or pre-existing manifest unchanged)
    manifest_path = root / ".notion-runtime-tracking" / "manifest.yml"
    # If it was written, it should not have live: true with a real cockpit
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text())
        assert manifest.get("live") is not True or manifest.get("cockpit_page_id") is None, (
            "Manifest should not record a live cockpit after workspace mismatch refusal"
        )

    # Only one request made (users/me), nothing else
    assert len(transport.requests) == 1, (
        f"Expected only /users/me request, got {len(transport.requests)} requests"
    )


# ---------------------------------------------------------------------------
# Test: token value absent from manifest, result, exception text
# ---------------------------------------------------------------------------

def test_token_never_leaks(tmp_path: Path) -> None:
    """Token value must not appear in manifest file, result dict, or exception text."""
    from genomes_agentic_os.runtime_ops import apply_runtime_tracking, build_runtime_tracking_plan

    root = _installed_root(tmp_path)
    _set_notion_tracking_config(root, parent_page_id=PARENT_PAGE_ID)

    plan = build_runtime_tracking_plan(str(root))
    record_count = len(plan["records"])

    responses: list[dict[str, Any]] = [
        _users_me_response(),
        _children_response([]),
        _page_response(COCKPIT_PAGE_ID, "Runtime Control Plane"),
        _children_response([]),
    ]
    for db_name in DB_NAMES:
        responses.append(_database_response(DB_IDS[db_name], db_name))
    for i in range(record_count):
        responses.append(_query_response([]))
        new_page_id = f"tokenleak{i:023d}"[:32]
        responses.append(_db_page_response(new_page_id))

    transport = FakeTransport(responses)

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        result = apply_runtime_tracking(str(root), verified_workspace="Genome's Notion", fetcher=transport)

    # Manifest must not contain token
    manifest_path = root / ".notion-runtime-tracking" / "manifest.yml"
    manifest_text = manifest_path.read_text()
    assert SENTINEL_TOKEN not in manifest_text, "Token leaked into manifest file"

    # Result dict must not contain token (check via YAML serialization)
    result_yaml = yaml.safe_dump(result)
    assert SENTINEL_TOKEN not in result_yaml, "Token leaked into result dict"

    # Request data must not contain token value in body
    transport.assert_token_not_leaked()


# ---------------------------------------------------------------------------
# Test: scaffold installs notion-tracking.yml into a fresh root
# ---------------------------------------------------------------------------

def test_scaffold_installs_notion_tracking_config(tmp_path: Path) -> None:
    """Fresh init installs notion-tracking.yml into 00-control-plane."""
    from genomes_agentic_os.cli import main
    from genomes_agentic_os.scaffold import shared_factory_path

    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    config_path = shared_factory_path(root, "00-control-plane", "notion-tracking.yml")
    assert config_path.is_file(), f"notion-tracking.yml not installed at {config_path}"

    config = yaml.safe_load(config_path.read_text())
    # parent_page_id must be empty by default (local mode out of the box)
    assert not (config.get("parent_page_id") or "").strip(), (
        "parent_page_id must be empty in fresh install (local mode default)"
    )
    # Must have the expected keys
    assert "workspace" in config
    assert "token_env" in config
    assert "cockpit_page_title" in config


def test_scaffold_does_not_overwrite_existing_notion_tracking_config(tmp_path: Path) -> None:
    """Re-running init does not overwrite an operator-edited notion-tracking.yml."""
    from genomes_agentic_os.cli import main
    from genomes_agentic_os.scaffold import shared_factory_path

    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    config_path = shared_factory_path(root, "00-control-plane", "notion-tracking.yml")
    # Operator edits the config
    original_content = config_path.read_text()
    edited_content = original_content + "\n# operator-edited\n"
    config_path.write_text(edited_content, encoding="utf-8")

    # Re-run init
    assert main(["init", "--target", str(root)]) == 0

    # Config must not have been overwritten
    assert config_path.read_text() == edited_content, "init overwrote operator-edited notion-tracking.yml"


# ---------------------------------------------------------------------------
# Test: notion_api module — get_bot_workspace with fake transport
# ---------------------------------------------------------------------------

def test_notion_api_get_bot_workspace(tmp_path: Path) -> None:
    """get_bot_workspace extracts workspace_name from /users/me response."""
    from genomes_agentic_os.notion_api import get_bot_workspace

    transport = FakeTransport([_users_me_response("Genome's Notion")])

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        name = get_bot_workspace("GENOMES_NOTION_PAT", fetcher=transport)

    assert name == "Genome's Notion"
    assert len(transport.requests) == 1
    # Token must not appear in request body or URL
    transport.assert_token_not_leaked()


def test_notion_api_get_bot_workspace_missing_token() -> None:
    """get_bot_workspace raises RuntimeError when token env var is absent."""
    from genomes_agentic_os.notion_api import get_bot_workspace

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GENOMES_NOTION_PAT", None)
        with pytest.raises(RuntimeError, match="not set"):
            get_bot_workspace("GENOMES_NOTION_PAT")
