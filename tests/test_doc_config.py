from __future__ import annotations

import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root, validate_schemas_strict


def test_doc_config_installs_and_plans_questions_bucket(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert (root / "harness" / "shared_factory" / "00-control-plane" / "doc-config.yml").is_file()
    assert (root / "harness" / "commands" / "os-add-spec.md").is_file()
    assert (root / "harness" / "commands" / "os-new-feature.md").is_file()
    assert (root / "harness" / "commands" / "os-add-bug.md").is_file()
    assert (root / "harness" / "commands" / "os-auto-add-spec.md").is_file()
    assert (root / "harness" / "commands" / "os-auto-add-feature.md").is_file()
    assert (root / "harness" / "commands" / "os-notion-org.md").is_file()
    assert (root / "harness" / "commands" / "os-quiet-run.md").is_file()
    assert (root / "harness" / "bin" / "agentic-os-quiet-run").is_file()
    assert (root / "harness" / "skills" / "spec-intake-router" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "feature-intake-router" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "bug-intake-router" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "auto-spec-intake" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "auto-feature-intake" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "os-authoring-guard" / "SKILL.md").is_file()
    assert (root / "harness" / "skills" / "quiet-async-runner" / "SKILL.md").is_file()
    assert (root / "harness" / "rules" / "os-authoring-rules.md").is_file()
    assert (root / "harness" / "shared_factory" / "04-workflows" / "spec-intake.md").is_file()
    assert (root / "harness" / "shared_factory" / "04-workflows" / "feature-intake.md").is_file()
    assert (root / "harness" / "shared_factory" / "04-workflows" / "bug-intake.md").is_file()
    assert (root / "harness" / "shared_factory" / "00-control-plane" / "notion-organization.yml").is_file()
    assert (root / "harness" / "shared_factory" / "05-knowledge" / "rules" / "os-authoring-rules.md").is_file()

    assert main(["doc-config", "doctor", "--root", str(root)]) == 0
    doctor = yaml.safe_load(capsys.readouterr().out)
    assert {"config", "ripgrep", "notion", "memory"} <= set(doctor["enabled_search_methods"])

    assert (
        main(
            [
                "doc-config",
                "plan",
                "--root",
                str(root),
                "--request",
                "Add this to Notion with open questions",
                "--domain",
                "work",
                "--project",
                "genomes_agentic_os",
                "--work-item",
                "doc_config_system",
                "--questions-present",
            ]
        )
        == 0
    )
    plan = yaml.safe_load(capsys.readouterr().out)
    titles = [bucket["title"] for bucket in plan["buckets"]]
    assert "QUESTIONS" in titles
    assert "FEATURES" not in titles
    assert "IDEA" not in titles
    assert plan["destination"]["notion_path"] == "Projects -> Genome's Agentic OS -> Specs -> doc_config_system"
    assert plan["target_kind"] == "spec"
    assert plan["source_of_truth"] == "filesystem"
    assert plan["filesystem_mirror"]["authority"] == "project_work_item"
    assert plan["filesystem_mirror"]["avoid_project_features_dir"] is True
    assert "worktrees/index.yml" in plan["filesystem_mirror"]["worktree_requirement"]
    assert plan["notion"]["style"]["use_color_variation"] is True
    assert validate_schemas_strict(root) == []
    assert validate_root(root).ok


def test_project_doc_config_override_can_disable_any_search_method(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "work", "genomes_agentic_os", "--root", str(root)]) == 0
    assert (
        main(
            [
                "doc-config",
                "init",
                "--root",
                str(root),
                "--domain",
                "work",
                "--project",
                "genomes_agentic_os",
            ]
        )
        == 0
    )
    override_path = root / "domains" / "work" / "02-projects" / "genomes_agentic_os" / "config" / "doc-config.yml"
    config = yaml.safe_load(override_path.read_text(encoding="utf-8"))
    config["search_methods"]["ripgrep"]["enabled"] = False
    config["search_methods"]["context_mode"]["enabled"] = False
    override_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    assert (
        main(
            [
                "doc-config",
                "plan",
                "--root",
                str(root),
                "--request",
                "Add this to notion",
                "--domain",
                "work",
                "--project",
                "genomes_agentic_os",
            ]
        )
        == 0
    )
    plan = yaml.safe_load(capsys.readouterr().out)
    enabled = {method["id"] for method in plan["search_methods"]["enabled"]}
    assert "ripgrep" not in enabled
    assert "context_mode" not in enabled
    assert {"ripgrep", "context_mode"} <= set(plan["search_methods"]["disabled"])
    assert validate_schemas_strict(root) == []


def test_docs_update_merges_doc_config_registry_entries(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    commands_path = root / "harness" / "registries" / "commands.yml"
    skills_path = root / "harness" / "registries" / "skills.yml"
    commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    skills = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "doc-config"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "notion-org"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "add-spec"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "groom-spec"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "new-feature"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "add-feature"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "add-bug"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "auto-add-spec"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "auto-add-feature"]
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "quiet-run"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "doc-config-router"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "spec-intake-router"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "spec-groomer"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "feature-intake-router"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "bug-intake-router"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "auto-spec-intake"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "auto-feature-intake"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "os-authoring-guard"]
    skills["skills"] = [entry for entry in skills["skills"] if entry.get("id") != "quiet-async-runner"]
    for entry in commands["commands"]:
        if entry.get("id") == "make-workflow":
            entry["source"] = "commands/os-create-workflow.md"
        if entry.get("id") == "make-automation":
            entry["source"] = "commands/os-create-automation.md"
    for entry in skills["skills"]:
        if entry.get("id") == "os-navigator":
            entry["source"] = "skills/os-navigator/SKILL.md"
        if entry.get("id") == "workflow-builder":
            entry["source"] = "skills/workflow-builder/SKILL.md"
        if entry.get("id") == "automation-qualifier":
            entry["source"] = "skills/automation-qualifier/SKILL.md"
    commands_path.write_text(yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")
    skills_path.write_text(yaml.safe_dump(skills, sort_keys=False), encoding="utf-8")

    assert main(["docs", "update", "--root", str(root)]) == 0

    updated_commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    updated_skills = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
    assert any(entry.get("id") == "doc-config" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "notion-org" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "add-spec" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "groom-spec" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "new-feature" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "add-feature" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "add-bug" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "auto-add-spec" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "auto-add-feature" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "quiet-run" for entry in updated_commands["commands"])
    assert any(entry.get("id") == "doc-config-router" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "spec-intake-router" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "spec-groomer" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "feature-intake-router" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "bug-intake-router" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "auto-spec-intake" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "auto-feature-intake" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "os-authoring-guard" for entry in updated_skills["skills"])
    assert any(entry.get("id") == "quiet-async-runner" for entry in updated_skills["skills"])
    assert any(
        entry.get("id") == "make-workflow" and entry.get("source") == "harness/commands/os-create-workflow.md"
        for entry in updated_commands["commands"]
    )
    assert any(
        entry.get("id") == "make-automation" and entry.get("source") == "harness/commands/os-create-automation.md"
        for entry in updated_commands["commands"]
    )
    assert any(
        entry.get("id") == "os-navigator" and entry.get("source") == "harness/skills/os-navigator/SKILL.md"
        for entry in updated_skills["skills"]
    )
    assert any(
        entry.get("id") == "workflow-builder" and entry.get("source") == "harness/skills/workflow-builder/SKILL.md"
        for entry in updated_skills["skills"]
    )
    assert any(
        entry.get("id") == "automation-qualifier"
        and entry.get("source") == "harness/skills/automation-qualifier/SKILL.md"
        for entry in updated_skills["skills"]
    )


def test_add_spec_command_uses_canonical_spec_engine_intake(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    command = (root / "harness" / "commands" / "os-add-spec.md").read_text(encoding="utf-8")
    legacy_command = (root / "harness" / "commands" / "os-new-feature.md").read_text(encoding="utf-8")
    skill = (root / "harness" / "skills" / "spec-intake-router" / "SKILL.md").read_text(encoding="utf-8")
    engine_skill = (root / "harness" / "skills" / "spec-engine" / "SKILL.md").read_text(encoding="utf-8")
    legacy_skill = (root / "harness" / "skills" / "feature-intake-router" / "SKILL.md").read_text(encoding="utf-8")
    workflow = (
        root / "harness" / "shared_factory" / "04-workflows" / "spec-intake.md"
    ).read_text(encoding="utf-8")

    assert "/add-spec" in command
    assert "/new-feature" in legacy_command
    assert "typed adapters for `/add-spec`" in legacy_command
    assert "agentic-os spec add" in command
    assert "bug|feature|config" in command
    assert "idea|grooming|blocked|ready|in_progress|built" in command
    assert "Compatibility adapter" in skill
    assert "agentic-os spec add" in skill
    assert "spec-engine/SKILL.md" in legacy_skill
    assert "blocked_from" in engine_skill
    assert "Notion" in engine_skill and "neither is an implicit lifecycle" in engine_skill
    assert "Trigger Phrases" in workflow
    assert "/add-spec" in workflow
    assert "/new-idea" in workflow
    assert "Do not use Notion as a mandatory queue" in command
    assert "project Jira/Linear intake rules" in command
    assert "filesystem|linear|jira" in command


def test_notion_org_doctor_checks_filesystem_and_backup_snapshot(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    backup_dir = tmp_path / "notion-backup"
    backup_dir.mkdir()
    snapshot_path = backup_dir / "los.json"
    snapshot = {
        "root_id": "root",
        "page_count": 1,
        "database_count": 0,
        "pages": {
            "root": {
                "blocks": [
                    {"id": "child-1", "type": "child_page", "child_page": {"title": "Random Old Page"}},
                ]
            }
        },
    }
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    (backup_dir / "manifest.json").write_text(json.dumps([{"file": str(snapshot_path)}]), encoding="utf-8")

    assert main(["notion-org", "doctor", "--root", str(root), "--backup-dir", str(backup_dir)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["expected_workspace"] == "Genome's Notion"
    assert "Specs" in result["canonical_buckets"]
    assert result["notion_backup"]["roots"][0]["direct_child_pages"] == 1
    assert any("canonical buckets" in item["message"] for item in result["findings"])


def test_convention_policy_installed_and_registered(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    convention_path = root / "harness" / "shared_factory" / "05-knowledge" / "references" / "os-conventions.md"
    authoring_rules = root / "harness" / "rules" / "os-authoring-rules.md"
    shared_authoring_rules = root / "harness" / "shared_factory" / "05-knowledge" / "rules" / "os-authoring-rules.md"
    rules_path = root / "harness" / "registries" / "rules.yml"
    commands_path = root / "harness" / "registries" / "commands.yml"
    skills_path = root / "harness" / "registries" / "skills.yml"

    assert convention_path.is_file()
    assert authoring_rules.is_file()
    assert shared_authoring_rules.is_file()
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    skills = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
    assert any(entry["id"] == "agentic-os-convention-authoring" for entry in rules["rules"])
    assert any(entry["source"] == "harness/rules/os-authoring-rules.md" for entry in rules["rules"])
    command_sources = {entry["source"] for entry in commands["commands"]}
    skill_sources = {entry["source"] for entry in skills["skills"]}
    assert {
        path.relative_to(root).as_posix()
        for path in (root / "harness" / "commands").glob("*.md")
        if path.name != "README.md"
    } <= command_sources
    assert {
        path.relative_to(root).as_posix()
        for path in (root / "harness" / "skills").glob("*/SKILL.md")
    } <= skill_sources
    assert validate_root(root).ok


def test_validate_reports_unregistered_command_and_skill_docs(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    commands_path = root / "harness" / "registries" / "commands.yml"
    skills_path = root / "harness" / "registries" / "skills.yml"
    commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    skills = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
    commands["commands"] = [
        entry for entry in commands["commands"] if entry.get("source") != "harness/commands/os-new-feature.md"
    ]
    skills["skills"] = [
        entry for entry in skills["skills"] if entry.get("source") != "harness/skills/feature-intake-router/SKILL.md"
    ]
    commands_path.write_text(yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")
    skills_path.write_text(yaml.safe_dump(skills, sort_keys=False), encoding="utf-8")

    result = validate_root(root)
    assert not result.ok
    assert any("command doc missing registry entry" in error for error in result.errors)
    assert any("skill doc missing registry entry" in error for error in result.errors)


def test_doc_config_doctor_fails_when_all_search_methods_are_disabled(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    config_path = root / "harness" / "shared_factory" / "00-control-plane" / "doc-config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for method in config["search_methods"].values():
        method["enabled"] = False
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    assert main(["doc-config", "doctor", "--root", str(root)]) == 1
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["ok"] is False
    assert any("at least one search method" in item["message"] for item in result["findings"])


def test_doc_config_plan_infers_work_area_from_request(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "work", "genomes_agentic_os", "--root", str(root)]) == 0

    assert (
        main(
            [
                "doc-config",
                "plan",
                "--root",
                str(root),
                "--request",
                "Add this Agentic OS doc config convention to Notion",
            ]
        )
        == 0
    )
    plan = yaml.safe_load(capsys.readouterr().out)
    assert plan["destination"]["work_area"] == "genomes_agentic_os"
    assert plan["destination"]["work_area_confidence"] == "high"
    assert plan["destination"]["domain"] == "work"
    assert plan["destination"]["project"] == "genomes_agentic_os"
    assert plan["destination"]["notion_path"] == "Projects -> Genome's Agentic OS -> Specs"
