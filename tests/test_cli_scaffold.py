from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


def test_init_creates_domain_first_tree_and_shared_templates(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    projects_source = tmp_path / "projects"
    projects_source.mkdir()

    assert main(["init", "--target", str(root), "--projects-source", str(projects_source)]) == 0

    assert (root / ".agentic_root").is_file()
    assert (root / "projects").is_symlink()
    assert (root / "projects").resolve() == projects_source.resolve()

    for domain in ("personal", "clarks_consulting", "los", "shared_factory", "archive"):
        domain_root = root / domain
        assert domain_root.is_dir()
        assert (domain_root / "ROUTER.md").is_file()
        assert (domain_root / "AGENTS.md").is_file()
        assert (domain_root / "CLAUDE.md").is_file()
        assert (domain_root / "CONTEXT.md").is_file()
        assert (domain_root / "RULES.md").is_file()
        assert (domain_root / "TOOLS.md").is_file()
        assert (domain_root / "REFERENCES.md").is_file()
        assert not (domain_root / "AGENT.md").exists()
        assert (domain_root / "00-control-plane" / "routing-rules.md").is_file()
        assert (domain_root / "01-inbox" / "triage.md").is_file()
        assert (domain_root / "03-workflows" / "README.md").is_file()
        assert (domain_root / "03-workflows" / "engineering" / "README.md").is_file()
        assert (domain_root / "03-workflows" / "engineering").is_dir()
        assert (domain_root / "04-automations" / "README.md").is_file()
        assert (domain_root / "04-automations" / "operations" / "README.md").is_file()
        assert (domain_root / "04-automations" / "operations").is_dir()
        assert (domain_root / "05-knowledge" / "source-map.md").is_file()
        assert (domain_root / "06-runs-and-logs" / "runs").is_dir()
        assert (domain_root / "06-runs-and-logs" / "runs" / "README.md").is_file()
        assert (domain_root / "06-runs-and-logs" / "failures" / "README.md").is_file()
        assert (domain_root / "08-archive" / "README.md").is_file()

    assert (root / "ROUTER.md").is_file()
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()
    assert (root / "CONTEXT.md").is_file()
    assert (root / "RULES.md").is_file()
    assert (root / "TOOLS.md").is_file()
    assert (root / "agentic-os.lock.json").is_file()
    assert (root / "UPDATE_POLICY.md").is_file()
    assert (root / "registries" / "updates.yml").is_file()
    assert (root / "registries" / "customer-identity.json").is_file()
    assert (root / "registries" / "backup-policy.yml").is_file()
    assert not (root / "registries" / "update-grant.json").exists()
    assert (root / "security" / "ssh").is_dir()
    assert (root / "logs" / "updates").is_dir()
    assert (root / "logs" / "backups").is_dir()
    assert not (root / "AGENT.md").exists()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    root_agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "ROUTER.md" in root_agents
    assert "CONTEXT.md" in root_agents
    assert "RULES.md" in root_agents
    assert "TOOLS.md" in root_agents
    for directory in ("bin", "commands", "skills", "mcp", "plugins", "libraries", "hooks", "rules", "registries"):
        assert (root / directory).is_dir()
    for registry_name in (
        "capabilities.yml",
        "commands.yml",
        "skills.yml",
        "mcp-servers.yml",
        "libraries.yml",
        "hooks.yml",
        "plugins.yml",
        "rules.yml",
    ):
        assert (root / "registries" / registry_name).is_file()
    inventory = (root / "INVENTORY.md").read_text(encoding="utf-8")
    assert "## Commands" in inventory
    assert "`make-skill`" in inventory
    assert "`orchestrate`" in inventory
    commands = yaml.safe_load((root / "registries" / "commands.yml").read_text(encoding="utf-8"))
    assert {entry["command"] for entry in commands["commands"]} >= {
        "/make-skill",
        "/make-domain",
        "/make-automation",
        "/make-workflow",
        "/orchestrate",
    }
    mcp_servers = yaml.safe_load((root / "registries" / "mcp-servers.yml").read_text(encoding="utf-8"))
    assert {"context_mode", "genomes_brain"} <= {entry["id"] for entry in mcp_servers["mcp_servers"]}
    libraries = yaml.safe_load((root / "registries" / "libraries.yml").read_text(encoding="utf-8"))
    assert {"context_mode", "unified_memory"} <= {entry["id"] for entry in libraries["libraries"]}
    assert (root / "commands" / "os-route.md").is_file()
    assert (root / "skills" / "os-navigator" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "workflow.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "outcome-brief.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "workflow" / "prd.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "domain" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "feature-spec.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "future-idea.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "notion" / "agentic-os-control-plane.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "router.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "routing-table.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "tool-index.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "source-priority.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "style-and-output-rules.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "decision-log.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "naming-conventions.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "source-priority.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "style-and-output-rules.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "references" / "decision-log.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "customer-handoff-checklist.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "notion" / "control-plane-database-spec.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "heartbeat.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "schedule.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "execution-target.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "integration.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "run-queue-item.yml").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "notion" / "runtime-tracking-database-spec.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "connected-system.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "source-provider.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "watch-source.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "watch-cursor.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "source-event.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "trigger-rule.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "event-envelope.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "event-ledger-index.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "chain-rule.yml").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "event-processing-result.yml"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "dead-letter-event.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "update-grant.json").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "backup-policy.yml").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "README.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "index.html").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "operating-manual" / "07-diagrams" / "layer-map.svg").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-route.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-capture-plan.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-discover-rooms.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-doctor.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-client-automation-brief.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-control-plane-bootstrap.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-context-audit.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-runtime-init.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-heartbeat.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-integration-setup.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-watch-source.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-event.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-chain.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "README.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "00-current-state-and-gap-map.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "09-future-ideas-intake.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "plans" / "11-room-first-installer-and-routing.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "12-factory-template-import-backlog.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "13-reference-and-skill-index-layer.md"
    ).is_file()
    assert (
        root
        / "shared_factory"
        / "05-knowledge"
        / "plans"
        / "14-client-automation-and-control-plane-playbooks.md"
    ).is_file()
    assert (
        root
        / "shared_factory"
        / "05-knowledge"
        / "plans"
        / "15-always-on-runtime-heartbeats-schedules-and-integrations.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "16-connected-source-watch-registry.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "plans" / "17-event-graph-and-chained-automations.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "room-builder" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "os-navigator" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "workflow-builder" / "SKILL.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "skills" / "client-automation-brief" / "SKILL.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "skills" / "control-plane-bootstrap" / "SKILL.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "context-audit" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "runtime-operator" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "integration-setup" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "source-watcher" / "SKILL.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "event-graph-operator" / "SKILL.md").is_file()
    assert not (root / "domains").exists()
    assert not (root / "lenders").exists()
    assert not validate_root(root).errors


def test_validate_fails_when_declared_capability_is_missing_from_registry(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    capabilities_path = root / "registries" / "capabilities.yml"
    capabilities = yaml.safe_load(capabilities_path.read_text(encoding="utf-8"))
    capabilities["capabilities"].append(
        {
            "id": "command:missing-command",
            "type": "command",
            "ref": "missing-command",
            "name": "Missing Command",
            "description": "This command is intentionally absent from the command registry.",
        }
    )
    capabilities_path.write_text(yaml.safe_dump(capabilities, sort_keys=False), encoding="utf-8")

    result = validate_root(root)

    assert not result.ok
    assert any("missing command 'missing-command'" in error for error in result.errors)


def test_update_channel_check_plan_apply_and_phone_home_are_local_and_safe(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    manifest = tmp_path / "manifest.yml"

    assert main(["init", "--target", str(root)]) == 0
    local_command = root / "commands" / "os-route.md"
    local_command.write_text("# local command edit\n", encoding="utf-8")
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": "0.2.0",
                "channel": "stable",
                "policy": "operator_approved",
                "safe_additive_paths": ["templates", "registries", "commands"],
                "changes": [
                    {"type": "template", "path": "templates/runtime/example.yml", "summary": "safe addition"},
                    {"type": "rule", "path": "RULES.md", "summary": "risky rule change"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert main(["update", "check", "--root", str(root), "--manifest", str(manifest)]) == 0
    check = yaml.safe_load(capsys.readouterr().out)
    assert check["update_available"] is True
    assert check["mutated"] is False
    assert not (root / "registries" / "update-plan.yml").exists()

    assert main(["update", "plan", "--root", str(root), "--manifest", str(manifest)]) == 0
    planned = yaml.safe_load(capsys.readouterr().out)
    assert Path(planned["plan_path"]).is_file()
    assert planned["plan"]["approval_required"] is True

    assert main(["update", "apply", "--root", str(root)]) == 2
    blocked = yaml.safe_load(capsys.readouterr().out)
    assert blocked["blocked"] is True
    assert "risky changes require approval" == blocked["status"]["reason"]

    assert main(["update", "apply", "--root", str(root), "--approve-risky"]) == 0
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["applied"] is True
    assert local_command.read_text(encoding="utf-8") == "# local command edit\n"

    assert main(["update", "phone-home", "--root", str(root)]) == 0
    payload = yaml.safe_load(capsys.readouterr().out)
    assert payload["install"]["root_name"] == "agentic_os"
    assert payload["privacy"]["excludes"] == ["prompts", "customer files", "source code", "logs", "secrets"]
    assert "logs" not in payload["health"]["registry_counts"]


def test_license_register_update_pull_and_backup_use_local_grants(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    raw_key = "license-key-should-not-print"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["license", "activate", "--root", str(root), "--key", raw_key]) == 0
    activated_output = capsys.readouterr().out
    assert raw_key not in activated_output
    activated = yaml.safe_load(activated_output)
    assert activated["license"]["status"] == "active"
    assert len(activated["license"]["key_hash"]) == 64
    identity = (root / "registries" / "customer-identity.json").read_text(encoding="utf-8")
    assert raw_key not in identity

    assert main(["update", "register", "--root", str(root)]) == 0
    registered = yaml.safe_load(capsys.readouterr().out)
    assert Path(registered["grant_path"]).is_file()
    assert "public_keys" in registered
    assert "private_keys" in registered
    assert raw_key not in yaml.safe_dump(registered)
    assert (root / "security" / "ssh" / "update_ed25519").stat().st_mode & 0o777 == 0o600
    assert (root / "security" / "ssh" / "backup_ed25519").stat().st_mode & 0o777 == 0o600

    assert main(["update", "pull", "--root", str(root), "--dry-run"]) == 0
    planned_pull = yaml.safe_load(capsys.readouterr().out)
    assert planned_pull["status"] == "planned"
    assert Path(planned_pull["log_path"]).is_file()

    assert main(["update", "pull", "--root", str(root), "--apply"]) == 0
    pulled = yaml.safe_load(capsys.readouterr().out)
    assert pulled["status"] == "pulled"

    assert main(["backup", "run", "--root", str(root), "--dry-run"]) == 0
    backup_plan = yaml.safe_load(capsys.readouterr().out)
    assert backup_plan["status"] == "planned"
    assert backup_plan["include"]
    assert backup_plan["exclude"]

    assert main(["backup", "run", "--root", str(root), "--apply"]) == 0
    backup = yaml.safe_load(capsys.readouterr().out)
    assert backup["status"] == "completed"
    assert Path(backup["log_path"]).is_file()
    assert not validate_root(root).errors


def test_update_register_blocks_when_billing_is_inactive(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    # No license activated yet -> billing inactive -> registration must be blocked
    # without generating any keypair or grant.
    assert main(["update", "register", "--root", str(root)]) == 2
    assert not (root / "registries" / "update-grant.json").is_file()
    assert not (root / "security" / "ssh" / "update_ed25519").exists()

    # Activating the license flips billing active and unblocks registration.
    assert main(["license", "activate", "--root", str(root), "--key", "fake-key"]) == 0
    assert main(["update", "register", "--root", str(root)]) == 0
    assert (root / "registries" / "update-grant.json").is_file()


def test_backup_policy_excludes_projects_keys_and_secrets(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    policy = yaml.safe_load((root / "registries" / "backup-policy.yml").read_text(encoding="utf-8"))
    excludes = policy["backup_policy"]["exclude"]
    # AC: backup excludes private keys, env files, secrets, raw customer data, and projects/ by default.
    assert "projects/" in excludes
    assert "security/ssh/*" in excludes
    assert "**/.env" in excludes
    assert any("secret" in pattern for pattern in excludes)


def test_runtime_init_and_dry_run_paths_are_file_backed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    assert (root / "shared_factory" / "00-control-plane" / "runtime-registry.yml").is_file()
    assert (root / "shared_factory" / "00-control-plane" / "integration-registry.yml").is_file()
    assert (root / "shared_factory" / "00-control-plane" / "run-queue.yml").is_file()
    assert (root / "shared_factory" / "06-runs-and-logs" / "heartbeats").is_dir()

    assert main(["runtime", "doctor", "--root", str(root)]) == 0
    assert main(["heartbeat", "list", "--root", str(root)]) == 0

    assert main(["heartbeat", "run", "granola_recent_notes_sync", "--root", str(root), "--dry-run"]) == 0
    assert list((root / "shared_factory" / "06-runs-and-logs" / "heartbeats").glob("*granola_recent_notes_sync.yml"))
    assert main(["schedule", "create", "weekly_runtime_doctor", "--root", str(root), "--cadence", "weekly"]) == 0
    assert main(["schedule", "run-due", "--root", str(root), "--dry-run"]) == 0
    assert main(["integration", "list", "--root", str(root)]) == 0
    assert main(["integration", "setup", "granola", "--root", str(root), "--dry-run"]) == 0
    assert main(["integration", "doctor", "granola", "--root", str(root)]) == 0
    assert main(["notion", "track-runtime", "--root", str(root), "--dry-run"]) == 0
    assert main(["notion", "track-runtime", "--root", str(root), "--apply"]) == 2
    assert (
        main(
            [
                "notion",
                "track-runtime",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 0
    )
    assert (root / ".notion-runtime-tracking" / "manifest.yml").is_file()

    registry = yaml.safe_load((root / "shared_factory" / "00-control-plane" / "runtime-registry.yml").read_text())
    integration_registry = yaml.safe_load(
        (root / "shared_factory" / "00-control-plane" / "integration-registry.yml").read_text()
    )
    assert {"codex_harness", "claude_harness", "script", "orgo_desktop", "composio_cli", "agentmail_api", "granola_local", "notion_api"} <= {
        target["id"] for target in registry["execution_targets"]
    }
    assert {"orgo", "composio", "agentmail", "granola", "notion"} <= {
        integration["id"] for integration in integration_registry["integrations"]
    }
    assert validate_root(root).ok


def test_schedule_run_due_is_idempotent_and_run_next_dispatches_script_work(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    first = yaml.safe_load(capsys.readouterr().out)
    assert first["queued"][0]["status"] == "queued"
    assert first["queued"][0]["created"] is True

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    second = yaml.safe_load(capsys.readouterr().out)
    assert second["queued"] == []
    assert second["skipped"][0]["reason"] == "not due"

    queue_path = root / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert len(queue["items"]) == 1
    assert queue["run_queue"] == queue["items"]
    item_id = queue["items"][0]["id"]

    assert main(["runtime", "run-next", "--root", str(root), "--item-id", item_id, "--dry-run"]) == 0
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["status"] == "would-run"
    queue_after_dry_run = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert queue_after_dry_run["items"][0]["status"] == "queued"

    assert main(["runtime", "run-next", "--root", str(root), "--item-id", item_id, "--apply"]) == 0
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert Path(dispatched["log"]).is_file()
    queue_after_apply = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert queue_after_apply["items"][0]["status"] == "done"
    assert queue_after_apply["items"][0]["dispatch_log"]


def test_runtime_gates_approval_needed_and_provider_targets(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0

    registry_path = root / "shared_factory" / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["schedules"] = [
        {
            "id": "approval_required_review",
            "display_name": "Approval Required Review",
            "enabled": True,
            "cadence": "hourly",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
            "runtime_policy": {"approval_required": True},
        },
        {
            "id": "orgo_browser_check",
            "display_name": "Orgo Browser Check",
            "enabled": True,
            "cadence": "hourly",
            "timezone": "America/Chicago",
            "execution_target": "orgo_desktop",
            "command": "agentic-os validate --root <root>",
        },
    ]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    by_ref = {item["ref"]: item for item in result["queued"]}
    assert by_ref["approval_required_review"]["status"] == "approval-needed"
    assert by_ref["approval_required_review"]["approval_state"] == "required"
    assert by_ref["orgo_browser_check"]["status"] == "blocked"
    assert "execution target is not active" in by_ref["orgo_browser_check"]["blocked_reason"]

    assert main(["runtime", "run-next", "--root", str(root), "--item-id", by_ref["approval_required_review"]["id"], "--apply"]) == 0
    run_next = yaml.safe_load(capsys.readouterr().out)
    assert run_next["status"] == "approval-needed"
    assert run_next["external_effect"] == "none"


def test_runtime_doctor_reports_invalid_schedule_semantics(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0

    registry_path = root / "shared_factory" / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["schedules"][0]["cadence"] = "every_zero_hours"
    registry["schedules"][0]["timezone"] = "Missing/Timezone"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    assert main(["runtime", "doctor", "--root", str(root)]) == 1
    doctor = yaml.safe_load(capsys.readouterr().out)
    messages = "\n".join(finding["message"] for finding in doctor["findings"])
    assert "unsupported cadence" in messages


def test_config_install_dry_run_does_not_create_missing_directory(tmp_path: Path) -> None:
    root = tmp_path / "new_workflow"

    assert main(["config", "install", "--root", str(root), "--layer", "workflow_or_task", "--dry-run"]) == 0

    assert not root.exists()


def test_config_install_apply_creates_config_and_prompt_files(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["config", "install", "--root", str(root), "--layer", "agentic_os_root", "--apply"]) == 0

    config = root / "config.toml"
    assert config.is_file()
    content = config.read_text(encoding="utf-8")
    assert 'layer = "agentic_os_root"' in content
    assert (
        'prompt_files = ["AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"]'
        in content
    )
    for filename in ("AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
        assert (root / filename).is_file()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    tools = (root / "TOOLS.md").read_text(encoding="utf-8")
    assert "`/orchestrate`" in tools
    assert "`context_mode`" in tools
    assert "`unified_memory`" in tools
    assert "`route-read-cd-repeat`" in tools
    assert not (root / "BRAIN.md").exists()


def test_config_doctor_accepts_installed_otel_and_mcp_contract(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["config", "install", "--root", str(root), "--layer", "agentic_os_root", "--apply"]) == 0

    content = (root / "config.toml").read_text(encoding="utf-8")
    assert "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT" in content
    assert "AGENTIC_OS_OTEL_HEADERS" in content
    assert "GENOMES_NOTION_PAT=" not in content
    assert main(["config", "doctor", "--root", str(root), "--layer", "agentic_os_root"]) == 0


def test_config_install_places_mcp_servers_by_layer(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["config", "install", "--root", str(root), "--layer", "agentic_os_root", "--apply"]) == 0
    root_config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    root_servers = root_config["mcp_servers"]
    assert {"notion", "genomes_brain", "github", "context_mode", "filesystem_runtime"} <= set(root_servers)
    assert "sentry" not in root_servers
    assert "datadog" not in root_servers
    assert "supabase" not in root_servers
    assert "composio" not in root_servers
    assert "orgo" not in root_servers
    assert "playwright" not in root_servers
    assert root_servers["github"]["bearer_token_env_var"] == "GITHUB_PAT_TOKEN"
    assert "GITHUB_PAT_TOKEN=" not in (root / "config.toml").read_text(encoding="utf-8")
    tools = (root / "TOOLS.md").read_text(encoding="utf-8")
    for server_id in ("notion", "genomes_brain", "github", "context_mode", "sentry", "datadog", "supabase", "composio", "orgo", "playwright"):
        assert f"`{server_id}`" in tools

    los_root = root / "los"
    assert main(["config", "install", "--root", str(los_root), "--layer", "domain_or_lane", "--apply"]) == 0
    los_servers = tomllib.loads((los_root / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    assert {"notion", "genomes_brain", "github", "context_mode", "sentry", "datadog"} <= set(los_servers)
    assert "supabase" not in los_servers
    assert "composio" not in los_servers
    assert "orgo" not in los_servers
    assert main(["config", "doctor", "--root", str(los_root), "--layer", "domain_or_lane"]) == 0

    clarks_root = root / "clarks_consulting"
    assert main(["config", "install", "--root", str(clarks_root), "--layer", "domain_or_lane", "--apply"]) == 0
    clarks_servers = tomllib.loads((clarks_root / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    assert {"notion", "genomes_brain", "github", "context_mode", "supabase"} <= set(clarks_servers)
    assert "sentry" not in clarks_servers
    assert "datadog" not in clarks_servers
    assert main(["config", "doctor", "--root", str(clarks_root), "--layer", "domain_or_lane"]) == 0


def test_config_doctor_reports_missing_required_otel_and_mcp_keys(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    (root / "config.toml").write_text('model = "gpt-5.2"\n', encoding="utf-8")

    assert main(["config", "doctor", "--root", str(root), "--layer", "agentic_os_root"]) == 1


def test_validate_requires_root_rules_and_tools(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    (root / "RULES.md").unlink()
    (root / "TOOLS.md").unlink()

    result = validate_root(root)
    assert not result.ok
    assert any("RULES.md" in error for error in result.errors)
    assert any("TOOLS.md" in error for error in result.errors)


def test_config_install_is_idempotent_on_repeated_apply(tmp_path: Path) -> None:
    root = tmp_path / "customer_os"

    assert main(["config", "install", "--root", str(root), "--layer", "customer_os_root", "--apply"]) == 0
    first = (root / "config.toml").read_text(encoding="utf-8")
    assert main(["config", "install", "--root", str(root), "--layer", "customer_os_root", "--apply"]) == 0

    assert (root / "config.toml").read_text(encoding="utf-8") == first


def test_config_install_preserves_existing_conflicts_until_confirmed(tmp_path: Path) -> None:
    root = tmp_path / "domain"
    root.mkdir()
    config = root / "config.toml"
    config.write_text('model = "local-model"\n', encoding="utf-8")

    assert main(["config", "install", "--root", str(root), "--layer", "domain_or_lane", "--apply"]) == 2
    assert config.read_text(encoding="utf-8") == 'model = "local-model"\n'

    assert (
        main(
            [
                "config",
                "install",
                "--root",
                str(root),
                "--layer",
                "domain_or_lane",
                "--apply",
                "--confirm-conflicts",
                "--backup",
            ]
        )
        == 0
    )
    merged = config.read_text(encoding="utf-8")
    assert 'model = "local-model"' in merged
    assert 'approval_policy = "on-request"' in merged
    assert (root / "AGENTS.md").is_file()
    assert list(root.glob("config.toml.bak-*"))
    assert main(["config", "doctor", "--root", str(root), "--layer", "domain_or_lane"]) == 0


def test_config_install_layers_create_expected_prompt_sets(tmp_path: Path) -> None:
    cases = {
        "customer_os_root": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "domain_or_lane": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "workflow_or_task": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "automation": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
    }

    for layer, expected_files in cases.items():
        root = tmp_path / layer
        assert main(["config", "install", "--root", str(root), "--layer", layer, "--apply"]) == 0
        assert (root / "config.toml").is_file()
        for filename in ("AGENTS.md", "CLAUDE.md", *expected_files):
            assert (root / filename).is_file()


def test_domain_create_creates_expected_top_level_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["domain", "create", "client_delivery", "--root", str(root)]) == 0

    domain_root = root / "client_delivery"
    assert (domain_root / "README.md").is_file()
    assert (domain_root / "ROUTER.md").is_file()
    assert (domain_root / "AGENTS.md").is_file()
    assert (domain_root / "CLAUDE.md").is_file()
    assert (domain_root / "CONTEXT.md").is_file()
    assert (domain_root / "RULES.md").is_file()
    assert (domain_root / "TOOLS.md").is_file()
    assert not (domain_root / "AGENT.md").exists()
    assert (domain_root / "REFERENCES.md").is_file()
    domain_config = (domain_root / "domain.yml").read_text(encoding="utf-8")
    assert domain_config.startswith("id: client_delivery")
    assert "context_loading:" in domain_config
    assert (domain_root / "00-control-plane" / "active-work.md").is_file()
    assert (domain_root / "00-control-plane" / "approval-rules.md").is_file()
    assert (domain_root / "01-inbox" / "raw-ideas.md").is_file()
    assert (domain_root / "02-projects" / "README.md").is_file()
    assert (domain_root / "03-workflows" / "engineering").is_dir()
    assert (domain_root / "04-automations" / "support").is_dir()
    assert (domain_root / "05-knowledge" / "memory-policy.md").is_file()
    assert (domain_root / "06-runs-and-logs" / "activity-log.md").is_file()
    assert (domain_root / "07-metrics" / "scorecards.md").is_file()


def test_workflow_automation_run_log_and_validate(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    workflow_root = root / "los" / "03-workflows" / "engineering" / "feature_dev"
    assert (workflow_root / "workflow.md").is_file()
    assert (workflow_root / "outcome-brief.md").is_file()
    assert (workflow_root / "alignment-questions.md").is_file()
    assert (workflow_root / "prd.md").is_file()
    assert (workflow_root / "implementation-plan.md").is_file()
    assert (workflow_root / "dispatch-handoff.md").is_file()
    assert (workflow_root / "progress.md").is_file()
    assert (workflow_root / "quick-reference.md").is_file()
    assert (workflow_root / "state-machine.md").is_file()
    assert (workflow_root / "context-pack.md").is_file()
    assert (workflow_root / "approval-rules.md").is_file()
    assert (workflow_root / "output-contract.md").is_file()
    assert (workflow_root / "runbook.md").is_file()
    assert (workflow_root / "examples").is_dir()
    assert (workflow_root / "examples" / "README.md").is_file()
    assert (workflow_root / "runs").is_dir()
    assert (workflow_root / "runs" / "README.md").is_file()

    assert (
        main(
            [
                "automation",
                "create",
                "los",
                "support",
                "production_thread_intake",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    automation_root = root / "los" / "04-automations" / "support" / "production_thread_intake"
    assert (automation_root / "automation.md").is_file()
    assert (automation_root / "inputs.md").is_file()
    assert (automation_root / "outputs.md").is_file()
    assert (automation_root / "permissions.md").is_file()
    assert (automation_root / "failure-modes.md").is_file()
    assert (automation_root / "runbook.md").is_file()
    assert (automation_root / "tests.md").is_file()
    assert (automation_root / "logs").is_dir()
    assert (automation_root / "logs" / "README.md").is_file()

    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_logs = list((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev/run-log.md"))
    assert len(run_logs) == 1
    assert validate_root(root).ok
    assert main(["validate", "--root", str(root)]) == 0


def test_commands_are_safe_to_rerun(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    command = ["domain", "create", "client_delivery", "--root", str(root)]
    assert main(command) == 0
    before = (root / "client_delivery" / "domain.yml").read_text(encoding="utf-8")
    assert main(command) == 0
    after = (root / "client_delivery" / "domain.yml").read_text(encoding="utf-8")

    assert before == after


def test_docs_update_is_additive_and_preserves_local_edits(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    manual_readme = root / "shared_factory" / "05-knowledge" / "operating-manual" / "README.md"
    command_file = root / "shared_factory" / "05-knowledge" / "commands" / "os-sync-notion.md"
    playbook_command = root / "shared_factory" / "05-knowledge" / "commands" / "os-client-automation-brief.md"
    playbook_skill = root / "shared_factory" / "05-knowledge" / "skills" / "client-automation-brief" / "SKILL.md"
    watch_command = root / "shared_factory" / "05-knowledge" / "commands" / "os-watch-source.md"
    watch_template = root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "watch-source.yml"
    event_command = root / "shared_factory" / "05-knowledge" / "commands" / "os-event.md"
    event_template = root / "shared_factory" / "05-knowledge" / "templates" / "runtime" / "event-envelope.yml"
    plan_readme = root / "shared_factory" / "05-knowledge" / "plans" / "README.md"
    plan_file = root / "shared_factory" / "05-knowledge" / "plans" / "09-future-ideas-intake.md"
    planning_template = root / "shared_factory" / "05-knowledge" / "templates" / "planning" / "feature-spec.md"
    domain_context_template = root / "shared_factory" / "05-knowledge" / "templates" / "domain" / "context.md"
    manual_readme.write_text("# local edit\n", encoding="utf-8")
    plan_readme.write_text("# local plan edit\n", encoding="utf-8")
    command_file.unlink()
    playbook_command.unlink()
    playbook_skill.unlink()
    watch_command.unlink()
    watch_template.unlink()
    event_command.unlink()
    event_template.unlink()
    plan_file.unlink()
    planning_template.unlink()
    domain_context_template.unlink()

    assert main(["docs", "update", "--root", str(root)]) == 0

    content = manual_readme.read_text(encoding="utf-8")
    assert content == "# local edit\n"
    assert plan_readme.read_text(encoding="utf-8") == "# local plan edit\n"
    assert command_file.is_file()
    assert playbook_command.is_file()
    assert playbook_skill.is_file()
    assert watch_command.is_file()
    assert watch_template.is_file()
    assert event_command.is_file()
    assert event_template.is_file()
    assert plan_file.is_file()
    assert planning_template.is_file()
    assert domain_context_template.is_file()
    assert (root / "shared_factory" / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md"
    ).is_file()
    assert (root / "shared_factory" / "05-knowledge" / "skills" / "os-doctor" / "SKILL.md").is_file()
    assert main(["validate", "--root", str(root)]) == 0
    assert main(["docs", "update", "--root", str(root)]) == 0
    assert manual_readme.read_text(encoding="utf-8") == "# local edit\n"
    assert plan_readme.read_text(encoding="utf-8") == "# local plan edit\n"


def test_lenders_alias_routes_to_los_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "lenders", "support", "lender_intake", "--root", str(root)]) == 0

    assert (root / "los" / "03-workflows" / "support" / "lender_intake" / "workflow.md").is_file()
    assert not (root / "lenders").exists()
    assert validate_root(root).ok


def test_project_create_creates_project_state_and_indexes(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert (
        main(
            [
                "project",
                "create",
                "los",
                "losmon_replacement",
                "--root",
                str(root),
                "--repo",
                "/Users/genome/projects/losmon",
                "--notion",
                "https://notion.so/example",
                "--jira",
                "LOS",
                "--lane",
                "engineering",
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "losmon_replacement"
    assert (project_root / "README.md").is_file()
    assert (project_root / "project.yml").is_file()
    assert (project_root / "status.md").is_file()
    assert (project_root / "decisions.md").is_file()
    assert (project_root / "source-map.md").is_file()
    assert (project_root / "artifacts").is_dir()
    assert "repo: /Users/genome/projects/losmon" in (project_root / "project.yml").read_text(encoding="utf-8")
    assert "| Repo | /Users/genome/projects/losmon |" in (project_root / "source-map.md").read_text(
        encoding="utf-8"
    )
    assert "`losmon_replacement`" in (root / "los" / "02-projects" / "README.md").read_text(encoding="utf-8")
    assert "`losmon_replacement`" in (root / "los" / "00-control-plane" / "active-work.md").read_text(
        encoding="utf-8"
    )
    assert validate_root(root).ok


def test_project_create_is_idempotent_and_preserves_local_edits(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    command = ["project", "create", "los", "losmon_replacement", "--root", str(root)]

    assert main(command) == 0
    status_file = root / "los" / "02-projects" / "losmon_replacement" / "status.md"
    status_file.write_text("# local status edit\n", encoding="utf-8")
    assert main(command) == 0

    assert status_file.read_text(encoding="utf-8") == "# local status edit\n"
    active_work = (root / "los" / "00-control-plane" / "active-work.md").read_text(encoding="utf-8")
    assert active_work.count("| `losmon_replacement` |") == 1
    assert validate_root(root).ok


def test_project_create_rejects_invalid_names_and_normalizes_domain_alias(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "bad-name", "--root", str(root)]) == 2
    assert main(["project", "create", "lenders", "lender_portal", "--root", str(root)]) == 0
    assert (root / "los" / "02-projects" / "lender_portal" / "project.yml").is_file()
    assert not (root / "lenders").exists()


def test_route_classifies_project_request_and_approval_risk(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "losmon_repo"
    repo.mkdir()

    assert main(["project", "create", "los", "losmon_replacement", "--repo", str(repo), "--root", str(root)]) == 0
    assert main(["route", "Deploy losmon_replacement to production", "--root", str(root)]) == 0

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"].endswith("los/02-projects/losmon_replacement")
    assert "production change" in packet["approval_risks"]
    assert any(path.endswith("source-map.md") for path in packet["sources_to_load"])


def test_context_build_returns_exact_project_sources(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert (
        main(
            [
                "context",
                "build",
                "--domain",
                "los",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert str(root / "ROUTER.md") in packet["sources_to_load"]
    assert str(root / "shared_factory" / "05-knowledge" / "references" / "tool-index.md") in packet[
        "sources_to_load"
    ]
    assert str(root / "shared_factory" / "05-knowledge" / "references" / "source-priority.md") in packet[
        "sources_to_load"
    ]
    assert str(root / "los" / "ROUTER.md") in packet["sources_to_load"]
    assert str(root / "los" / "02-projects" / "losmon_replacement" / "project.yml") in packet["sources_to_load"]


def test_here_detects_os_path_and_linked_project_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "losmon_repo"
    repo.mkdir()

    assert main(["project", "create", "los", "losmon_replacement", "--repo", str(repo), "--root", str(root)]) == 0
    monkeypatch.chdir(root / "los")
    assert main(["here", "route", "Summarize active work", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "domain"

    monkeypatch.chdir(repo)
    assert main(["here", "context", "build", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"].endswith("los/02-projects/losmon_replacement")


def test_route_fails_safely_when_ambiguous(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["route", "Do the thing", "--root", str(root)]) == 2
    assert main(["route", "Compare los and personal work", "--root", str(root)]) == 2


def write_ready_automation_contract(path: Path) -> None:
    path.write_text(
        """# Automation: production_thread_intake

## Metadata

| Field | Value |
| --- | --- |
| Domain | `los` |
| Lane | `support` |
| Status | `draft` |
| Level | `observe` |
| Owner | `OS Owner` |
| Last Reviewed | `2026-05-21` |

## Trigger

- Type: `manual`
- Source: `support queue`
- Frequency: `on demand`

## Idempotency

- Key: `support_thread_id`
- Duplicate handling: `link existing run log`

## Permissions

- Read: `support queue`
- Write: `filesystem only`
- Requires approval: `external messages`
- Default action before approval: `propose`

## Outputs

- Run log with evidence.
- Draft response for approval.

## Audit Requirements

- Input reference.
- Action taken.
- Result.
- Evidence.
""",
        encoding="utf-8",
    )


def test_automation_check_and_safe_maturity_levels(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    automation_md = root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    assert "| Level | `observe` |" in automation_md.read_text(encoding="utf-8")

    capsys.readouterr()
    assert main(["automation", "check", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["level"] == "observe"
    assert any(finding["severity"] == "blocker" for finding in packet["findings"])

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "prepare",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert "| Level | `prepare` |" in automation_md.read_text(encoding="utf-8")
    decisions = (root / "los" / "00-control-plane" / "decisions.md").read_text(encoding="utf-8")
    assert "maturity changed from `observe` to `prepare`" in decisions

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "propose",
                "--root",
                str(root),
            ]
        )
        == 2
    )


def test_automation_maturity_advances_after_file_first_evidence(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    automation_md = root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    write_ready_automation_contract(automation_md)

    capsys.readouterr()
    assert main(["automation", "check", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert not [finding for finding in packet["findings"] if finding["severity"] == "blocker"]

    assert (
        main(
            [
                "automation",
                "set-maturity",
                "los",
                "support",
                "production_thread_intake",
                "propose",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["old_level"] == "observe"
    assert result["new_level"] == "propose"
    assert "| Level | `propose` |" in automation_md.read_text(encoding="utf-8")


def test_automation_attach_updates_project_status_and_source_map(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0

    capsys.readouterr()
    assert (
        main(
            [
                "automation",
                "attach",
                "los",
                "support",
                "production_thread_intake",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["project"].endswith("los/02-projects/losmon_replacement")

    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "## Automation Attachments" in project_status
    assert "`production_thread_intake`" in project_status
    source_map = (root / "los" / "02-projects" / "losmon_replacement" / "source-map.md").read_text(
        encoding="utf-8"
    )
    assert "| Automation | 04-automations/support/production_thread_intake/ |" in source_map
    automation_md = (
        root / "los" / "04-automations" / "support" / "production_thread_intake" / "automation.md"
    ).read_text(encoding="utf-8")
    assert "## Project Attachments" in automation_md
    assert "`losmon_replacement`" in automation_md


def write_customer_profile(path: Path) -> None:
    path.write_text(
        """customer:
  slug: acme_ops
  display_name: Acme Operations
  owner: Operations Lead
  notion_workspace: Acme Notion
  approved_domains:
    - support
  source_systems:
    - name: helpdesk
      role: customer support inbox
  default_workflows:
    - domain: support
      lane: support
      name: intake_triage
  default_automations:
    - domain: support
      lane: support
      name: thread_intake
  approval_policy:
    external_writes_require_approval: true
    customer_visible_output_requires_approval: true
    production_changes_require_approval: true
    destructive_actions_require_approval: true
""",
        encoding="utf-8",
    )


def write_room_profile(path: Path) -> None:
    path.write_text(
        """os:
  display_name: Studio OS
  owner: Operator
approval_policy:
  external_writes_require_approval: true
rooms:
  - slug: writing_room
    display_name: Writing Room
    purpose: Ideas become polished drafts.
    inputs:
      - rough ideas
      - research notes
    output_folders:
      drafts: drafts
      finals: final
    routing:
      - task: write blog post
        read_first:
          - docs/voice.md
        read_when_needed:
          - docs/audience.md
        skip_by_default:
          - production docs
        output_path: drafts/
    tools:
      - name: humanizer
        trigger: before final
        notes: remove generic wording
    done_means:
      - output exists in the expected folder
      - source files are preserved
""",
        encoding="utf-8",
    )


def customer_text_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".yml", ".yaml"}
    ]


def test_customer_init_generates_public_customer_os_from_profile(tmp_path: Path, capsys) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["customer"] == "acme_ops"
    assert (root / "README.md").is_file()
    assert (root / "ROUTER.md").is_file()
    assert (root / "customer.yml").is_file()
    assert (root / "support" / "domain.yml").is_file()
    assert (root / "support" / "03-workflows" / "support" / "intake_triage" / "workflow.md").is_file()
    assert (root / "support" / "04-automations" / "support" / "thread_intake" / "automation.md").is_file()
    assert not (root / "clarks_consulting").exists()
    assert not (root / "los").exists()

    disallowed = ("genome", "clark", "clarks_consulting", "los", "lenders")
    generated_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in customer_text_files(root))
    assert not any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", generated_text) for term in disallowed)

    assert main(["customer", "validate", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["ok"] is True
    assert packet["core_errors"] == []
    assert packet["profile_warnings"] == []


def test_customer_update_is_additive_and_preserves_local_edits(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    handoff = root / "customer" / "handoff-checklist.md"
    brief = root / "customer" / "client-automation-brief.md"
    handoff.write_text("# local customer handoff edit\n", encoding="utf-8")
    brief.unlink()

    assert main(["customer", "update", "acme_ops", "--root", str(root)]) == 0

    assert handoff.read_text(encoding="utf-8") == "# local customer handoff edit\n"
    assert brief.is_file()
    assert main(["customer", "validate", "--root", str(root)]) == 0


def test_customer_init_rejects_private_source_domains(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    profile.write_text(
        """customer:
  slug: acme_ops
  display_name: Acme Operations
  owner: Operations Lead
  approved_domains:
    - los
""",
        encoding="utf-8",
    )

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(tmp_path / "out")]) == 2


def test_room_profile_init_creates_custom_room_without_default_domains(tmp_path: Path, capsys) -> None:
    profile = tmp_path / "room-profile.yml"
    root = tmp_path / "studio_os"
    write_room_profile(profile)

    assert main(["profile", "validate", str(profile)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["rooms"] == ["writing_room"]

    assert main(["init", "--target", str(root), "--profile", str(profile)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["rooms"] == ["writing_room"]
    assert (root / "writing_room" / "CONTEXT.md").is_file()
    assert not (root / "los").exists()
    assert not (root / "clarks_consulting").exists()

    context = (root / "writing_room" / "CONTEXT.md").read_text(encoding="utf-8")
    assert "rough ideas" in context
    assert "docs/voice.md" in context
    assert "humanizer" in context
    assert "output exists in the expected folder" in context
    router = (root / "ROUTER.md").read_text(encoding="utf-8")
    assert "`writing_room`" in router
    assert main(["validate", "--root", str(root)]) == 0

    (root / "writing_room" / "CONTEXT.md").write_text("# local room context edit\n<!-- room-profile-managed -->\n", encoding="utf-8")
    assert main(["room", "update", "writing_room", "--root", str(root), "--from-profile", str(profile)]) == 0
    assert (root / "writing_room" / "CONTEXT.md").read_text(encoding="utf-8").startswith("# local room context edit")


def test_profile_validate_rejects_duplicate_rooms_and_missing_approvals(tmp_path: Path) -> None:
    profile = tmp_path / "bad-profile.yml"
    profile.write_text(
        """rooms:
  - slug: writing_room
    purpose: Drafts.
    done_means:
      - done
  - slug: writing_room
    purpose: Duplicate.
    done_means:
      - done
""",
        encoding="utf-8",
    )
    assert main(["profile", "validate", str(profile)]) == 2


def test_factory_templates_install_and_customer_facing_templates_are_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (root / "shared_factory" / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
    ).is_file()

    sanitized_roots = [
        Path("templates/room"),
        Path("templates/stage"),
        Path("templates/reference"),
        Path("templates/profile"),
        Path("templates/customer"),
    ]
    disallowed = ("eduba", "school", "acme", "clarks_consulting")
    for relative_root in sanitized_roots:
        for path in relative_root.rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8").lower()
                assert not any(term in content for term in disallowed), path


def test_client_playbook_commands_and_skills_are_installed_and_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    knowledge_root = root / "shared_factory" / "05-knowledge"
    command_paths = [
        knowledge_root / "commands" / "os-client-automation-brief.md",
        knowledge_root / "commands" / "os-control-plane-bootstrap.md",
        knowledge_root / "commands" / "os-context-audit.md",
    ]
    skill_paths = [
        knowledge_root / "skills" / "client-automation-brief" / "SKILL.md",
        knowledge_root / "skills" / "control-plane-bootstrap" / "SKILL.md",
        knowledge_root / "skills" / "context-audit" / "SKILL.md",
    ]
    for path in [*command_paths, *skill_paths]:
        assert path.is_file(), path

    brief_command = command_paths[0].read_text(encoding="utf-8").lower()
    brief_skill = skill_paths[0].read_text(encoding="utf-8").lower()
    brief_template = (
        knowledge_root / "templates" / "customer" / "client-automation-brief.md"
    ).read_text(encoding="utf-8").lower()
    control_plane_skill = skill_paths[1].read_text(encoding="utf-8").lower()

    assert "deterministic" in brief_command
    assert "rule-based" in brief_command
    assert "llm-needed" in brief_command
    assert "human judgment" in brief_command
    assert "automation-fit-matrix.md" in brief_skill
    assert "approval gate" in brief_skill
    assert "filesystem remains the source of truth" in control_plane_skill
    for required_heading in (
        "## outcome",
        "## current manual workflow",
        "## automation candidate steps",
        "## approval gate",
        "## metrics baseline",
    ):
        assert required_heading in brief_template

    disallowed = ("eduba", "school", "clarks_consulting", "michael clark", "flywheel")
    installed_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in command_paths + skill_paths)
    assert not any(term in installed_text for term in disallowed)


def test_watch_source_registry_create_doctor_poll_and_run_due(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["connected-system", "list", "--root", str(root)]) == 0
    systems = yaml.safe_load(capsys.readouterr().out)
    notion = next(system for system in systems["connected_systems"] if system["id"] == "notion_genome")
    assert notion["selected_provider"] == "notion_mcp"

    assert (
        main(
            [
                "watch-source",
                "create",
                "agentic_os_kanban",
                "--root",
                str(root),
                "--external-ref",
                "database_id=366683b48dab81a1ab5fc73e7e1f5c60",
                "--enabled",
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["action"] == "created"
    assert (root / "shared_factory" / "00-control-plane" / "watch-sources.yml").is_file()
    assert (root / "shared_factory" / "00-control-plane" / "watch-cursors.yml").is_file()

    assert main(["watch-source", "doctor", "agentic_os_kanban", "--root", str(root)]) == 0
    doctor = yaml.safe_load(capsys.readouterr().out)
    assert doctor["ok"] is True
    assert doctor["findings"] == []

    assert main(["watch-source", "poll", "agentic_os_kanban", "--root", str(root), "--dry-run"]) == 0
    poll = yaml.safe_load(capsys.readouterr().out)
    assert poll["dry_run"] is True
    assert poll["events"][0]["source"]["watch_source_id"] == "agentic_os_kanban"
    assert poll["events"][0]["source"]["provider"] == "notion_mcp"
    assert poll["events"][0]["route"]["fallback_domain"] == "shared_factory"

    assert main(["watch-source", "run-due", "--root", str(root), "--apply"]) == 0
    run_due = yaml.safe_load(capsys.readouterr().out)
    assert run_due["dry_run"] is False
    assert run_due["actions"][0]["written"]
    assert Path(run_due["actions"][0]["written"][0]).is_file()
    assert main(["validate", "--root", str(root)]) == 0


def test_connected_system_defaults_cover_plan_16_source_examples(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["connected-system", "list", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    systems = {system["system"]: system for system in result["connected_systems"]}

    assert {
        "notion",
        "slack",
        "jira",
        "linear",
        "email",
        "github",
        "granola",
        "agentmail",
        "filesystem",
    }.issubset(systems)
    assert systems["slack"]["selected_provider"] == "composio"
    assert systems["filesystem"]["selected_provider"] == "filesystem"


def test_watch_source_doctor_catches_missing_cursor_and_provider(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["watch-source", "create", "agentic_os_kanban", "--root", str(root), "--enabled"]) == 0
    capsys.readouterr()
    watch_file = root / "shared_factory" / "00-control-plane" / "watch-sources.yml"
    data = yaml.safe_load(watch_file.read_text(encoding="utf-8"))
    source = data["watch_sources"][0]
    source.pop("cursor")
    source["dedupe"] = {}
    watch_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["watch-source", "doctor", "agentic_os_kanban", "--root", str(root)]) == 1
    doctor = yaml.safe_load(capsys.readouterr().out)
    messages = {finding["message"] for finding in doctor["findings"]}
    assert "missing cursor type or state_ref" in messages
    assert "missing dedupe idempotency_key" in messages

    systems_file = root / "shared_factory" / "00-control-plane" / "connected-systems.yml"
    systems = yaml.safe_load(systems_file.read_text(encoding="utf-8"))
    systems["connected_systems"][0]["provider_priority"] = ["missing_provider"]
    systems_file.write_text(yaml.safe_dump(systems, sort_keys=False), encoding="utf-8")

    assert main(["connected-system", "doctor", "notion_genome", "--root", str(root)]) == 1
    system_doctor = yaml.safe_load(capsys.readouterr().out)
    assert any("missing providers" in finding["message"] for finding in system_doctor["findings"])


def test_watch_source_doctor_catches_enabled_source_without_trigger_rules(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["watch-source", "create", "agentic_os_kanban", "--root", str(root), "--enabled"]) == 0
    capsys.readouterr()
    watch_file = root / "shared_factory" / "00-control-plane" / "watch-sources.yml"
    data = yaml.safe_load(watch_file.read_text(encoding="utf-8"))
    data["watch_sources"][0]["trigger_rules"] = []
    watch_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["watch-source", "doctor", "agentic_os_kanban", "--root", str(root)]) == 1
    doctor = yaml.safe_load(capsys.readouterr().out)
    assert any(finding["message"] == "enabled source missing trigger_rules" for finding in doctor["findings"])
    assert main(["validate", "--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert "enabled without trigger_rules" in captured.err


def test_watch_source_dedupe_templates_use_external_refs_safely(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert (
        main(
            [
                "watch-source",
                "create",
                "agentic_os_kanban",
                "--root",
                str(root),
                "--external-ref",
                "database_id=db1",
                "--external-ref",
                "page_id=page1",
                "--external-ref",
                "last_edited_time=2026-05-28T00:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()
    watch_file = root / "shared_factory" / "00-control-plane" / "watch-sources.yml"
    data = yaml.safe_load(watch_file.read_text(encoding="utf-8"))
    data["watch_sources"][0]["dedupe"] = {
        "idempotency_key": "{source_type}:{database_id}:{page_id}:{last_edited_time}:{unknown_field}"
    }
    watch_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["watch-source", "poll", "agentic_os_kanban", "--root", str(root), "--dry-run"]) == 0
    poll = yaml.safe_load(capsys.readouterr().out)
    key = poll["events"][0]["dedupe"]["idempotency_key"]
    assert key == "notion_database:db1:page1:2026-05-28T00:00:00Z:{unknown_field}"


def test_watch_source_trigger_rules_emit_event_and_enqueue_work(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert (
        main(
            [
                "watch-source",
                "create",
                "local_dropbox",
                "--root",
                str(root),
                "--connected-system",
                "filesystem_local",
                "--source-type",
                "filesystem_glob",
                "--external-ref",
                "glob=*.md",
                "--enabled",
            ]
        )
        == 0
    )
    capsys.readouterr()
    watch_file = root / "shared_factory" / "00-control-plane" / "watch-sources.yml"
    data = yaml.safe_load(watch_file.read_text(encoding="utf-8"))
    data["watch_sources"][0]["trigger_rules"] = [
        {
            "id": "local_dropbox_to_review",
            "display_name": "Local dropbox to review",
            "enabled": True,
            "when": {"event_type": "filesystem_glob.polled", "fields": {"source_type": "filesystem_glob"}},
            "then": {
                "emit_event": {"type": "os.source.observed"},
                "enqueue": {
                    "work_type": "source_review",
                    "route_to": "shared_factory",
                    "workflow": "review_source_event",
                    "context_profile": "source_event",
                    "maturity": "prepare",
                },
            },
            "approval": {"required": False},
            "idempotency": {"key": "{source_id}:local_dropbox_to_review"},
        }
    ]
    watch_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["watch-source", "poll", "local_dropbox", "--root", str(root), "--apply"]) == 0
    poll = yaml.safe_load(capsys.readouterr().out)
    assert {action["action"] for action in poll["trigger_actions"]} == {"emit_event", "enqueue"}
    assert next(action for action in poll["trigger_actions"] if action["action"] == "emit_event")["path"]

    queue = yaml.safe_load((root / "shared_factory" / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    assert queue["run_queue"][0]["kind"] == "source_trigger"
    assert queue["run_queue"][0]["work_type"] == "source_review"

    assert main(["watch-source", "poll", "local_dropbox", "--root", str(root), "--apply"]) == 0
    repeated = yaml.safe_load(capsys.readouterr().out)
    enqueue = next(action for action in repeated["trigger_actions"] if action["action"] == "enqueue")
    assert enqueue["status"] == "skipped"
    assert len(list((root / "shared_factory" / "06-runs-and-logs" / "source-events").glob("*.yml"))) == 1


def test_event_graph_append_chain_process_and_idempotency(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert (
        main(
            [
                "event",
                "append",
                "--root",
                str(root),
                "--type",
                "github.pull_request.merged",
                "--source",
                "github:genomes_agentic_os:pull/123",
                "--summary",
                "PR 123 merged into main.",
            ]
        )
        == 0
    )
    event = yaml.safe_load(capsys.readouterr().out)
    event_path = Path(event["path"])
    assert event_path.is_file()
    assert (root / "shared_factory" / "06-runs-and-logs" / "events" / "event-ledger-index.md").is_file()

    chain_rules = root / "shared_factory" / "00-control-plane" / "chain-rules.yml"
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    data["chain_rules"][0]["enabled"] = True
    data["chain_rules"][0]["when"]["filters"] = {}
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["chain", "test", "feature_merged_to_docs_update", "--event", str(event_path), "--root", str(root)]) == 0
    test_result = yaml.safe_load(capsys.readouterr().out)
    assert test_result["matched"] is True
    assert test_result["queue_item"]["work_type"] == "documentation_update"

    assert main(["event", "process-due", "--root", str(root), "--dry-run"]) == 0
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["dry_run"] is True
    assert dry_run["actions"][0]["results"][0]["status"] == "dry-run"
    assert not (root / "shared_factory" / "00-control-plane" / "run-queue.yml").read_text(
        encoding="utf-8"
    ).count("documentation_update")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["actions"][0]["results"][0]["status"] == "queued"
    run_queue = yaml.safe_load((root / "shared_factory" / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    assert run_queue["run_queue"][0]["work_type"] == "documentation_update"

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    repeated = yaml.safe_load(capsys.readouterr().out)
    assert repeated["actions"][0]["results"][0]["status"] == "skipped"
    assert main(["event", "summary", "--root", str(root), "--limit", "5"]) == 0
    summary = yaml.safe_load(capsys.readouterr().out)
    assert summary["last_events"][0]["id"] == event["id"]
    assert summary["pending_follow_up"][0]["work_type"] == "documentation_update"
    assert summary["processing_results"]
    assert main(["validate", "--root", str(root)]) == 0


def test_event_graph_duplicate_event_envelopes_do_not_duplicate_queue_work(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert (
        main(
            [
                "event",
                "append",
                "--root",
                str(root),
                "--type",
                "github.pull_request.merged",
                "--source",
                "github:genomes_agentic_os:pull/123",
            ]
        )
        == 0
    )
    event = yaml.safe_load(capsys.readouterr().out)
    event_path = Path(event["path"])
    duplicate = yaml.safe_load(event_path.read_text(encoding="utf-8"))
    duplicate["id"] = "evt_duplicate_pr_123"
    duplicate["observed_at"] = "2026-05-28T00:00:01Z"
    duplicate_path = event_path.parent / "evt_duplicate_pr_123.yml"
    duplicate_path.write_text(yaml.safe_dump(duplicate, sort_keys=False), encoding="utf-8")

    chain_rules = root / "shared_factory" / "00-control-plane" / "chain-rules.yml"
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    data["chain_rules"][0]["enabled"] = True
    data["chain_rules"][0]["when"]["filters"] = {}
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    processed = yaml.safe_load(capsys.readouterr().out)
    statuses = [action["results"][0]["status"] for action in processed["actions"]]
    assert statuses == ["queued", "skipped"]
    assert processed["actions"][1]["results"][0]["reason"] == "idempotency key already processed"

    run_queue = yaml.safe_load((root / "shared_factory" / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    assert len(run_queue["run_queue"]) == 1


def test_event_graph_max_depth_and_approval_needed_outputs(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["event", "append", "--root", str(root), "--type", "github.check_suite.failed", "--source", "github:check:1"]) == 0
    event = yaml.safe_load(capsys.readouterr().out)
    event_path = Path(event["path"])
    envelope = yaml.safe_load(event_path.read_text(encoding="utf-8"))
    envelope["correlation"]["chain_depth"] = 2
    event_path.write_text(yaml.safe_dump(envelope, sort_keys=False), encoding="utf-8")

    chain_rules = root / "shared_factory" / "00-control-plane" / "chain-rules.yml"
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    ci_rule = next(rule for rule in data["chain_rules"] if rule["id"] == "ci_failure_investigation")
    ci_rule["enabled"] = True
    ci_rule["limits"]["max_chain_depth"] = 2
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    max_depth = yaml.safe_load(capsys.readouterr().out)
    assert max_depth["actions"][0]["results"][0]["status"] == "skipped"
    assert "max chain depth reached" in max_depth["actions"][0]["results"][0]["reason"]

    assert main(["event", "append", "--root", str(root), "--type", "os.run.closed.needs_approval", "--source", "run:needs-approval"]) == 0
    capsys.readouterr()
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    approval_rule = next(rule for rule in data["chain_rules"] if rule["id"] == "run_needs_approval_to_approval_item")
    approval_rule["enabled"] = True
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    approval = yaml.safe_load(capsys.readouterr().out)
    approval_result = next(
        result
        for action in approval["actions"]
        for result in action["results"]
        if result["chain_rule_id"] == "run_needs_approval_to_approval_item"
    )
    assert approval_result["status"] == "approval-needed"
    assert approval_result["queue_item"]["approval_state"] == "required"


def test_event_graph_dead_letter_and_run_close_emit_events(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["event", "append", "--root", str(root), "--type", "example.failed", "--source", "example:1"]) == 0
    capsys.readouterr()
    chain_rules = root / "shared_factory" / "00-control-plane" / "chain-rules.yml"
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    data["chain_rules"].append(
        {
            "id": "broken_rule",
            "display_name": "Broken Rule",
            "enabled": True,
            "when": {"event_type": "example.failed"},
            "then": {},
            "limits": {"max_chain_depth": 1},
            "idempotency": {"key": "{event_id}:broken"},
        }
    )
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["chain", "doctor", "--root", str(root)]) == 1
    doctor = yaml.safe_load(capsys.readouterr().out)
    assert any("missing enqueue action" in finding["message"] for finding in doctor["findings"])

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    processed = yaml.safe_load(capsys.readouterr().out)
    assert processed["actions"][0]["results"][0]["status"] == "dead-letter"
    assert list((root / "shared_factory" / "06-runs-and-logs" / "events" / "dead-letter").glob("*.yml"))

    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    data["chain_rules"][-1]["then"] = {
        "enqueue": {
            "work_type": "failure_review",
            "route_to": "shared_factory",
            "workflow": "review_failed_event",
            "context_profile": "event_context",
            "maturity": "prepare",
        }
    }
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert main(["event", "replay", processed["actions"][0]["event_id"], "--root", str(root), "--dry-run"]) == 0
    replay = yaml.safe_load(capsys.readouterr().out)
    assert replay["results"][0]["status"] == "dry-run"
    assert replay["results"][0]["queue_item"]["work_type"] == "failure_review"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_dir = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev"))
    assert (
        main(
            [
                "run-log",
                "close",
                "los",
                run_dir.name,
                "--status",
                "done",
                "--validation",
                "event graph test validation passed",
                "--emit-events",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    closeout = yaml.safe_load(capsys.readouterr().out)
    assert closeout["emitted_event"]["type"] == "os.run.closed.done"
    assert Path(closeout["emitted_event"]["emitted_path"]).is_file()


def test_notion_sync_plan_maps_filesystem_objects_and_is_idempotent(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    capsys.readouterr()
    assert main(["notion", "plan-sync", "--root", str(root)]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    action_kinds = {(action["action"], action["kind"]) for action in plan["actions"]}
    assert ("create", "domain") in action_kinds
    assert ("create", "project") in action_kinds
    assert ("create", "workflow") in action_kinds
    assert ("create", "automation") in action_kinds
    assert ("create", "run") in action_kinds
    assert not (root / ".notion-sync" / "mapping.yml").exists()

    assert main(["notion", "sync", "--root", str(root), "--apply"]) == 2
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Michael Clark Personal Notion",
            ]
        )
        == 2
    )

    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 0
    )
    assert (root / ".notion-sync" / "mapping.yml").is_file()

    capsys.readouterr()
    assert main(["notion", "sync", "--root", str(root), "--dry-run"]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert {action["action"] for action in plan["actions"]} == {"no-op"}


def test_customer_notion_sync_requires_configured_customer_workspace(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_os"
    write_customer_profile(profile)

    assert main(["customer", "init", "acme_ops", "--profile", str(profile), "--target", str(root)]) == 0
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Acme Notion",
            ]
        )
        == 0
    )


def test_notion_bootstrap_requires_verified_workspace_and_parent(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    capsys.readouterr()
    assert main(["notion", "bootstrap", "--root", str(root), "--dry-run"]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert plan["home_page"]["name"] == "Agentic OS"
    assert {database["name"] for database in plan["databases"]} >= {
        "OS Inbox",
        "Work Items",
        "Runs",
        "Approvals",
        "Domains",
    }
    assert plan["seed_records"]["runs"]
    assert not (root / ".notion-control-plane" / "manifest.yml").exists()

    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Michael Clark Personal Notion",
                "--parent-page-id",
                "abc123",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "notion",
                "bootstrap",
                "--root",
                str(root),
                "--apply",
                "--verified-workspace",
                "Genome's Notion",
                "--parent-page-id",
                "366683b48dab81a1ab5fc73e7e1f5c60",
            ]
        )
        == 0
    )
    manifest = yaml.safe_load((root / ".notion-control-plane" / "manifest.yml").read_text(encoding="utf-8"))
    assert manifest["workspace"] == "Genome's Notion"
    assert manifest["home_page"]["name"] == "Agentic OS"


def test_doctor_reports_stale_run_logs_and_repairs_missing_managed_files(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    missing_doc = root / "shared_factory" / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
    missing_doc.unlink()
    local_readme = root / "README.md"
    local_readme.write_text("# local root edit\n", encoding="utf-8")

    assert main(["doctor", "--root", str(root)]) == 1
    report = yaml.safe_load(capsys.readouterr().out)
    assert any(finding["severity"] == "blocker" and str(missing_doc) in finding["message"] for finding in report["findings"])

    assert main(["doctor", "--root", str(root), "--fix-missing"]) == 0
    report = yaml.safe_load(capsys.readouterr().out)
    assert report["repairs"]
    assert missing_doc.is_file()
    assert local_readme.read_text(encoding="utf-8") == "# local root edit\n"

    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--root", str(root)]) == 0
    report = yaml.safe_load(capsys.readouterr().out)
    assert any("run log has no final status" in finding["message"] for finding in report["findings"])


def test_migration_plan_and_apply_require_stable_preview(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 2

    assert main(["migrate", "plan", "--root", str(root)]) == 0
    plan = yaml.safe_load(capsys.readouterr().out)
    assert plan["migrations"][0]["migration_id"] == "notion-sync-readme-v1"
    assert "---" in plan["migrations"][0]["diff"]

    target = root / ".notion-sync" / "README.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# changed after preview\n", encoding="utf-8")
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 2

    target.unlink()
    assert main(["migrate", "plan", "--root", str(root)]) == 0
    assert main(["migrate", "apply", "notion-sync-readme-v1", "--root", str(root)]) == 0
    assert "Filesystem state remains the source of truth" in target.read_text(encoding="utf-8")


def test_losmon_validate_creates_required_validation_objects(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "los_repo"
    repo.mkdir()

    assert main(["losmon", "validate", "--root", str(root), "--repo", str(repo)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["project"].endswith("los/02-projects/losmon_replacement")

    required_paths = [
        root / "los" / "02-projects" / "losmon_replacement" / "project.yml",
        root / "los" / "03-workflows" / "engineering" / "pr_review" / "workflow.md",
        root / "los" / "03-workflows" / "engineering" / "failing_ci_triage" / "workflow.md",
        root / "los" / "03-workflows" / "operations" / "deploy_planning" / "workflow.md",
        root / "los" / "04-automations" / "support" / "thread_intake" / "automation.md",
        root / "los" / "02-projects" / "losmon_replacement" / "artifacts" / "losmon-comparison.md",
    ]
    for path in required_paths:
        assert path.is_file(), path

    comparison = (root / "los" / "02-projects" / "losmon_replacement" / "artifacts" / "losmon-comparison.md").read_text(
        encoding="utf-8"
    )
    assert "LOSMon Still Better / Required" in comparison
    assert "Need live connected-source watcher" in comparison
    assert len(result["run_logs"]) == 3
    for run_log in result["run_logs"]:
        content = Path(run_log).read_text(encoding="utf-8")
        assert "## Closeout" in content
        assert "Run this workflow against a real read-only LOS task" in content
    assert main(["validate", "--root", str(root)]) == 0


def test_plan_capture_routes_os_domain_and_project_ideas(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--title",
                "Telemetry Adapter",
                "--summary",
                "Capture losmon telemetry into run logs.",
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    os_plan = Path(result["target"])
    assert os_plan.is_file()
    assert "Capture losmon telemetry into run logs." in os_plan.read_text(encoding="utf-8")
    assert "future-ideas/telemetry-adapter.md" in (
        root / "shared_factory" / "05-knowledge" / "plans" / "README.md"
    ).read_text(encoding="utf-8")

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--kind",
                "domain",
                "--domain",
                "los",
                "--title",
                "CI failure clustering",
                "--summary",
                "Group related CI failures before triage.",
            ]
        )
        == 0
    )
    raw_ideas = (root / "los" / "01-inbox" / "raw-ideas.md").read_text(encoding="utf-8")
    assert "CI failure clustering" in raw_ideas

    assert (
        main(
            [
                "plan",
                "capture",
                "--root",
                str(root),
                "--kind",
                "customer",
                "--domain",
                "los",
                "--project",
                "losmon_replacement",
                "--title",
                "Customer-safe deploy brief",
                "--summary",
                "Create reusable customer deploy planning notes.",
            ]
        )
        == 0
    )
    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "Customer-safe deploy brief" in project_status


def test_workflow_check_reports_readiness_findings(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["workflow", "check", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)

    severities = {finding["severity"] for finding in packet["findings"]}
    assert severities <= {"blocker", "fix-soon", "cleanup", "observation"}
    assert "fix-soon" in severities

    runbook = root / "los" / "03-workflows" / "engineering" / "feature_dev" / "runbook.md"
    runbook.write_text(runbook.read_text(encoding="utf-8").replace("## After Running", "## Finish"), encoding="utf-8")

    assert main(["workflow", "check", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert {
        "severity": "blocker",
        "path": str(runbook),
        "message": "missing required section: After Running",
    } in packet["findings"]


def test_run_log_close_requires_validation_for_done_and_rejects_invalid_status(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_id = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev")).name

    assert main(["run-log", "close", "los", run_id, "--status", "done", "--root", str(root)]) == 2
    with pytest.raises(SystemExit) as exc:
        main(["run-log", "close", "los", run_id, "--status", "finished", "--root", str(root)])
    assert exc.value.code == 2


def test_run_log_close_records_closeout_and_activity_updates(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_dir = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev"))

    assert (
        main(
            [
                "run-log",
                "close",
                "los",
                run_dir.name,
                "--status",
                "done",
                "--summary",
                "Built and verified the workflow closeout command.",
                "--validation",
                "uv run --extra dev pytest -q passed",
                "--artifact",
                "run-log.md",
                "--approval",
                "No external approval gate encountered.",
                "--next-action",
                "Promote to the next feature.",
                "--learning",
                "Closeout needs validation evidence before done.",
                "--project",
                "losmon_replacement",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["status"] == "done"

    run_log = run_dir / "run-log.md"
    content = run_log.read_text(encoding="utf-8")
    assert "| Status | `done` |" in content
    assert "## Closeout" in content
    assert "uv run --extra dev pytest -q passed" in content
    assert "Promote to the next feature." in content

    activity_log = (root / "los" / "06-runs-and-logs" / "activity-log.md").read_text(encoding="utf-8")
    assert run_dir.name in activity_log
    progress = (root / "los" / "03-workflows" / "engineering" / "feature_dev" / "progress.md").read_text(
        encoding="utf-8"
    )
    assert run_dir.name in progress
    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "## Run Closeout" in project_status
    assert validate_root(root).ok


def test_generated_markdown_has_level_specific_contracts(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0

    workflow_root = root / "los" / "03-workflows" / "engineering" / "feature_dev"
    automation_root = root / "los" / "04-automations" / "support" / "production_thread_intake"
    run_log = next((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev/run-log.md"))

    required_sections = {
        root / "ROUTER.md": ("# Agent Router", "## Routing Table", "## Operating Rules"),
        root / "AGENTS.md": ("# Agent Entry Point", "## Required Loop", "RULES.md", "TOOLS.md"),
        root / "CLAUDE.md": ("@AGENTS.md",),
        root / "CONTEXT.md": ("# Local Context", "## What To Load", "## Done Means"),
        root / "RULES.md": ("# Rules", "## Approval Gates", "## Operating Rules"),
        root / "TOOLS.md": ("# Tools", "## Skills", "## Commands", "## MCP Servers"),
        root / "los" / "ROUTER.md": ("# Agent Router: LOS", "## Where To Put Work", "## Approval Rules"),
        root / "los" / "AGENTS.md": ("# Agent Entry Point", "## Required Loop", "RULES.md", "TOOLS.md"),
        root / "los" / "CLAUDE.md": ("@AGENTS.md",),
        root / "los" / "CONTEXT.md": ("# Context: LOS", "## What To Load", "## Tools And Skills", "## Done Means"),
        root / "los" / "RULES.md": ("# Rules: LOS", "## Approval Gates", "## Operating Rules"),
        root / "los" / "TOOLS.md": ("# Tools: LOS", "## Skills", "## Commands", "## MCP Servers"),
        root / "los" / "REFERENCES.md": ("# References: LOS", "## Source Systems", "## Known Gaps"),
        root / "los" / "03-workflows" / "README.md": ("# Workflows: LOS", "## Lane Directories", "## Workflow Folder Format"),
        root / "los" / "03-workflows" / "engineering" / "README.md": (
            "# Workflow Lane: engineering",
            "## Workflow Folder Format",
            "## Routing Rule",
        ),
        workflow_root / "workflow.md": ("# Workflow: feature_dev", "## Metadata", "## Purpose", "## Validation"),
        workflow_root / "outcome-brief.md": (
            "# Outcome Brief: feature_dev",
            "## Definition Of Done",
            "## Acceptance Criteria",
        ),
        workflow_root / "alignment-questions.md": (
            "# Alignment Questions: feature_dev",
            "## Required Questions",
            "## Dispatch Decision",
        ),
        workflow_root / "prd.md": (
            "# PRD: feature_dev",
            "## Requirements",
            "## Validation",
        ),
        workflow_root / "implementation-plan.md": (
            "# Implementation Plan: feature_dev",
            "## Build Stages",
            "## Validation Plan",
        ),
        workflow_root / "dispatch-handoff.md": (
            "# Dispatch Handoff: feature_dev",
            "## Required Sources To Load",
            "## Stop Conditions",
        ),
        workflow_root / "progress.md": (
            "# Progress: feature_dev",
            "## Current State",
            "## Handoff Prompt",
        ),
        workflow_root / "quick-reference.md": (
            "# Quick Reference: feature_dev",
            "## Start Here",
            "## Common Failure Modes",
        ),
        workflow_root / "state-machine.md": ("# State Machine: feature_dev", "| From | To | Condition |"),
        workflow_root / "output-contract.md": ("# Output Contract: feature_dev", "## Required Outputs", "## Quality Bar"),
        workflow_root / "examples" / "README.md": ("# Examples: feature_dev", "## Example Format"),
        root / "los" / "04-automations" / "README.md": (
            "# Automations: LOS",
            "## Lane Directories",
            "## Automation Folder Format",
        ),
        automation_root / "automation.md": ("# Automation: production_thread_intake", "## Metadata", "## Trigger"),
        automation_root / "inputs.md": ("# Inputs: production_thread_intake", "| Input | Required | Source | Validation |"),
        automation_root / "logs" / "README.md": ("# Automation Logs: production_thread_intake", "## Log Format"),
        root / "los" / "06-runs-and-logs" / "runs" / "README.md": ("# Runs: LOS", "## Run Folder Format"),
        root / "los" / "06-runs-and-logs" / "failures" / "README.md": ("# Failures: LOS", "## Failure Record Format"),
        run_log: ("# Run Log:", "## Metadata", "## Input", "## Session Continuity", "## Validation", "## Handoff"),
    }

    for path, sections in required_sections.items():
        content = path.read_text(encoding="utf-8")
        if path.name != "CLAUDE.md":
            assert content.startswith("# "), path
        for section in sections:
            assert section in content, path
