from __future__ import annotations

import importlib.machinery
import importlib.util
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

_BIN_PATH = Path(__file__).resolve().parents[1] / "harness" / "bin" / "agentic-os-notion-migrate"


def _load_module():
    loader = importlib.machinery.SourceFileLoader("notion_migrate", str(_BIN_PATH))
    spec = importlib.util.spec_from_loader("notion_migrate", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)

ORG = {
    "root_policy": {"allowed_root_slugs": ["os_home", "people_db"]},
    "tree": [
        {"slug": "os_home", "parent": None},
        {"slug": "domain_los", "parent": "os_home"},
        {"slug": "los_prs", "parent": "domain_los"},
    ],
    "stale_policy": {"threshold_days": 60, "exempt_subtree_slugs": ["domain_archive"]},
}

SURFACES = {
    "surfaces": {
        "os_home": {"id": "aaa"},
        "people_db": {"id": "ppp"},
        "domain_los": {"id": "bbb"},
        "los_prs": {"id": "ccc"},
        "domain_archive": {"id": "arc"},
    }
}


def _item(parent: str, title: str = "x", obj: str = "page", edited: str = "2026-07-01T00:00:00Z", parent_type: str = "page_id"):
    return {
        "object": obj,
        "title": title,
        "parent": parent,
        "parent_type": "workspace" if parent == "workspace" else parent_type,
        "edited": edited,
        "url": "",
    }


def test_clean_workspace_has_no_drift() -> None:
    module = _load_module()
    items = {
        "aaa": _item("workspace", "Home"),
        "ppp": _item("workspace", "People", obj="database"),
        "bbb": _item("aaa", "LOS"),
        "ccc": _item("bbb", "PRs"),
    }
    drift = module.compute_drift(ORG, SURFACES, items, NOW)
    assert not module.has_drift(drift)
    assert drift["counts"]["stale_pages"] == 0


def test_unexpected_root_and_misplaced_surface_flagged() -> None:
    module = _load_module()
    items = {
        "aaa": _item("workspace", "Home"),
        "bbb": _item("aaa", "LOS"),
        "ccc": _item("aaa", "PRs"),          # should be under LOS (bbb)
        "zzz": _item("workspace", "Stray"),  # unexpected root
    }
    drift = module.compute_drift(ORG, SURFACES, items, NOW)
    assert module.has_drift(drift)
    assert drift["counts"]["unexpected_roots"] == 1
    assert drift["unexpected_roots"][0]["id"] == "zzz"
    assert drift["counts"]["misplaced"] == 1
    assert drift["misplaced"][0]["slug"] == "los_prs"
    assert drift["misplaced"][0]["actual_parent"] == "os_home"


def test_missing_surface_flagged() -> None:
    module = _load_module()
    items = {
        "aaa": _item("workspace", "Home"),
        "bbb": _item("aaa", "LOS"),
        # ccc missing entirely (trashed)
    }
    drift = module.compute_drift(ORG, SURFACES, items, NOW)
    assert drift["counts"]["missing_surfaces"] == 1
    assert drift["missing_surfaces"][0]["slug"] == "los_prs"


def test_stale_pages_reported_but_archive_exempt() -> None:
    module = _load_module()
    items = {
        "aaa": _item("workspace", "Home"),
        "bbb": _item("aaa", "LOS"),
        "ccc": _item("bbb", "PRs"),
        "arc": _item("aaa", "Archive"),
        "old1": _item("aaa", "Old doc", edited="2026-01-01T00:00:00Z"),
        "old2": _item("arc", "Parked old doc", edited="2026-01-01T00:00:00Z"),
        "row": _item("db1", "db row", edited="2026-01-01T00:00:00Z", parent_type="database_id"),
    }
    drift = module.compute_drift(ORG, SURFACES, items, NOW)
    stale_ids = {entry["id"] for entry in drift["stale_pages"]}
    assert "old1" in stale_ids          # counted
    assert "old2" not in stale_ids      # exempt under archive
    assert "row" not in stale_ids       # db rows exempt
    assert not module.has_drift(drift)  # stale alone is not drift


def test_render_report_lists_sections() -> None:
    module = _load_module()
    items = {
        "aaa": _item("workspace", "Home"),
        "zzz": _item("workspace", "Stray"),
    }
    drift = module.compute_drift(ORG, SURFACES, items, NOW)
    report = module.render_report(drift, NOW)
    assert "Unexpected roots" in report
    assert "Stray" in report


def test_crawl_workspace_uses_complete_normalized_bridge_search(monkeypatch) -> None:
    module = _load_module()
    requests = []

    class FakeClient:
        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            return {
                "values": [
                    {
                        "object": "database",
                        "id": "aaa-bbb",
                        "title": [{"plainText": "People"}],
                        "parent": {"type": "workspace"},
                        "updatedAt": "2026-07-31T12:00:00.000Z",
                        "url": "https://www.notion.so/database",
                    }
                ],
                "complete": True,
            }

    monkeypatch.setattr(module, "notion_client", lambda: FakeClient())

    assert module.crawl_workspace() == {
        "aaabbb": {
            "object": "database",
            "title": "People",
            "parent": "workspace",
            "parent_type": "workspace",
            "edited": "2026-07-31T12:00:00.000Z",
            "url": "https://www.notion.so/database",
        }
    }
    assert requests == [("search", {}, {})]


def test_trash_backs_up_then_uses_guarded_bridge_mutation(monkeypatch, tmp_path) -> None:
    module = _load_module()
    requests = []

    class FakeClient:
        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            if operation == "getPage":
                return {"object": "page", "id": args["pageId"]}
            if operation == "listBlockChildren":
                return {"values": [], "complete": True}
            return {"object": "page", "id": args["pageId"], "inTrash": True}

    monkeypatch.setattr(module, "notion_client", lambda: FakeClient())
    backup_dir = tmp_path / "backup"
    args = Namespace(
        root=str(tmp_path), ids="aaa", backup_dir=str(backup_dir), live=True
    )

    assert module.cmd_trash(args) == 0
    assert (backup_dir / "aaa.json").is_file()
    assert requests[-1] == ("trashPage", {"pageId": "aaa"}, {"mutation": True})
