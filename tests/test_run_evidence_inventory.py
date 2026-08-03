"""Tests for bounded run-evidence inventory."""

from __future__ import annotations

import json
from pathlib import Path

from genomes_agentic_os.run_evidence_inventory import inventory_run_evidence


def test_inventory_aggregates_families_without_following_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "06-runs-and-logs"
    run = root / "runs" / "run-1"
    async_run = root / "async-runs" / "async-1"
    run.mkdir(parents=True)
    async_run.mkdir(parents=True)
    run.joinpath("run-log.yml").write_text("status: done\n", encoding="utf-8")
    async_run.joinpath("output.log").write_text("ok\n", encoding="utf-8")
    root.joinpath("runs", "loop").symlink_to(root, target_is_directory=True)
    progress = tmp_path / "progress.json"

    result = inventory_run_evidence(root, progress_path=progress, progress_every=1)

    assert result["files"] == 2
    assert result["directories"] == 4
    assert result["bytes"] == len("status: done\n") + len("ok\n")
    assert result["families"]["runs"]["extensions"] == {".yml": 1}
    assert result["families"]["runs"]["directories"] == 2
    assert result["families"]["async-runs"]["extensions"] == {".log": 1}
    assert result["families"]["async-runs"]["directories"] == 2
    progress_document = json.loads(progress.read_text(encoding="utf-8"))
    assert progress_document["schema"] == "agentic-os-long-running-progress/v1"
    assert progress_document["status"] == "completed"
    assert progress_document["phase"] == "terminal"
    assert progress_document["files_completed"] == 2


def test_inventory_keeps_only_root_files_in_root_family(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    root.joinpath("single.log").write_text("root file\n", encoding="utf-8")
    root.joinpath("runs").mkdir()

    result = inventory_run_evidence(root)

    assert result["families"]["<root>"]["files"] == 1
    assert result["families"]["<root>"]["directories"] == 0
    assert result["families"]["runs"]["directories"] == 1


def test_inventory_records_explicit_directory_exclusions(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    evidence = root / "harness" / "runs"
    dependency = root / "project" / "node_modules"
    evidence.mkdir(parents=True)
    dependency.mkdir(parents=True)
    evidence.joinpath("run.yml").write_text("status: done\n", encoding="utf-8")
    dependency.joinpath("dependency.js").write_text("large copy\n", encoding="utf-8")

    result = inventory_run_evidence(root, excluded_directory_names=frozenset({"node_modules"}))

    assert result["files"] == 1
    assert result["excluded_directories"] == {"node_modules": 1}


def test_inventory_rejects_missing_root(tmp_path: Path) -> None:
    try:
        inventory_run_evidence(tmp_path / "missing")
    except ValueError as error:
        assert "not a directory" in str(error)
    else:  # pragma: no cover
        raise AssertionError("missing root should fail")
