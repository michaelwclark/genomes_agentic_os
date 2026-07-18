from __future__ import annotations

import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.library import (
    MANIFEST_API_VERSION,
    UNIFIED_REGISTRY,
    apply_legacy_migration,
    canonical_object_id,
    create_object,
    init_library,
    legacy_migration_plan,
    library_doctor,
    object_relative_path,
    query_objects,
    refresh_registry,
)
from genomes_agentic_os.validate import ValidationResult, validate_object_library


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    root.mkdir()
    (root / ".agentic_root").write_text("agentic-os\n", encoding="utf-8")
    return root


def _object(
    root: Path,
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
    entrypoint: str,
) -> Path:
    relative = object_relative_path(
        kind,
        object_id,
        level=level,
        domain=domain,
        project=project,
    )
    target = root / "lib" / relative
    target.mkdir(parents=True, exist_ok=True)
    (target / entrypoint).write_text(f"# {object_id}\n", encoding="utf-8")
    manifest = {
        "api_version": MANIFEST_API_VERSION,
        "kind": kind,
        "id": object_id,
        "title": object_id,
        "description": "Test object.",
        "status": "active",
        "scope": {"level": level, "domain": domain, "project": project},
        "owner": {"type": "operator", "id": "Genome"},
        "entrypoint": entrypoint,
        "tags": [],
        "dependencies": [],
        "aliases": [],
        "runtime": {},
        "validation": {},
    }
    (target / "object.yml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return target


def test_scope_paths_and_ids() -> None:
    assert object_relative_path("program", "one") == Path("programs/root/one")
    assert object_relative_path("workflow", "two", level="domain", domain="los") == Path(
        "workflows/domains/los/two"
    )
    assert object_relative_path(
        "automation",
        "three",
        level="project",
        domain="los",
        project="django",
    ) == Path("automations/domains/los/projects/django/three")
    assert canonical_object_id(
        "automation",
        "three",
        level="project",
        domain="los",
        project="django",
    ) == "automation:project:los:django:three"


def test_init_is_dry_run_first_and_can_initialize_git(tmp_path: Path) -> None:
    root = _root(tmp_path)
    planned = init_library(root, dry_run=True, initialize_git=True)
    assert planned["status"] == "planned"
    assert not (root / "lib").exists()

    applied = init_library(root, dry_run=False, initialize_git=True)
    assert applied["status"] == "initialized"
    assert (root / "lib/.git").exists()
    assert (root / UNIFIED_REGISTRY).is_file()
    assert (
        __import__("subprocess")
        .run(
            ["git", "-C", str(root / "lib"), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        == ".githooks"
    )


def test_create_object_is_dry_run_first_and_refreshes_registry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    planned = create_object(root, "program", "night_shift", domain="los", level="domain")
    assert planned["status"] == "planned"
    assert not (root / "lib/programs/domains/los/night_shift").exists()

    created = create_object(
        root,
        "program",
        "night_shift",
        domain="los",
        level="domain",
        description="Run the night shift.",
        dry_run=False,
    )
    assert created["status"] == "created"
    assert len(query_objects(root, kind="program", domain="los")) == 1


def test_refresh_writes_unified_and_per_type_registries_idempotently(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    _object(root, "skill", "review", entrypoint="SKILL.md")
    _object(root, "program", "delivery", level="domain", domain="los", entrypoint="program.md")

    first = refresh_registry(root, dry_run=False)
    assert first["status"] == "refreshed"
    payload = json.loads((root / UNIFIED_REGISTRY).read_text(encoding="utf-8"))
    assert payload["object_count"] == 2
    assert (root / "lib/registry/skills.yml").is_file()
    assert (root / "lib/registry/programs.yml").is_file()

    second = refresh_registry(root, dry_run=False)
    assert second["status"] == "unchanged"
    assert len(query_objects(root, domain="los")) == 1


def test_doctor_reports_stale_registry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    _object(root, "command", "one", entrypoint="command.md")
    result = library_doctor(root)
    assert result["status"] == "failed"
    assert any(item["code"] == "registry_stale" for item in result["diagnostics"])


def test_definition_change_makes_registry_stale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    target = _object(root, "command", "one", entrypoint="command.md")
    refresh_registry(root, dry_run=False)
    (target / "command.md").write_text("# One\n\nChanged.\n", encoding="utf-8")
    result = library_doctor(root)
    assert any(item["code"] == "registry_stale" for item in result["diagnostics"])


def test_legacy_migration_uses_compact_registry_and_excludes_runtime(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "los/03-workflows/engineering/example"
    source.mkdir(parents=True)
    (source / "workflow.md").write_text("# Example\n\nMigrated workflow.\n", encoding="utf-8")
    (source / "runs").mkdir()
    (source / "runs/result.log").write_text("runtime", encoding="utf-8")
    (source / ".features").mkdir()
    (source / ".features/state.json").write_text("{}", encoding="utf-8")
    (source / "tenant_config_snapshots").mkdir()
    (source / "tenant_config_snapshots/customer.json").write_text("{}", encoding="utf-8")
    (source / "tenant_config_toolkit_outputs").mkdir()
    (source / "tenant_config_toolkit_outputs/result.json").write_text("{}", encoding="utf-8")
    (source / "reports").mkdir()
    (source / "reports/result.md").write_text("runtime", encoding="utf-8")
    (source / "raw").mkdir()
    (source / "raw/evidence.json").write_text("{}", encoding="utf-8")
    (source / "config.toml.bak-20260718").write_text("legacy", encoding="utf-8")
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "kind": "workflow_instance",
                        "native_id": "workflow_instance:los:example",
                        "source": "los/03-workflows/engineering/example",
                        "title": "Example",
                        "summary": "Migrated workflow.",
                        "scope": {"domain": "los", "project": None},
                        "tags": ["workflow"],
                        "subtype": "instance",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    init_library(root, dry_run=False)
    planned = apply_legacy_migration(root, dry_run=True)
    assert planned["candidate_count"] == 1
    assert not (root / "lib/workflows/domains/los/example").exists()

    applied = apply_legacy_migration(root, dry_run=False)
    assert applied["copied"] == 1
    target = root / "lib/workflows/domains/los/example"
    assert (target / "workflow.md").is_file()
    assert not (target / "runs").exists()
    assert not (target / ".features").exists()
    assert not (target / "tenant_config_snapshots").exists()
    assert not (target / "tenant_config_toolkit_outputs").exists()
    assert not (target / "reports").exists()
    assert not (target / "raw").exists()
    assert not (target / "config.toml.bak-20260718").exists()
    manifest = yaml.safe_load((target / "object.yml").read_text(encoding="utf-8"))
    assert manifest["aliases"] == ["los/03-workflows/engineering/example"]
    assert manifest["runtime"]["legacy_roots"] == [
        "los/03-workflows/engineering/example/.features",
        "los/03-workflows/engineering/example/raw",
        "los/03-workflows/engineering/example/reports",
        "los/03-workflows/engineering/example/runs",
        "los/03-workflows/engineering/example/tenant_config_snapshots",
        "los/03-workflows/engineering/example/tenant_config_toolkit_outputs",
    ]


def test_legacy_migration_preserves_registered_empty_object_for_review(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "harness/shared_factory/05-knowledge/templates/thread-lifecycle"
    source.mkdir(parents=True)
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "kind": "template",
                        "native_id": "template:thread-lifecycle",
                        "source": source.relative_to(root).as_posix(),
                        "title": "Thread Lifecycle",
                        "summary": "Registered placeholder.",
                        "scope": {"domain": None, "project": None},
                        "tags": ["template"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    init_library(root, dry_run=False)

    applied = apply_legacy_migration(root, dry_run=False)

    assert applied["copied"] == 1
    target = root / "lib/templates/root/thread-lifecycle"
    assert "had no definition files" in (target / "README.md").read_text(encoding="utf-8")
    manifest = yaml.safe_load((target / "object.yml").read_text(encoding="utf-8"))
    assert manifest["entrypoint"] == "README.md"


def test_domain_references_preserve_same_stem_different_extensions(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"resources": []}\n', encoding="utf-8")
    knowledge = root / "los/05-knowledge"
    knowledge.mkdir(parents=True)
    (root / "los/domain.yml").write_text("name: los\n", encoding="utf-8")
    (knowledge / "team-identities.md").write_text("# Team identities\n", encoding="utf-8")
    (knowledge / "team-identities.yml").write_text("people: []\n", encoding="utf-8")
    plan = legacy_migration_plan(root)
    references = [item for item in plan["objects"] if item["kind"] == "reference"]
    assert {item["id"] for item in references} == {
        "team-identities",
        "team-identities_yml",
    }


def test_library_cli_round_trip(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    assert main(["library", "init", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    _object(root, "hook", "conversation-log", entrypoint="hook.py")
    assert main(["library", "refresh", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    assert main(["library", "list", "--root", str(root), "--kind", "hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1


def test_root_validation_only_enforces_library_after_opt_in(tmp_path: Path) -> None:
    root = _root(tmp_path)
    legacy = ValidationResult(root=root)
    validate_object_library(root, legacy)
    assert legacy.errors == []

    init_library(root, dry_run=False)
    _object(root, "rule", "one", entrypoint="rule.md")
    opted_in = ValidationResult(root=root)
    validate_object_library(root, opted_in)
    assert any("registry_stale" in error for error in opted_in.errors)
