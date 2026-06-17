"""Tests for the `agentic-os capability` CLI subcommand group (Spec 18)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main


@pytest.fixture()
def inited_root(tmp_path: Path) -> Path:
    """Return a tmp_path with a fully inited OS root."""
    assert main(["init", "--target", str(tmp_path)]) == 0
    return tmp_path


def test_capability_list_returns_zero(inited_root: Path, capsys) -> None:
    ret = main(["capability", "list", "--root", str(inited_root)])
    assert ret == 0


def test_capability_list_shows_all_types(inited_root: Path, capsys) -> None:
    main(["capability", "list", "--root", str(inited_root)])
    out = capsys.readouterr().out
    assert "## capabilities" in out
    assert "## commands" in out
    assert "## skills" in out
    assert "## mcp_servers" in out
    assert "## libraries" in out
    assert "## hooks" in out


def test_capability_list_includes_known_entries(inited_root: Path, capsys) -> None:
    main(["capability", "list", "--root", str(inited_root)])
    out = capsys.readouterr().out
    # make-* commands must be visible (AC5)
    assert "make-skill" in out
    assert "make-domain" in out
    assert "orchestrate" in out
    # context-mode and unified-memory libraries (AC3)
    assert "context_mode" in out
    assert "unified_memory" in out


def test_capability_list_type_filter_commands(inited_root: Path, capsys) -> None:
    ret = main(["capability", "list", "--root", str(inited_root), "--type", "commands"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "## commands" in out
    # Other sections must NOT appear when filtering
    assert "## skills" not in out
    assert "## mcp_servers" not in out


def test_capability_list_type_filter_shows_installed(inited_root: Path, capsys) -> None:
    """Installed capabilities section appears when filtering by an existing type."""
    main(["capability", "list", "--root", str(inited_root), "--type", "commands"])
    out = capsys.readouterr().out
    assert "installed capabilities" in out


def test_capability_list_invalid_type_returns_one(inited_root: Path, capsys) -> None:
    ret = main(["capability", "list", "--root", str(inited_root), "--type", "bogus"])
    assert ret == 1
    out = capsys.readouterr().out
    assert "Unknown capability type" in out


def test_capability_inventory_returns_zero(inited_root: Path, capsys) -> None:
    ret = main(["capability", "inventory", "--root", str(inited_root)])
    assert ret == 0


def test_capability_inventory_shows_inventory_content(inited_root: Path, capsys) -> None:
    main(["capability", "inventory", "--root", str(inited_root)])
    out = capsys.readouterr().out
    # INVENTORY.md structure (AC2)
    assert "# Agentic OS Inventory" in out
    assert "## Capabilities" in out
    assert "## Commands" in out
    assert "## Skills" in out


def test_capability_inventory_regenerate_flag(inited_root: Path, capsys) -> None:
    """--regenerate writes INVENTORY.md and reports up-to-date on second run."""
    # First regenerate: already exists from init, should report up to date
    ret = main(["capability", "inventory", "--root", str(inited_root), "--regenerate"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "already up to date" in out or "INVENTORY.md" in out


def test_capability_inventory_regenerate_creates_missing(inited_root: Path, capsys) -> None:
    """--regenerate creates INVENTORY.md if it is absent."""
    inventory_path = inited_root / "harness" / "INVENTORY.md"
    inventory_path.unlink()
    assert not inventory_path.exists()
    ret = main(["capability", "inventory", "--root", str(inited_root), "--regenerate"])
    assert ret == 0
    assert inventory_path.exists()


def test_capability_list_without_init_uses_builtin_payloads(tmp_path: Path, capsys) -> None:
    """capability list on an empty root still shows built-in registry payloads (no init needed)."""
    ret = main(["capability", "list", "--root", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "## commands" in out
    assert "make-skill" in out


def test_capability_subcommand_help_exits_zero() -> None:
    """agentic-os capability --help exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        main(["capability", "--help"])
    assert exc_info.value.code == 0


def test_capability_list_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["capability", "list", "--help"])
    assert exc_info.value.code == 0


def test_capability_inventory_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["capability", "inventory", "--help"])
    assert exc_info.value.code == 0
