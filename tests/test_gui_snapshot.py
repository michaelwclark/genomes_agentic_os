from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import jsonschema
import yaml

from genomes_agentic_os.gui_snapshot import SCHEMA_VERSION, build_gui_snapshot, build_transcript_snapshot
from genomes_agentic_os.long_run import update_registry
from genomes_agentic_os.runtime_backend import apply_queue_mode
from genomes_agentic_os.runtime_ops import append_run_queue_item, runtime_init
from genomes_agentic_os.state import db


NOW = datetime(2026, 7, 13, 18, 0, tzinfo=timezone.utc)
CODEX_ID = "11111111-1111-4111-8111-111111111111"
DESCRIPTION_ONLY_ID = "22222222-2222-4222-8222-222222222222"
CLAUDE_DESKTOP_ID = "33333333-3333-4333-8333-333333333333"
CLAUDE_CLI_ID = "44444444-4444-4444-8444-444444444444"


def make_gui_fixture(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "agentic_os"
    project = root / "domains" / "los" / "02-projects" / "los_app_los_django"
    repo = tmp_path / "projects" / "los-django"
    repo.mkdir(parents=True)
    project.mkdir(parents=True)
    (project / "src").symlink_to(repo)
    (root / "domains" / "los" / "domain.yml").write_text("title: LOS\n", encoding="utf-8")
    (project / "project.yml").write_text(
        yaml.safe_dump({"title": "LOS Django", "status": "active"}),
        encoding="utf-8",
    )
    item = project / "work-items" / "02-active" / "041_retry_fix"
    item.mkdir(parents=True)
    (item / "work.yml").write_text("id: 041_retry_fix\n", encoding="utf-8")
    (item / "SPEC.md").write_text(
        "FLYWL-2044 https://github.com/example/los/pull/42\n",
        encoding="utf-8",
    )

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    rollout = codex_home / "sessions" / "2026" / "07" / "13" / f"rollout-{CODEX_ID}.jsonl"
    rollout.parent.mkdir(parents=True)
    codex_rows = [
        {
            "type": "response_item",
            "timestamp": "2026-07-13T17:00:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Review FLYWL-2044 at https://github.com/example/los/pull/42 "
                            "and https://example.slack.com/archives/C1234567890/p1783951200000000 "
                            f"using {repo / 'design.png'}"
                        ),
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-13T17:05:00Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The review is ready."}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "PRIVATE DEVELOPER CONTROL"}],
            },
        },
    ]
    rollout.write_text("".join(json.dumps(row) + "\n" for row in codex_rows), encoding="utf-8")

    database = codex_home / "state_5.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE threads (
          id TEXT PRIMARY KEY, rollout_path TEXT, created_at INTEGER, updated_at INTEGER,
          created_at_ms INTEGER, updated_at_ms INTEGER, recency_at_ms INTEGER,
          source TEXT, thread_source TEXT, model_provider TEXT, model TEXT,
          reasoning_effort TEXT, cwd TEXT, title TEXT, first_user_message TEXT,
          preview TEXT, archived INTEGER
        )
        """
    )
    base = (
        str(rollout),
        1783960000,
        1783962300,
        1783960000000,
        1783962300000,
        1783962300000,
        "vscode",
        "user",
        "openai",
        "gpt-5.6-sol",
        "high",
        str(root),
        "A very long original prompt that is not the native Desktop title",
        "Review the LOS retry behavior",
        "Review retry behavior",
        0,
    )
    connection.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (CODEX_ID, *base))
    connection.execute(
        "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (DESCRIPTION_ONLY_ID, *base),
    )
    connection.commit()
    connection.close()
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "pinned-thread-ids": [CODEX_ID],
                "projectless-thread-ids": [],
                "thread-project-assignments": {CODEX_ID: {"cwd": str(repo)}},
                "electron-persisted-atom-state": {
                    "thread-descriptions-v1": {
                        CODEX_ID: "Review LOS Django retry behavior",
                        DESCRIPTION_ONLY_ID: "Description cache is not an active UI reference",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (codex_home / "session_index.jsonl").write_text(
        json.dumps({"id": CODEX_ID, "thread_name": "Short fallback title", "updated_at": "2026-07-13T17:00:00Z"})
        + "\n",
        encoding="utf-8",
    )

    claude_home = tmp_path / ".claude"
    transcript = claude_home / "projects" / "-tmp-project" / f"{CLAUDE_CLI_ID}.jsonl"
    transcript.parent.mkdir(parents=True)
    claude_rows = [
        {
            "type": "user",
            "timestamp": "2026-07-13T16:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Continue FLYWL-2044 and https://github.com/example/los/pull/42"},
                    {"type": "tool_result", "content": "PRIVATE TOOL RESULT"},
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-13T16:05:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will prepare the patch."},
                    {"type": "tool_use", "name": "Read", "input": {"path": "/secret"}},
                ],
            },
        },
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "PRIVATE META"}},
    ]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in claude_rows), encoding="utf-8")

    claude_desktop = tmp_path / "Claude" / "claude-code-sessions"
    metadata_dir = claude_desktop / "account" / "organization"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "local_active.json").write_text(
        json.dumps(
            {
                "sessionId": CLAUDE_DESKTOP_ID,
                "cliSessionId": CLAUDE_CLI_ID,
                "cwd": str(root),
                "createdAt": 1783950000000,
                "lastActivityAt": 1783960000000,
                "model": "claude-fable-5",
                "effort": "max",
                "isArchived": False,
                "title": "Review LOS Django retry behavior in Claude",
                "prNumber": 44,
                "prUrl": "https://github.com/example/los/pull/44",
                "prRepository": "example/los",
                "prState": "OPEN",
                "prs": [
                    {
                        "prNumber": 43,
                        "url": "https://github.com/example/los/pull/43",
                        "repo": "example/los",
                        "state": "OPEN",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (metadata_dir / "local_archived.json").write_text(
        json.dumps(
            {
                "sessionId": "55555555-5555-4555-8555-555555555555",
                "cliSessionId": "66666666-6666-4666-8666-666666666666",
                "isArchived": True,
                "title": "Archived task",
            }
        ),
        encoding="utf-8",
    )
    return {
        "root": root,
        "repo": repo,
        "codex_home": codex_home,
        "claude_home": claude_home,
        "claude_desktop": claude_desktop,
    }


def test_snapshot_joins_native_open_sets_and_validates_schema(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    snapshot = build_gui_snapshot(
        fixture["root"],
        codex_home=fixture["codex_home"],
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
        now=NOW,
    )
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "gui-snapshot.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(snapshot, schema)

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["summary"] == {"conversations": 2, "codex": 1, "claude": 1, "pinned": 1, "unrouted": 0}
    assert {item["key"] for item in snapshot["conversations"]} == {
        f"codex:{CODEX_ID}",
        f"claude:{CLAUDE_DESKTOP_ID}",
    }
    assert DESCRIPTION_ONLY_ID not in {item["id"] for item in snapshot["conversations"]}

    codex = next(item for item in snapshot["conversations"] if item["harness"] == "codex")
    assert codex["title"] == "Review LOS Django retry behavior"
    assert codex["provider"] == "openai"
    assert codex["model_tier"] == "frontier"
    assert codex["route_source"] == "native_workspace_hint"
    assert codex["jira_keys"] == ["FLYWL-2044"]

    claude = next(item for item in snapshot["conversations"] if item["harness"] == "claude")
    assert claude["id"] == CLAUDE_DESKTOP_ID
    assert claude["resume_id"] == CLAUDE_CLI_ID
    assert claude["id"] != claude["resume_id"]
    assert claude["imported"] is True
    assert claude["continuation"]["fallback_argv"][-1] == "--fork-session"
    assert {str(item["number"]) for item in claude["pull_requests"]} == {"42", "43", "44"}
    assert claude["work_item"] == "041_retry_fix"

    domain = snapshot["navigation"]["domains"][0]
    assert domain["name"] == "LOS"
    assert domain["projects"][0]["name"] == "LOS Django"
    assert domain["projects"][0]["domain"] == "los"


def test_gui_v1_schema_still_accepts_legacy_snapshot_without_runtime(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    snapshot = build_gui_snapshot(
        fixture["root"],
        codex_home=fixture["codex_home"],
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
        now=NOW,
    )
    snapshot.pop("runtime")
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "gui-snapshot.schema.json").read_text(encoding="utf-8"))

    jsonschema.validate(snapshot, schema)


def test_command_center_snapshot_exposes_named_queue_and_worker_health(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    runtime_init(fixture["root"])
    apply_queue_mode(fixture["root"], "execution_fabric", dry_run=False)
    append_run_queue_item(
        fixture["root"],
        {
            "id": "gui-codex",
            "kind": "manual",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "codex_harness",
        },
    )
    snapshot = build_gui_snapshot(
        fixture["root"],
        codex_home=fixture["codex_home"],
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
        now=NOW,
    )

    assert snapshot["runtime"]["status"] == "healthy"
    assert snapshot["runtime"]["queue_mode"] == "execution_fabric"
    assert snapshot["runtime"]["queue_depth"] == 1
    assert snapshot["runtime"]["retrying"] == 0
    assert snapshot["runtime"]["delayed_retries"] == 0
    assert snapshot["runtime"]["oldest_wait_seconds"] >= 0
    assert {queue["queue_name"] for queue in snapshot["runtime"]["queues"]} == {"codex", "claude", "non_llm"}
    assert snapshot["runtime"]["task_count"] == 1
    assert snapshot["runtime"]["tasks"][0]["id"] == "gui-codex"
    assert snapshot["runtime"]["tasks"][0]["queue_name"] == "codex"
    assert snapshot["runtime"]["captured_at"]
    assert snapshot["runtime"]["max_interactive_running"] == 1
    assert snapshot["runtime"]["workers"] == []


def test_command_center_snapshot_exposes_long_running_safety_state(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    update_registry(
        fixture["root"],
        {
            "id": "071926-active-scan",
            "kind": "scan",
            "label": "inventory scan",
            "status": "running",
            "phase": "inventory",
            "created_at": "2026-07-19T10:00:00Z",
            "updated_at": "2026-07-19T10:01:00Z",
            "run_dir": str(fixture["root"] / "runs/071926-active-scan"),
        },
    )
    update_registry(
        fixture["root"],
        {
            "id": "071926-stale-migration",
            "kind": "migration",
            "label": "stale migration",
            "status": "stale",
            "phase": "terminal",
            "created_at": "2026-07-19T09:00:00Z",
            "updated_at": "2026-07-19T09:30:00Z",
            "run_dir": str(fixture["root"] / "runs/071926-stale-migration"),
        },
    )

    snapshot = build_gui_snapshot(
        fixture["root"],
        codex_home=fixture["codex_home"],
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
        now=NOW,
    )

    assert snapshot["runtime"]["long_running_active"] == 1
    assert snapshot["runtime"]["long_running_attention"] == 1
    assert {row["id"] for row in snapshot["runtime"]["long_running_runs"]} == {
        "071926-active-scan",
        "071926-stale-migration",
    }


def test_command_center_marks_selected_fabric_unavailable_when_state_database_is_missing(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    runtime_init(fixture["root"])
    apply_queue_mode(fixture["root"], "execution_fabric", dry_run=False)
    db.default_db_path(fixture["root"]).unlink()

    snapshot = build_gui_snapshot(
        fixture["root"],
        codex_home=fixture["codex_home"],
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
        now=NOW,
    )

    assert snapshot["runtime"]["status"] == "unavailable"
    assert "state database is missing" in snapshot["runtime"]["reason"]
    assert any(item["message"] == "Runtime queue health is unavailable." for item in snapshot["diagnostics"])


def test_transcripts_return_only_visible_user_and_assistant_text(tmp_path: Path) -> None:
    fixture = make_gui_fixture(tmp_path)
    codex = build_transcript_snapshot("codex", CODEX_ID, codex_home=fixture["codex_home"])
    claude = build_transcript_snapshot(
        "claude",
        CLAUDE_DESKTOP_ID,
        claude_home=fixture["claude_home"],
        claude_desktop_root=fixture["claude_desktop"],
    )

    assert [message["role"] for message in codex["messages"]] == ["user", "assistant"]
    assert [message["role"] for message in claude["messages"]] == ["user", "assistant"]
    encoded = json.dumps([codex, claude])
    assert "PRIVATE DEVELOPER CONTROL" not in encoded
    assert "PRIVATE TOOL RESULT" not in encoded
    assert "PRIVATE META" not in encoded
    assert codex["truncated"] is False
    assert claude["continuation"]["mode"] == "fork-on-continue"
