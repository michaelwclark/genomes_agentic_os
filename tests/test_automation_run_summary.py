from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "harness"
        / "bin"
        / "agentic-os-automation-run-summary"
    )
    loader = SourceFileLoader("automation_run_summary_under_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _title(value: str) -> dict:
    return {
        "Name": {
            "type": "title",
            "title": [{"plain_text": value}],
        }
    }


def test_target_verification_uses_normalized_bridge_identity_and_parent_chain() -> None:
    module = load_module()
    parent_id = "a" * 32
    page_id = "b" * 32
    ancestor_id = "c" * 32
    requests = []

    class FakeClient:
        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            if operation == "preflightIdentity":
                return {"workspaceName": "Genome's Notion"}
            object_id = args["pageId"]
            if object_id == page_id:
                return {
                    "id": page_id,
                    "parent": {"type": "page_id", "id": parent_id},
                    "properties": _title("Summary"),
                }
            if object_id == parent_id:
                return {
                    "id": parent_id,
                    "parent": {"type": "page_id", "id": ancestor_id},
                    "properties": _title("Automations"),
                }
            return {
                "id": ancestor_id,
                "parent": {"type": "workspace"},
                "properties": _title("Genome's Agentic OS"),
            }

    manifest = {
        "notion": {
            "workspace_expected": "Genome's Notion",
            "parent_page_id": parent_id,
            "parent_title": "Automations",
            "parent_ancestor_title": "Genome's Agentic OS",
        }
    }
    result = module.verify_target(FakeClient(), manifest, {"page_id": page_id})

    assert result["workspace"] == "Genome's Notion"
    assert [request[0] for request in requests] == [
        "preflightIdentity",
        "getPage",
        "getPage",
        "getPage",
    ]


def test_replace_page_reads_all_children_then_trashes_and_appends() -> None:
    module = load_module()
    requests = []

    class FakeClient:
        def request(self, operation, args, **kwargs):
            requests.append((operation, args, kwargs))
            if operation == "listBlockChildren":
                return {
                    "values": [{"id": "block-1", "type": "paragraph"}],
                    "complete": True,
                }
            return {"id": args.get("blockId")}

    blocks = [module.paragraph("replacement")]
    module.replace_page(FakeClient(), "page-1", blocks)

    assert requests == [
        ("listBlockChildren", {"blockId": "page-1"}, {}),
        ("trashBlock", {"blockId": "block1"}, {"mutation": True}),
        (
            "appendBlockChildren",
            {"blockId": "page-1", "children": blocks},
            {"mutation": True},
        ),
    ]


def test_replace_page_refuses_unsafe_children_before_mutation() -> None:
    module = load_module()

    class FakeClient:
        def request(self, operation, args, **kwargs):
            assert operation == "listBlockChildren"
            return {
                "values": [{"id": "child", "type": "child_page"}],
                "complete": True,
            }

    with pytest.raises(module.TrackingError, match="unsafe child blocks"):
        module.replace_page(FakeClient(), "page-1", [])
