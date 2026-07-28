"""Guards the Conventional Commit enforcement and version-derivation wiring.

Commitizen and pre-commit are invoked as executables rather than imported, so
they are exempt from the import-surface gate in tests/contracts/. What can
still break silently is the configuration that binds them to the release
process, which is what these tests pin:

- the version commitizen bumps is the one the Release workflow validates,
- the commit-msg hook that rejects malformed messages is still declared,
- the two parallel declarations of the dev toolchain do not drift apart.
"""

from __future__ import annotations

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


def test_the_pip_extra_and_the_uv_dependency_group_agree() -> None:
    """They are declared twice because pip and uv read different tables."""
    data = _pyproject()
    extra = sorted(data["project"]["optional-dependencies"]["dev"])
    group = sorted(data["dependency-groups"]["dev"])
    assert extra == group
