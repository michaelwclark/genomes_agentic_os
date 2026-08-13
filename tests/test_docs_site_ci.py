"""The docs site's CI contract.

Two properties are worth a regression test because both fail silently. A
downgraded `onBrokenLinks` leaves CI green while the site rots, which is the
whole reason AGE-110 exists. And an over-broad token on the publishing job is
invisible until it is abused, so the deploy job's permissions are pinned to
exactly what the Pages API needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/docs.yml"
DOCUSAURUS_CONFIG = ROOT / "website/docusaurus.config.ts"
PNPM_WORKSPACE = ROOT / "website/pnpm-workspace.yaml"

# The directory `pnpm build` writes, relative to the repository root rather
# than to `website/`. Action inputs do not inherit `defaults.run
# .working-directory`, so this is the one path in the workflow that has to
# carry the `website/` prefix itself.
BUILD_OUTPUT = "website/build"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 resolves a bare `on:` key to the boolean True, so the trigger
    # block cannot be read as workflow["on"].
    return workflow[True]


@pytest.fixture(scope="module")
def build(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["build"]


@pytest.fixture(scope="module")
def deploy(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["deploy"]


def _step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    """Return the single step running `action`, ignoring its pinned version."""
    matches = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).split("@")[0] == action
    ]
    assert len(matches) == 1, f"expected exactly one {action} step, got {matches}"
    return matches[0]


def test_a_broken_internal_link_fails_the_build(build: dict[str, Any]) -> None:
    config = DOCUSAURUS_CONFIG.read_text(encoding="utf-8")
    assert "onBrokenLinks: 'throw'" in config
    assert "onBrokenMarkdownLinks: 'throw'" in config

    commands = [str(step.get("run", "")) for step in build["steps"]]
    assert "pnpm build" in commands


def test_docs_changes_are_checked_before_they_land(
    triggers: dict[str, Any],
    build: dict[str, Any],
) -> None:
    assert "pull_request" in triggers
    # Pull requests must not be filtered at the event level: the stable policy
    # check is required on every head, including changes unrelated to docs.
    assert triggers["pull_request"] is None
    assert triggers["push"]["branches"] == ["main"]

    # Main only needs a Pages build when documentation-impacting paths changed.
    assert triggers["push"]["paths"] == [
        "docs/**",
        "operating-manual/**",
        "website/**",
        ".github/workflows/docs.yml",
    ]

    assert build["name"] == "Docs link policy"
    docs_scope = next(step for step in build["steps"] if step.get("id") == "docs-scope")
    assert docs_scope["if"] == "github.event_name == 'pull_request'"
    assert 'git diff --name-only --no-renames "${BASE_SHA}" "${HEAD_SHA}"' in docs_scope["run"]
    assert "docs/|operating-manual/|website/" in docs_scope["run"]

    no_op = next(
        step
        for step in build["steps"]
        if step.get("name") == "Record successful non-documentation policy result"
    )
    assert no_op["if"] == (
        "github.event_name == 'pull_request' "
        "&& steps.docs-scope.outputs.required != 'true'"
    )

    heavy_gate = (
        "github.event_name == 'push' "
        "|| steps.docs-scope.outputs.required == 'true'"
    )
    heavy_steps = [
        step
        for step in build["steps"]
        if str(step.get("uses", "")).startswith(("actions/setup-node@", "pnpm/action-setup@"))
        or step.get("name")
        in {
            "Install dependencies",
            "Typecheck config and components",
            "Build site and check every internal link",
        }
    ]
    assert len(heavy_steps) == 5
    assert all(step["if"] == heavy_gate for step in heavy_steps)


def test_docs_ci_uses_the_committed_pnpm_build_approval_policy(
    build: dict[str, Any],
) -> None:
    setup_node = _step_using(build, "actions/setup-node")
    assert setup_node["with"]["cache"] == "pnpm"
    assert setup_node["with"]["cache-dependency-path"] == "website/pnpm-lock.yaml"

    pnpm_setup = _step_using(build, "pnpm/action-setup")
    assert pnpm_setup["with"]["version"] == "11.21.0"
    assert build["steps"].index(pnpm_setup) < build["steps"].index(setup_node)

    commands = [str(step.get("run", "")) for step in build["steps"]]
    assert "pnpm install --frozen-lockfile" in commands

    policy = yaml.safe_load(PNPM_WORKSPACE.read_text(encoding="utf-8"))
    assert policy["allowBuilds"] == {"@swc/core": True, "core-js": True}


def test_the_deployed_artifact_is_the_build_that_was_link_checked(
    build: dict[str, Any],
) -> None:
    upload = _step_using(build, "actions/upload-pages-artifact")
    assert upload["with"]["path"] == BUILD_OUTPUT
    assert upload["if"] == "github.event_name == 'push'"


def test_publishing_waits_for_the_link_check(deploy: dict[str, Any]) -> None:
    assert deploy["needs"] == "build"
    _step_using(deploy, "actions/deploy-pages")


def test_only_main_publishes(deploy: dict[str, Any]) -> None:
    condition = deploy["if"]
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition


def test_the_publishing_job_holds_least_privilege(
    workflow: dict[str, Any],
    build: dict[str, Any],
    deploy: dict[str, Any],
) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    # Job-level permissions replace the workflow default, so the deploy job's
    # block is the complete grant. `deploy-pages` never checks the repository
    # out, so it needs no read access to it.
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    # The build job runs `npm ci` over third-party dependencies and must not be
    # able to publish.
    assert "permissions" not in build


def test_a_main_run_is_not_cancelled_part_way_through_a_deploy(
    workflow: dict[str, Any],
) -> None:
    cancel = workflow["concurrency"]["cancel-in-progress"]
    assert cancel == "${{ github.event_name == 'pull_request' }}"


def test_the_deployment_url_is_reported_on_the_run(deploy: dict[str, Any]) -> None:
    environment = deploy["environment"]
    assert environment["name"] == "github-pages"
    assert environment["url"] == "${{ steps.deployment.outputs.page_url }}"
    assert _step_using(deploy, "actions/deploy-pages")["id"] == "deployment"


def test_the_site_is_configured_for_its_pages_url() -> None:
    config = DOCUSAURUS_CONFIG.read_text(encoding="utf-8")
    assert "url: 'https://michaelwclark.github.io'" in config
    assert "baseUrl: '/genomes_agentic_os/'" in config
