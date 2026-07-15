from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.report_engine import (
    REPORT_ARTIFACT_REGISTRY,
    REPORT_REGISTRY,
    REPORT_RUN_REGISTRY,
    consolidation_plan,
    create_report_definition,
    get_report_resource,
    query_report_resources,
    rollback_report_action,
    run_report_now,
    set_report_archived,
    update_report_definition,
    validate_report_definition,
)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()


def _definition(
    report_id: str = "daily_engineering",
    *,
    source_path: str = "data/report.json",
    source_required: bool = True,
    max_runs: int = 10,
    destinations: list[dict] | None = None,
    sections: list[dict] | None = None,
) -> dict:
    return {
        "id": report_id,
        "name": "Daily engineering",
        "summary": "A concise engineering operating report.",
        "scope": {"domain": "clarks_consulting", "project": "genomes_agentic_os"},
        "generator": {
            "kind": "builtin",
            "id": "rich_sections_v1",
            "workflow_ref": None,
            "program_ref": None,
        },
        "sources": [
            {
                "id": "engineering_data",
                "kind": "filesystem",
                "required": source_required,
                "path": source_path,
                "parser": "json",
            }
        ],
        "parameters": {},
        "schedule": {"schedule_id": None},
        "destinations": destinations or [{"kind": "filesystem", "enabled": True}],
        "retention": {"max_runs": max_runs, "max_age_days": 30},
        "permissions": {"run_now": True, "edit": True, "notion_projection": True},
        "health_policy": {"max_stale_hours": 24, "partial_is_error": False},
        "sections": sections
        or [{"id": "overview", "type": "table", "title": "Overview", "source_id": "engineering_data"}],
    }


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_init_scaffolds_versioned_registries_and_schemas(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    assert yaml.safe_load((root / REPORT_REGISTRY).read_text()) == {
        "api_version": "report-registry/v1",
        "definitions": [],
    }
    assert yaml.safe_load((root / REPORT_RUN_REGISTRY).read_text())["api_version"] == "report-run-registry/v1"
    assert yaml.safe_load((root / REPORT_ARTIFACT_REGISTRY).read_text())["api_version"] == "report-artifact-registry/v1"
    assert (root / "harness/schemas/report-definition.schema.json").is_file()
    example = yaml.safe_load(
        (root / "harness/shared_factory/05-knowledge/templates/runtime/report-definition.yml").read_text()
    )
    assert validate_report_definition(root, example)["ok"] is True
    assert main(["report", "query", "definition", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["items"] == []


def test_create_is_dry_run_by_default_then_queryable_with_relationship_counts(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    definition_file = tmp_path / "definition.yml"
    definition_file.write_text(yaml.safe_dump(_definition()), encoding="utf-8")

    assert main(["report", "create", "--definition-file", str(definition_file), "--root", str(root), "--json"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["api_version"] == "resource-actions/v1"
    assert planned["status"] == "planned"
    assert yaml.safe_load((root / REPORT_REGISTRY).read_text())["definitions"] == []

    assert main(
        ["report", "create", "--definition-file", str(definition_file), "--root", str(root), "--apply", "--json"]
    ) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "created"
    assert created["readback"]["ok"] is True
    assert Path(created["backup"]).is_file()
    assert Path(created["receipt"]).is_file()
    projection = get_report_resource(root, "definition", "daily_engineering")["resource"]
    assert projection["run_count"] == projection["artifact_count"] == 0
    assert projection["health"]["status"] == "never_run"
    assert validate_report_definition(root, projection["definition"])["ok"] is True


def test_create_dry_run_on_uninitialized_root_does_not_create_registries(tmp_path: Path) -> None:
    root = tmp_path / "uninitialized"
    root.mkdir()

    result = create_report_definition(root, _definition(), dry_run=True)

    assert result["status"] == "planned"
    assert not (root / "harness").exists()


def test_update_archive_restore_and_optimistic_rollback_are_receipted(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    created = create_report_definition(root, _definition(), dry_run=False)
    original = created["readback"]["definition"]
    changed = _definition()
    changed["name"] = "Renamed engineering report"
    updated = update_report_definition(root, "daily_engineering", changed, dry_run=False)

    receipt = Path(updated["receipt"]).relative_to(root).as_posix()
    assert rollback_report_action(root, receipt, dry_run=True)["status"] == "planned"
    rolled_back = rollback_report_action(root, receipt, dry_run=False)
    assert rolled_back["status"] == "rolled_back"
    assert get_report_resource(root, "definition", "daily_engineering")["resource"]["name"] == original["name"]

    archived = set_report_archived(root, "daily_engineering", archived=True, dry_run=False)
    assert archived["readback"]["definition"]["status"] == "archived"
    assert query_report_resources(root, "definition")["count"] == 0
    restored = set_report_archived(root, "daily_engineering", archived=False, dry_run=False)
    assert restored["readback"]["definition"]["status"] == "active"
    with pytest.raises(ValueError, match="changed after the receipt"):
        rollback_report_action(root, receipt, dry_run=False)


def test_run_now_builds_all_rich_sections_and_independent_run_artifact_records(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    _write_json(root / "data/report.json", [{"day": "Mon", "count": 3, "url": "https://example.test/3"}])
    sections = [
        {"id": "markdown", "type": "markdown", "title": "Markdown", "source_id": "engineering_data"},
        {"id": "table", "type": "table", "title": "Table", "source_id": "engineering_data"},
        {"id": "chart", "type": "chart", "title": "Chart", "source_id": "engineering_data", "chart_type": "bar", "x": "day", "y": "count"},
        {"id": "list", "type": "list", "title": "List", "source_id": "engineering_data"},
        {"id": "timeline", "type": "timeline", "title": "Timeline", "source_id": "engineering_data"},
        {"id": "links", "type": "links", "title": "Links", "source_id": "engineering_data"},
        {"id": "evidence", "type": "evidence", "title": "Evidence", "source_id": "engineering_data"},
    ]
    create_report_definition(root, _definition(sections=sections), dry_run=False)

    planned = run_report_now(root, "daily_engineering", dry_run=True)
    assert planned["status"] == "planned"
    assert query_report_resources(root, "run")["count"] == 0
    result = run_report_now(root, "daily_engineering", dry_run=False)

    assert result["status"] == "success"
    assert result["run"]["source_completeness"] == 1
    assert {item["type"] for item in result["artifact"]["sections"]} == {
        "markdown", "table", "chart", "list", "timeline", "links", "evidence"
    }
    assert result["artifact"]["content_sha256"]
    assert Path(result["paths"]["markdown"]).read_text().startswith("# Daily engineering")
    run_id = result["run"]["id"]
    artifact_id = result["artifact"]["id"]
    assert get_report_resource(root, "run", run_id)["resource"]["definition_id"] == "daily_engineering"
    assert get_report_resource(root, "artifact", artifact_id)["resource"]["run_id"] == run_id
    projection = get_report_resource(root, "definition", "daily_engineering")["resource"]
    assert projection["run_count"] == projection["artifact_count"] == 1


def test_bounded_query_contract_links_catalog_scope_source_latest_run_and_artifact(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    _write_json(root / "data/report.json", [{"count": 2}])
    catalog_path = root / "harness/registries/reports.yml"
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "reports": [
                    {
                        "id": "daily_engineering_catalog",
                        "name": "Daily engineering catalog",
                        "description": "Prompt-backed authoring entry.",
                        "source": "harness/reports/daily_engineering_catalog.md",
                        "status": "draft",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    definition = _definition()
    definition["catalog_ref"] = "daily_engineering_catalog"
    create_report_definition(root, definition, dry_run=False)
    result = run_report_now(root, "daily_engineering", dry_run=False)

    definitions = query_report_resources(root, "definition", limit=1)
    assert definitions["count"] == definitions["total_count"] == 1
    assert definitions["limit"] == 1
    assert definitions["truncated"] is False
    row = definitions["items"][0]
    assert row["source"] == {"kind": "registry", "path": REPORT_REGISTRY}
    assert row["scope"] == {"domain": "clarks_consulting", "project": "genomes_agentic_os"}
    assert row["catalog_ref"] == "daily_engineering_catalog"
    assert row["catalog"]["source"] == "harness/reports/daily_engineering_catalog.md"
    assert row["latest_run"]["id"] == result["run"]["id"]
    assert row["latest_artifact"]["id"] == result["artifact"]["id"]
    assert row["schedule_id"] is None

    run_row = query_report_resources(root, "run", limit=1)["items"][0]
    artifact_row = query_report_resources(root, "artifact", limit=1)["items"][0]
    assert run_row["scope"] == row["scope"]
    assert run_row["source"]["kind"] == "run"
    assert artifact_row["scope"] == row["scope"]
    assert artifact_row["source"]["kind"] == "artifact"

    with pytest.raises(ValueError, match="between 1 and 500"):
        query_report_resources(root, "definition", limit=0)


@pytest.mark.parametrize(
    ("required", "expected_status", "evidence_status"),
    [(True, "error", "error"), (False, "partial", "partial")],
)
def test_missing_sources_remain_explicit_in_run_and_markdown(
    tmp_path: Path, capsys, required: bool, expected_status: str, evidence_status: str
) -> None:
    root = tmp_path / f"agentic_os_{required}"
    _init(root, capsys)
    create_report_definition(root, _definition(source_required=required), dry_run=False)

    result = run_report_now(root, "daily_engineering", dry_run=False)

    assert result["status"] == expected_status
    assert result["run"]["source_evidence"][0]["status"] == evidence_status
    assert result["run"]["errors"][0]["code"] == "source_unavailable"
    assert "Errors and partial evidence" in Path(result["paths"]["markdown"]).read_text()


def test_notion_projection_is_exact_workspace_guarded_and_failure_is_partial(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    _write_json(root / "data/report.json", [{"ok": True}])
    destinations = [
        {"kind": "filesystem", "enabled": True},
        {"kind": "notion", "enabled": True, "workspace": "Genome's Notion", "parent_id": "test-parent"},
    ]
    create_report_definition(root, _definition(destinations=destinations), dry_run=False)
    called = []

    with pytest.raises(ValueError, match="exact workspace verification"):
        run_report_now(
            root,
            "daily_engineering",
            dry_run=False,
            project_notion=True,
            notion_workspace="Michael Clark's Notion",
            notion_projector=lambda *_: called.append(True),
        )
    assert called == []

    result = run_report_now(
        root,
        "daily_engineering",
        dry_run=False,
        project_notion=True,
        notion_workspace="Genome's Notion",
        notion_projector=lambda *_: {"ok": False, "error": "simulated unavailable"},
    )
    assert result["status"] == "partial"
    notion = next(item for item in result["run"]["projection_evidence"] if item["kind"] == "notion")
    assert notion["status"] == "error"
    assert notion["external_write"] is False
    assert any(item["code"] == "notion_projection_failed" for item in result["run"]["errors"])


def test_stale_schedule_reference_is_rejected_before_create(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(["runtime", "init", "--root", str(root)]) == 0
    capsys.readouterr()
    definition = _definition()
    definition["schedule"] = {"schedule_id": "removed_schedule"}

    with pytest.raises(ValueError, match="schedule_reference_stale"):
        create_report_definition(root, definition, dry_run=False)


def test_retention_and_consolidation_are_plans_without_deletion(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    _write_json(root / "data/report.json", [{"count": 1}])
    create_report_definition(root, _definition(max_runs=1), dry_run=False)
    first = run_report_now(root, "daily_engineering", dry_run=False)
    second = run_report_now(root, "daily_engineering", dry_run=False)

    assert second["retention"]["deleted"] == 0
    assert second["retention"]["candidates"] == [{"run_id": first["run"]["id"], "reasons": ["max_runs"]}]
    assert Path(first["paths"]["artifact"]).is_file()

    duplicate = _definition("daily_engineering_copy", max_runs=1)
    create_report_definition(root, duplicate, dry_run=False)
    plan = consolidation_plan(root, stale_days=30)
    assert plan["mutation"] == {"performed": False, "deletions": 0, "automatic_archive": False}
    assert plan["summary"]["duplicate_groups"] == 1
    assert {item["definition_id"] for item in plan["stale"]} == {"daily_engineering_copy"}
    assert plan["catalog_gaps"]["definition_without_catalog"] == [
        "daily_engineering",
        "daily_engineering_copy",
    ]


def test_filesystem_sources_cannot_escape_or_traverse_symlinks(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    outside = tmp_path / "outside.json"
    _write_json(outside, {"secret": True})
    create_report_definition(root, _definition(source_path="../outside.json"), dry_run=False)
    escaped = run_report_now(root, "daily_engineering", dry_run=False)
    assert escaped["status"] == "error"
    assert "escapes Agentic OS root" in escaped["run"]["source_evidence"][0]["detail"]

    root_two = tmp_path / "agentic_os_symlink"
    _init(root_two, capsys)
    (root_two / "data").symlink_to(tmp_path, target_is_directory=True)
    create_report_definition(root_two, _definition(source_path="data/outside.json"), dry_run=False)
    linked = run_report_now(root_two, "daily_engineering", dry_run=False)
    assert linked["status"] == "error"
    assert "may not traverse a symlink" in linked["run"]["source_evidence"][0]["detail"]
