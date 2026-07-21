from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from genomes_agentic_os.development_delivery import (
    DevelopmentDeliveryError,
    resolve_development_policy,
    start_development_run,
)
from genomes_agentic_os.scaffold import create_project


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
        root / "harness/shared_factory/05-knowledge/dev_standards/10_root.md",
        root / "domains/acme/05-knowledge/dev_standards/20_domain.md",
        project / "config/dev_standards/30_project.md",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    first = resolve_development_policy(root, "acme", "app", "dev_standards")
    refs = [item["source_ref"] for item in first["sources"]]
    assert "harness/shared_factory/05-knowledge/dev_standards/10_root.md" in refs
    assert "domains/acme/05-knowledge/dev_standards/20_domain.md" in refs
    assert "domains/acme/02-projects/app/config/dev_standards/30_project.md" in refs
    assert refs.index("harness/shared_factory/05-knowledge/dev_standards/10_root.md") < refs.index(
        "domains/acme/05-knowledge/dev_standards/20_domain.md"
    ) < refs.index("domains/acme/02-projects/app/config/dev_standards/30_project.md")
    added = project / "config/dev_standards/40_new_focus.md"
    added.write_text("# New Focus\n", encoding="utf-8")
    second = resolve_development_policy(root, "acme", "app", "dev_standards")
    assert second["fingerprint"] != first["fingerprint"]
    assert second["counts"]["sources"] == first["counts"]["sources"] + 1

    plan = start_development_run(root, "acme", "app", ["ENG-1"], run_id="policy-run", apply=False)
    assert plan["policy_fingerprint"]
    assert plan["policy_sources"]["dev_standards"][-1].endswith("40_new_focus.md")


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
    policy = project / "config/dev_standards/10_project.md"
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
