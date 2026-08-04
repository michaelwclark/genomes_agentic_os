from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import jsonschema
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.cockpit import (
    SCHEMA_VERSION,
    build_cockpit_bundle,
    build_cockpit_snapshot,
    collect_conversations,
    collect_hygiene,
    collect_work_items,
)
from genomes_agentic_os.review_queue import queue_kind, review_payload
from genomes_agentic_os.state import db as state_db
from genomes_agentic_os.state import queue as state_queue


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    item = root / "domains" / "clarks_consulting" / "02-projects" / "genomes_agentic_os" / "work-items" / "02-active" / "040_demo"
    conversations = item / "logs" / "conversations"
    conversations.mkdir(parents=True)
    (item / "work.yml").write_text(
        yaml.safe_dump(
            {
                "id": "040_demo",
                "title": "Demo cockpit",
                "domain": "clarks_consulting",
                "project": "genomes_agentic_os",
                "status": "building",
                "updated_at": "2026-07-13T10:00:00Z",
                "summary": "Unify engineering lead state in one local projection.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (item / "SPEC.md").write_text(
        "# Spec\n\nTrack FLYWL-2400 and https://github.com/example/app/pull/123.\n",
        encoding="utf-8",
    )
    (item / "NEXT.md").write_text("# Next\n\n- Build and validate the cockpit.\n", encoding="utf-8")
    rows = [
        {"type": "session_meta", "payload": {"id": "session-1", "timestamp": "2026-07-13T11:00:00Z", "cwd": str(item), "originator": "codex"}},
        {"type": "response_item", "payload": {"text": "Review FLYWL-2400 and https://github.com/example/app/pull/123"}},
    ]
    (conversations / "session.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    hosts = root / "harness" / "config"
    hosts.mkdir(parents=True)
    (hosts / "hosts.yml").write_text(
        yaml.safe_dump({"hosts": {"genomesbox": {"hostname": "genomesbox", "roles": ["runtime"]}}}),
        encoding="utf-8",
    )
    worktrees = item.parents[2] / "worktrees"
    worktrees.mkdir(parents=True)
    (worktrees / "stale-demo").symlink_to(tmp_path / "missing-worktree")
    return root


def test_work_and_conversation_collectors_extract_route_and_refs(tmp_path: Path) -> None:
    root = _root(tmp_path)
    work = collect_work_items(root)
    conversations = collect_conversations(root, max_files=10, include_harness_sessions=False)

    assert work[0]["id"] == "040_demo"
    assert work[0]["jira_keys"] == ["FLYWL-2400"]
    assert work[0]["pull_requests"][0]["number"] == "123"
    assert conversations[0]["harness"] == "codex"
    assert conversations[0]["project"] == "genomes_agentic_os"
    assert conversations[0]["work_item"] == "040_demo"
    assert conversations[0]["jira_keys"] == ["FLYWL-2400"]


def test_snapshot_is_schema_valid_and_read_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    snapshot = build_cockpit_snapshot(root, now=NOW, max_files=20, include_harness_sessions=False)
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "cockpit-snapshot.schema.json").read_text(encoding="utf-8"))

    jsonschema.validate(snapshot, schema)
    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["summary"]["active_work"] == 1
    assert snapshot["summary"]["conversations"] == 1
    assert snapshot["summary"]["reviews"] == 1
    assert snapshot["summary"]["hosts"] == 1
    assert snapshot["root"] == str(root.resolve())
    assert all(isinstance(item, dict) for item in snapshot["diagnostics"])
    assert all(item.get("id") for group in snapshot["sources"].values() for item in group)


def test_snapshot_surfaces_generalized_state_plane_reviews(tmp_path: Path) -> None:
    root = _root(tmp_path)
    connection = state_db.connect(state_db.default_db_path(root))
    try:
        state_queue.enqueue(
            connection,
            id="proposal-review",
            kind=queue_kind("proposal"),
            status="approval-needed",
            payload=review_payload(
                "proposal",
                title="Approve control-plane proposal",
                summary="A proposal is waiting for adjudication.",
                subject="AGE-49",
            ),
        )
    finally:
        connection.close()

    snapshot = build_cockpit_snapshot(root, now=NOW, max_files=20, include_harness_sessions=False)

    review = next(item for item in snapshot["reviews"] if item["id"] == "review-queue:proposal-review")
    assert review["review_kind"] == "proposal"
    assert review["status"] == "approval-needed"
    assert "review-queue" in review["tags"]


def test_hygiene_only_proposes_existing_guarded_commands(tmp_path: Path) -> None:
    root = _root(tmp_path)
    work = collect_work_items(root)
    conversations = collect_conversations(root, max_files=10, include_harness_sessions=False)
    findings = collect_hygiene(root, work, conversations, now=NOW)

    broken = next(item for item in findings if item["kind"] == "worktree")
    assert "cleanup-closed" in broken["suggested_command"]
    assert (root / "domains" / "clarks_consulting" / "02-projects" / "genomes_agentic_os" / "worktrees" / "stale-demo").is_symlink()


def test_bundle_and_cli_build_offline_artifacts(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    output = tmp_path / "cockpit"
    result = build_cockpit_bundle(root, output_dir=output, now=NOW, max_files=20, include_harness_sessions=False)

    assert Path(result["snapshot_path"]).is_file()
    html_path = Path(result["html_path"])
    assert html_path.is_file()
    assert "Agentic OS Cockpit" in html_path.read_text(encoding="utf-8")

    cli_output = tmp_path / "cli-cockpit"
    assert main([
        "cockpit",
        "build",
        "--root",
        str(root),
        "--output-dir",
        str(cli_output),
        "--max-files",
        "20",
        "--no-harness-sessions",
    ]) == 0
    output_text = capsys.readouterr().out
    assert "snapshot:" in output_text
    assert (cli_output / "snapshot.json").is_file()
    assert (cli_output / "index.html").is_file()
