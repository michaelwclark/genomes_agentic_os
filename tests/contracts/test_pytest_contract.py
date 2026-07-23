"""Contract test: pytest — validates the API surface used by this project.

Feature usage across tests/: tmp_path, capsys (pytest.CaptureFixture),
pytest.raises, monkeypatch (pytest.MonkeyPatch: setattr/setenv/delenv/chdir),
pytest.mark.parametrize, pytest.fixture, pytest.skip, pytest.fail.

If a pytest upgrade breaks any assertion here, our tests must be updated
before the dependency bump can merge.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_pytest_major_version_meets_requirement() -> None:
    assert int(pytest.__version__.split(".")[0]) >= 8


@pytest.fixture()
def sample_fixture() -> str:
    return "fixture-value"


def test_fixture_injection_works(sample_fixture: str) -> None:
    assert sample_fixture == "fixture-value"


@pytest.mark.parametrize(("value", "expected"), [(1, 2), (2, 3)])
def test_mark_parametrize_expands_cases(value: int, expected: int) -> None:
    assert value + 1 == expected


def test_raises_matches_exception_type_and_message() -> None:
    with pytest.raises(ValueError, match="boom"):
        raise ValueError("boom goes the contract")


def test_monkeypatch_setenv_and_delenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AOS_CONTRACT_SENTINEL", "1")
    assert os.environ["AOS_CONTRACT_SENTINEL"] == "1"
    monkeypatch.delenv("AOS_CONTRACT_SENTINEL")
    assert "AOS_CONTRACT_SENTINEL" not in os.environ


def test_monkeypatch_setattr(monkeypatch: pytest.MonkeyPatch) -> None:
    target = SimpleNamespace(attr="old")
    monkeypatch.setattr(target, "attr", "new")
    assert target.attr == "new"


def test_monkeypatch_chdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert Path.cwd().resolve() == tmp_path.resolve()


def test_tmp_path_provides_writable_directory(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("data", encoding="utf-8")
    assert sample.read_text(encoding="utf-8") == "data"


def test_capsys_captures_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    print("contract-echo")
    assert capsys.readouterr().out.strip() == "contract-echo"


def test_skip_and_fail_remain_callable() -> None:
    assert callable(pytest.skip)
    assert callable(pytest.fail)
