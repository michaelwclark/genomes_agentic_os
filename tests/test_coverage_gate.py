"""Regression coverage for the repository-wide Python coverage gate."""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYTEST_COV_SPEC = "pytest-cov>=7.0,<8"
_COVERAGE_COMMAND = (
    "python -m pytest tests/ -q --cov=genomes_agentic_os --cov-branch "
    "--cov-report=term --cov-report=json:coverage.json --cov-fail-under=80"
)


def _pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _test_workflow() -> dict:
    text = (_REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text)


def test_pytest_cov_is_bounded_and_identical_in_both_dev_lists() -> None:
    """pip extras and uv groups must install the same coverage toolchain."""
    data = _pyproject()
    pip_dev = data["project"]["optional-dependencies"]["dev"]
    uv_dev = data["dependency-groups"]["dev"]

    assert pip_dev == uv_dev
    assert pip_dev.count(_PYTEST_COV_SPEC) == 1


def test_python_job_runs_the_full_branch_coverage_gate() -> None:
    """The stable Python job must enforce the measured 80-percent floor."""
    python_job = _test_workflow()["jobs"]["python"]
    assert python_job["name"] == "Python suite and packaging"

    test_step = next(
        step for step in python_job["steps"] if step.get("name") == "Run full Python suite"
    )
    assert shlex.split(test_step["run"]) == shlex.split(_COVERAGE_COMMAND)


def test_python_job_uploads_coverage_even_when_pytest_fails() -> None:
    """A red gate still needs durable JSON for diagnosis and comparison."""
    python_job = _test_workflow()["jobs"]["python"]
    upload_step = next(
        step
        for step in python_job["steps"]
        if step.get("name") == "Upload Python coverage evidence"
    )

    assert upload_step["if"] == "${{ always() }}"
    assert upload_step["uses"] == "actions/upload-artifact@v6"
    assert upload_step["with"] == {
        "name": "python-coverage",
        "path": "coverage.json",
        "if-no-files-found": "error",
    }
