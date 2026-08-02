from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


def load_intake_row_module():
    script = Path(__file__).resolve().parents[1] / "harness" / "bin" / "agentic-os-intake-row"
    loader = SourceFileLoader("agentic_os_intake_row_under_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_intake_row_create_uses_guarded_bridge_with_stable_title_marker(monkeypatch):
    module = load_intake_row_module()
    requests = []

    class FakeClient:
        identity = {
            "workspaceName": "Genome's Notion",
            "parentPageId": "3a8683b4-8dab-8111-bdc1-c2069129f031",
        }

        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            return {"id": "page-1", "url": "https://www.notion.so/page-1"}

    monkeypatch.setattr(module, "_notion_client", lambda token: FakeClient())
    properties = module.build_properties(
        "Stable intake title", "feature", "Agentic OS", "inbox", "P2", "manual"
    )
    page = module.create_intake_page(
        "secret",
        properties,
        children=[{"object": "block", "type": "paragraph", "paragraph": {}}],
    )

    assert page["id"] == "page-1"
    operation, args, kwargs = requests[0]
    assert operation == "createPage"
    assert kwargs == {"mutation": True}
    assert args["input"]["parent"] == {
        "type": "database_id",
        "id": module.NOTION_DB_ID,
    }
    assert args["input"]["reconciliation"] == {
        "parentPageId": "3a8683b4-8dab-8111-bdc1-c2069129f031",
        "marker": "Stable intake title",
    }


def test_intake_row_sanitizes_escaped_title_marker(monkeypatch):
    module = load_intake_row_module()
    requests = []

    class FakeClient:
        identity = {
            "workspaceName": "Genome's Notion",
            "parentPageId": "3a8683b4-8dab-8111-bdc1-c2069129f031",
        }

        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            return {"id": "page-2", "url": "https://www.notion.so/page-2"}

    monkeypatch.setattr(module, "_notion_client", lambda token: FakeClient())
    properties = module.build_properties(
        'Fix "quoted"\\path crash',
        "bug",
        "Agentic OS",
        "inbox",
        "P1",
        "manual",
    )

    module.create_intake_page("secret", properties)

    assert requests[0][1]["input"]["reconciliation"]["marker"] == "path crash"
