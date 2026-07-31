from __future__ import annotations

import json
from pathlib import Path

from genomes_agentic_os import notion_api


def test_notion_provider_transport_exists_only_behind_shared_bridge() -> None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        *sorted((root / "src" / "genomes_agentic_os").rglob("*.py")),
        *sorted((root / "harness" / "bin").glob("*")),
    ]
    forbidden = ("api.notion.com", "Notion-Version")
    findings: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in forbidden:
            if marker in text:
                findings.append(f"{path.relative_to(root)}: {marker}")
    assert findings == []

    facade = (root / "src" / "genomes_agentic_os" / "notion_api.py").read_text()
    assert "urllib.request.urlopen(" not in facade
    assert "https://notion-fixture.invalid/v1" in facade
    fixture_facade = facade.split("def get_bot_workspace(", 1)[1]
    assert "resolve_token(token_env)" not in fixture_facade
    assert '"Authorization"' not in facade
    assert '"Cookie"' not in facade


class _FixtureResponse:
    def read(self) -> bytes:
        return json.dumps(
            {"bot": {"workspace_name": "Genome's Notion"}}
        ).encode("utf-8")


def test_injected_notion_fixture_is_credential_free_and_allowlisted(
    monkeypatch,
) -> None:
    monkeypatch.delenv("GENOMES_NOTION_PAT", raising=False)
    seen = []

    def fetcher(request):
        seen.append(request)
        return _FixtureResponse()

    assert notion_api.get_bot_workspace(fetcher=fetcher) == "Genome's Notion"
    assert len(seen) == 1
    request = seen[0]
    assert request.full_url == "https://notion-fixture.invalid/v1/users/me"
    assert request.headers == {"Content-type": "application/json"}
    assert request.data is None
