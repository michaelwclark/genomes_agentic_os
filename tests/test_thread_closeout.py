from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main


def work_item_root(root: Path) -> Path:
    active_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os" / "work-items" / "02-active"
    return next(path for path in active_root.iterdir() if path.is_dir())


def create_project_with_work_item(root: Path) -> Path:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "shared_factory", "genomes_agentic_os", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "shared_factory",
                "genomes_agentic_os",
                "--root",
                str(root),
                "--title",
                "Thread Test",
                "--summary",
                "Exercise thread closeout behavior.",
                "--status",
                "specified",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    return work_item_root(root)


def age_work_item_files(work_root: Path, *, days: int) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    for path in work_root.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))


def test_thread_end_writes_work_item_closeout(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)

    assert (
        main(
            [
                "thread",
                "end",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--thread-id",
                "unit_closeout",
                "--summary",
                "Implemented thread closeout.",
                "--next-action",
                "None",
                "--validation",
                "pytest -q",
                "--artifact",
                "SPEC.md",
                "--memory-receipt",
                "project: thread closeout command verified",
                "--skip-notion",
            ]
        )
        == 0
    )

    closeout_root = work_root / "artifacts" / "thread-closeouts" / "unit_closeout"
    assert (closeout_root / "thread.yml").is_file()
    assert (closeout_root / "thread-closeout.yml").is_file()
    assert (closeout_root / "closeout.md").is_file()
    assert (closeout_root / "evidence.jsonl").is_file()
    assert (closeout_root / "memory-write-receipts.jsonl").is_file()
    assert (closeout_root / "notion-sync.md").is_file()

    payload = yaml.safe_load((closeout_root / "thread-closeout.yml").read_text(encoding="utf-8"))
    assert payload["thread"]["id"] == "unit_closeout"
    assert payload["thread"]["closeout_mode"] == "artifact-closeout"
    assert payload["closeout"]["final_state"] == "finalized"
    assert payload["notion_sync"]["status"] == "skipped"
    assert payload["closeout"]["next_action"] is None

    assert "Implemented thread closeout." in (work_root / "WORKLOG.md").read_text(encoding="utf-8")
    assert "Next action: None" in (work_root / "NEXT.md").read_text(encoding="utf-8")
    assert main(["validate", "--root", str(root), "--strict"]) == 0


def test_thread_end_without_work_item_writes_run_log_closeout(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    assert (
        main(
            [
                "thread",
                "end",
                "--root",
                str(root),
                "--thread-id",
                "run_closeout",
                "--summary",
                "Standalone closeout.",
                "--skip-notion",
            ]
        )
        == 0
    )

    run_root = root / "harness" / "shared_factory" / "06-runs-and-logs" / "runs" / "run_closeout"
    assert (run_root / "run-log.md").is_file()
    assert (run_root / "thread-closeout.yml").is_file()
    assert (run_root / "closeout.md").is_file()
    payload = yaml.safe_load((run_root / "thread-closeout.yml").read_text(encoding="utf-8"))
    assert payload["thread"]["id"] == "run_closeout"


def test_thread_archive_refuses_unresolved_next_action(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    create_project_with_work_item(root)

    exit_code = main(
        [
            "thread",
            "archive",
            "--root",
            str(root),
            "--domain",
            "shared_factory",
            "--project",
            "genomes_agentic_os",
            "--thread-id",
            "archive_refusal",
            "--summary",
            "Archive attempt.",
            "--next-action",
            "Finish remaining implementation.",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "archive refused" in captured.err


def test_stale_finalize_is_dry_run_then_apply(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)
    age_work_item_files(work_root, days=5)
    capsys.readouterr()

    assert (
        main(
            [
                "thread",
                "stale-finalize",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--older-than-days",
                "3",
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["candidate_count"] == 1
    assert not list((work_root / "artifacts" / "thread-closeouts").glob("stale_*"))

    assert (
        main(
            [
                "thread",
                "stale-finalize",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--older-than-days",
                "3",
                "--apply",
            ]
        )
        == 0
    )
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["mode"] == "apply"
    assert len(applied["applied"]) == 1
    assert list((work_root / "artifacts" / "thread-closeouts").glob("stale_*"))


def test_runtime_dispatches_stale_thread_finalizer(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)
    age_work_item_files(work_root, days=5)
    assert main(["runtime", "init", "--root", str(root)]) == 0

    registry_path = root / "harness" / "shared_factory" / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for schedule in registry["schedules"]:
        schedule["enabled"] = schedule["id"] == "stale_thread_finalizer"
        schedule["next_due_at"] = None
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    queued = yaml.safe_load(capsys.readouterr().out)
    item_id = queued["queued"][0]["id"]
    assert queued["queued"][0]["ref"] == "stale_thread_finalizer"

    assert main(["runtime", "run-next", "--root", str(root), "--item-id", item_id, "--apply"]) == 0
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["queue_item"]["status"] == "done"
    assert list((work_root / "artifacts" / "thread-closeouts").glob("stale_*"))
