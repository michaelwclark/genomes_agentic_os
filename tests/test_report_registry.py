from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from genomes_agentic_os.report_registry import collect_reports, report_summary


NOW = datetime(2026, 7, 13, 6, 0, tzinfo=timezone.utc)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_collect_reports_discovers_canonical_surfaces_and_extracts_contract(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    work_item = _write(
        root / "domains/clarks_consulting/02-projects/genomes_agentic_os/work-items/02-active/040_cockpit/SUMMARY.md",
        """---
status: validating
severity: warning
updated_at: 2026-07-13T05:30:00Z
---
# Unified Cockpit Report

The cockpit projection is ready for focused verification. A second sentence stays in detail.
""",
    )
    watcher = _write(
        root / "watchers/slack_ingest/reports/2026-07-13.md",
        "# Slack ingest daily report\n\nCaptured 12 messages without errors.\n",
    )
    run = _write(
        root / "harness/shared_factory/06-runs-and-logs/runs/20260713T050000Z-demo/summary.md",
        "# Demo run\n\nStatus: success\n\nThe scheduled demonstration completed normally.\n",
    )
    _write(
        root / "harness/shared_factory/06-runs-and-logs/self-improvement/reports/daily.json",
        '{"title":"Self improvement daily","summary":"Two proposals were accepted.","status":"success","generated_at":"2026-07-13T05:45:00Z"}',
    )
    _write(
        root / "harness/shared_factory/06-runs-and-logs/adaptive-routing/observation-reports/latest.yml",
        "title: Adaptive routing observation\nsummary: Routing stayed within budget.\nstatus: passed\ndate: 2026-07-13\n",
    )

    reports = collect_reports(root, now=NOW)

    assert len(reports) == 5
    by_source = {row["source"]: row for row in reports}
    item = by_source[work_item.relative_to(root).as_posix()]
    assert item == {
        "id": item["id"],
        "title": "Unified Cockpit Report",
        "summary": "The cockpit projection is ready for focused verification.",
        "detail": "The cockpit projection is ready for focused verification. A second sentence stays in detail.",
        "status": "validating",
        "severity": "warning",
        "type": "work-item-report",
        "scope": "work_item",
        "domain": "clarks_consulting",
        "project": "genomes_agentic_os",
        "generated_at": "2026-07-13T05:30:00Z",
        "updated_at": "2026-07-13T05:30:00Z",
        "source": work_item.relative_to(root).as_posix(),
    }
    assert by_source[watcher.relative_to(root).as_posix()]["type"] == "watcher-report"
    assert by_source[run.relative_to(root).as_posix()]["status"] == "success"
    assert {row["type"] for row in reports} == {
        "adaptive-routing-report",
        "run-report",
        "self-improvement-report",
        "watcher-report",
        "work-item-report",
    }


def test_collect_reports_prunes_sources_worktrees_caches_raw_logs_and_non_report_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    included = _write(
        root / "domains/los/02-projects/los_app/reports/leadership/2026-07-13.md",
        "# Leadership update\n\nThe sprint remains on track.\n",
    )
    excluded = [
        root / "domains/los/02-projects/los_app/worktrees/feature/reports/fake.md",
        root / "domains/los/02-projects/los_app/src/reports/fake.md",
        root / "domains/los/02-projects/los_app/node_modules/pkg/reports/fake.md",
        root / "domains/los/02-projects/los_app/work-items/02-active/001/artifacts/screenshot.png",
        root / "watchers/slack_ingest/reports/raw.log",
        root / "watchers/slack_ingest/logs/events.jsonl",
        root / "watchers/slack_ingest/reports/README.md",
        root / "watchers/slack_ingest/reports/config.yml",
        root / "watchers/slack_ingest/reports/items.json",
    ]
    for path in excluded:
        _write(path, "# Must not surface\n")

    reports = collect_reports(root, now=NOW)

    assert [row["source"] for row in reports] == [included.relative_to(root).as_posix()]


def test_collect_reports_is_stable_bounded_and_tolerates_malformed_structured_reports(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    for index in range(4):
        _write(root / f"watchers/demo/reports/report-{index}.md", f"# Report {index}\n\nItem {index} completed.\n")
    malformed = _write(root / "watchers/demo/reports/broken.json", "{not-json")

    first = collect_reports(root, now=NOW, max_files=3)
    second = collect_reports(root, now=NOW, max_files=3)

    assert len(first) == 3
    assert first == second
    assert len({row["id"] for row in first}) == 3
    all_reports = collect_reports(root, now=NOW)
    broken = next(row for row in all_reports if row["source"] == malformed.relative_to(root).as_posix())
    assert broken["title"] == "Broken"
    assert broken["status"] == "unknown"


def test_collect_reports_uses_structured_run_identity_and_redacts_summary(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _write(
        root / "harness/shared_factory/06-runs-and-logs/runs/20260713-demo/run-log.yml",
        """run_id: 20260713-demo
kind: runtime_dispatch
status: done
summary: Completed with token sk-abcdefghijklmnopqrstuvwxyz123456.
updated_at: 2026-07-13T05:00:00Z
""",
    )

    report = collect_reports(root, now=NOW)[0]

    assert report["title"] == "Runtime Dispatch — 20260713-demo"
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in report["summary"]
    assert report["status"] == "completed"


def test_report_summary_returns_sorted_cockpit_counts() -> None:
    reports = [
        {"status": "success", "severity": "info", "type": "run-report", "scope": "run", "domain": "los", "project": "django"},
        {"status": "blocked", "severity": "error", "type": "run-report", "scope": "run", "domain": "los", "project": "django"},
        {"status": "success", "severity": "info", "type": "watcher-report", "scope": "watcher", "domain": "watchers", "project": "slack"},
    ]

    assert report_summary(reports) == {
        "total": 3,
        "by_status": {"blocked": 1, "success": 2},
        "by_severity": {"error": 1, "info": 2},
        "by_type": {"run-report": 2, "watcher-report": 1},
        "by_scope": {"run": 2, "watcher": 1},
        "by_domain": {"los": 2, "watchers": 1},
        "by_project": {"django": 2, "slack": 1},
    }
