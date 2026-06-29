from __future__ import annotations

from pathlib import Path

from genomes_agentic_os.cli import build_parser


def test_aos_console_script_is_declared() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'agentic-os = "genomes_agentic_os.cli:main"' in pyproject
    assert 'aos = "genomes_agentic_os.cli:main"' in pyproject


def test_aos_help_uses_short_prog_name() -> None:
    assert build_parser(prog="aos").format_usage().startswith("usage: aos ")
