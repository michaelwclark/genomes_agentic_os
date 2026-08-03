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
    assert result["families"]["async-runs"]["extensions"] == {".log": 1}
    progress_document = json.loads(progress.read_text(encoding="utf-8"))
    assert progress_document["schema"] == "agentic-os-long-running-progress/v1"
    assert progress_document["phase"] == "scan"
    assert progress_document["files_completed"] == 2


def test_inventory_rejects_missing_root(tmp_path: Path) -> None:
    try:
        inventory_run_evidence(tmp_path / "missing")
    except ValueError as error:
        assert "not a directory" in str(error)
    else:  # pragma: no cover
        raise AssertionError("missing root should fail")
