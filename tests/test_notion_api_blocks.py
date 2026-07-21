from __future__ import annotations

import io
import json

from genomes_agentic_os import notion_api


class Fetcher:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if request.method == "GET":
            return io.BytesIO(json.dumps({"results": [
                {"id": "keep", "type": "child_page"},
                {"id": "archive", "type": "paragraph"},
            ], "has_more": False}).encode())
        return io.BytesIO(b"{}")


def test_replace_block_children_preserves_child_pages(monkeypatch) -> None:
    monkeypatch.setenv("TOKEN", "secret")
    fetcher = Fetcher()
    notion_api.replace_block_children("page", [{"object": "block", "type": "paragraph", "paragraph": {}}], "TOKEN", fetcher=fetcher)
    methods_and_urls = [(request.method, request.full_url) for request in fetcher.requests]
    assert any(method == "DELETE" and url.endswith("/blocks/archive") for method, url in methods_and_urls)
    assert not any(method == "DELETE" and url.endswith("/blocks/keep") for method, url in methods_and_urls)
    assert any(method == "PATCH" and "/blocks/page/children" in url for method, url in methods_and_urls)
