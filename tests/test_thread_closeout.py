from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess

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


def test_finalize_lingering_moves_terminal_packets_and_syncs_active_container(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
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
                "--work-id",
                "001_lingering_done",
                "--title",
                "Lingering Done",
                "--summary",
                "Already finished but still in active.",
                "--status",
                "building",
                "--format",
                "packet",
            ]
        )
        == 0
    )
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
                "--work-id",
                "002_still_active",
                "--title",
                "Still Active",
                "--summary",
                "Still being built.",
                "--status",
                "building",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    lingering = project_root / "work-items" / "02-active" / "001_lingering_done"
    metadata_path = lingering / "work.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "documented"
    metadata["state"] = "documented"
    metadata["lifecycle"]["state"] = "documented"
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    automation_root = root / "los" / "04-automations" / "engineering" / "test_auto"
    automation_root.mkdir(parents=True)
    with (root / "los" / "00-control-plane" / "active-work.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "| `test_auto` automation | `active` | OS Owner | Keep running. | `04-automations/engineering/test_auto` |\n"
        )
    shared_automation_root = root / "harness" / "shared_factory" / "04-automations" / "engineering" / "shared_auto"
    shared_automation_root.mkdir(parents=True)
    with (root / "harness" / "shared_factory" / "00-control-plane" / "active-work.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "| `shared_auto` automation | `active` | OS Owner | Keep running. | `04-automations/engineering/shared_auto` |\n"
        )
    capsys.readouterr()

    assert (
        main(
            [
                "project",
                "work-item",
                "finalize-lingering",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["candidate_count"] == 1
    assert lingering.is_dir()

    assert (
        main(
            [
                "project",
                "work-item",
                "finalize-lingering",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--apply",
            ]
        )
        == 0
    )
    applied = yaml.safe_load(capsys.readouterr().out)
    completed = project_root / "work-items" / "03-complete" / "001_lingering_done"
    assert applied["mode"] == "apply"
    assert applied["candidate_count"] == 1
    assert completed.is_dir()
    assert not lingering.exists()
    assert "work-items/03-complete/001_lingering_done" in (
        root / "harness" / "shared_factory" / "00-control-plane" / "active-work.md"
    ).read_text(encoding="utf-8")
    active_worklog = project_root / "work-items" / "02-active" / "002_still_active" / "WORKLOG.md"
    active_worklog_marker = datetime(2026, 6, 16, tzinfo=timezone.utc).timestamp()
    for path in active_worklog.parent.rglob("*"):
        if path.is_file():
            os.utime(path, (active_worklog_marker, active_worklog_marker))
    for path in sorted(active_worklog.parent.rglob("*"), reverse=True):
        if path.is_dir():
            os.utime(path, (active_worklog_marker, active_worklog_marker))
    os.utime(active_worklog.parent, (active_worklog_marker, active_worklog_marker))

    assert main(["project", "work-item", "sync-active", "--root", str(root)]) == 0
    capsys.readouterr()

    active_index = yaml.safe_load((root / "00-control-plane" / "active" / "index.yml").read_text(encoding="utf-8"))
    assert [item["id"] for item in active_index["work_items"]] == ["002_still_active"]
    assert active_index["work_items"][0]["created_at"]
    assert active_index["work_items"][0]["last_modified_at"] == "2026-06-16T00:00:00Z"
    assert {item["id"] for item in active_index["automations"]} == {"test_auto automation", "shared_auto automation"}
    assert all(item["created_at"] for item in active_index["automations"])
    assert all(item["last_modified_at"] for item in active_index["automations"])
    assert (root / "00-control-plane" / "active" / "worktrees" / ".metadata_never_index").is_file()
    active_link = Path(active_index["work_items"][0]["link"])
    assert active_link.is_symlink()
    assert active_link.resolve() == (project_root / "work-items" / "02-active" / "002_still_active")


def test_cleanup_closed_worktrees_moves_terminal_entries_to_closed_bucket(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "shared_factory", "genomes_agentic_os", "--root", str(root)]) == 0
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    closed_candidate = project_root / "worktrees" / "feature-closed"
    status_candidate = project_root / "worktrees" / "feature-status-done"
    active_candidate = project_root / "worktrees" / "feature-active"
    closed_candidate.mkdir(parents=True)
    status_candidate.mkdir(parents=True)
    active_candidate.mkdir(parents=True)
    index_path = project_root / "worktrees" / "index.yml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "project": "genomes_agentic_os",
                "worktrees": [
                    {
                        "id": "feature-closed",
                        "path": str(closed_candidate),
                        "link": "worktrees/feature-closed",
                        "status": "active",
                        "jira_key": "AOS-1",
                        "jira_status": "QA Ready",
                    },
                    {
                        "id": "feature-active",
                        "path": str(active_candidate),
                        "link": "worktrees/feature-active",
                        "status": "active",
                        "jira_key": "AOS-2",
                        "jira_status": "Building",
                    },
                    {
                        "id": "feature-status-done",
                        "path": str(status_candidate),
                        "link": "worktrees/feature-status-done",
                        "status": "Done",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert (
        main(
            [
                "project",
                "worktree",
                "cleanup-closed",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["candidate_count"] == 2
    assert {candidate["reason"] for candidate in dry_run["candidates"]} == {"jira_status:qa_ready", "status:done"}
    assert closed_candidate.is_dir()
    assert not (project_root / "worktrees" / "closed.yml").exists()

    assert (
        main(
            [
                "project",
                "worktree",
                "cleanup-closed",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--apply",
            ]
        )
        == 0
    )
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["mode"] == "apply"
    assert applied["candidate_count"] == 2
    assert {entry["id"] for entry in applied["closed"]} == {"feature-closed", "feature-status-done"}
    assert closed_candidate.is_dir()
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    assert [entry["id"] for entry in index["worktrees"]] == ["feature-active"]
    closed = yaml.safe_load((project_root / "worktrees" / "closed.yml").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in closed["worktrees"]] == ["feature-closed", "feature-status-done"]
    active_index = yaml.safe_load((root / "00-control-plane" / "active" / "index.yml").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in active_index["worktrees"]] == ["feature-active"]


def test_cleanup_closed_worktrees_removes_only_clean_in_project_checkouts(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "shared_factory", "genomes_agentic_os", "--root", str(root)]) == 0
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    clean_worktree = project_root / "worktrees" / "clean-merged"
    dirty_worktree = project_root / "worktrees" / "dirty-merged"
    external_worktree = tmp_path / "external-merged"
    clean_worktree.mkdir(parents=True)
    dirty_worktree.mkdir(parents=True)
    external_worktree.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=clean_worktree, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=dirty_worktree, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=external_worktree, check=True, capture_output=True)
    (dirty_worktree / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    index_path = project_root / "worktrees" / "index.yml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "project": "genomes_agentic_os",
                "worktrees": [
                    {
                        "id": "clean-merged",
                        "path": str(clean_worktree),
                        "link": "worktrees/clean-merged",
                        "status": "active",
                        "pull_request": {"state": "merged"},
                    },
                    {
                        "id": "dirty-merged",
                        "path": str(dirty_worktree),
                        "link": "worktrees/dirty-merged",
                        "status": "active",
                        "pull_request": {"merged": True},
                    },
                    {
                        "id": "external-merged",
                        "path": str(external_worktree),
                        "status": "active",
                        "pull_request": {"state": "merged"},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert (
        main(
            [
                "project",
                "worktree",
                "cleanup-closed",
                "--root",
                str(root),
                "--domain",
                "shared_factory",
                "--project",
                "genomes_agentic_os",
                "--apply",
                "--remove-files",
            ]
        )
        == 0
    )
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["candidate_count"] == 3
    assert not clean_worktree.exists()
    assert dirty_worktree.is_dir()
    assert external_worktree.is_dir()
    assert applied["skipped"] == [
        {"path": str(dirty_worktree), "reason": "git checkout has uncommitted changes"},
        {"path": str(external_worktree), "reason": "target is outside project worktrees/"},
    ]
