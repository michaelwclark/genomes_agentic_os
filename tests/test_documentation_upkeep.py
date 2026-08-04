from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.cli import main


def _seed_documentation_sources(root: Path) -> None:
    config_path = root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for entry in config["registry"]:
        for source in entry["sources"]:
            source_path = root / source
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(f"# {source}\n", encoding="utf-8")


def test_documentation_upkeep_installs_and_reports_drift(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    assert (root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/templates/runtime/documentation-upkeep.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/commands/os-docs-upkeep.md").is_file()
    _seed_documentation_sources(root)

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["ok"] is True
    assert result["mode"] == "observe"
    assert result["notion_writes"] is False
    assert result["entry_count"] == 2
    assert result["counts"]["stale"] == 2
    assert {entry["status"] for entry in result["entries"]} == {"stale"}


def test_documentation_upkeep_detects_unchanged_hashes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    _seed_documentation_sources(root)

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    first_result = yaml.safe_load(capsys.readouterr().out)
    hashes_by_id = {entry["id"]: entry["source_hash"] for entry in first_result["entries"]}

    config_path = root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for entry in config["registry"]:
        entry["last_source_hash"] = hashes_by_id[entry["id"]]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    second_result = yaml.safe_load(capsys.readouterr().out)

    assert second_result["counts"]["unchanged"] == 2
    assert {entry["status"] for entry in second_result["entries"]} == {"unchanged"}


def test_documentation_upkeep_writes_receipt_files(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    receipt_dir = tmp_path / "receipts"

    assert main(["init", "--target", str(root)]) == 0

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root), "--write-receipt", "--output-dir", str(receipt_dir)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["receipt_dir"] == str(receipt_dir)
    assert (receipt_dir / "documentation-upkeep-report.yml").is_file()
    assert (receipt_dir / "documentation-upkeep-report.md").is_file()


def test_documentation_upkeep_falls_back_to_installed_template(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    _seed_documentation_sources(root)
    config_path = root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml"
    config_path.unlink()

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["ok"] is True
    assert result["config_path"].endswith("harness/shared_factory/05-knowledge/templates/runtime/documentation-upkeep.yml")
    assert result["entry_count"] == 2


def test_documentation_upkeep_requires_site_delivery_or_a_rubicon_follow_up(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    config_path = root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml"
    source = root / "harness/skills/example/SKILL.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# example\n", encoding="utf-8")
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "documentation_upkeep",
                "mode": "observe",
                "registry": [
                    {
                        "id": "missing_site_destination",
                        "scope": "workflow",
                        "title": "Example workflow documentation",
                        "sources": ["harness/skills/example/SKILL.md"],
                        "target": {"system": "notion", "path": "Programs -> Example"},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    delivery = result["entries"][0]["documentation_site_delivery"]
    assert delivery["status"] == "follow_up_required"
    assert delivery["follow_up"]["provider"] == "linear"
    assert delivery["follow_up"]["project"] == "Rubicon: Documentation"
    assert result["linear_writes"] is False
    assert result["follow_up_requests"] == [delivery["follow_up"]]


def test_documentation_upkeep_accepts_a_published_site_path(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    source = root / "harness/skills/example/SKILL.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# example\n", encoding="utf-8")
    config_path = root / "harness/shared_factory/00-control-plane/documentation-upkeep.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "documentation_upkeep",
                "mode": "observe",
                "registry": [
                    {
                        "id": "published_site_destination",
                        "scope": "workflow",
                        "title": "Example workflow documentation",
                        "sources": ["harness/skills/example/SKILL.md"],
                        "target": {
                            "system": "github_pages",
                            "path": "Reference -> Example",
                            "site_path": "docs/example.md",
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    capsys.readouterr()
    assert main(["docs", "upkeep", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    delivery = result["entries"][0]["documentation_site_delivery"]
    assert delivery == {
        "status": "required",
        "site_paths": ["docs/example.md"],
        "validation": "npm --prefix website run build",
    }
    assert result["counts"]["site_delivery_required"] == 1
