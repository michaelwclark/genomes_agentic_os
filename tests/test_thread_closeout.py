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


def named_work_item(project_root: Path, lane: str, legacy_name: str) -> Path:
    return next((project_root / "work-items" / lane).glob(f"??????-{legacy_name}"))


def dated_artifact(parent: Path, legacy_name: str) -> Path:
    return next(parent.glob(f"??????-{legacy_name}"))


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

    closeout_root = dated_artifact(work_root / "artifacts" / "thread-closeouts", "unit_closeout")
    assert (closeout_root / "thread.yml").is_file()
    assert (closeout_root / "thread-closeout.yml").is_file()
    assert (closeout_root / "closeout.md").is_file()
    assert (closeout_root / "evidence.jsonl").is_file()
    assert (closeout_root / "memory-write-receipts.jsonl").is_file()
    assert (closeout_root / "notion-sync.md").is_file()

    payload = yaml.safe_load((closeout_root / "thread-closeout.yml").read_text(encoding="utf-8"))
    assert payload["thread"]["id"] == closeout_root.name
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

    run_root = dated_artifact(
        root / "harness" / "shared_factory" / "06-runs-and-logs" / "runs",
        "run_closeout",
    )
    assert (run_root / "run-log.md").is_file()
    assert (run_root / "thread-closeout.yml").is_file()
    assert (run_root / "closeout.md").is_file()
    payload = yaml.safe_load((run_root / "thread-closeout.yml").read_text(encoding="utf-8"))
    assert payload["thread"]["id"] == run_root.name


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
    assert not list((work_root / "artifacts" / "thread-closeouts").glob("??????-stale_*"))

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
    assert list((work_root / "artifacts" / "thread-closeouts").glob("??????-stale_*"))


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
    assert list((work_root / "artifacts" / "thread-closeouts").glob("??????-stale_*"))


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
    lingering = named_work_item(project_root, "02-active", "001_lingering_done")
    still_active = named_work_item(project_root, "02-active", "002_still_active")
    metadata_path = lingering / "work.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "documented"
    metadata["state"] = "documented"
    metadata["lifecycle"]["state"] = "documented"
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    automation_root = root / "domains" / "work" / "04-automations" / "engineering" / "test_auto"
    automation_root.mkdir(parents=True)
    with (root / "domains" / "work" / "00-control-plane" / "active-work.md").open("a", encoding="utf-8") as handle:
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
    completed = project_root / "work-items" / "03-complete" / lingering.name
    assert applied["mode"] == "apply"
    assert applied["candidate_count"] == 1
    assert completed.is_dir()
    assert not lingering.exists()
    assert f"work-items/03-complete/{lingering.name}" in (
        root / "harness" / "shared_factory" / "00-control-plane" / "active-work.md"
    ).read_text(encoding="utf-8")
    active_worklog = still_active / "WORKLOG.md"
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
    assert [item["id"] for item in active_index["work_items"]] == [still_active.name]
    assert active_index["work_items"][0]["created_at"]
    assert active_index["work_items"][0]["last_modified_at"] == "2026-06-16T00:00:00Z"
    assert {item["id"] for item in active_index["automations"]} == {"test_auto automation", "shared_auto automation"}
    assert all(item["created_at"] for item in active_index["automations"])
    assert all(item["last_modified_at"] for item in active_index["automations"])
    assert (root / "00-control-plane" / "active" / "worktrees" / ".metadata_never_index").is_file()
    active_link = Path(active_index["work_items"][0]["link"])
    assert active_link.is_symlink()
    assert active_link.resolve() == still_active


def test_infer_complete_reports_needs_thread_finalizer_without_writing(tmp_path: Path, capsys) -> None:
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
                "001_merged_without_closeout",
                "--title",
                "Merged Without Closeout",
                "--summary",
                "Merged but still active.",
                "--status",
                "validating",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    capsys.readouterr()
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    item = named_work_item(project_root, "02-active", "001_merged_without_closeout")
    metadata_path = item / "work.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["pull_request"] = {"state": "merged"}
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (item / "SUMMARY.md").write_text("# Summary\n\nImplemented and merged.\n", encoding="utf-8")
    (item / "HOLDOUT_QA_RESULTS.md").write_text("# Holdout QA Results\n\nPassed.\n", encoding="utf-8")
    (item / "NEXT.md").write_text("# Next\n\n## Next Action\n\n- None\n", encoding="utf-8")

    assert (
        main(
            [
                "project",
                "work-item",
                "infer-complete",
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
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["mode"] == "dry-run"
    assert result["decision_counts"]["needs-thread-finalizer"] == 1
    assert result["candidate_count"] == 1
    assert item.is_dir()


def test_infer_complete_keeps_recent_conversation_active(tmp_path: Path, capsys) -> None:
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
                "001_recent_conversation",
                "--title",
                "Recent Conversation",
                "--summary",
                "Merged but discussion continues.",
                "--status",
                "validating",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    capsys.readouterr()
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    item = named_work_item(project_root, "02-active", "001_recent_conversation")
    metadata_path = item / "work.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["pull_request"] = {"state": "merged"}
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (item / "SUMMARY.md").write_text("# Summary\n\nImplemented and merged.\n", encoding="utf-8")
    (item / "HOLDOUT_QA_RESULTS.md").write_text("# Holdout QA Results\n\nPassed.\n", encoding="utf-8")
    (item / "NEXT.md").write_text("# Next\n\n## Next Action\n\n- None\n", encoding="utf-8")
    log_file = item / "logs" / "conversations" / "recent.md"
    log_file.write_text("recent discussion\n", encoding="utf-8")

    assert (
        main(
            [
                "project",
                "work-item",
                "infer-complete",
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
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["decision_counts"]["keep-active"] == 1
    assert "quiet window" in result["decisions"][0]["missing"]


def test_infer_complete_apply_marks_finished_and_moves_packet(tmp_path: Path, capsys) -> None:
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
                "001_ready_to_finish",
                "--title",
                "Ready To Finish",
                "--summary",
                "Merged and closed out.",
                "--status",
                "validating",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    capsys.readouterr()
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    item = named_work_item(project_root, "02-active", "001_ready_to_finish")
    metadata_path = item / "work.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["pull_request"] = {"state": "merged"}
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (item / "SUMMARY.md").write_text("# Summary\n\nImplemented and merged.\n", encoding="utf-8")
    (item / "HOLDOUT_QA_RESULTS.md").write_text("# Holdout QA Results\n\nPassed.\n", encoding="utf-8")
    (item / "NEXT.md").write_text("# Next\n\n## Next Action\n\n- None\n", encoding="utf-8")
    closeout = item / "artifacts" / "thread-closeouts" / "manual" / "closeout.md"
    closeout.parent.mkdir(parents=True)
    closeout.write_text("# Thread Closeout\n\nDone.\n", encoding="utf-8")

    assert (
        main(
            [
                "project",
                "work-item",
                "infer-complete",
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
    result = yaml.safe_load(capsys.readouterr().out)
    completed = project_root / "work-items" / "03-complete" / item.name
    assert result["mode"] == "apply"
    assert result["decision_counts"]["finish-ready"] == 1
    assert result["applied"][0]["marked_status"] == "finished"
    assert completed.is_dir()
    assert not item.exists()
    completed_metadata = yaml.safe_load((completed / "work.yml").read_text(encoding="utf-8"))
    assert completed_metadata["status"] == "finished"
    assert completed_metadata["lane"] == "03-complete"


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


def test_cleanup_closed_worktrees_removes_merged_project_checkouts_unless_reopened(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "shared_factory", "genomes_agentic_os", "--root", str(root)]) == 0
    project_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os"
    clean_worktree = project_root / "worktrees" / "clean-merged"
    dirty_worktree = project_root / "worktrees" / "dirty-merged"
    reopened_worktree = project_root / "worktrees" / "reopened-merged"
    external_worktree = tmp_path / "external-merged"
    clean_worktree.mkdir(parents=True)
    dirty_worktree.mkdir(parents=True)
    reopened_worktree.mkdir(parents=True)
    external_worktree.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=clean_worktree, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=dirty_worktree, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=reopened_worktree, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=external_worktree, check=True, capture_output=True)
    (dirty_worktree / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    (reopened_worktree / "REOPEN.md").write_text("Reopened for QA follow-up.\n", encoding="utf-8")
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
                        "id": "reopened-merged",
                        "path": str(reopened_worktree),
                        "link": "worktrees/reopened-merged",
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
    assert applied["candidate_count"] == 4
    assert not clean_worktree.exists()
    assert not dirty_worktree.exists()
    assert reopened_worktree.is_dir()
    assert external_worktree.is_dir()
    assert applied["skipped"] == [
        {"path": str(reopened_worktree), "reason": "REOPEN.md present; ask before cleanup"},
        {"path": str(external_worktree), "reason": "target is outside project worktrees/"},
    ]


# ---------------------------------------------------------------------------
# WI-004: lifecycle_closeout_readiness_check
# ---------------------------------------------------------------------------

def test_lifecycle_closeout_readiness_check_incomplete_packet(tmp_path: Path) -> None:
    """Readiness check returns findings when a state-required file is missing."""
    from genomes_agentic_os.validate import lifecycle_closeout_readiness_check

    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)

    # Work item is created with status "specified" which requires SPEC.md.
    # Delete SPEC.md to make the packet incomplete.
    spec_path = work_root / "SPEC.md"
    assert spec_path.is_file(), "expected SPEC.md from scaffold"
    spec_path.unlink()

    findings = lifecycle_closeout_readiness_check(work_root)
    assert findings, "expected at least one finding for missing SPEC.md"
    messages = [f["message"] for f in findings]
    assert any("SPEC.md" in m for m in messages), f"expected SPEC.md in findings: {messages}"
    for finding in findings:
        assert "severity" in finding
        assert "path" in finding
        assert "message" in finding


def test_lifecycle_closeout_readiness_check_complete_packet(tmp_path: Path) -> None:
    """Readiness check returns empty list when the packet has all required files."""
    from genomes_agentic_os.validate import lifecycle_closeout_readiness_check

    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)

    # The scaffold creates a complete packet; no files removed.
    findings = lifecycle_closeout_readiness_check(work_root)
    assert findings == [], f"expected no findings for complete packet, got: {findings}"


def test_thread_end_succeeds_despite_readiness_findings(tmp_path: Path) -> None:
    """Closeout must succeed (exit 0) even when readiness findings exist (non-blocking gate)."""
    root = tmp_path / "agentic_os"
    work_root = create_project_with_work_item(root)

    # Make the packet incomplete so readiness findings will be generated.
    spec_path = work_root / "SPEC.md"
    assert spec_path.is_file()
    spec_path.unlink()

    exit_code = main(
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
            "readiness_gate_test",
            "--summary",
            "Closeout with incomplete packet.",
            "--next-action",
            "None",
            "--skip-notion",
        ]
    )
    # Gate is advisory — closeout must not abort.
    assert exit_code == 0, "closeout must succeed even when readiness findings exist"

    closeout_root = dated_artifact(work_root / "artifacts" / "thread-closeouts", "readiness_gate_test")
    assert (closeout_root / "thread-closeout.yml").is_file()

    payload = yaml.safe_load((closeout_root / "thread-closeout.yml").read_text(encoding="utf-8"))
    assert payload["thread"]["id"] == closeout_root.name
