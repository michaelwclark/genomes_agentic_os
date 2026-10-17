from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from genomes_agentic_os import __version__
from genomes_agentic_os import cli


@pytest.mark.parametrize("prog", ["agentic-os", "aos"])
def test_version_uses_executing_distribution_without_root(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], prog: str
) -> None:
    monkeypatch.setattr(cli, "version", lambda name: "9.8.7")
    monkeypatch.setenv("AGENTIC_OS_ROOT", "/nonexistent/unused-root")
    with pytest.raises(SystemExit) as result:
        cli.build_parser(prog).parse_args(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out == f"{prog} 9.8.7\n"


def test_uninstalled_source_version_is_explicit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(cli, "version", missing)
    with pytest.raises(SystemExit) as result:
        cli.main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out == f"agentic-os {__version__} (uninstalled source)\n"


def test_subcommand_remains_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        cli.main([])
    assert result.value.code == 2
    assert "required" in capsys.readouterr().err


def test_help_includes_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    assert "--version" in capsys.readouterr().out
