from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.cli import main


def test_doc_config_cli_installs_doctors_and_plans_questions(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    assert (root / "harness/shared_factory/00-control-plane/doc-config.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/templates/runtime/doc-config.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/commands/os-doc-config.md").is_file()

    capsys.readouterr()
    assert main(["doc-config", "doctor", "--root", str(root)]) == 0
    doctor = yaml.safe_load(capsys.readouterr().out)
    assert doctor["ok"] is True
    assert set(doctor["enabled_search_methods"]) >= {
        "config",
        "markdown",
        "ripgrep",
        "filesystem",
        "notion",
        "context_mode",
        "memory",
    }

    assert (
        main(
            [
                "doc-config",
                "plan",
                "--root",
                str(root),
                "--request",
                "Create a workflow spec with open questions",
                "--domain",
                "work",
                "--project",
                "genomes_agentic_os",
                "--questions-present",
            ]
        )
        == 0
    )
    plan = yaml.safe_load(capsys.readouterr().out)
    bucket_titles = {bucket["title"] for bucket in plan["buckets"]}
    plan_bucket = next(bucket for bucket in plan["buckets"] if bucket["title"] == "PLAN")
    assert "QUESTIONS" in bucket_titles
    assert "PLANS" in plan_bucket["aliases"]
    assert plan["destination"]["notion_namespace"] == "Specs"
    assert "Features" in plan["destination"]["compatibility_namespaces"]


def test_notion_org_doctor_installed_and_safe_by_default(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "index.yml").write_text("pages: []\n", encoding="utf-8")

    assert main(["init", "--target", str(root)]) == 0

    assert (root / "harness/shared_factory/00-control-plane/notion-organization.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/templates/runtime/notion-organization.yml").is_file()
    assert (root / "harness/shared_factory/05-knowledge/commands/os-notion-org.md").is_file()

    capsys.readouterr()
    assert main(["notion-org", "doctor", "--root", str(root), "--backup-dir", str(backup)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["workspace"] == "Genome's Notion"
    assert result["live_moves_allowed"] is False
    assert "Specs" in result["project_buckets"]
