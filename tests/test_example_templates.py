"""Tests for the runtime example library (plans 16, 17, and 09).

Verifies that:
- Nine connected-system example files are installed under
  shared_factory/05-knowledge/templates/runtime/examples/connected-systems/
- Nine watch-source example files are installed under
  shared_factory/05-knowledge/templates/runtime/examples/watch-sources/
- Six chain-rule example files are installed under
  shared_factory/05-knowledge/templates/runtime/examples/chain-rules/
- os-capture-plan.md is installed under
  shared_factory/05-knowledge/templates/planning/
- Re-running the install preserves local edits to example files (additive pattern).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.cli import main


def shared_factory(root: Path) -> Path:
    return root / "harness" / "shared_factory"


def knowledge_templates(root: Path) -> Path:
    return shared_factory(root) / "05-knowledge" / "templates"


# ---------------------------------------------------------------------------
# Helpers: expected file paths
# ---------------------------------------------------------------------------

CONNECTED_SYSTEM_EXAMPLES = [
    "notion.yml",
    "slack.yml",
    "jira.yml",
    "linear.yml",
    "email.yml",
    "github.yml",
    "granola.yml",
    "agentmail.yml",
    "filesystem.yml",
]

WATCH_SOURCE_EXAMPLES = [
    "notion-database.yml",
    "slack-channel.yml",
    "jira-jql.yml",
    "linear-team.yml",
    "email-inbox.yml",
    "github-repo.yml",
    "granola-folder.yml",
    "agentmail-inbox.yml",
    "filesystem-glob.yml",
]

CHAIN_RULE_EXAMPLES = [
    "feature-merge-to-docs.yml",
    "email-sent-to-crm.yml",
    "transcript-to-tasks.yml",
    "notion-card-to-worktree.yml",
    "approval-granted.yml",
    "ci-failure-investigation.yml",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_connected_system_examples_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "connected-systems"
    for filename in CONNECTED_SYSTEM_EXAMPLES:
        path = examples_root / filename
        assert path.is_file(), f"Missing connected-system example: {path}"


def test_watch_source_examples_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "watch-sources"
    for filename in WATCH_SOURCE_EXAMPLES:
        path = examples_root / filename
        assert path.is_file(), f"Missing watch-source example: {path}"


def test_chain_rule_examples_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "chain-rules"
    for filename in CHAIN_RULE_EXAMPLES:
        path = examples_root / filename
        assert path.is_file(), f"Missing chain-rule example: {path}"


def test_os_capture_plan_template_is_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    capture_plan = knowledge_templates(root) / "planning" / "os-capture-plan.md"
    assert capture_plan.is_file()
    content = capture_plan.read_text(encoding="utf-8")
    assert "Where To Put New Plans" in content
    assert "Do not create a source-repo planning file" in content
    assert "Installed project `work-items/01-intake/<NNN>_<slug>/SPEC.md`" in content
    assert "SPEC.md" in content


def test_thread_closeout_templates_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    thread_templates = knowledge_templates(root) / "thread"
    expected = {
        "README.md",
        "thread.yml",
        "thread-closeout.yml",
        "closeout.md",
        "evidence.jsonl",
        "memory-write-receipts.jsonl",
        "notion-sync.md",
        "archive-manifest.yml",
    }
    for filename in expected:
        assert (thread_templates / filename).is_file(), f"Missing thread closeout template: {filename}"


def test_end_chat_command_and_finalizer_skill_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    assert (root / "harness" / "commands" / "os-end-chat.md").is_file()
    assert (root / "harness" / "skills" / "thread-finalizer" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-end-chat.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "thread-finalizer" / "SKILL.md").is_file()

    commands = yaml.safe_load((root / "harness" / "registries" / "commands.yml").read_text(encoding="utf-8"))
    command_ids = {entry["id"] for entry in commands["commands"]}
    assert {"end-chat", "finalize", "cleanup-thread", "archive"} <= command_ids

    skills = yaml.safe_load((root / "harness" / "registries" / "skills.yml").read_text(encoding="utf-8"))
    skill_ids = {entry["id"] for entry in skills["skills"]}
    assert "thread-finalizer" in skill_ids


def test_thread_schemas_are_installed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    schemas = root / "harness" / "schemas"
    assert (schemas / "thread.schema.json").is_file()
    assert (schemas / "thread-closeout.schema.json").is_file()
    assert (schemas / "archive-manifest.schema.json").is_file()


def test_connected_system_examples_are_valid_yaml_with_required_fields(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "connected-systems"
    required_keys = {"id", "display_name", "system", "status", "provider_priority", "credential_refs"}
    for filename in CONNECTED_SYSTEM_EXAMPLES:
        path = examples_root / filename
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{filename}: not a YAML mapping"
        missing = required_keys - set(data.keys())
        assert not missing, f"{filename}: missing keys {missing}"
        # No real secrets — only env-var references
        raw = path.read_text(encoding="utf-8")
        assert "password" not in raw.lower() or "<" in raw, f"{filename}: appears to contain a hardcoded secret"


def test_watch_source_examples_are_valid_yaml_with_required_fields(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "watch-sources"
    required_keys = {"id", "display_name", "connected_system", "source_type", "watch_method", "enabled", "cursor", "dedupe"}
    for filename in WATCH_SOURCE_EXAMPLES:
        path = examples_root / filename
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{filename}: not a YAML mapping"
        missing = required_keys - set(data.keys())
        assert not missing, f"{filename}: missing keys {missing}"
        # All examples must be disabled by default
        assert data["enabled"] is False, f"{filename}: enabled should default to false"


def test_chain_rule_examples_are_valid_yaml_with_required_fields(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "chain-rules"
    required_keys = {"id", "display_name", "enabled", "when", "then", "approval", "limits", "idempotency", "outputs"}
    for filename in CHAIN_RULE_EXAMPLES:
        path = examples_root / filename
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{filename}: not a YAML mapping"
        missing = required_keys - set(data.keys())
        assert not missing, f"{filename}: missing keys {missing}"
        # All chain rules must be disabled by default
        assert data["enabled"] is False, f"{filename}: enabled should default to false"
        # Idempotency key must reference event_idempotency_key
        key = data["idempotency"]["key"]
        assert "{event_idempotency_key}" in key, f"{filename}: idempotency key must include {{event_idempotency_key}}"
        # Limits must declare max_chain_depth
        assert "max_chain_depth" in data["limits"], f"{filename}: limits must declare max_chain_depth"


def test_chain_rule_examples_cover_all_six_plan17_scenarios(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    examples_root = knowledge_templates(root) / "runtime" / "examples" / "chain-rules"

    # Collect all event_types from the installed examples
    event_types = set()
    for filename in CHAIN_RULE_EXAMPLES:
        path = examples_root / filename
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        event_types.add(data["when"]["event_type"])

    # Plan-17 names these six triggering event types
    required_events = {
        "github.pull_request.merged",
        "email.message.sent",
        "granola.note.created",
        "os.work_item.started",
        "os.approval.granted",
        "github.check_suite.failed",
    }
    assert required_events == event_types, f"Missing plan-17 event types: {required_events - event_types}"


def test_docs_update_preserves_local_edits_to_example_files(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    # Locally edit one connected-system example, one chain-rule example, and the capture-plan template
    cs_example = knowledge_templates(root) / "runtime" / "examples" / "connected-systems" / "notion.yml"
    cr_example = knowledge_templates(root) / "runtime" / "examples" / "chain-rules" / "feature-merge-to-docs.yml"
    capture_plan = knowledge_templates(root) / "planning" / "os-capture-plan.md"

    cs_example.write_text("# local notion example edit\n", encoding="utf-8")
    cr_example.write_text("# local chain rule edit\n", encoding="utf-8")
    capture_plan.write_text("# local capture plan edit\n", encoding="utf-8")

    # Re-run docs update — additive, must not overwrite local edits
    assert main(["docs", "update", "--root", str(root)]) == 0

    assert cs_example.read_text(encoding="utf-8") == "# local notion example edit\n"
    assert cr_example.read_text(encoding="utf-8") == "# local chain rule edit\n"
    assert capture_plan.read_text(encoding="utf-8") == "# local capture plan edit\n"


def test_init_twice_preserves_example_edits(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    ws_example = knowledge_templates(root) / "runtime" / "examples" / "watch-sources" / "slack-channel.yml"
    ws_example.write_text("# local slack watch edit\n", encoding="utf-8")

    # Running init again must not overwrite the locally edited file
    assert main(["init", "--target", str(root)]) == 0

    assert ws_example.read_text(encoding="utf-8") == "# local slack watch edit\n"
