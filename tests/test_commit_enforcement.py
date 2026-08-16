"""Guards the Conventional Commit enforcement and version-derivation wiring.

Commitizen and pre-commit are invoked as executables rather than imported, so
they are exempt from the import-surface gate in tests/contracts/. What can
still break silently is the configuration that binds them to the release
process and each other, which is what these tests pin:

- the version commitizen bumps is the one the Release workflow validates,
- the commit-msg hook that rejects malformed messages is still declared,
- the package, hook, and CI all consume one exact Commitizen version,
- the two parallel declarations of the dev toolchain do not drift apart,
- the stable check name and pull-request revision range remain intact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

tomllib = pytest.importorskip("tomllib", reason="needs Python 3.11+ tomllib")

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _pre_commit_config() -> dict:
    text = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _test_workflow() -> dict:
    text = (_REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text)


def _exact_commitizen_version(dependencies: list[str]) -> str:
    declarations = [
        dependency
        for dependency in dependencies
        if dependency.casefold().startswith("commitizen")
    ]
    assert len(declarations) == 1, "expected one Commitizen dependency declaration"

    match = re.fullmatch(r"commitizen==([0-9]+(?:\.[0-9]+){2})", declarations[0])
    assert match, "Commitizen must use an exact three-part version pin"
    return match.group(1)


def _commitizen_hook_revision() -> str:
    repos = [
        repo
        for repo in _pre_commit_config()["repos"]
        if repo["repo"] == "https://github.com/commitizen-tools/commitizen"
    ]
    assert len(repos) == 1, "expected one Commitizen pre-commit repository"
    assert any(hook["id"] == "commitizen" for hook in repos[0]["hooks"])

    revision = repos[0]["rev"]
    assert re.fullmatch(r"v[0-9]+(?:\.[0-9]+){2}", revision)
    return revision.removeprefix("v")


def test_commitizen_reads_the_version_from_the_pep621_project_table() -> None:
    """Any other provider would let pyproject's version drift from the bump."""
    assert _pyproject()["tool"]["commitizen"]["version_provider"] == "pep621"


def test_commitizen_tag_format_matches_the_release_workflow_check() -> None:
    """.github/workflows/release.yml asserts the tag equals "v${version}"."""
    assert _pyproject()["tool"]["commitizen"]["tag_format"] == "v$version"

    release_workflow = (
        _REPO_ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")
    assert 'test "${GITHUB_REF_NAME}" = "v${version}"' in release_workflow


def test_project_version_is_the_only_declared_version() -> None:
    """A second version string is the usual way these two fall out of step."""
    assert _pyproject()["project"]["version"]
    assert "version" not in _pyproject()["tool"]["commitizen"]


def test_commit_message_hook_is_declared() -> None:
    """Losing this hook would silently disable local enforcement."""
    hooks = [
        hook
        for repo in _pre_commit_config()["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "commitizen"
    ]
    assert hooks, "no commitizen hook declared in .pre-commit-config.yaml"
    assert all(hook["stages"] == ["commit-msg"] for hook in hooks)


def test_only_the_commit_message_stage_is_installed_by_default() -> None:
    """Worktrees share one hooks directory, so a mutating hook installed here
    would fire in every unrelated worktree at once."""
    assert _pre_commit_config()["default_install_hook_types"] == ["commit-msg"]


def test_commitizen_package_pin_matches_the_pre_commit_hook_revision() -> None:
    """pip, uv, and pre-commit must all resolve the same exact tool version."""
    data = _pyproject()
    extra = sorted(data["project"]["optional-dependencies"]["dev"])
    group = sorted(data["dependency-groups"]["dev"])

    assert extra == group
    assert _exact_commitizen_version(extra) == _commitizen_hook_revision() == "4.17.0"


def test_commit_message_ci_syncs_the_locked_repository_development_extra() -> None:
    """CI must consume the governed lock instead of resolving a second toolchain."""
    steps = _test_workflow()["jobs"]["commit-messages"]["steps"]
    sync_commands = [
        step["run"]
        for step in steps
        if isinstance(step, dict) and step.get("run", "").startswith("uv sync")
    ]

    assert sync_commands == ["uv sync --locked --extra dev"]
    assert not any(
        "pip install" in step.get("run", "")
        for step in steps
        if isinstance(step, dict)
    )

    setup_uv = next(
        step
        for step in steps
        if step.get("uses")
        == "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"
    )
    assert setup_uv["with"] == {"python-version": "3.14", "enable-cache": True}


def test_commit_message_ci_preserves_the_stable_check_and_revision_range() -> None:
    """Branch protection and validation depend on this exact public contract."""
    job = _test_workflow()["jobs"]["commit-messages"]

    assert job["name"] == "Commit messages"
    assert job["if"] == "github.event_name == 'pull_request'"

    checkout = next(
        step for step in job["steps"] if step.get("uses") == "actions/checkout@v7"
    )
    assert checkout["with"]["fetch-depth"] == 0

    check = next(
        step
        for step in job["steps"]
        if step.get("name") == "Check every commit added by this pull request"
    )
    assert check["env"] == {
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    assert (
        check["run"]
        == 'uv run --no-sync cz check --rev-range "${BASE_SHA}..${HEAD_SHA}"'
    )
