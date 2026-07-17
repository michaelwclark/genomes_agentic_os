from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_notification_is_visible_in_agent_templates_and_registry() -> None:
    agents = (ROOT / "templates/agent-config/AGENTS.md").read_text(encoding="utf-8")
    rules = (ROOT / "templates/agent-config/RULES.md").read_text(encoding="utf-8")
    tools = (ROOT / "templates/agent-config/TOOLS.md").read_text(encoding="utf-8")
    command_index = (ROOT / "harness/commands/README.md").read_text(encoding="utf-8")
    command = (ROOT / "harness/commands/os-notify.md").read_text(encoding="utf-8")
    skill = (ROOT / "harness/skills/notification-operator/SKILL.md").read_text(encoding="utf-8")
    skill_metadata = (ROOT / "harness/skills/notification-operator/agents/openai.yaml").read_text(encoding="utf-8")
    registry = yaml.safe_load((ROOT / "harness/registries/skills.yml").read_text(encoding="utf-8"))
    shared_registry = yaml.safe_load((ROOT / "harness/skills/skill-registry.yml").read_text(encoding="utf-8"))

    assert "Notification Contract" in agents
    assert "Notification Rules" in rules
    assert "`/notify`" in tools
    assert "notification-operator" in tools
    assert "os-notify.md" in command_index
    assert "--dedupe-key" in command
    assert "sources:" in command
    assert "--dry-run" in skill
    assert "name: notification-operator" in skill_metadata
    assert any(item["id"] == "notification-operator" for item in registry["skills"])
    assert any(item["id"] == "notification-operator" for item in shared_registry["skills"])


def test_watcher_template_has_a_conservative_notification_recipe() -> None:
    watcher_docs = (ROOT / "templates/watcher/README-watchers.md").read_text(encoding="utf-8")

    assert "Notification integration" in watcher_docs
    assert "cooldown_seconds: 900" in watcher_docs
    assert "max_deliveries_per_hour: 3" in watcher_docs
