from __future__ import annotations

from pathlib import Path

import pytest

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_source_package


def write_source_file(root: Path, relative_path: str, content: str = "id: sample\n") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_source_package_validation_distinguishes_required_and_optional(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_source_file(
        source,
        "docs/07-agent-surfaces/codex-config-toml-inventory.md",
        "# Codex config.toml Inventory\n",
    )
    write_source_file(source, "templates/agent-config/codex-config-layer-map.yml")

    result = validate_source_package(source)

    assert result.ok
    assert not result.errors
    assert any("missing optional Codex layer config" in warning for warning in result.warnings)


def test_source_package_validation_blocks_missing_required_config(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_source_file(source, "templates/agent-config/codex-profile-manifest.yml")

    result = validate_source_package(source)

    assert not result.ok
    assert any("missing required Codex config source" in error for error in result.errors)
    assert any("codex-config-layer-map.yml" in error for error in result.errors)


def test_validate_source_cli_is_read_only_and_actionable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source"
    write_source_file(
        source,
        "docs/07-agent-surfaces/codex-config-toml-inventory.md",
        "# Codex config.toml Inventory\n",
    )
    write_source_file(source, "templates/agent-config/codex-config-layer-map.yml")

    assert main(["validate-source", "--source", str(source)]) == 0

    captured = capsys.readouterr()
    assert "valid source package" in captured.out
    assert "missing optional Codex layer config" in captured.err
    assert not (source / "generated").exists()
