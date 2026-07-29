"""Coverage gate: every dependency declared in pyproject.toml must have a
contract test in tests/contracts/ or an explicit exclusion with a reason.

New dependency => add tests/contracts/test_<normalized_name>_contract.py
asserting the API surface this project uses, or add the package to EXCLUDED
below with a reason. See docs/dependency-contract-tests.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="coverage gate needs Python 3.11+ tomllib")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_DIR = Path(__file__).resolve().parent

# Packages with no runtime import surface in this project. Key: normalized
# package name, value: the reason it is exempt from contract coverage.
EXCLUDED: dict[str, str] = {
    "setuptools": "build backend tooling (build-system.requires); never imported at runtime",
    "wheel": "build tooling (build-system.requires); never imported at runtime",
    "commitizen": (
        "commit tooling invoked as the `cz` executable by the commit-msg hook and CI; "
        "never imported. Its configuration contract is covered by "
        "tests/test_commit_enforcement.py"
    ),
    "pre_commit": (
        "hook runner invoked as the `pre-commit` executable; never imported. Its "
        "configuration contract is covered by tests/test_commit_enforcement.py"
    ),
    "pytest_cov": (
        "test-only pytest plugin invoked through command-line coverage options; never "
        "imported by the product. Its dependency and CI wiring are covered by "
        "tests/test_coverage_gate.py"
    ),
}


def _normalize(requirement: str) -> str:
    """Reduce a PEP 508 requirement to a filename-safe module-ish name."""
    base = re.split(r"[\[<>=!~; ]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "_", base).lower()


def _declared_requirements() -> list[str]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(data["project"].get("dependencies", []))
    for group in data["project"].get("optional-dependencies", {}).values():
        requirements.extend(group)
    requirements.extend(data.get("build-system", {}).get("requires", []))
    return requirements


def test_every_dependency_has_a_contract_test_or_exclusion() -> None:
    excluded_names = {_normalize(name) for name in EXCLUDED}
    missing: list[str] = []
    for requirement in sorted(_declared_requirements()):
        name = _normalize(requirement)
        if name in excluded_names:
            continue
        expected = _CONTRACT_DIR / f"test_{name}_contract.py"
        if not expected.exists():
            missing.append(f"{requirement} -> tests/contracts/{expected.name}")
    assert not missing, (
        "Dependencies without contract tests:\n  "
        + "\n  ".join(missing)
        + "\nAdd a contract test asserting the API surface we use, or add the "
        "package to EXCLUDED in tests/contracts/test_contract_coverage.py with a reason."
    )


def test_exclusions_carry_reasons_and_are_not_stale() -> None:
    declared = {_normalize(requirement) for requirement in _declared_requirements()}
    for name, reason in EXCLUDED.items():
        assert reason.strip(), f"EXCLUDED entry {name!r} has no reason"
        assert _normalize(name) in declared, (
            f"EXCLUDED entry {name!r} is not declared in pyproject.toml; remove it"
        )
