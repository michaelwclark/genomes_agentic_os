"""Tests for the read-only release/* SemVer candidate guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/release/derive-semver.py"
WORKFLOW_PATH = ROOT / ".github/workflows/release-candidate.yml"
TAG_RELEASE_PATH = ROOT / ".github/workflows/release.yml"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("derive_semver", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DERIVE = _module()


def _workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_derivation_obeys_conventional_commit_precedence() -> None:
    base = DERIVE.Version.parse("0.6.0")

    assert DERIVE.change_level(["docs: clarify release notes"]) is None
    assert DERIVE.next_version(base, DERIVE.change_level(["fix: repair guard"]), major_version_zero=True) == DERIVE.Version(0, 6, 1)
    assert DERIVE.next_version(base, DERIVE.change_level(["feat: add release guard", "fix: repair guard"]), major_version_zero=True) == DERIVE.Version(0, 7, 0)
    assert DERIVE.next_version(base, DERIVE.change_level(["feat!: change release contract"]), major_version_zero=True) == DERIVE.Version(0, 7, 0)


def test_workflow_runs_only_after_a_merged_release_branch_pull_request() -> None:
    workflow = _workflow()

    assert workflow["on"]["pull_request"]["branches"] == ["release/**"]
    assert workflow["on"]["pull_request"]["types"] == ["closed"]
    job = workflow["jobs"]["derive"]
    assert job["if"] == "github.event.pull_request.merged == true"
    assert workflow["permissions"] == {"contents": "read"}


def test_dry_run_uses_the_merged_commit_and_preserves_tag_publication() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    tag_release = TAG_RELEASE_PATH.read_text(encoding="utf-8")

    assert "github.event.pull_request.merge_commit_sha" in source
    assert "git describe --tags --abbrev=0" in source
    assert "--expected-version" in source
    assert "--major-version-zero" in source
    assert 'tags: ["v*"]' in tag_release
