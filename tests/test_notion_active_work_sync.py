from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from genomes_agentic_os.cli import main


SENTINEL_TOKEN = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
DATABASE_ID = "380683b48dab813a9ba1c4506c91f800"


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body


class FakeTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any) -> _FakeResponse:
        body = (req.data or b"").decode("utf-8", errors="replace")
        self.requests.append({"method": req.method, "url": req.full_url, "body": body})
        if not self.responses:
            raise AssertionError(f"no fake response for {req.method} {req.full_url}")
        return _FakeResponse(self.responses.pop(0))


def _write_active_index(root: Path) -> None:
    index_path = root / "00-control-plane" / "active" / "index.yml"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        yaml.safe_dump(
            {
                "generated_at": "2026-06-18T12:00:00Z",
                "source_of_truth": "filesystem work-items and project worktree registries",
                "work_items": [
                    {
                        "domain": "clarks_consulting",
                        "project": "genomes_agentic_os",
                        "id": "010_notion_os_operations_reorg",
                        "status": "building",
                        "link": "/active/work-items/reorg",
                        "target": "/work-items/010_notion_os_operations_reorg",
                    }
                ],
                "worktrees": [
                    {
                        "domain": "clarks_consulting",
                        "project": "genomes_agentic_os",
                        "id": "notion_active_work_sync",
                        "link": "/active/worktrees/notion_active_work_sync",
                        "target": "/worktrees/notion_active_work_sync",
                    }
                ],
                "automations": [
                    {
                        "id": "closed_worktree_cleanup automation",
                        "status": "observe",
                        "path": "/automations/closed_worktree_cleanup",
                        "link": "/active/automations/closed_worktree_cleanup_automation",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _users_me(workspace: str = "Genome's Notion") -> dict[str, Any]:
    return {"object": "user", "type": "bot", "bot": {"workspace_name": workspace}}


def _database_schema() -> dict[str, Any]:
    return {
        "object": "database",
        "properties": {
            "Name": {"type": "title"},
            "Type": {"type": "select"},
            "Status": {"type": "select"},
            "Domain": {"type": "rich_text"},
            "Project": {"type": "rich_text"},
            "Active Link": {"type": "rich_text"},
            "Source Path": {"type": "rich_text"},
            "Last Synced": {"type": "date"},
        },
    }


def _query_empty() -> dict[str, Any]:
    return {"object": "list", "results": []}


def _page(page_id: str) -> dict[str, Any]:
    return {"object": "page", "id": page_id}


def _existing_page(
    page_id: str,
    *,
    name: str,
    row_type: str,
    status: str,
    domain: str,
    project: str,
    link: str,
    path: str,
    synced: str,
) -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": name}]},
            "Type": {"type": "select", "select": {"name": row_type}},
            "Status": {"type": "select", "select": {"name": status}},
            "Domain": {"type": "rich_text", "rich_text": [{"plain_text": domain}] if domain else []},
            "Project": {"type": "rich_text", "rich_text": [{"plain_text": project}] if project else []},
            "Active Link": {"type": "rich_text", "rich_text": [{"plain_text": link}]},
            "Source Path": {"type": "rich_text", "rich_text": [{"plain_text": path}]},
            "Last Synced": {"type": "date", "date": {"start": synced}},
        },
    }


def test_active_work_sync_dry_run_reads_generated_index(tmp_path: Path, capsys: Any) -> None:
    root = tmp_path / "agentic_os"
    _write_active_index(root)

    assert main(["notion", "active-work-sync", "--root", str(root), "--dry-run"]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["mode"] == "dry-run"
    assert result["planned"] == 3
    assert {row["type"] for row in result["rows"]} == {"Automation", "Work Item", "Worktree"}
    assert not (root / ".notion-active-work-sync" / "last-run.yml").exists()


def test_active_work_sync_apply_creates_updates_and_skips_unchanged(tmp_path: Path) -> None:
    from genomes_agentic_os.notion_sync import apply_active_work_sync

    root = tmp_path / "agentic_os"
    _write_active_index(root)
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    transport = FakeTransport(
        [
            _users_me(),
            _database_schema(),
            _query_empty(),
            _page("page-automation"),
            {"object": "list", "results": [_existing_page("page-work-item", name="genomes_agentic_os / 010_notion_os_operations_reorg", row_type="Work Item", status="building", domain="clarks_consulting", project="genomes_agentic_os", link="/active/work-items/reorg", path="/work-items/010_notion_os_operations_reorg", synced=today)]},
            {"object": "list", "results": [_existing_page("page-worktree", name="genomes_agentic_os / notion_active_work_sync", row_type="Worktree", status="stale", domain="clarks_consulting", project="genomes_agentic_os", link="/active/worktrees/notion_active_work_sync", path="/worktrees/notion_active_work_sync", synced=today)]},
            _page("page-worktree"),
        ]
    )

    with patch.dict(os.environ, {"GENOMES_NOTION_PAT": SENTINEL_TOKEN}):
        result = apply_active_work_sync(
            str(root),
            database_id=DATABASE_ID,
            verified_workspace="Genome's Notion",
            fetcher=transport,
        )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["unchanged"] == 1
    assert result["counts"] == {"created": 1, "updated": 1, "unchanged": 1}
    assert result["workspace"] == "Genome's Notion"
    assert (root / ".notion-active-work-sync" / "last-run.yml").is_file()
    assert all(SENTINEL_TOKEN not in request["url"] and SENTINEL_TOKEN not in request["body"] for request in transport.requests)


def test_active_work_sync_apply_requires_verified_workspace_and_database(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _write_active_index(root)

    assert main(["notion", "active-work-sync", "--root", str(root), "--apply", "--database-id", DATABASE_ID]) == 2
    assert main(["notion", "active-work-sync", "--root", str(root), "--apply", "--verified-workspace", "Genome's Notion"]) == 2
