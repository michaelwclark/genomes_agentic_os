from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from genomes_agentic_os.conversation_index import (
    age_label,
    build_project_routes,
    extract_references,
    human_title,
    model_metadata,
    route_conversation,
)


NOW = datetime(2026, 7, 13, 18, 0, tzinfo=timezone.utc)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "agentic_os"
    project = root / "domains" / "los" / "02-projects" / "los_app_los_django"
    repo = tmp_path / "projects" / "los-django"
    repo.mkdir(parents=True)
    project.mkdir(parents=True)
    (project / "src").symlink_to(repo)
    (project / "project.yml").write_text(
        yaml.safe_dump({"title": "LOS Django", "status": "active"}),
        encoding="utf-8",
    )
    item = project / "work-items" / "02-active" / "041_retry_fix"
    item.mkdir(parents=True)
    (item / "work.yml").write_text("id: 041_retry_fix\n", encoding="utf-8")
    (item / "SPEC.md").write_text(
        "Track FLYWL-2044 and https://github.com/example/los/pull/42.\n",
        encoding="utf-8",
    )
    return root, repo


def test_titles_ages_and_model_semantics_are_human_readable() -> None:
    assert human_title("Conversation 4044d024-dead-beef-dead-4044d0240000", "Review retry behavior") == "Review retry behavior"
    assert age_label("2026-07-13T13:00:00Z", now=NOW) == "5h"
    assert age_label("2026-07-06T13:00:00Z", now=NOW) == "1w"
    assert model_metadata("openai", "gpt-5.6-sol", "high") == {
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "model_tier": "frontier",
    }
    assert model_metadata("anthropic", "claude-fable-5", "max")["model_tier"] == "balanced"
    assert model_metadata("anthropic", "unknown-private-model", None)["reasoning_effort"] == "unknown"


def test_reference_metadata_and_project_routes(tmp_path: Path) -> None:
    root, repo = _project(tmp_path)
    text = (
        "Fix FLYWL-2044 at https://flywheelio.atlassian.net/browse/FLYWL-2044 "
        "and CC-263 at https://linear.app/agenticoslinear/issue/CC-263/command-center "
        "from https://example.slack.com/archives/C1234567890/p1783951200000000 "
        "in https://github.com/example/los/pull/42 using " + str(repo / "design.png")
    )
    refs = extract_references([text])

    assert refs["jira"] == [{"key": "FLYWL-2044", "url": "https://flywheelio.atlassian.net/browse/FLYWL-2044"}]
    assert refs["linear"] == [{"key": "CC-263", "url": "https://linear.app/agenticoslinear/issue/CC-263/command-center"}]
    assert refs["pull_requests"][0]["number"] == "42"
    assert refs["slack"][0]["channel_id"] == "C1234567890"
    assert refs["assets"][0]["kind"] == "png"

    routes = build_project_routes(root)
    routed = route_conversation(
        cwd=str(root),
        routes=routes,
        work_items=[],
        title="Shared OS conversation",
        visible_texts=[text],
        references=refs,
        native_hints=[str(repo)],
    )
    assert routed["domain"] == "los"
    assert routed["project"] == "los_app_los_django"
    assert routed["route_source"] == "native_workspace_hint"


def test_work_item_evidence_routes_shared_root_and_sets_work_item(tmp_path: Path) -> None:
    from genomes_agentic_os.conversation_index import build_work_item_routes

    root, _ = _project(tmp_path)
    refs = extract_references(["Please finish FLYWL-2044."])
    routed = route_conversation(
        cwd=str(root),
        routes=build_project_routes(root),
        work_items=build_work_item_routes(root),
        title="Retry fix",
        visible_texts=["Please finish FLYWL-2044."],
        references=refs,
    )

    assert routed["project"] == "los_app_los_django"
    assert routed["work_item"] == "041_retry_fix"
    assert routed["route_source"] == "work_item_reference"


def test_conventional_domain_project_and_work_item_routes(tmp_path: Path) -> None:
    from genomes_agentic_os.conversation_index import build_work_item_routes

    root = tmp_path / "agentic_os"
    project = root / "domains/los/02-projects/los_app_los_django"
    repo = tmp_path / "projects/los-django"
    repo.mkdir(parents=True)
    project.mkdir(parents=True)
    (project / "src").symlink_to(repo)
    (project / "project.yml").write_text("title: LOS Django\n", encoding="utf-8")
    item = project / "work-items/02-active/041_retry_fix"
    item.mkdir(parents=True)
    (item / "work.yml").write_text("id: 041_retry_fix\n", encoding="utf-8")
    (item / "SPEC.md").write_text("Track FLYWL-2044.\n", encoding="utf-8")

    routes = build_project_routes(root)
    assert routes[0]["domain"] == "los"
    assert routes[0]["project"] == "los_app_los_django"

    work_items = build_work_item_routes(root)
    assert work_items[0]["domain"] == "los"
    assert work_items[0]["project"] == "los_app_los_django"
