from __future__ import annotations

from pathlib import Path


def test_notion_provider_transport_exists_only_behind_shared_bridge() -> None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        *sorted((root / "src" / "genomes_agentic_os").glob("*.py")),
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
