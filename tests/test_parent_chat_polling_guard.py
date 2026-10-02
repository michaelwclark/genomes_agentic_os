"""Exercise the actual hook wire protocol, literal parsing and installation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from genomes_agentic_os.hook_ops import required_commands, sync_claude_hooks, sync_codex_hooks
from genomes_agentic_os.scaffold import root_rules


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "harness" / "hooks" / "parent-chat-polling-guard.py"
TOOL = "mcp__codex_app__automation_update"
POLL = {
    "mode": "create", "kind": "heartbeat", "status": "ACTIVE",
    "prompt": "Read PR581 watch-state.json. Stay quiet while checks are pending. On failure repair the test; on terminal success record a receipt.",
    "rrule": "FREQ=MINUTELY;INTERVAL=10",
}


def invoke(tool_input, name=TOOL):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": name, "tool_input": tool_input}),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout) if result.stdout else None


def assert_denied(output, reason="polling"):
    decision = output["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert reason in decision["permissionDecisionReason"]


@pytest.mark.parametrize("mode", ["create", "suggested_create", "update", "suggested_update"])
def test_recurring_observer_creation_and_reactivation_are_denied(mode):
    assert_denied(invoke({**POLL, "mode": mode, "id": "existing"}))


@pytest.mark.parametrize("maintenance", [
    {"mode": "view", "id": "existing"},
    {"mode": "delete", "id": "existing"},
    {"mode": "update", "id": "existing", "status": "PAUSED"},
    {"mode": "update", "id": "existing", "notificationPolicy": "failed_runs_only"},
])
def test_maintenance_stays_silent(maintenance):
    assert invoke(maintenance) is None
    assert invoke(f"await tools.{TOOL}({json.dumps(maintenance)});", "functions.exec") is None


@pytest.mark.parametrize("prompt", [
    "Remind me every week to check the PR queue.",
    "Generate a weekly report comparing failed CI jobs and their causes.",
    "Investigate failed tests in PR581 and implement a repair.",
    "Draft the release notes for the next release.",
    "Build the project and run its tests every night.",
])
def test_ordinary_reminders_and_substantive_work_are_allowed(prompt):
    assert invoke({**POLL, "prompt": prompt}) is None


def test_single_followup_and_standalone_job_are_allowed():
    assert invoke({**POLL, "rrule": "RRULE:FREQ=MINUTELY;COUNT=1;INTERVAL=10"}) is None
    assert invoke({**POLL, "kind": "cron", "prompt": "Generate a nightly CI reliability report."}) is None


def test_status_only_cron_and_reminder_label_are_not_workarounds():
    assert_denied(invoke({**POLL, "kind": "cron"}))
    assert_denied(invoke({**POLL, "prompt": "Reminder: read watch-state.json and check PR581 CI."}))


@pytest.mark.parametrize("prompt", [
    "Read the PR581 watcher state and write a status summary.",
    "Check CI status and write a receipt.",
    "Inspect PR581 checks. Generate a progress summary.",
])
def test_recording_observed_status_does_not_become_substantive_work(prompt):
    assert_denied(invoke({**POLL, "prompt": prompt}))


@pytest.mark.parametrize("source", [
    f"await tools.{TOOL}({json.dumps(POLL)});",
    f"await tools['{TOOL}']({json.dumps(POLL)});",
    "await tools.mcp__codex_app__automation_update({mode:'create',kind:'heartbeat',status:'ACTIVE',prompt:`Monitor CI for PR581; stay quiet while pending`,rrule:'FREQ=MINUTELY;INTERVAL=10',});",
    f"await Promise.all([tools.{TOOL}({{mode:'view',id:'ok'}}), tools.{TOOL}({json.dumps(POLL)})]);",
])
@pytest.mark.parametrize("shape", ["raw", "code", "source", "input"])
def test_wrapped_and_batched_calls_cannot_hide_polling(source, shape):
    payload = source if shape == "raw" else {shape: source}
    assert_denied(invoke(payload, "functions.exec"))


@pytest.mark.parametrize("source", [
    f"await tools.{TOOL}(args);",
    f"await tools.{TOOL}({{...args, mode:'create'}});",
    f"const update = tools.{TOOL}; await update(args);",
    f"await tools.{TOOL}({{mode:'create',prompt:`Watch ${{target}}`}});",
    f"await tools.{TOOL}({{mode:'create',mode:'view'}});",
    f"await tools.{TOOL}({{mode:condition ? 'view' : 'create'}});",
    f"await tools.{TOOL}(JSON.parse(source));",
])
def test_unresolved_automation_inputs_fail_with_direct_call_guidance(source):
    assert_denied(invoke(source, "exec"), "direct")


def test_sparse_reactivation_requires_complete_fields():
    assert_denied(invoke({"mode": "update", "id": "existing", "status": "ACTIVE"}), "direct")


@pytest.mark.parametrize("source", [
    f"// await tools.{TOOL}({json.dumps(POLL)});\ntext('done');",
    f"/* tools.{TOOL}(args) */ await tools.clock__curr_time({{}});",
    f"text({json.dumps('tools.' + TOOL + '(args)')});",
    "await tools.exec_command({cmd:'gh pr view 581'});",
    "await tools.exec_command({cmd:'echo `ordinary ${text}`'});",
    "text(values[`field_${name}`]);",
    "const config = {automation_update: false}; text(config);",
])
def test_comments_strings_and_unrelated_tools_are_not_automation_calls(source):
    assert invoke(source, "functions.exec") is None


def test_paused_object_is_parsed_without_mistaking_prompt_text_for_a_call():
    args = {**POLL, "status": "PAUSED", "prompt": "tools.automation_update(args);"}
    assert invoke(f"await tools.{TOOL}({json.dumps(args)});", "exec") is None


@pytest.mark.parametrize("sync,target", [(sync_codex_hooks, "codex"), (sync_claude_hooks, "claude")])
def test_hook_sync_covers_every_tool_preserves_existing_hooks_and_is_idempotent(tmp_path, sync, target):
    existing = {"matcher": "custom", "hooks": [{"type": "command", "command": "user-hook"}]}
    config = {"hooks": {"PreToolUse": [existing]}}
    assert sync(config, tmp_path)
    assert not sync(config, tmp_path)
    entries = config["hooks"]["PreToolUse"]
    assert existing in entries
    guards = [entry for entry in entries if any("parent-chat-polling-guard.py" in hook["command"] for hook in entry["hooks"])]
    assert len(guards) == 1
    assert guards[0]["matcher"] == "*"
    assert any("parent-chat-polling-guard.py" in command for command in required_commands(tmp_path, target))


@pytest.mark.parametrize("rules", [root_rules(), (ROOT / "templates" / "agent-config" / "RULES.md").read_text()])
def test_generated_rules_have_cross_harness_quiet_execution_policy(rules):
    assert "not recurring model wakeups" in rules
    assert "lib/rules/root/quiet-async-long-runs/RULES.md" in rules
    assert "Claude and Codex" in rules
