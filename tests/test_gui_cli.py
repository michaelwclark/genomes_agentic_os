from __future__ import annotations

import json
from subprocess import CompletedProcess

from genomes_agentic_os.cli import main
from genomes_agentic_os.cli import gui as gui_cli

from test_gui_snapshot import CODEX_ID, make_gui_fixture


def test_gui_snapshot_cli_contract(tmp_path, capsys) -> None:
    fixture = make_gui_fixture(tmp_path)
    result = main(
        [
            "gui",
            "snapshot",
            "--root",
            str(fixture["root"]),
            "--codex-home",
            str(fixture["codex_home"]),
            "--claude-home",
            str(fixture["claude_home"]),
            "--claude-desktop-root",
            str(fixture["claude_desktop"]),
            "--json",
        ]
    )
    snapshot = json.loads(capsys.readouterr().out)

    assert result == 0
    assert snapshot["schema_version"] == "agentic-os-gui/v1"
    assert snapshot["summary"]["conversations"] == 2
    assert snapshot["navigation"]["domains"][0]["name"] == "LOS"


def test_gui_transcript_cli_contract(tmp_path, capsys) -> None:
    fixture = make_gui_fixture(tmp_path)
    result = main(
        [
            "gui",
            "transcript",
            "--root",
            str(fixture["root"]),
            "--provider",
            "codex",
            "--conversation-id",
            CODEX_ID,
            "--codex-home",
            str(fixture["codex_home"]),
            "--json",
        ]
    )
    transcript = json.loads(capsys.readouterr().out)

    assert result == 0
    assert transcript["provider"] == "codex"
    assert transcript["conversation_id"] == CODEX_ID
    assert [message["role"] for message in transcript["messages"]] == ["user", "assistant"]


def test_gui_open_uses_fixed_open_argv(tmp_path, capsys, monkeypatch) -> None:
    app = tmp_path / "AgenticOSGui.app"
    app.mkdir()
    root = tmp_path / "installed-os"
    root.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gui_cli.subprocess, "run", fake_run)
    result = main(["gui", "open", "--root", str(root), "--app", str(app)])

    assert result == 0
    assert calls == [["/usr/bin/open", str(app), "--args", f"--aos-root={root}"]]
    assert "opened: true" in capsys.readouterr().out


def test_gui_open_reports_exact_source_commands_when_package_missing(tmp_path, capsys, monkeypatch) -> None:
    missing = tmp_path / "missing.app"
    source_dir = tmp_path / "source-app"

    monkeypatch.setattr(gui_cli, "_source_app_dir", lambda: source_dir)
    monkeypatch.setattr(gui_cli, "_gui_app_candidates", lambda _explicit=None: [missing])

    result = main(["gui", "open", "--app", str(missing)])
    output = capsys.readouterr().out

    assert result == 1
    assert f"pnpm --dir {source_dir} dev" in output
    assert f"pnpm --dir {source_dir} package:mac" in output
