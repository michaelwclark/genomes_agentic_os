from __future__ import annotations

from pathlib import Path

import pytest

from genomes_agentic_os.cockpit_render import render_cockpit_html, write_cockpit_html


def sample_snapshot() -> dict:
    return {
        "schema_version": "agentic-os-cockpit/v1",
        "generated_at": "2026-07-13T08:00:00Z",
        "root": "/Users/example/agentic_os",
        "summary": {},
        "work_items": [
            {
                "id": "040_unified_engineering_lead_os_cockpit",
                "title": "Unified engineering lead cockpit",
                "summary": "One place to see current work.",
                "detail": "A read-only projection over canonical OS state.",
                "status": "building",
                "domain": "clarks_consulting",
                "project": "genomes_agentic_os",
                "tags": ["cockpit", "local-first"],
                "source": "clarks_consulting/02-projects/genomes_agentic_os/work-items/040/SPEC.md",
            }
        ],
        "conversations": [
            {
                "id": "thread-1",
                "title": "Cockpit implementation",
                "summary": "Codex thread routed to work item 040.",
                "status": "active",
                "harness": "codex",
                "work_item": "040_unified_engineering_lead_os_cockpit",
            }
        ],
        "reviews": [{"id": "pr-42", "title": "PR #42", "status": "review_requested"}],
        "reports": [{"id": "daily", "title": "Daily lead report", "summary": "Three items need attention."}],
        "automations": [],
        "sources": {
            "configured": [{"id": "github", "title": "GitHub", "status": "configured"}],
            "observed": [],
            "suggestions": [{"id": "slack-eng", "title": "#engineering", "reason": "Referenced often", "score": 8}],
        },
        "hosts": [],
        "hygiene": [{"id": "stale-1", "title": "Stale conversation", "severity": "warning"}],
        "diagnostics": [],
    }


def test_render_is_self_contained_accessible_and_has_all_sections() -> None:
    html = render_cockpit_html(sample_snapshot())

    assert html.startswith("<!doctype html>")
    assert 'role="tablist"' in html
    assert 'role="tabpanel"' in html
    assert 'aria-live="polite"' in html
    for label in (
        "Today",
        "Work",
        "Conversations",
        "Reviews",
        "Reports",
        "Automations",
        "Sources",
        "Hosts",
        "Hygiene",
    ):
        assert f'>{label}</button>' in html
    assert "https://" not in html
    assert "http://" not in html
    assert "<link rel=" not in html
    assert "@media (max-width: 680px)" in html
    assert "prefers-reduced-motion" in html


def test_render_embeds_snapshot_and_escapes_script_terminators() -> None:
    snapshot = sample_snapshot()
    attack = '</script><script data-owned="yes">alert(1)</script>&\u2028'
    snapshot["work_items"][0]["title"] = attack

    html = render_cockpit_html(snapshot)

    assert attack not in html
    assert '<script data-owned="yes">' not in html
    assert "\\u003c/script\\u003e" in html
    assert "\\u0026\\u2028" in html
    assert html.count('id="cockpit-data"') == 1
    assert "textContent" in html


def test_render_has_search_filters_drawer_and_empty_states() -> None:
    snapshot = sample_snapshot()
    for key in ("work_items", "conversations", "reviews", "reports", "automations", "hosts", "hygiene"):
        snapshot[key] = []
    snapshot["sources"] = {}

    html = render_cockpit_html(snapshot)

    assert 'id="search" type="search"' in html
    assert 'id="status-filter"' in html
    assert 'id="detail-drawer"' in html
    assert "Nothing captured here yet" in html
    assert "optional source is empty" in html
    assert "replaceChildren" in html


def test_render_rejects_non_dictionary_snapshot() -> None:
    with pytest.raises(TypeError, match="snapshot must be a dictionary"):
        render_cockpit_html([])  # type: ignore[arg-type]


def test_write_cockpit_html_creates_parent_and_returns_resolved_path(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "cockpit.html"

    result = write_cockpit_html(sample_snapshot(), output)

    assert result == output.resolve()
    assert result.is_file()
    contents = result.read_text(encoding="utf-8")
    assert "Agentic OS Cockpit" in contents
    assert "agentic-os-cockpit/v1" in contents
