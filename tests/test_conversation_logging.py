"""Tests for conversation_logging.py — plan-22 validation requirements.

Covers:
- Synthetic Claude stop payload handling
- Synthetic Codex stop payload handling
- Token-shaped value redaction (never reaches disk)
- Temp-root smoke test simulating the hook end-to-end
- Hook-failure logging: forced exception lands in hook log without raising
- LOS policy fixture: specified work item with Jira-targeted external_tracker,
  promotes without live Jira writes
"""

from __future__ import annotations

import json
from pathlib import Path
import textwrap
from typing import Any

import pytest
import yaml

from genomes_agentic_os.conversation_logging import (
    append_hook_failure,
    conversation_log_from_payload,
    find_os_root,
    main,
    redact_json,
    _HOOK_LOG_RELATIVE,
)
from genomes_agentic_os.lifecycle import (
    TOKEN_SHAPED_VALUE_RE,
    contains_token_shaped_value,
    redact_text,
)
from genomes_agentic_os.scaffold import create_project, init_os
from genomes_agentic_os.work_lifecycle import (
    create_project_work_item,
    promote_project_work_item,
    work_lifecycle_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_os_root(tmp_path: Path) -> Path:
    """Create a minimal installed OS root suitable for hook tests."""
    root = tmp_path / "agentic_os"
    projects_source = tmp_path / "projects"
    projects_source.mkdir()
    init_os(root, projects_source=projects_source)
    return root


def _write_transcript(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. Synthetic Claude stop payload
# ---------------------------------------------------------------------------

class TestClaudeStopPayload:
    """Verify the hook handles a realistic Claude PostToolUse/Stop payload."""

    def test_claude_stop_payload_produces_ok_result(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript, [
            {"type": "message", "role": "user", "content": "Hello from Claude"},
            {"type": "tool_result", "tool_use_id": "tu_001", "content": "done"},
        ])
        payload = {
            "hook_event_name": "Stop",
            "session_id": "claude-test-session",
            "cwd": str(root),
            "transcript_path": str(transcript),
        }
        result = conversation_log_from_payload(payload)
        assert result["ok"] is True
        assert result["root"] == str(root)
        assert Path(result["tool_calls_jsonl"]).is_file()
        assert Path(result["tool_calls_markdown"]).is_file()

    def test_claude_stop_payload_writes_redacted_transcript(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        # Inject a token-shaped value into the transcript
        _write_transcript(transcript, [
            {"type": "message", "role": "assistant", "content": "token: sk-abc1234567890ABCDEF12345"},
        ])
        payload = {
            "hook_event_name": "Stop",
            "session_id": "claude-redact-test",
            "cwd": str(root),
            "transcript_path": str(transcript),
        }
        result = conversation_log_from_payload(payload)
        assert result["ok"] is True
        assert result["redacted"] is True
        raw_path = Path(result["raw_transcript"])
        assert raw_path.is_file()
        content = raw_path.read_text(encoding="utf-8")
        # Token must not appear verbatim on disk
        assert "sk-abc1234567890ABCDEF12345" not in content
        assert "[REDACTED]" in content


# ---------------------------------------------------------------------------
# 2. Synthetic Codex stop payload
# ---------------------------------------------------------------------------

class TestCodexStopPayload:
    """Verify the hook handles a Codex-style stop payload (different field names)."""

    def test_codex_stop_payload_uses_sessionId_camelCase(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        transcript = tmp_path / "codex_transcript.jsonl"
        _write_transcript(transcript, [
            {"event": "mcp_call", "name": "Bash", "arguments": {"command": "ls"}},
            {"event": "mcp_result", "name": "Bash", "output": "file.txt"},
        ])
        payload = {
            # Codex uses camelCase session/transcript keys
            "sessionId": "codex-test-session-001",
            "transcriptPath": str(transcript),
            "cwd": str(root),
        }
        result = conversation_log_from_payload(payload)
        assert result["ok"] is True
        assert result["tool_call_count"] > 0, "Codex mcp_call events should be detected as tool calls"

    def test_codex_stop_payload_without_transcript_still_writes_stubs(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        payload = {
            "sessionId": "codex-no-transcript",
            "cwd": str(root),
            # No transcriptPath — Codex may not always provide one
        }
        result = conversation_log_from_payload(payload)
        assert result["ok"] is True
        # Stub files (empty tool calls) must still be created
        assert Path(result["tool_calls_jsonl"]).is_file()
        assert Path(result["tool_calls_markdown"]).is_file()
        assert result["raw_transcript"] == ""  # no source transcript


# ---------------------------------------------------------------------------
# 3. Redaction tests
# ---------------------------------------------------------------------------

class TestTokenRedaction:
    """Prove token-shaped values never reach disk."""

    _TOKEN_SAMPLES = [
        "sk-abcdefghijklmnopqrstuvwxyz1234",      # OpenAI-style
        "ghp_ABCDEFghijklmnopqrstuvwxyz123456",   # GitHub PAT
        "xoxb-fakefixturevalue-notarealsecret",  # Slack bot token
        "bearer abcdef1234567890abcdef1234567890", # Bearer token
        "api_key: my_super_secret_key_1234567890",# api_key assignment
    ]

    @pytest.mark.parametrize("token", _TOKEN_SAMPLES)
    def test_token_shaped_value_regex_matches(self, token: str) -> None:
        """TOKEN_SHAPED_VALUE_RE detects each token pattern."""
        assert contains_token_shaped_value(token), f"Expected match for: {token!r}"

    @pytest.mark.parametrize("token", _TOKEN_SAMPLES)
    def test_redact_text_removes_token(self, token: str) -> None:
        """redact_text replaces the token with [REDACTED]."""
        result = redact_text(token)
        assert "[REDACTED]" in result
        # The raw token body should not survive (check the distinctive part)
        # Extract a 12+ char run of alphanumerics from the token to check absence
        import re
        bodies = re.findall(r"[a-zA-Z0-9]{12,}", token)
        for body in bodies:
            assert body not in result, f"Raw token body {body!r} survived redaction"

    def test_redact_json_cleans_nested_structures(self) -> None:
        """redact_json recurses into dicts and lists."""
        data = {
            "messages": [
                {"role": "user", "content": "my key is sk-abcdefghij123456789012"},
                {"role": "assistant", "content": "I see"},
            ],
            "meta": {"token": "bearer abcdefghijklmnopqrstuvwxyz"},
        }
        cleaned = redact_json(data)
        flat = json.dumps(cleaned)
        assert "sk-abcdefghij123456789012" not in flat
        assert "bearer abcdefghijklmnopqrstuvwxyz" not in flat
        assert "[REDACTED]" in flat

    def test_token_does_not_reach_disk(self, tmp_path: Path) -> None:
        """End-to-end: a token in a transcript is never written verbatim to disk."""
        root = _make_os_root(tmp_path)
        transcript = tmp_path / "transcript.jsonl"
        secret = "sk-supersecret1234567890abcdefgh"
        _write_transcript(transcript, [
            {"type": "message", "content": f"my key is {secret}"},
        ])
        payload = {
            "cwd": str(root),
            "transcript_path": str(transcript),
            "session_id": "redact-disk-test",
        }
        result = conversation_log_from_payload(payload)
        assert result["ok"] is True
        # Scan every file written under the OS root for the secret
        written_files = [
            Path(result["raw_transcript"]),
            Path(result["tool_calls_jsonl"]),
            Path(result["tool_calls_markdown"]),
        ]
        for fpath in written_files:
            if fpath.is_file() and fpath.stat().st_size > 0:
                content = fpath.read_text(encoding="utf-8")
                assert secret not in content, f"Secret found in {fpath}"


# ---------------------------------------------------------------------------
# 4. Temp-root smoke test
# ---------------------------------------------------------------------------

class TestTempRootSmoke:
    """End-to-end smoke: init root → create project → capture idea →
    simulate conversation logging hook → verify lifecycle state."""

    def test_full_hook_lifecycle_smoke(self, tmp_path: Path) -> None:
        # Step 1: init root
        root = _make_os_root(tmp_path)
        assert (root / ".agentic_root").is_file()

        # Step 2: create a project under the 'personal' domain
        create_project(root, "personal", "test_smoke_project")
        project_root = root / "personal" / "02-projects" / "test_smoke_project"
        assert project_root.is_dir()
        assert (project_root / "project.yml").is_file()

        # Step 3: capture a project idea (create a work item)
        wi_result = create_project_work_item(
            root,
            "personal",
            "test_smoke_project",
            title="Smoke test idea",
            summary="Testing the full hook lifecycle",
            state="captured",
        )
        assert wi_result["state"] == "captured"
        work_item_id = wi_result["work_item"]
        work_item_path = Path(wi_result["path"])
        assert work_item_path.is_dir()
        assert (work_item_path / "work.yml").is_file()

        # Step 4: promote to spec
        promote_result = promote_project_work_item(
            root,
            "personal",
            "test_smoke_project",
            work_item_id,
            state="specified",
            note="Smoke test promotion to specified",
        )
        assert promote_result["state"] == "specified"
        # Promotion moves the item from 01-intake to the 02-active lane.
        work_item_path = Path(promote_result["path"])
        assert work_item_path.is_dir()

        # Step 5: simulate conversation logging hook
        transcript = tmp_path / "smoke_transcript.jsonl"
        _write_transcript(transcript, [
            {"type": "message", "role": "user", "content": "start work"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}},
        ])
        payload = {
            "cwd": str(work_item_path),  # cwd inside work item triggers routing
            "transcript_path": str(transcript),
            "session_id": "smoke-test-session",
        }
        hook_result = conversation_log_from_payload(payload)
        assert hook_result["ok"] is True, f"Hook failed: {hook_result}"

        # Step 6: verify lifecycle state — conversations log directory created
        conv_log_dir = work_item_path / "logs" / "conversations"
        assert conv_log_dir.is_dir()
        log_files = list(conv_log_dir.iterdir())
        # At least tool_calls files should be present
        assert len(log_files) >= 2, f"Expected conversation log files, got: {log_files}"


# ---------------------------------------------------------------------------
# 5. Hook-failure visibility
# ---------------------------------------------------------------------------

class TestHookFailureLogging:
    """Forced hook failures land in the hook log without raising."""

    def test_forced_failure_writes_hook_log_entry(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        append_hook_failure(root, "conversation_logging", "ValueError: test failure")

        log_path = root / _HOOK_LOG_RELATIVE
        assert log_path.is_file(), f"Hook log not created at {log_path}"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["hook"] == "conversation_logging"
        assert "ValueError: test failure" in entry["error"]
        assert "timestamp" in entry
        # Timestamp must be an ISO-8601 string (non-empty)
        assert len(entry["timestamp"]) >= 10

    def test_multiple_failures_append_to_same_log(self, tmp_path: Path) -> None:
        root = _make_os_root(tmp_path)
        for i in range(3):
            append_hook_failure(root, "conversation_logging", f"error #{i}")
        log_path = root / _HOOK_LOG_RELATIVE
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(entries) == 3

    def test_hook_failure_does_not_raise(self, tmp_path: Path) -> None:
        """append_hook_failure is always silent — even with a non-writable path."""
        # Pass None root so it tries a fallback path; we just verify no exception
        try:
            append_hook_failure(None, "conversation_logging", "silent error")
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"append_hook_failure raised: {exc}")

    def test_main_captures_exception_in_hook_log(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() writes to hook log when conversation_log_from_payload raises."""
        root = _make_os_root(tmp_path)

        def _exploding_payload(payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("simulated hook crash")

        monkeypatch.setattr(
            "genomes_agentic_os.conversation_logging.conversation_log_from_payload",
            _exploding_payload,
        )
        # main() reads from stdin; supply a valid payload pointing at our root
        payload_str = json.dumps({"cwd": str(root)})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload_str))

        # Must not raise; must return 0
        rc = main([])
        assert rc == 0

        log_path = root / _HOOK_LOG_RELATIVE
        assert log_path.is_file(), "Hook log must be written when main() catches an exception"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(entries) >= 1
        assert "simulated hook crash" in entries[-1]["error"]

    def test_hook_log_entry_never_contains_token_shaped_value(self, tmp_path: Path) -> None:
        """Error summaries are not redacted (they should be safe), but
        we assert that append_hook_failure doesn't accidentally embed tokens."""
        root = _make_os_root(tmp_path)
        safe_error = "OSError: permission denied on /tmp/foo"
        append_hook_failure(root, "conversation_logging", safe_error)
        log_path = root / _HOOK_LOG_RELATIVE
        raw = log_path.read_text(encoding="utf-8")
        # The safe error is preserved verbatim
        assert safe_error in raw
        # No token-shaped patterns should be in a safe error summary
        assert not contains_token_shaped_value(raw)


# ---------------------------------------------------------------------------
# 6. LOS policy fixture — specified → Jira-targeted mirror (no live writes)
# ---------------------------------------------------------------------------

class TestLOSPolicyJiraFixture:
    """Proves a work item at state 'specified' with a Jira-targeted
    external_tracker config can promote to a Jira-targeted mirror without
    any live Jira network calls.

    Pattern follows feature-60 style: build the minimal filesystem scaffold,
    configure the project's work-lifecycle.yml, call the Python API directly,
    assert on the returned dict and on the state of on-disk files.
    """

    def _make_los_django_project(self, tmp_path: Path) -> tuple[Path, Path]:
        """Return (os_root, project_root) with a Jira-targeted work-lifecycle config."""
        root = _make_os_root(tmp_path)
        # Create a project that mirrors the LOS Django pattern
        create_project(root, "los", "los_app_los_django")
        project_root = root / "los" / "02-projects" / "los_app_los_django"

        # Write a work-lifecycle.yml that routes specified items to Jira.
        # Keys are at the top level (not nested under 'work_lifecycle:') —
        # that is what work_lifecycle_config() reads from config/work-lifecycle.yml.
        config_dir = project_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        lifecycle_config = {
            "enabled": True,
            "work_items_root": "work-items",
            "default_state": "captured",
            "transcript_logging": {
                "enabled": True,
                "include_raw_transcript": True,
                "include_tool_call_jsonl": True,
                "include_tool_call_markdown": True,
                "redaction_policy": "strict",
            },
            "spec_destination": {
                "type": "jira",
                "project_key": "DLOS",
                "local_mirror": True,
            },
            "external_tracker": {
                "type": "jira",
                "key_field": "jira_key",
            },
        }
        (config_dir / "work-lifecycle.yml").write_text(
            yaml.safe_dump(lifecycle_config, sort_keys=False),
            encoding="utf-8",
        )
        return root, project_root

    def test_work_lifecycle_config_reads_jira_external_tracker(self, tmp_path: Path) -> None:
        """work_lifecycle_config returns the Jira tracker config from work-lifecycle.yml."""
        _root, project_root = self._make_los_django_project(tmp_path)
        config = work_lifecycle_config(project_root)
        assert config["external_tracker"]["type"] == "jira"
        assert config["external_tracker"]["key_field"] == "jira_key"
        assert config["spec_destination"]["type"] == "jira"
        assert config["spec_destination"]["project_key"] == "DLOS"
        assert config["spec_destination"]["local_mirror"] is True

    def test_create_work_item_in_jira_configured_project(self, tmp_path: Path) -> None:
        """create_project_work_item succeeds with Jira config — no network call needed."""
        root, _project_root = self._make_los_django_project(tmp_path)
        result = create_project_work_item(
            root,
            "los",
            "los_app_los_django",
            title="DLOS-style feature",
            summary="Route a specified item to Jira without live writes",
            state="captured",
        )
        assert result["state"] == "captured"
        work_item_id = result["work_item"]
        work_item_path = Path(result["path"])
        assert work_item_path.is_dir()
        assert (work_item_path / "work.yml").is_file()

        # work.yml carries the Jira tracker config as metadata (for agent reference)
        work_yml = yaml.safe_load((work_item_path / "work.yml").read_text(encoding="utf-8"))
        assert work_yml["external_tracker"]["type"] == "jira"
        assert work_yml["spec_destination"]["project_key"] == "DLOS"

    def test_specified_state_promotes_locally_without_live_jira_writes(self, tmp_path: Path) -> None:
        """Promoting a work item to 'specified' records the state and destination
        in local files only.  No Jira client is invoked; the function must not
        raise, and work.yml must reflect the new state."""
        root, _project_root = self._make_los_django_project(tmp_path)

        # Create work item at 'captured'
        create_result = create_project_work_item(
            root,
            "los",
            "los_app_los_django",
            title="DLOS-style feature",
            summary="Promote to specified",
            state="captured",
        )
        work_item_id = create_result["work_item"]
        work_item_path = Path(create_result["path"])

        # Promote to 'specified' — must succeed with no live Jira writes
        promote_result = promote_project_work_item(
            root,
            "los",
            "los_app_los_django",
            work_item_id,
            state="specified",
            note="Spec complete; ready for Jira mirror",
        )
        assert promote_result["state"] == "specified"
        assert promote_result["old_state"] == "captured"
        # Promotion moves the item from 01-intake to the 02-active lane.
        work_item_path = Path(promote_result["path"])

        # Local mirror is the evidence: work.yml reflects new state
        work_yml = yaml.safe_load((work_item_path / "work.yml").read_text(encoding="utf-8"))
        assert work_yml["state"] == "specified"

        # WORKLOG.md and NEXT.md are updated
        worklog = (work_item_path / "WORKLOG.md").read_text(encoding="utf-8")
        assert "specified" in worklog
        next_md = (work_item_path / "NEXT.md").read_text(encoding="utf-8")
        assert "specified" in next_md

        # Jira tracker config is still present in work.yml (agent reference)
        assert work_yml["external_tracker"]["type"] == "jira"
        assert work_yml["spec_destination"]["local_mirror"] is True

    def test_promote_does_not_require_jira_credentials(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Promote must succeed even when JIRA_API_TOKEN is absent."""
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)

        root, _project_root = self._make_los_django_project(tmp_path)
        create_result = create_project_work_item(
            root,
            "los",
            "los_app_los_django",
            title="No creds feature",
            summary="Jira credentials absent",
            state="captured",
        )
        # This must not raise — Jira integration is additive/optional
        promote_result = promote_project_work_item(
            root,
            "los",
            "los_app_los_django",
            create_result["work_item"],
            state="specified",
            note="No credentials — local only",
        )
        assert promote_result["state"] == "specified"
