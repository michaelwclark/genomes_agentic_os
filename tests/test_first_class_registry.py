from __future__ import annotations

import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.first_class_registry import (
    API_VERSION,
    REGISTRY_PATH,
    query_first_class_registry,
    refresh_first_class_registry,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _yaml(path: Path, value: object) -> None:
    _write(path, yaml.safe_dump(value, sort_keys=False))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    _write(root / ".agentic_root", "agentic-os\n")
    _write(root / "harness/rules/os-authoring-rules.md", "# Rules\n")
    _yaml(root / "harness/registries/skills.yml", {"skills": [{"id": "review", "name": "Review", "description": "Review work.", "source": "harness/skills/review/SKILL.md"}]})
    _yaml(root / "harness/registries/commands.yml", {"commands": [{"id": "review", "command": "/review", "description": "Review work.", "source": "harness/commands/review.md"}]})
    _yaml(root / "harness/registries/rules.yml", {"rules": []})
    _yaml(root / "harness/registries/reports.yml", {"reports": []})
    _yaml(root / "harness/registries/report-definitions.yml", {"definitions": [{"id": "daily", "name": "Daily report", "summary": "Daily status.", "scope": {"domain": "work", "project": "demo"}}]})
    _write(root / "harness/shared_factory/03-workflows/engineering/review/workflow.md", "# Workflow: Review\n\n## Purpose\n\nReview changes safely.\n")
    _write(root / "work/02-projects/demo/RULES.md", "# Demo rules\n\n## Purpose\n\nProject constraints.\n")
    _yaml(root / "work/02-projects/demo/config/resource-registries/skills.yml", {"skills": [{"id": "demo-helper", "name": "Demo helper", "description": "Project helper.", "source": "work/02-projects/demo/TOOLS.md"}]})
    return root


def test_refresh_materializes_scoped_atomic_registry_and_query_is_snapshot_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = refresh_first_class_registry(root)

    assert payload["api_version"] == API_VERSION
    target = root / REGISTRY_PATH
    assert target.is_file()
    assert not list(target.parent.glob(".*.tmp"))
    by_id = {item["id"]: item for item in payload["resources"]}
    assert by_id["workflow:harness:shared_factory:03-workflows:engineering:review:workflow.md"]["scope"] == {"domain": "shared_factory", "project": None}
    project_skill = next(item for item in payload["resources"] if item["native_id"] == "demo-helper")
    assert project_skill["scope"] == {"domain": "work", "project": "demo"}
    report = next(item for item in payload["resources"] if item["native_id"] == "daily")
    assert report["id"] == "report:typed:definition:daily"

    # Prove a normal query does not rediscover the tree: remove a source after refresh.
    (root / "harness/registries/skills.yml").unlink()
    queried = query_first_class_registry(root, kind="skill")
    assert {item["native_id"] for item in queried["resources"]} == {"review", "demo-helper"}
    assert queried["fingerprint"] == payload["fingerprint"]


def test_refresh_excludes_templates_artifacts_and_worktrees(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for excluded in ("templates", "artifacts", "worktrees", "logs"):
        _write(root / f"work/{excluded}/bad/workflow.md", "# Workflow: Must not load\n")
    payload = refresh_first_class_registry(root)
    sources = {item["source"] for item in payload["resources"]}
    assert not any("/bad/workflow.md" in source for source in sources)


def test_cli_refresh_then_filtered_query(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    assert main(["resource-registry", "refresh", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["resource-registry", "query", "--kind", "workflow", "--domain", "shared_factory", "--root", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["query"]["kind"] == "workflow"
    assert [item["native_id"] for item in result["resources"]] == ["review"]
