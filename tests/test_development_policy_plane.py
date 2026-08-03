from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from genomes_agentic_os.development_delivery import (
    DevelopmentDeliveryError,
    resolve_development_policy,
    resolve_development_policies,
    start_development_run,
)
from genomes_agentic_os.scaffold import (
    AUTO_DEV_POLICY_COMPATIBILITY_BREADCRUMB,
    ScaffoldResult,
    create_project,
    migrate_auto_dev_policy_directories,
)


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    _git("init", "--bare", str(remote))
    repo = tmp_path / "repo"
    _git("init", "-b", "main", str(repo))
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)
    root = tmp_path / "os"
    create_project(root, "acme", "app", repo=str(repo))
    project = root / "domains/acme/02-projects/app"
    profile = {
        "version": 1,
        "enabled": True,
        "tracker": {"primary": "filesystem"},
        "repository": {"root": str(repo), "base_branch": "main"},
        "worktrees": {"directory": "worktrees", "branch_template": "feature/{ticket}-{slug}"},
        "work_items": {"active_status": "building"},
        "runtime": {"ownership": "not_managed", "provider": "none", "identity": "not-managed"},
        "validation": {"commands": [], "test_policy": "risk_based_triangle"},
        "review": {"opposing_harness": {"required": True}},
        "merge": {"policy": "never_auto"},
        "recovery": {"max_attempts": 2, "lease_minutes": 30, "stale_after_minutes": 45},
    }
    (project / "config/development.yml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return root, project


def test_conventional_root_domain_project_files_are_dynamic_and_receipted(tmp_path: Path) -> None:
    root, project = _tree(tmp_path)
    paths = [
        root / "harness/shared_factory/05-knowledge/auto_dev/dev_standards/10_root.md",
        root / "domains/acme/config/auto_dev/dev_standards/20_domain.md",
        project / "config/auto_dev/dev_standards/30_project.md",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    first = resolve_development_policy(root, "acme", "app", "dev_standards")
    refs = [item["source_ref"] for item in first["sources"]]
    assert "harness/shared_factory/05-knowledge/auto_dev/dev_standards/10_root.md" in refs
    assert "domains/acme/config/auto_dev/dev_standards/20_domain.md" in refs
    assert "domains/acme/02-projects/app/config/auto_dev/dev_standards/30_project.md" in refs
    assert refs.index("harness/shared_factory/05-knowledge/auto_dev/dev_standards/10_root.md") < refs.index(
        "domains/acme/config/auto_dev/dev_standards/20_domain.md"
    ) < refs.index("domains/acme/02-projects/app/config/auto_dev/dev_standards/30_project.md")
    added = project / "config/auto_dev/dev_standards/40_new_focus.md"
    added.write_text("# New Focus\n", encoding="utf-8")
    second = resolve_development_policy(root, "acme", "app", "dev_standards")
    assert second["fingerprint"] != first["fingerprint"]
    assert second["counts"]["sources"] == first["counts"]["sources"] + 1

    plan = start_development_run(root, "acme", "app", ["ENG-1"], run_id="policy-run", apply=False)
    assert plan["policy_fingerprint"]
    assert plan["policy_sources"]["dev_standards"][-1].endswith("40_new_focus.md")


def test_domain_config_auto_dev_overrides_legacy_domain_knowledge_policy(
    tmp_path: Path,
) -> None:
    root, _ = _tree(tmp_path)
    legacy = root / "domains/acme/05-knowledge/auto_dev/qa_gates/10-legacy.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("# Legacy domain QA\n", encoding="utf-8")

    legacy_result = resolve_development_policy(root, "acme", "app", "qa_gates")
    assert legacy.relative_to(root).as_posix() in {
        item["source_ref"] for item in legacy_result["sources"]
    }

    canonical = root / "domains/acme/config/auto_dev/qa_gates/10-canonical.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("# Canonical domain QA\n", encoding="utf-8")

    canonical_result = resolve_development_policy(root, "acme", "app", "qa_gates")
    refs = {item["source_ref"] for item in canonical_result["sources"]}
    assert canonical.relative_to(root).as_posix() in refs
    assert legacy.relative_to(root).as_posix() not in refs


def test_explicit_legacy_domain_policy_path_normalizes_to_domain_config(
    tmp_path: Path,
) -> None:
    root, project = _tree(tmp_path)
    canonical = root / "domains/acme/config/auto_dev/dev_standards/10-canonical.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("# Canonical domain standard\n", encoding="utf-8")
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["policies"] = {
        "dev_standards": {
            "paths": ["domains/acme/05-knowledge/auto_dev/dev_standards"]
        }
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    resolved = resolve_development_policy(root, "acme", "app", "dev_standards")
    assert canonical.relative_to(root).as_posix() in {
        item["source_ref"] for item in resolved["sources"]
    }


def test_auto_dev_parent_does_not_duplicate_nested_policy_planes(tmp_path: Path) -> None:
    root, project = _tree(tmp_path)
    workflow = project / "config/auto_dev/10-workflow.md"
    nested_workflow = project / "config/auto_dev/release/20-release.md"
    development = project / "config/auto_dev/dev_standards/10-development.md"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    nested_workflow.parent.mkdir(parents=True, exist_ok=True)
    development.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("# Workflow\n", encoding="utf-8")
    nested_workflow.write_text("# Release workflow\n", encoding="utf-8")
    development.write_text("# Development\n", encoding="utf-8")

    auto_dev = resolve_development_policy(root, "acme", "app", "auto_dev")
    dev_standards = resolve_development_policy(root, "acme", "app", "dev_standards")

    auto_dev_refs = {item["source_ref"] for item in auto_dev["sources"]}
    dev_refs = {item["source_ref"] for item in dev_standards["sources"]}
    assert workflow.relative_to(root).as_posix() in auto_dev_refs
    assert nested_workflow.relative_to(root).as_posix() in auto_dev_refs
    assert development.relative_to(root).as_posix() not in auto_dev_refs
    assert development.relative_to(root).as_posix() in dev_refs
    development.write_text("# Changed development\n", encoding="utf-8")
    assert (
        resolve_development_policy(root, "acme", "app", "auto_dev")["fingerprint"]
        == auto_dev["fingerprint"]
    )
    assert (
        resolve_development_policy(root, "acme", "app", "dev_standards")["fingerprint"]
        != dev_standards["fingerprint"]
    )


def test_conventional_policy_uses_legacy_directory_only_when_canonical_is_absent(
    tmp_path: Path,
) -> None:
    root, project = _tree(tmp_path)
    legacy = project / "config/qa_gates/10-legacy.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("# Legacy\n", encoding="utf-8")

    legacy_result = resolve_development_policy(root, "acme", "app", "qa_gates")
    assert legacy.relative_to(root).as_posix() in {
        item["source_ref"] for item in legacy_result["sources"]
    }

    canonical = project / "config/auto_dev/qa_gates/10-canonical.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("# Canonical\n", encoding="utf-8")
    canonical_result = resolve_development_policy(root, "acme", "app", "qa_gates")
    canonical_refs = {item["source_ref"] for item in canonical_result["sources"]}
    assert canonical.relative_to(root).as_posix() in canonical_refs
    assert legacy.relative_to(root).as_posix() not in canonical_refs


def test_configured_legacy_conventional_member_normalizes_without_changing_custom_paths(
    tmp_path: Path,
) -> None:
    root, project = _tree(tmp_path)
    canonical = (
        root
        / "harness/shared_factory/05-knowledge/auto_dev/dev_standards/10-canonical.md"
    )
    custom = project / "config/custom-development/20-custom.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    custom.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("# Canonical\n", encoding="utf-8")
    custom.write_text("# Custom\n", encoding="utf-8")
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["policies"] = {
        "dev_standards": {
            "paths": [
                "harness/shared_factory/05-knowledge/dev_standards",
                "config/custom-development",
            ]
        }
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    resolved = resolve_development_policy(root, "acme", "app", "dev_standards")
    refs = {item["source_ref"] for item in resolved["sources"]}
    assert canonical.relative_to(root).as_posix() in refs
    assert custom.relative_to(root).as_posix() in refs


def test_policy_directory_migration_is_idempotent(tmp_path: Path) -> None:
    parent = tmp_path / "config"
    legacy = parent / "dev_standards/10-standard.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Standard\n", encoding="utf-8")
    result = ScaffoldResult()

    migrate_auto_dev_policy_directories(parent, result)
    canonical = parent / "auto_dev/dev_standards/10-standard.md"

    assert canonical.read_text(encoding="utf-8") == "# Standard\n"
    assert not (parent / "dev_standards").exists()
    migrate_auto_dev_policy_directories(parent, ScaffoldResult())
    assert canonical.is_file()


@pytest.mark.parametrize(
    ("legacy_content", "canonical_content"),
    (
        ("# Identical index\n", "# Identical index\n"),
        (AUTO_DEV_POLICY_COMPATIBILITY_BREADCRUMB, "# Canonical index\n"),
    ),
)
def test_policy_directory_migration_collapses_only_safe_readme_collisions(
    tmp_path: Path,
    legacy_content: str,
    canonical_content: str,
) -> None:
    parent = tmp_path / "config"
    legacy_readme = parent / "dev_standards/README.md"
    legacy_policy = parent / "dev_standards/10-standard.md"
    canonical_readme = parent / "auto_dev/dev_standards/README.md"
    legacy_readme.parent.mkdir(parents=True)
    canonical_readme.parent.mkdir(parents=True)
    legacy_readme.write_text(legacy_content, encoding="utf-8")
    legacy_policy.write_text("# Standard\n", encoding="utf-8")
    canonical_readme.write_text(canonical_content, encoding="utf-8")

    migrate_auto_dev_policy_directories(parent, ScaffoldResult())

    assert canonical_readme.read_text(encoding="utf-8") == canonical_content
    assert (parent / "auto_dev/dev_standards/10-standard.md").is_file()
    assert not (parent / "dev_standards").exists()


def test_policy_directory_migration_preserves_user_readme_conflict_atomically(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "config"
    movable = parent / "dev_standards/10-movable.md"
    legacy_readme = parent / "qa_gates/README.md"
    canonical_readme = parent / "auto_dev/qa_gates/README.md"
    movable.parent.mkdir(parents=True)
    legacy_readme.parent.mkdir(parents=True)
    canonical_readme.parent.mkdir(parents=True)
    movable.write_text("# Movable\n", encoding="utf-8")
    legacy_readme.write_text("# Team-authored QA notes\n", encoding="utf-8")
    canonical_readme.write_text("# Canonical QA index\n", encoding="utf-8")

    with pytest.raises(ValueError, match="migration conflict"):
        migrate_auto_dev_policy_directories(parent, ScaffoldResult())

    assert movable.read_text(encoding="utf-8") == "# Movable\n"
    assert legacy_readme.read_text(encoding="utf-8") == "# Team-authored QA notes\n"
    assert canonical_readme.read_text(encoding="utf-8") == "# Canonical QA index\n"
    assert not (parent / "auto_dev/dev_standards/10-movable.md").exists()


def test_policy_directory_migration_preflights_all_conflicts(tmp_path: Path) -> None:
    parent = tmp_path / "config"
    movable = parent / "dev_standards/10-movable.md"
    conflict = parent / "qa_gates/10-conflict.md"
    canonical_conflict = parent / "auto_dev/qa_gates/10-conflict.md"
    movable.parent.mkdir(parents=True)
    conflict.parent.mkdir(parents=True)
    canonical_conflict.parent.mkdir(parents=True)
    movable.write_text("# Movable\n", encoding="utf-8")
    conflict.write_text("# Old\n", encoding="utf-8")
    canonical_conflict.write_text("# New\n", encoding="utf-8")

    with pytest.raises(ValueError, match="migration conflict"):
        migrate_auto_dev_policy_directories(parent, ScaffoldResult())

    assert movable.is_file()
    assert conflict.is_file()
    assert not (parent / "auto_dev/dev_standards/10-movable.md").exists()


def test_repository_folder_profile_is_required_and_fingerprinted_overlay(
    tmp_path: Path,
) -> None:
    root, project = _tree(tmp_path)
    profile = yaml.safe_load(
        (project / "config/development.yml").read_text(encoding="utf-8")
    )
    repo = Path(profile["repository"]["root"])
    folder_profile = repo / "auto_dev/profile.yml"
    folder_profile.parent.mkdir(parents=True)
    contract = {
        "api_version": "auto-dev-folder/v1",
        "identity": {"domain": "acme", "project": "app"},
        "lifecycle": {
            "build": {"command": "make build"},
            "validate": {"commands": ["make test"]},
            "release": {"required": True},
            "document": {"required": True},
        },
    }
    folder_profile.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")

    first = resolve_development_policies(root, "acme", "app")
    assert first["folder_profile"]["status"] == "loaded"
    assert first["folder_profile"]["source_ref"] == "auto_dev/profile.yml"
    assert first["folder_profile"]["identity"] == {
        "domain": "acme",
        "project": "app",
    }

    contract["lifecycle"]["build"]["command"] = "make package"
    folder_profile.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    second = resolve_development_policies(root, "acme", "app")
    assert second["fingerprint"] != first["fingerprint"]


@pytest.mark.parametrize(
    ("identity", "message"),
    (
        ({"domain": "other", "project": "app"}, "identity.domain does not match"),
        ({"domain": "acme", "project": "other"}, "identity.project does not match"),
        ({"project": "app"}, "identity.domain is required"),
        ({"domain": "acme"}, "identity.project is required"),
    ),
)
def test_repository_folder_profile_rejects_misrouted_identity(
    tmp_path: Path,
    identity: dict[str, str],
    message: str,
) -> None:
    root, project = _tree(tmp_path)
    profile = yaml.safe_load(
        (project / "config/development.yml").read_text(encoding="utf-8")
    )
    repo = Path(profile["repository"]["root"])
    folder_profile = repo / "auto_dev/profile.yml"
    folder_profile.parent.mkdir(parents=True)
    folder_profile.write_text(
        yaml.safe_dump(
            {
                "api_version": "auto-dev-folder/v1",
                "identity": identity,
                "lifecycle": {
                    "build": {"command": "make build"},
                    "validate": {"commands": ["make test"]},
                    "release": {"required": True},
                    "document": {"required": True},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(DevelopmentDeliveryError, match=message):
        resolve_development_policies(root, "acme", "app")


def test_snake_case_command_resolves_recovered_kebab_case_project_room(tmp_path: Path) -> None:
    root, project = _tree(tmp_path)
    legacy_project = project.parent / "legacy-app"
    project.rename(legacy_project)
    policy = legacy_project / "config/auto_dev/10-legacy.md"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("# Legacy project policy\n", encoding="utf-8")

    resolved = resolve_development_policy(root, "acme", "legacy_app", "auto_dev")

    assert resolved["project"] == "legacy_app"
    assert resolved["sources"][-1]["source_ref"].endswith(
        "domains/acme/02-projects/legacy-app/config/auto_dev/10-legacy.md"
    )


def test_policy_readback_works_before_repository_onboarding(tmp_path: Path) -> None:
    root = tmp_path / "os"
    create_project(root, "acme", "unrooted")
    project = root / "domains/acme/02-projects/unrooted"
    policy = project / "config/auto_dev/10-unrooted.md"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        "# Unrooted project policy\n\nReadiness blocks until a repository is verified.\n",
        encoding="utf-8",
    )

    resolved = resolve_development_policy(root, "acme", "unrooted", "auto_dev")

    assert resolved["project"] == "unrooted"
    assert resolved["sources"][-1]["source_ref"].endswith(
        "domains/acme/02-projects/unrooted/config/auto_dev/10-unrooted.md"
    )
    with pytest.raises(DevelopmentDeliveryError, match="repository.root or repository.catalog"):
        start_development_run(root, "acme", "unrooted", ["ENG-3"], apply=False)


def test_applied_run_pins_policy_snapshot_and_reports_later_drift(tmp_path: Path) -> None:
    root, project = _tree(tmp_path)
    policy = project / "config/auto_dev/dev_standards/10_project.md"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("# Initial standard\n", encoding="utf-8")

    first = start_development_run(root, "acme", "app", ["ENG-2"], run_id="pinned-policy", apply=True)
    snapshot_path = project / "state/development-runs/pinned-policy/effective-policies.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["planes"]["dev_standards"]["sources"][-1]["body_markdown"] == "# Initial standard\n"

    policy.write_text("# Changed standard\n", encoding="utf-8")
    resumed = start_development_run(root, "acme", "app", ["ENG-2"], run_id="pinned-policy", apply=True)

    assert first["policy_fingerprint"] == snapshot["fingerprint"]
    assert resumed["policy_drift"]["run_fingerprint"] == snapshot["fingerprint"]
    assert resumed["policy_drift"]["current_fingerprint"] != snapshot["fingerprint"]
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == snapshot
