from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import yaml

from genomes_agentic_os import runtime_ops
from genomes_agentic_os.cli import main
from genomes_agentic_os.config_ops import LAYER_POLICIES, PROFILE_MANAGED_MARKER, sidecar_path
from genomes_agentic_os.routing import context_from_here
from genomes_agentic_os.scaffold import PROJECT_CONFIG_FILES, create_project_worktree
from genomes_agentic_os.validate import validate_root
from genomes_agentic_os.work_lifecycle import (
    create_project_work_item as create_compat_project_work_item,
    list_project_work_items as list_compat_project_work_items,
    promote_project_work_item as promote_compat_project_work_item,
)


def harness(root: Path) -> Path:
    return root / "harness"


def shared_factory(root: Path) -> Path:
    return harness(root) / "shared_factory"


def limit_self_improvement_evidence_to_runs(root: Path) -> None:
    config_path = shared_factory(root) / "00-control-plane" / "self-improvement.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["evidence_roots"] = [
        {
            "path": "harness/shared_factory/06-runs-and-logs/runs",
            "legacy_read_only": False,
        }
    ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_init_creates_domain_first_tree_and_shared_templates(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    projects_source = tmp_path / "projects"
    projects_source.mkdir()

    assert main(["init", "--target", str(root), "--projects-source", str(projects_source)]) == 0

    assert (root / ".agentic_root").is_file()
    assert not (root / "projects").exists()
    assert {path.name for path in root.iterdir() if not path.name.startswith(".")} == {
        "archive",
        "harness",
        "personal",
        "work",
    }

    for domain in ("personal", "work", "archive"):
        domain_root = root / domain
        assert domain_root.is_dir()
        assert (domain_root / "config.toml").is_file()
        assert (domain_root / "ROUTER.md").is_file()
        assert (domain_root / "AGENTS.md").is_file()
        assert (domain_root / "CLAUDE.md").is_file()
        assert (domain_root / "CONTEXT.md").is_file()
        assert (domain_root / "RULES.md").is_file()
        assert (domain_root / "TOOLS.md").is_file()
        assert (domain_root / "MEMORY.md").is_file()
        assert (domain_root / "REFERENCES.md").is_file()
        assert not (domain_root / "AGENT.md").exists()
        assert (domain_root / "00-programs" / "README.md").is_file()
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

    assert (shared_factory(root) / "domain.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "state-index.md").is_file()
    assert not (root / "shared_factory").exists()

    assert (harness(root) / "ROUTER.md").is_file()
    assert (harness(root) / "config.toml").is_file()
    assert (harness(root) / "AGENTS.md").is_file()
    assert (harness(root) / "CLAUDE.md").is_file()
    assert (harness(root) / "CONTEXT.md").is_file()
    assert (harness(root) / "RULES.md").is_file()
    assert (harness(root) / "TOOLS.md").is_file()
    assert (harness(root) / "MEMORY.md").is_file()
    assert (harness(root) / "agentic-os.lock.json").is_file()
    assert (harness(root) / "UPDATE_POLICY.md").is_file()
    assert (harness(root) / "registries" / "updates.yml").is_file()
    assert (harness(root) / "registries" / "customer-identity.json").is_file()
    assert (harness(root) / "registries" / "backup-policy.yml").is_file()
    assert (harness(root) / "bin" / "README.md").is_file()
    assert (harness(root) / "mcp" / "README.md").is_file()
    assert (harness(root) / "plugins" / "README.md").is_file()
    assert (harness(root) / "libraries" / "README.md").is_file()
    assert (harness(root) / "rules" / "README.md").is_file()
    assert not (harness(root) / "registries" / "update-grant.json").exists()
    assert (harness(root) / "security" / "ssh").is_dir()
    assert (harness(root) / "logs" / "updates").is_dir()
    assert (harness(root) / "logs" / "backups").is_dir()
    assert not (root / "AGENT.md").exists()
    assert (harness(root) / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    root_agents = (harness(root) / "AGENTS.md").read_text(encoding="utf-8")
    assert "ROUTER.md" in root_agents
    assert "CONTEXT.md" in root_agents
    assert "RULES.md" in root_agents
    assert "TOOLS.md" in root_agents
    for directory in ("bin", "commands", "skills", "mcp", "plugins", "libraries", "hooks", "rules", "registries"):
        assert (harness(root) / directory).is_dir()
    for registry_name in (
        "capabilities.yml",
        "commands.yml",
        "skills.yml",
        "mcp-servers.yml",
        "libraries.yml",
        "hooks.yml",
        "plugins.yml",
        "rules.yml",
        "composio-tools.yml",
    ):
        assert (harness(root) / "registries" / registry_name).is_file()
    inventory = (harness(root) / "INVENTORY.md").read_text(encoding="utf-8")
    assert "## Commands" in inventory
    assert "`make-skill`" in inventory
    assert "`orchestrate`" in inventory
    assert "`config-install-tree`" in inventory
    assert "`project-worktree-cleanup-closed`" in inventory
    commands = yaml.safe_load((harness(root) / "registries" / "commands.yml").read_text(encoding="utf-8"))
    assert {entry["command"] for entry in commands["commands"]} >= {
        "/make-skill",
        "/make-domain",
        "/make-automation",
        "/make-workflow",
        "/groom-spec",
        "/orchestrate",
        "agentic-os project worktree cleanup-closed",
    }
    skills = yaml.safe_load((harness(root) / "registries" / "skills.yml").read_text(encoding="utf-8"))
    assert "os-cleaner" in {entry["id"] for entry in skills["skills"]}
    assert "spec-groomer" in {entry["id"] for entry in skills["skills"]}
    mcp_servers = yaml.safe_load((harness(root) / "registries" / "mcp-servers.yml").read_text(encoding="utf-8"))
    assert {"context_mode", "genomes_brain"} <= {entry["id"] for entry in mcp_servers["mcp_servers"]}
    composio_tools = yaml.safe_load((harness(root) / "registries" / "composio-tools.yml").read_text(encoding="utf-8"))
    composio_route_ids = {entry["id"] for entry in composio_tools["composio_tools"]}
    assert {"agentmail_genome", "slack_genome", "notion_blocks", "composio_discovery"} <= composio_route_ids
    libraries = yaml.safe_load((harness(root) / "registries" / "libraries.yml").read_text(encoding="utf-8"))
    assert {"context_mode", "unified_memory"} <= {entry["id"] for entry in libraries["libraries"]}
    hooks = yaml.safe_load((harness(root) / "registries" / "hooks.yml").read_text(encoding="utf-8"))
    assert {"memory-session-start", "memory-stop", "harness-trace-emitter", "context-mode-cache-heal"} <= {
        entry["id"] for entry in hooks["hooks"]
    }
    for hook_name in (
        "memory-session-start.sh",
        "memory-stop.sh",
        "harness-emit-trace.sh",
        "conversation-auto-log.py",
        "context-mode-cache-heal.mjs",
    ):
        hook_path = harness(root) / "hooks" / hook_name
        assert hook_path.is_file()
        assert hook_path.stat().st_mode & 0o111
    assert (harness(root) / "commands" / "os-route.md").is_file()
    assert (harness(root) / "commands" / "os-groom-spec.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-groom-spec.md").is_file()
    assert (harness(root) / "skills" / "os-navigator" / "SKILL.md").is_file()
    assert (harness(root) / "skills" / "spec-groomer" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "spec-groomer" / "SKILL.md").is_file()
    assert (shared_factory(root) / "00-programs" / "spec_grooming" / "program.md").is_file()
    assert (
        shared_factory(root)
        / "00-programs"
        / "spec_grooming"
        / "templates"
        / "ORIGINAL_INTENT_TEMPLATE.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "workflow" / "workflow.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "workflow" / "outcome-brief.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "workflow" / "prd.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "domain" / "context.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "planning" / "feature-spec.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "planning" / "future-idea.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "notion" / "agentic-os-control-plane.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "room" / "router.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "room" / "routing-table.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "reference" / "os-conventions.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "os-conventions.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "reference" / "tool-index.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "reference" / "source-priority.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "reference" / "style-and-output-rules.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "reference" / "decision-log.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "naming-conventions.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "os-conventions.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "tool-index.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "source-priority.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "style-and-output-rules.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "references" / "decision-log.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "customer" / "customer-handoff-checklist.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "notion" / "control-plane-database-spec.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "heartbeat.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "schedule.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "execution-target.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "integration.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "run-queue-item.yml").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "notion" / "runtime-tracking-database-spec.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "connected-system.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "source-provider.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "watch-source.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "watch-cursor.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "source-event.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "trigger-rule.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "event-envelope.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "event-ledger-index.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "chain-rule.yml").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "event-processing-result.yml"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "dead-letter-event.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "update-grant.json").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "backup-policy.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "self-improvement.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "managed-templates.yml").is_file()
    assert (shared_factory(root) / "04-workflows" / "self-improvement-review.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "self-improvement.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "managed-templates.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "self-improvement-workflow.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "self-improvement-review.yml").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "self-improvement-proposal.yml").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "self-improvement-usage-sidecar.json"
    ).is_file()
    assert (shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "runs").is_dir()
    assert (shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "proposals").is_dir()
    assert (shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "approvals").is_dir()
    assert (shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "drafts").is_dir()
    assert (shared_factory(root) / "05-knowledge" / "operating-manual" / "README.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "operating-manual" / "index.html").is_file()
    assert (shared_factory(root) / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "operating-manual" / "07-diagrams" / "layer-map.svg").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-route.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-capture-plan.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-discover-rooms.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-doctor.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-client-automation-brief.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-control-plane-bootstrap.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-context-audit.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-runtime-init.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-heartbeat.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-integration-setup.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-self-improvement.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-watch-source.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-event.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-chain.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "plans" / "README.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "plans" / "23-doc-config-system.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "room-builder" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "os-navigator" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "workflow-builder" / "SKILL.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "skills" / "client-automation-brief" / "SKILL.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "skills" / "control-plane-bootstrap" / "SKILL.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "context-audit" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "runtime-operator" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "integration-setup" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "source-watcher" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "event-graph-operator" / "SKILL.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "toolsmith-reviewer" / "SKILL.md").is_file()
    assert not (root / "domains").exists()
    assert not (root / "lenders").exists()
    assert not validate_root(root).errors


def test_spec_grooming_program_installs_contract(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0

    program_root = shared_factory(root) / "00-programs" / "spec_grooming"
    skill = (harness(root) / "skills" / "spec-groomer" / "SKILL.md").read_text(encoding="utf-8")
    command = (harness(root) / "commands" / "os-groom-spec.md").read_text(encoding="utf-8")
    root_tools = (harness(root) / "TOOLS.md").read_text(encoding="utf-8")

    assert (program_root / "components.yml").is_file()
    assert (program_root / "templates" / "A_PLUS_SPEC_TEMPLATE.md").is_file()
    assert (program_root / "examples" / "01_universal_spec_grooming_os" / "SPEC.md").is_file()
    assert (program_root / "examples" / "02_capability_discovery_gate" / "SPEC.md").is_file()
    assert (program_root / "examples" / "03_pr_reviewer_dashboard_route" / "SPEC.md").is_file()
    assert "ORIGINAL_INTENT.md" in skill
    assert "$jira-product-orchestrator" in skill
    assert "/groom-spec" in command
    assert "spec_grooming" in root_tools


def test_validate_requires_self_improvement_surface(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    (shared_factory(root) / "00-control-plane" / "self-improvement.yml").unlink()

    result = validate_root(root)

    assert not result.ok
    assert any("self-improvement.yml" in error for error in result.errors)


def test_self_improvement_dry_run_reports_seeded_evidence_without_writes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "seeded-self-improvement.md"
    evidence.write_text(
        "\n".join(
            [
                "Validation failed after repeated manual command sequence.",
                "Validation failed after repeated manual command sequence.",
                "Manual command workaround should become a shared workflow.",
                "token: ghp_1234567890abcdefghijklmnopqrst",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    self_improvement_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement"
    before = {
        path.relative_to(self_improvement_root)
        for path in self_improvement_root.rglob("*")
        if path.is_file()
    }

    assert main(["self-improvement", "run", "--root", str(root), "--dry-run"]) == 0

    output = capsys.readouterr().out
    after = {
        path.relative_to(self_improvement_root)
        for path in self_improvement_root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert "Self Improvement Dry Run" in output
    assert "writes: none" in output
    assert "Deterministic findings:" in output
    assert "Recurring failure signal" in output or "Repeated evidence pattern" in output
    assert "ghp_1234567890abcdefghijklmnopqrst" not in output
    assert "redactions: 1" in output


def test_self_improvement_bare_run_is_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    """Bare `self-improvement run` (no flag) must be dry-run — SPEC 15 first-run safety."""
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "bare-run-evidence.md"
    evidence.write_text(
        "Validation failed after repeated manual command sequence.\n"
        "Validation failed after repeated manual command sequence.\n"
        "Manual command workaround should become a shared workflow.\n",
        encoding="utf-8",
    )
    self_improvement_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement"
    before = {
        path.relative_to(self_improvement_root)
        for path in self_improvement_root.rglob("*")
        if path.is_file()
    }

    # Bare invocation — no --dry-run, no --apply.
    assert main(["self-improvement", "run", "--root", str(root)]) == 0

    after = {
        path.relative_to(self_improvement_root)
        for path in self_improvement_root.rglob("*")
        if path.is_file()
    }
    assert before == after, "Bare run must write nothing (dry-run by default)"
    output = capsys.readouterr().out
    assert "Self Improvement Dry Run" in output
    assert "writes: none" in output


def test_self_improvement_apply_writes_proposals_and_dedupes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    limit_self_improvement_evidence_to_runs(root)
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "apply-evidence.md"
    evidence.write_text(
        "\n".join(
            [
                "Validation failed after repeated manual command sequence.",
                "Validation failed after repeated manual command sequence.",
                "Manual command workaround should become a shared workflow.",
                "token: ghp_1234567890abcdefghijklmnopqrst",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Self Improvement Apply" in output
    assert "ghp_1234567890abcdefghijklmnopqrst" not in output

    self_improvement_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement"
    run_files = sorted((self_improvement_root / "runs").glob("*.yml"))
    proposal_files = sorted((self_improvement_root / "proposals").glob("*.yml"))
    assert run_files
    assert proposal_files
    assert all(path.stem.startswith("si-") for path in proposal_files)
    assert len({path.stem for path in proposal_files}) == len(proposal_files)
    first_count = len(proposal_files)
    proposal = yaml.safe_load(proposal_files[0].read_text(encoding="utf-8"))
    assert proposal["proposal_id"] == proposal_files[0].stem
    assert proposal["content_hash"].startswith("sha256:")
    assert proposal["promotion_status"] == "proposed"
    assert proposal["approval_requirement"] == "operator_required"
    assert proposal["validation_plan"]
    assert "ghp_1234567890abcdefghijklmnopqrst" not in yaml.safe_dump(proposal)

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    assert len(sorted((self_improvement_root / "proposals").glob("*.yml"))) == first_count

    proposal_id = proposal["proposal_id"]
    assert main(["self-improvement", "status", "--root", str(root)]) == 0
    status_output = capsys.readouterr().out
    assert "proposal_counts:" in status_output
    assert "queue_health:" in status_output
    assert main(["self-improvement", "list", "--root", str(root)]) == 0
    assert proposal_id in capsys.readouterr().out
    assert main(["self-improvement", "show", proposal_id, "--root", str(root)]) == 0
    assert proposal_id in capsys.readouterr().out


def test_self_improvement_reject_starts_cooldown_and_suppresses_duplicate(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    limit_self_improvement_evidence_to_runs(root)
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "single-finding.md"
    evidence.write_text(
        "Repeated operator friction should become a draft feature.\n"
        "Repeated operator friction should become a draft feature.\n",
        encoding="utf-8",
    )

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    proposals_dir = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "proposals"
    proposal_path = next(proposals_dir.glob("*.yml"))
    proposal_id = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))["proposal_id"]

    assert main(["self-improvement", "reject", proposal_id, "--root", str(root)]) == 0
    rejected = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert rejected["promotion_status"] == "rejected"
    assert rejected["cooldown_until"]

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    output = capsys.readouterr().out
    assert "cooldown_active" in output
    assert len(sorted(proposals_dir.glob("*.yml"))) == 1


def test_self_improvement_approve_and_promote_feature_draft(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    limit_self_improvement_evidence_to_runs(root)
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "feature-draft.md"
    evidence.write_text(
        "Repeated operator friction should become a draft feature.\n"
        "Repeated operator friction should become a draft feature.\n",
        encoding="utf-8",
    )

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    proposals_dir = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "proposals"
    proposal_path = next(proposals_dir.glob("*.yml"))
    proposal_id = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))["proposal_id"]

    assert main(["self-improvement", "approve", proposal_id, "--target", "feature-spec", "--root", str(root)]) == 0
    approved = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert approved["promotion_status"] == "approved"
    assert approved["approval_record_id"]
    approval_path = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "approvals" / f"{approved['approval_record_id']}.yml"
    assert approval_path.is_file()

    assert main(["self-improvement", "promote", proposal_id, "--target", "feature-spec", "--root", str(root)]) == 0
    draft_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "drafts" / proposal_id
    assert (draft_root / "feature.yml").is_file()
    assert (draft_root / "SPEC.md").is_file()
    assert (draft_root / "PLAN.md").is_file()
    assert (draft_root / "VALIDATION.md").is_file()
    assert (draft_root / "NEXT.md").is_file()
    spec = (draft_root / "SPEC.md").read_text(encoding="utf-8")
    assert "## Acceptance Criteria" in spec
    assert f"Proposal: `{proposal_id}`" in spec
    drafted = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert drafted["promotion_status"] == "drafted"


def test_self_improvement_promote_rejects_mutated_approval_content(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    limit_self_improvement_evidence_to_runs(root)
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "mutated-approval.md"
    evidence.write_text(
        "Repeated operator friction should become a draft feature.\n"
        "Repeated operator friction should become a draft feature.\n",
        encoding="utf-8",
    )

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 0
    proposals_dir = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "proposals"
    proposal_path = next(proposals_dir.glob("*.yml"))
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal_id = proposal["proposal_id"]
    assert main(["self-improvement", "approve", proposal_id, "--target", "feature-spec", "--root", str(root)]) == 0

    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal["summary"] = "Changed after approval."
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    assert main(["self-improvement", "promote", proposal_id, "--target", "feature-spec", "--root", str(root)]) == 2
    draft_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement" / "drafts" / proposal_id
    assert not draft_root.exists()


def test_self_improvement_apply_rejects_unsafe_output_paths(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    limit_self_improvement_evidence_to_runs(root)
    evidence = shared_factory(root) / "06-runs-and-logs" / "runs" / "unsafe-path.md"
    evidence.write_text(
        "Repeated operator friction should become a draft feature.\n"
        "Repeated operator friction should become a draft feature.\n",
        encoding="utf-8",
    )
    config_path = shared_factory(root) / "00-control-plane" / "self-improvement.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["output_paths"]["proposals"] = "../escape"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    assert main(["self-improvement", "run", "--root", str(root), "--apply"]) == 2
    assert not (tmp_path / "escape").exists()


def test_self_improvement_runtime_schedule_is_disabled_but_dispatchable_when_enabled(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    registry_path = shared_factory(root) / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    schedules = {schedule["id"]: schedule for schedule in registry["schedules"]}
    assert schedules["stale_thread_finalizer"]["enabled"] is True
    assert (
        schedules["stale_thread_finalizer"]["command"]
        == "agentic-os thread stale-finalize --root <root> --older-than-days 3 --apply"
    )
    assert schedules["self_improvement_review"]["enabled"] is False
    assert schedules["self_improvement_review"]["command"] == "agentic-os self-improvement run --root <root> --apply"
    assert schedules["closed_worktree_cleanup_0500"]["enabled"] is True
    assert (
        schedules["closed_worktree_cleanup_0500"]["command"]
        == "agentic-os project worktree cleanup-closed --root <root> --apply"
    )
    assert schedules["closed_worktree_cleanup_0500"]["local_time"] == "05:00"
    assert schedules["closed_worktree_cleanup_2200"]["enabled"] is True
    assert (
        schedules["closed_worktree_cleanup_2200"]["command"]
        == "agentic-os project worktree cleanup-closed --root <root> --apply"
    )
    assert schedules["closed_worktree_cleanup_2200"]["local_time"] == "22:00"

    for schedule in registry["schedules"]:
        schedule["enabled"] = schedule["id"] == "self_improvement_review"
        schedule["next_due_at"] = None
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    queued = yaml.safe_load(capsys.readouterr().out)
    by_ref = {item["ref"]: item for item in queued["queued"]}
    assert by_ref["self_improvement_review"]["ref"] == "self_improvement_review"
    item_id = by_ref["self_improvement_review"]["id"]

    assert main(["runtime", "run-next", "--root", str(root), "--item-id", item_id, "--apply"]) == 0
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    # Dispatch now persists and documents: a run record is written and the daily
    # report is rendered (the heartbeat documents, it does not mutate live OS surfaces).
    self_improvement_root = shared_factory(root) / "06-runs-and-logs" / "self-improvement"
    assert list((self_improvement_root / "runs").glob("*.yml"))
    assert (self_improvement_root / "latest-report.md").is_file()


def test_adaptive_routing_observation_report_schedule_is_idempotent_and_dispatchable(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    capsys.readouterr()

    registry_path = shared_factory(root) / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    schedules = {schedule["id"]: schedule for schedule in registry["schedules"]}
    report_schedule = schedules["adaptive_routing_observation_report"]

    assert report_schedule["enabled"] is False
    assert report_schedule["cadence"] == "every_12_hours"
    assert report_schedule["command"] == (
        "agentic-os adaptive-routing report --root <root> --hours 12 --apply-notion"
    )
    assert report_schedule["outputs"] == [
        "harness/shared_factory/06-runs-and-logs/adaptive-routing/observation-reports/"
    ]
    assert report_schedule["external_effect"] == "append-only projection to verified Genome's Notion"
    assert report_schedule["notion_update"] == {
        "workspace": "Genome's Notion",
        "mode": "append_only",
        "requires_verified_workspace": True,
    }

    for schedule in registry["schedules"]:
        schedule["enabled"] = schedule["id"] == "adaptive_routing_observation_report"
        schedule["next_due_at"] = None
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    first = yaml.safe_load(capsys.readouterr().out)
    assert [item["ref"] for item in first["queued"]] == ["adaptive_routing_observation_report"]
    queued_item = first["queued"][0]
    assert queued_item["command"] == report_schedule["command"]

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    second = yaml.safe_load(capsys.readouterr().out)
    assert second["queued"] == []
    assert next(
        item for item in second["skipped"] if item["schedule"] == "adaptive_routing_observation_report"
    )["reason"] == "not due"

    dispatched_commands: list[str] = []

    def fake_subprocess_script(
        dispatch_root: Path, command: str, *, timeout_seconds: int
    ) -> dict[str, object]:
        assert dispatch_root == root
        assert timeout_seconds == runtime_ops.SCRIPT_DISPATCH_TIMEOUT_SECONDS
        dispatched_commands.append(command)
        return {
            "supported": True,
            "ok": True,
            "command": command,
            "errors": [],
            "warnings": [],
            "external_effect": "stubbed; no external call",
        }

    monkeypatch.setattr(runtime_ops, "_run_subprocess_script", fake_subprocess_script)
    assert main(
        ["runtime", "run-next", "--root", str(root), "--item-id", queued_item["id"], "--apply"]
    ) == 0
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["external_effect"] == "stubbed; no external call"
    assert dispatched_commands == [
        f"agentic-os adaptive-routing report --root {root} --hours 12 --apply-notion"
    ]


def test_validate_fails_when_declared_capability_is_missing_from_registry(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    capabilities_path = harness(root) / "registries" / "capabilities.yml"
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


def test_validate_requires_context_mode_and_unified_memory_runtime_integrations(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    mcp_path = harness(root) / "registries" / "mcp-servers.yml"
    mcp_servers = yaml.safe_load(mcp_path.read_text(encoding="utf-8"))
    mcp_servers["mcp_servers"] = [
        entry for entry in mcp_servers["mcp_servers"] if entry.get("id") != "context_mode"
    ]
    mcp_path.write_text(yaml.safe_dump(mcp_servers, sort_keys=False), encoding="utf-8")

    hooks_path = harness(root) / "registries" / "hooks.yml"
    hooks = yaml.safe_load(hooks_path.read_text(encoding="utf-8"))
    hooks["hooks"] = [entry for entry in hooks["hooks"] if entry.get("id") != "memory-stop"]
    hooks_path.write_text(yaml.safe_dump(hooks, sort_keys=False), encoding="utf-8")

    result = validate_root(root)

    assert not result.ok
    assert any("missing required runtime MCP server 'context_mode'" in error for error in result.errors)
    assert any("missing required runtime hook 'memory-stop'" in error for error in result.errors)


def test_update_apply_merges_missing_default_capability_registry_entries(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    commands_path = harness(root) / "registries" / "commands.yml"
    commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    commands["commands"] = [entry for entry in commands["commands"] if entry.get("id") != "hook-sync"]
    commands["commands"].append(
        {
            "id": "local-command",
            "command": "local only",
            "description": "Preserve local registry entries.",
            "source": "local",
        }
    )
    commands_path.write_text(yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")

    assert main(["update", "plan", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["update", "apply", "--root", str(root)]) == 0
    capsys.readouterr()

    repaired = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    command_ids = {entry["id"] for entry in repaired["commands"]}
    assert "hook-sync" in command_ids
    assert "local-command" in command_ids


def test_update_channel_check_plan_apply_and_phone_home_are_local_and_safe(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    manifest = tmp_path / "manifest.yml"

    assert main(["init", "--target", str(root)]) == 0
    local_command = harness(root) / "commands" / "os-route.md"
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
    assert not (harness(root) / "registries" / "update-plan.yml").exists()

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


def test_update_apply_migrates_legacy_root_layout_to_harness(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "los_app_los_django", "--root", str(root)]) == 0
    legacy_project = root / "los" / "02-projects" / "los_app_los_django"
    shutil.rmtree(legacy_project / "work-items")
    (legacy_project / "config" / "work-lifecycle.yml").unlink()
    for child in sorted(harness(root).iterdir(), key=lambda path: path.name):
        shutil.move(str(child), str(root / child.name))
    harness(root).rmdir()
    assert (root / "AGENTS.md").is_file()
    assert (root / "shared_factory" / "domain.yml").is_file()
    assert not (harness(root) / "AGENTS.md").exists()

    assert main(["update", "plan", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["update", "apply", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert result["status"]["layout_migration"] is True
    assert result["status"]["project_surface_repair"] is True
    assert {path.name for path in root.iterdir() if not path.name.startswith(".")} == {
        "archive",
        "harness",
        "los",
        "personal",
        "work",
    }
    assert (harness(root) / "AGENTS.md").is_file()
    assert (harness(root) / "PROFILE.md").is_file()
    assert (harness(root) / "config.toml").is_file()
    assert sidecar_path(harness(root)).is_file()
    assert (shared_factory(root) / "domain.yml").is_file()
    assert (legacy_project / "work-items").is_dir()
    assert (legacy_project / "work-items" / "01-intake").is_dir()
    assert (legacy_project / "work-items" / "02-active").is_dir()
    assert (legacy_project / "work-items" / "03-complete").is_dir()
    assert (legacy_project / "config" / "work-lifecycle.yml").is_file()
    assert not (root / "shared_factory").exists()
    assert not (root / "PROFILE.md").exists()
    assert not (root / "config").exists()
    assert list((harness(root) / "logs" / "migrations").glob("harness-layout-*/legacy-root/AGENTS.md"))
    assert validate_root(root).ok


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
    identity = (harness(root) / "registries" / "customer-identity.json").read_text(encoding="utf-8")
    assert raw_key not in identity

    assert main(["update", "register", "--root", str(root)]) == 0
    registered = yaml.safe_load(capsys.readouterr().out)
    assert Path(registered["grant_path"]).is_file()
    assert "public_keys" in registered
    assert "private_keys" in registered
    assert raw_key not in yaml.safe_dump(registered)
    assert (harness(root) / "security" / "ssh" / "update_ed25519").stat().st_mode & 0o777 == 0o600
    assert (harness(root) / "security" / "ssh" / "backup_ed25519").stat().st_mode & 0o777 == 0o600

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
    assert not (harness(root) / "registries" / "update-grant.json").is_file()
    assert not (harness(root) / "security" / "ssh" / "update_ed25519").exists()

    # Activating the license flips billing active and unblocks registration.
    assert main(["license", "activate", "--root", str(root), "--key", "fake-key"]) == 0
    assert main(["update", "register", "--root", str(root)]) == 0
    assert (harness(root) / "registries" / "update-grant.json").is_file()


def test_backup_policy_excludes_projects_keys_and_secrets(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    policy = yaml.safe_load((harness(root) / "registries" / "backup-policy.yml").read_text(encoding="utf-8"))
    includes = policy["backup_policy"]["include"]
    excludes = policy["backup_policy"]["exclude"]
    assert "harness/bin/" in includes
    assert "harness/commands/" in includes
    assert "harness/rules/" in includes
    assert "harness/skills/" in includes
    # AC: backup excludes private keys, env files, secrets, raw customer data, and projects/ by default.
    assert "projects/" in excludes
    assert "harness/security/ssh/*" in excludes
    assert "**/.env" in excludes
    assert any("secret" in pattern for pattern in excludes)


def test_runtime_init_and_dry_run_paths_are_file_backed(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    assert (shared_factory(root) / "00-control-plane" / "runtime-registry.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "integration-registry.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "run-queue.yml").is_file()
    assert (shared_factory(root) / "06-runs-and-logs" / "heartbeats").is_dir()

    assert main(["runtime", "doctor", "--root", str(root)]) == 0
    assert main(["heartbeat", "list", "--root", str(root)]) == 0

    assert main(["heartbeat", "run", "granola_recent_notes_sync", "--root", str(root), "--dry-run"]) == 0
    assert list((shared_factory(root) / "06-runs-and-logs" / "heartbeats").glob("*granola_recent_notes_sync.yml"))
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

    registry = yaml.safe_load((shared_factory(root) / "00-control-plane" / "runtime-registry.yml").read_text())
    integration_registry = yaml.safe_load(
        (shared_factory(root) / "00-control-plane" / "integration-registry.yml").read_text()
    )
    schedules_by_id = {schedule["id"]: schedule for schedule in registry["schedules"]}
    assert schedules_by_id["notion_runtime_tracking"]["enabled"] is True
    assert schedules_by_id["notion_runtime_tracking"]["cadence"] == "daily"
    assert "notion track-runtime" in schedules_by_id["notion_runtime_tracking"]["command"]
    assert 'verified-workspace "Genome\'s Notion"' in schedules_by_id["notion_runtime_tracking"]["command"]
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
    first_by_ref = {item["ref"]: item for item in first["queued"]}
    assert first_by_ref["daily_agentic_os_doctor"]["status"] == "queued"
    assert first_by_ref["daily_agentic_os_doctor"]["created"] is True

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    second = yaml.safe_load(capsys.readouterr().out)
    assert second["queued"] == []
    assert second["skipped"][0]["reason"] == "not due"

    queue_path = shared_factory(root) / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert len(queue["items"]) == len(first["queued"])
    assert queue["run_queue"] == queue["items"]
    item_id = first_by_ref["daily_agentic_os_doctor"]["id"]

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
    dispatched_item = next(item for item in queue_after_apply["items"] if item["id"] == item_id)
    assert dispatched_item["status"] == "done"
    assert dispatched_item["dispatch_log"]


def test_schedule_run_due_batches_queue_load_for_multiple_due_schedules(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0

    queue_load_count = 0
    original_queue = runtime_ops._queue

    def counted_queue(path: Path) -> dict[str, object]:
        nonlocal queue_load_count
        queue_load_count += 1
        return original_queue(path)

    monkeypatch.setattr(runtime_ops, "_queue", counted_queue)

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    result = yaml.safe_load(capsys.readouterr().out)

    assert len(result["queued"]) > 1
    assert queue_load_count == 1


def test_schedule_run_due_catches_up_stale_interval_next_due(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    assert main(
        [
            "schedule",
            "create",
            "stale_interval_schedule",
            "--root",
            str(root),
            "--cadence",
            "every_10_minutes",
            "--command",
            "agentic-os validate --root <root>",
        ]
    ) == 0
    capsys.readouterr()

    registry_path = shared_factory(root) / "00-control-plane" / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for schedule in registry["schedules"]:
        schedule["enabled"] = schedule["id"] == "stale_interval_schedule"
        if schedule["id"] == "stale_interval_schedule":
            schedule["next_due_at"] = "2000-01-01T00:00:00Z"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    assert main(["schedule", "run-due", "--root", str(root), "--apply"]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert [item["ref"] for item in result["queued"]] == ["stale_interval_schedule"]

    registry_after = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    schedule_after = next(schedule for schedule in registry_after["schedules"] if schedule["id"] == "stale_interval_schedule")
    next_due = datetime.fromisoformat(schedule_after["next_due_at"].replace("Z", "+00:00"))
    assert next_due > datetime.now(timezone.utc)


def test_runtime_gates_approval_needed_and_provider_targets(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0

    registry_path = shared_factory(root) / "00-control-plane" / "runtime-registry.yml"
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

    registry_path = shared_factory(root) / "00-control-plane" / "runtime-registry.yml"
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
    parsed = tomllib.loads(content)
    assert parsed["model"] == "gpt-5.4-mini"
    assert parsed["profiles"]["agentic_os_root"]["agentic_os"]["prompt_files"] == [
        "AGENTS.md",
        "PROFILE.md",
        "CLAUDE.md",
        "ROUTER.md",
        "CONTEXT.md",
        "RULES.md",
        "TOOLS.md",
        "MEMORY.md",
    ]
    assert parsed["project_doc_fallback_filenames"][0] == "PROFILE.md"
    for filename in ("AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
        assert (root / filename).is_file()
    assert sidecar_path(root).is_file()
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


def test_validate_allows_root_config_sidecar_after_config_install(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["config", "install", "--root", str(root), "--layer", "agentic_os_root", "--apply"]) == 0

    result = validate_root(root)

    assert result.ok
    assert f"legacy root folder present: {root / 'config'}" not in result.warnings


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

    # Domain-gated servers activate only through the mcp-domain-gating
    # registry of an installed OS root; domain names alone install nothing.
    assert main(["init", "--target", str(root)]) == 0
    ungated_root = root / "work"
    assert main(["config", "install", "--root", str(ungated_root), "--layer", "domain_or_lane", "--apply"]) == 0
    ungated_servers = tomllib.loads((ungated_root / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    assert "sentry" not in ungated_servers
    assert "datadog" not in ungated_servers
    assert "supabase" not in ungated_servers

    gating = root / "harness" / "registries" / "mcp-domain-gating.yml"
    gating.write_text(
        "domains:\n  alpha_ops:\n    - sentry\n    - datadog\n  beta_labs:\n    - supabase\n",
        encoding="utf-8",
    )
    assert main(["domain", "create", "alpha_ops", "--root", str(root)]) == 0
    assert main(["domain", "create", "beta_labs", "--root", str(root)]) == 0

    alpha_root = root / "alpha_ops"
    assert main(["config", "install", "--root", str(alpha_root), "--layer", "domain_or_lane", "--apply"]) == 0
    alpha_servers = tomllib.loads((alpha_root / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    assert {"notion", "genomes_brain", "github", "context_mode", "sentry", "datadog"} <= set(alpha_servers)
    assert "supabase" not in alpha_servers
    assert "composio" not in alpha_servers
    assert "orgo" not in alpha_servers
    assert main(["config", "doctor", "--root", str(alpha_root), "--layer", "domain_or_lane"]) == 0

    beta_root = root / "beta_labs"
    assert main(["config", "install", "--root", str(beta_root), "--layer", "domain_or_lane", "--apply"]) == 0
    beta_servers = tomllib.loads((beta_root / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    assert {"notion", "genomes_brain", "github", "context_mode", "supabase"} <= set(beta_servers)
    assert "sentry" not in beta_servers
    assert "datadog" not in beta_servers
    assert main(["config", "doctor", "--root", str(beta_root), "--layer", "domain_or_lane"]) == 0


def test_hook_sync_points_active_settings_at_installed_harness_hooks(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    codex_hooks = tmp_path / "codex-hooks.json"
    claude_settings = tmp_path / "claude-settings.json"

    assert main(["init", "--target", str(root)]) == 0
    codex_hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear",
                            "hooks": [{"type": "command", "command": "/Users/genome/.codex/hooks/memory-session-start.sh"}],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "/Users/genome/.codex/hooks/memory-stop.sh"},
                                {"type": "command", "command": "/Users/genome/.local/bin/harness-emit-trace codex"},
                            ]
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claude_settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "/Users/genome/.claude/hooks/memory-session-start.sh"}]},
                        {"hooks": [{"type": "command", "command": "\"/Users/genome/.claude/hooks/context-mode-cache-heal.mjs\""}]},
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "/Users/genome/.claude/hooks/memory-stop.sh"},
                                {"type": "command", "command": "/Users/genome/.local/bin/harness-emit-trace claude"},
                            ]
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "hook",
                "doctor",
                "--root",
                str(root),
                "--codex-hooks-path",
                str(codex_hooks),
                "--claude-settings-path",
                str(claude_settings),
            ]
        )
        == 1
    )
    capsys.readouterr()
    assert (
        main(
            [
                "hook",
                "sync",
                "--root",
                str(root),
                "--apply",
                "--codex-hooks-path",
                str(codex_hooks),
                "--claude-settings-path",
                str(claude_settings),
            ]
        )
        == 0
    )
    capsys.readouterr()

    codex_text = codex_hooks.read_text(encoding="utf-8")
    claude_text = claude_settings.read_text(encoding="utf-8")
    assert str(root / "harness" / "hooks" / "memory-session-start.sh") in codex_text
    assert str(root / "harness" / "hooks" / "memory-stop.sh") in claude_text
    assert str(root / "harness" / "hooks" / "context-mode-cache-heal.mjs") in claude_text
    assert ".codex/hooks" not in codex_text
    assert ".claude/hooks" not in claude_text

    assert (
        main(
            [
                "hook",
                "doctor",
                "--root",
                str(root),
                "--codex-hooks-path",
                str(codex_hooks),
                "--claude-settings-path",
                str(claude_settings),
            ]
        )
        == 0
    )


def test_config_doctor_reports_missing_required_otel_and_mcp_keys(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    (root / "config.toml").write_text('model = "local-model"\n', encoding="utf-8")

    assert main(["config", "doctor", "--root", str(root), "--layer", "agentic_os_root"]) == 1


def test_validate_requires_root_rules_and_tools(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    (harness(root) / "RULES.md").unlink()
    (harness(root) / "TOOLS.md").unlink()

    result = validate_root(root)
    assert not result.ok
    assert any("RULES.md" in error for error in result.errors)
    assert any("TOOLS.md" in error for error in result.errors)


def test_config_install_is_idempotent_on_repeated_apply(tmp_path: Path) -> None:
    root = tmp_path / "customer_os"

    assert main(["config", "install", "--root", str(root), "--layer", "customer_os_root", "--apply"]) == 0
    first = (root / "config.toml").read_text(encoding="utf-8")
    first_profile = (root / "PROFILE.md").read_text(encoding="utf-8")
    first_sidecar = sidecar_path(root).read_text(encoding="utf-8")
    assert main(["config", "install", "--root", str(root), "--layer", "customer_os_root", "--apply"]) == 0

    assert (root / "config.toml").read_text(encoding="utf-8") == first
    assert (root / "PROFILE.md").read_text(encoding="utf-8") == first_profile
    assert sidecar_path(root).read_text(encoding="utf-8") == first_sidecar


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
    assert (root / "PROFILE.md").is_file()
    assert sidecar_path(root).is_file()
    assert list(root.glob("config.toml.bak-*"))
    assert main(["config", "doctor", "--root", str(root), "--layer", "domain_or_lane"]) == 0


def test_config_install_layers_create_expected_prompt_sets(tmp_path: Path) -> None:
    cases = {
        "customer_os_root": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "domain_or_lane": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "project": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "workflow_or_task": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
        "automation": ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"),
    }

    for layer, expected_files in cases.items():
        root = tmp_path / layer
        assert main(["config", "install", "--root", str(root), "--layer", layer, "--apply"]) == 0
        config_path = root / "config.toml"
        assert config_path.is_file()
        policy = LAYER_POLICIES[layer]
        parsed_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert parsed_config["model"] == policy.model
        assert parsed_config["model_reasoning_effort"] == policy.model_reasoning_effort
        assert parsed_config["model_verbosity"] == policy.model_verbosity
        assert parsed_config["model_reasoning_summary"] == policy.model_reasoning_summary
        assert parsed_config["project_doc_fallback_filenames"][0] == "PROFILE.md"
        assert policy.profile in parsed_config["profiles"]
        for legacy_profile in policy.legacy_profiles:
            assert legacy_profile in parsed_config["profiles"]
            assert parsed_config["profiles"][legacy_profile]["model"] == policy.model
            assert parsed_config["profiles"][legacy_profile]["model_verbosity"] == policy.model_verbosity
        for filename in ("AGENTS.md", "PROFILE.md", "CLAUDE.md", *expected_files):
            assert (root / filename).is_file()
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        assert "<!-- agentic-os-codex-profile:start -->" in agents
        assert f"Role: {policy.role}" in agents
        assert f"Profile: {policy.profile}" in agents
        profile = (root / "PROFILE.md").read_text(encoding="utf-8")
        assert PROFILE_MANAGED_MARKER in profile
        assert f"Role: {policy.role}" in profile
        assert f"Layer: {policy.layer_token}" in profile
        assert f"Profile: {policy.profile}" in profile
        assert f"Default model: {policy.model}" in profile
        sidecar = yaml.safe_load(sidecar_path(root).read_text(encoding="utf-8"))
        assert sidecar["layer"] == policy.layer_token
        assert sidecar["profile"] == policy.profile
        assert sidecar["legacy_profiles"] == list(policy.legacy_profiles)
        assert sidecar["role"] == policy.role
        assert sidecar["model"] == policy.model
        assert sidecar["model_reasoning_effort"] == policy.model_reasoning_effort
        assert sidecar["model_verbosity"] == policy.model_verbosity
        assert sidecar["model_reasoning_summary"] == policy.model_reasoning_summary
        assert sidecar["prompt_files"] == list(policy.prompt_files)
        assert "PROFILE.md" in sidecar["prompt_files"]


def test_config_install_blocks_unmanaged_and_changed_managed_profile_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    profile = root / "PROFILE.md"
    sidecar = sidecar_path(root)
    sidecar.parent.mkdir()
    profile.write_text("# Local profile\n", encoding="utf-8")
    sidecar.write_text("role: local\n", encoding="utf-8")

    assert main(["config", "install", "--root", str(root), "--layer", "project", "--apply"]) == 2
    assert profile.read_text(encoding="utf-8") == "# Local profile\n"
    assert sidecar.read_text(encoding="utf-8") == "role: local\n"

    assert main(["config", "install", "--root", str(root), "--layer", "project", "--apply", "--confirm-conflicts"]) == 0
    assert "Profile: project_orchestrator" in profile.read_text(encoding="utf-8")
    assert yaml.safe_load(sidecar.read_text(encoding="utf-8"))["profile"] == "project_orchestrator"

    profile.write_text(profile.read_text(encoding="utf-8") + "\nLocal managed edit.\n", encoding="utf-8")
    sidecar_payload = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    sidecar_payload["role_summary"] = "local managed edit"
    sidecar.write_text(yaml.safe_dump(sidecar_payload, sort_keys=False), encoding="utf-8")

    assert main(["config", "install", "--root", str(root), "--layer", "project", "--apply"]) == 2
    assert "Local managed edit." in profile.read_text(encoding="utf-8")
    assert yaml.safe_load(sidecar.read_text(encoding="utf-8"))["role_summary"] == "local managed edit"


def test_config_install_tree_covers_domain_project_workflow_and_automation_layers(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(["config", "install-tree", "--root", str(root), "--dry-run"]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    targets = {(target["root"], target["layer"]) for target in result["targets"]}

    assert (str(harness(root)), "agentic_os_root") in targets
    assert (str(root / "los"), "domain_or_lane") in targets
    assert (str(root / "los" / "02-projects" / "losmon_replacement"), "project") in targets
    assert (str(root / "los" / "03-workflows" / "engineering" / "feature_dev"), "workflow_or_task") in targets
    assert (str(root / "los" / "04-automations" / "support" / "production_thread_intake"), "automation") in targets


def test_config_install_tree_requires_installed_root(tmp_path: Path) -> None:
    root = tmp_path / "missing_os"

    assert main(["config", "install-tree", "--root", str(root), "--dry-run"]) == 2


def test_config_install_tree_apply_writes_and_doctors_discovered_layers(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert main(["workflow", "create", "los", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "los", "support", "production_thread_intake", "--root", str(root)]) == 0
    capsys.readouterr()

    targets = {
        harness(root): "agentic_os_root",
        root / "los": "domain_or_lane",
        root / "los" / "02-projects" / "losmon_replacement": "project",
        root / "los" / "03-workflows" / "engineering" / "feature_dev": "workflow_or_task",
        root / "los" / "04-automations" / "support" / "production_thread_intake": "automation",
    }
    for target in targets:
        (target / "config.toml").unlink()
    assert all(not (target / "config.toml").exists() for target in targets)

    assert main(["config", "install-tree", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()

    for target, layer in targets.items():
        config = target / "config.toml"
        assert config.is_file()
        assert f'layer = "{layer}"' in config.read_text(encoding="utf-8")
        assert (target / "PROFILE.md").is_file()
        assert sidecar_path(target).is_file()
        assert yaml.safe_load(sidecar_path(target).read_text(encoding="utf-8"))["profile"] == LAYER_POLICIES[layer].profile
        assert main(["config", "doctor", "--root", str(target), "--layer", layer]) == 0


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
    assert "programs: 00-programs" in domain_config
    assert "context_loading:" in domain_config
    assert (domain_root / "00-programs" / "README.md").is_file()
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
    assert (workflow_root / "config.toml").is_file()
    assert (workflow_root / "AGENTS.md").is_file()

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
    assert (automation_root / "config.toml").is_file()
    assert (automation_root / "AGENTS.md").is_file()

    assert main(["run-log", "create", "los", "feature_dev", "--root", str(root)]) == 0
    run_logs = list((root / "los" / "06-runs-and-logs" / "runs").glob("*-los-feature_dev/run-log.md"))
    assert len(run_logs) == 1
    assert validate_root(root).ok
    assert main(["validate", "--root", str(root)]) == 0


def test_program_and_instance_program_scaffolds(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["program", "create", "os_program_lifecycle", "--root", str(root)]) == 0
    program_root = root / "harness" / "shared_factory" / "00-programs" / "os_program_lifecycle"
    assert (program_root / "program.md").is_file()
    assert (program_root / "components.yml").is_file()
    assert (program_root / "crud.md").is_file()
    assert (program_root / "documentation.md").is_file()
    assert (program_root / "config.toml").is_file()
    components = yaml.safe_load((program_root / "components.yml").read_text(encoding="utf-8"))
    assert components["type"] == "OSProgram"
    assert components["documentation_required"] is True

    assert main(["instance-program", "create", "los", "team_pr_sync", "--root", str(root)]) == 0
    instance_root = root / "los" / "00-programs" / "team_pr_sync"
    assert (instance_root / "AGENTS.md").is_file()
    assert (instance_root / "program.md").is_file()
    assert (instance_root / "components.yml").is_file()
    assert (instance_root / "context-pack.md").is_file()
    assert (instance_root / "runbook.md").is_file()
    assert (instance_root / "tests.md").is_file()
    assert (instance_root / "artifacts").is_dir()
    instance_components = yaml.safe_load((instance_root / "components.yml").read_text(encoding="utf-8"))
    assert instance_components["type"] == "InstanceOSProgram"
    assert "Program Status" in (root / "los" / "00-control-plane" / "state-index.md").read_text(encoding="utf-8")
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
    manual_readme = shared_factory(root) / "05-knowledge" / "operating-manual" / "README.md"
    command_file = shared_factory(root) / "05-knowledge" / "commands" / "os-sync-notion.md"
    playbook_command = shared_factory(root) / "05-knowledge" / "commands" / "os-client-automation-brief.md"
    playbook_skill = shared_factory(root) / "05-knowledge" / "skills" / "client-automation-brief" / "SKILL.md"
    watch_command = shared_factory(root) / "05-knowledge" / "commands" / "os-watch-source.md"
    watch_template = shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "watch-source.yml"
    event_command = shared_factory(root) / "05-knowledge" / "commands" / "os-event.md"
    event_template = shared_factory(root) / "05-knowledge" / "templates" / "runtime" / "event-envelope.yml"
    plans_root = shared_factory(root) / "05-knowledge" / "plans"
    planning_template = shared_factory(root) / "05-knowledge" / "templates" / "planning" / "feature-spec.md"
    domain_context_template = shared_factory(root) / "05-knowledge" / "templates" / "domain" / "context.md"
    convention_reference = shared_factory(root) / "05-knowledge" / "references" / "os-conventions.md"
    manual_readme.write_text("# local edit\n", encoding="utf-8")
    command_file.unlink()
    playbook_command.unlink()
    playbook_skill.unlink()
    watch_command.unlink()
    watch_template.unlink()
    event_command.unlink()
    event_template.unlink()
    planning_template.unlink()
    domain_context_template.unlink()
    convention_reference.unlink()

    assert main(["docs", "update", "--root", str(root)]) == 0

    content = manual_readme.read_text(encoding="utf-8")
    assert content == "# local edit\n"
    assert command_file.is_file()
    assert playbook_command.is_file()
    assert playbook_skill.is_file()
    assert watch_command.is_file()
    assert watch_template.is_file()
    assert event_command.is_file()
    assert event_template.is_file()
    assert (plans_root / "README.md").is_file()
    assert (plans_root / "23-doc-config-system.md").is_file()
    assert planning_template.is_file()
    assert domain_context_template.is_file()
    assert convention_reference.is_file()
    assert (shared_factory(root) / "05-knowledge" / "commands" / "os-update.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "operating-manual" / "00-start-here" / "update-contract.md"
    ).is_file()
    assert (shared_factory(root) / "05-knowledge" / "skills" / "os-doctor" / "SKILL.md").is_file()
    assert main(["validate", "--root", str(root)]) == 0
    assert main(["docs", "update", "--root", str(root)]) == 0
    assert manual_readme.read_text(encoding="utf-8") == "# local edit\n"
    assert (plans_root / "README.md").is_file()
    assert (plans_root / "23-doc-config-system.md").is_file()


def test_workflow_create_bootstraps_arbitrary_domain_name(tmp_path: Path) -> None:
    # Domain names are pure data: any slug bootstraps its own domain and the
    # tree still validates. No built-in alias map rewrites operator names.
    root = tmp_path / "agentic_os"

    assert main(["workflow", "create", "lender_ops", "support", "lender_intake", "--root", str(root)]) == 0

    assert (root / "lender_ops" / "03-workflows" / "support" / "lender_intake" / "workflow.md").is_file()
    assert (root / "lender_ops" / "domain.yml").is_file()
    assert validate_root(root).ok


def test_project_create_creates_project_state_and_indexes(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()

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
                str(repo),
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
    assert (project_root / "config").is_dir()
    assert (project_root / "SPECS" / "README.md").is_file()
    assert (project_root / "worklogs" / "README.md").is_file()
    assert (project_root / "ideas" / "raw-ideas.md").is_file()
    assert (project_root / "work-items" / "01-intake").is_dir()
    assert (project_root / "work-items" / "02-active").is_dir()
    assert (project_root / "work-items" / "03-complete").is_dir()
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert (project_root / "worktrees" / "index.yml").is_file()
    for filename in PROJECT_CONFIG_FILES:
        assert (project_root / "config" / filename).is_file()
    assert (project_root / "config.toml").is_file()
    assert (project_root / "AGENTS.md").is_file()
    assert (project_root / "src").is_symlink()
    assert (project_root / "src").resolve() == repo.resolve()
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "config/*.yml" in agents
    assert "worktrees/index.yml" in agents
    output_artifacts = yaml.safe_load((project_root / "config" / "output-artifacts.yml").read_text(encoding="utf-8"))
    assert output_artifacts["output_artifacts"]["feature_root"] == "work-items/02-active/{ticket_or_slug}/artifacts"
    assert output_artifacts["output_artifacts"]["spec_root"] == "SPECS/{ticket_or_slug}"
    assert output_artifacts["output_artifacts"]["worklog_root"] == "worklogs/{ticket_or_slug}"
    work_lifecycle = yaml.safe_load((project_root / "config" / "work-lifecycle.yml").read_text(encoding="utf-8"))
    assert work_lifecycle["work_lifecycle"]["lanes"] == {
        "intake": "01-intake",
        "active": "02-active",
        "complete": "03-complete",
    }
    assert f"repo: {repo}" in (project_root / "project.yml").read_text(encoding="utf-8")
    assert f"| Repo | {repo} |" in (project_root / "source-map.md").read_text(encoding="utf-8")
    assert "`losmon_replacement`" in (root / "los" / "02-projects" / "README.md").read_text(encoding="utf-8")
    assert "`losmon_replacement`" in (root / "los" / "00-control-plane" / "active-work.md").read_text(
        encoding="utf-8"
    )
    assert validate_root(root).ok


def test_project_create_does_not_symlink_remote_repo_urls(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert (
        main(
            [
                "project",
                "create",
                "los",
                "remote_project",
                "--root",
                str(root),
                "--repo",
                "https://github.com/example/repo.git",
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "remote_project"
    assert not (project_root / "src").exists()
    assert validate_root(root).ok


def test_project_link_source_adds_src_and_repo_metadata(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["project", "create", "los", "linked_project", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "link-source",
                "los",
                "linked_project",
                "--root",
                str(root),
                "--repo",
                str(repo),
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "linked_project"
    assert (project_root / "src").is_symlink()
    assert (project_root / "src").resolve() == repo.resolve()
    assert f"repo: {repo}" in (project_root / "project.yml").read_text(encoding="utf-8")
    assert f"| Repo | {repo} |" in (project_root / "source-map.md").read_text(encoding="utf-8")
    assert validate_root(root).ok


def test_project_src_alias_uses_existing_repo_metadata(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["project", "create", "los", "linked_project", "--root", str(root), "--repo", str(repo)]) == 0
    project_root = root / "los" / "02-projects" / "linked_project"
    (project_root / "src").unlink()

    assert main(["project", "src", "los", "linked_project", "--root", str(root)]) == 0

    assert (project_root / "src").is_symlink()
    assert (project_root / "src").resolve() == repo.resolve()
    assert validate_root(root).ok


def test_project_link_source_rejects_remote_repo_urls(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "remote_project", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "link-source",
                "los",
                "remote_project",
                "--root",
                str(root),
                "--repo",
                "https://github.com/example/repo.git",
            ]
        )
        == 2
    )

    assert not (root / "los" / "02-projects" / "remote_project" / "src").exists()


def test_project_onboard_repairs_project_config_ideas_and_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "repairable_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "repairable_project"
    (project_root / "config" / "tools.yml").unlink()
    (project_root / "ideas" / "raw-ideas.md").unlink()
    (project_root / "worktrees" / "index.yml").unlink()

    assert main(["project", "onboard", "los", "repairable_project", "--root", str(root)]) == 0

    assert (project_root / "config" / "tools.yml").is_file()
    assert (project_root / "ideas" / "raw-ideas.md").is_file()
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert (project_root / "worktrees" / "index.yml").is_file()
    assert validate_root(root).ok


def test_project_worktree_add_registers_visible_link_and_routes_from_target(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    worktree = tmp_path / "launch_feature"
    nested = worktree / "app"
    nested.mkdir(parents=True)

    assert main(["project", "create", "los", "linked_project", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "worktree",
                "add",
                "los",
                "linked_project",
                "launch_feature",
                "--path",
                str(worktree),
                "--root",
                str(root),
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "linked_project"
    link_path = project_root / "worktrees" / "launch_feature"
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert link_path.is_symlink()
    assert link_path.resolve() == worktree.resolve()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"] == [
        {
            "id": "launch_feature",
            "path": str(worktree.resolve()),
            "link": "worktrees/launch_feature",
            "status": "active",
            "link_policy": "symlink_to_external_worktree",
        }
    ]
    config = yaml.safe_load((project_root / "config" / "worktrees.yml").read_text(encoding="utf-8"))
    assert config["worktrees"]["registered"] == index["worktrees"]
    assert config["worktrees"]["link_policy"] == "symlink_to_external_worktree"
    packet = context_from_here(root, cwd=nested)
    assert packet.domain == "los"
    assert packet.object_type == "project"
    assert packet.target_path == project_root.resolve()
    assert validate_root(root).ok


def test_context_build_project_infers_domain_from_project_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "context_project", "--root", str(root)]) == 0
    capsys.readouterr()
    project_root = root / "los" / "02-projects" / "context_project"

    monkeypatch.chdir(project_root)
    assert main(["context", "build", "--project", "context_project", "--root", str(root)]) == 0

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"] == str(project_root)


def test_context_build_project_infers_domain_from_unique_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "unique_context_project", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(["context", "build", "--project", "unique_context_project", "--root", str(root)]) == 0

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"


def test_context_build_selects_legacy_work_item_markdown_by_ticket(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "legacy_packet_project", "--root", str(root)]) == 0
    capsys.readouterr()
    project_root = root / "los" / "02-projects" / "legacy_packet_project"
    work_item_root = project_root / "work-items" / "02-active" / "001_flywl_1404_login_button"
    work_item_root.mkdir(parents=True)
    (work_item_root / "work-item.md").write_text(
        """---
id: 001_flywl_1404_login_button
ticket: FLYWL-1404
title: Add login button
state: validating
lane: 02-active
---

# FLYWL-1404
""",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "context",
                "build",
                "--domain",
                "los",
                "--project",
                "legacy_packet_project",
                "--work-item",
                "FLYWL-1404",
                "--root",
                str(root),
            ]
        )
        == 0
    )

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["object_type"] == "work_item"
    assert packet["target_path"] == str(work_item_root)
    assert packet["lifecycle"]["metadata"] == str(work_item_root / "work-item.md")
    assert packet["lifecycle"]["state"] == "validating"


def test_project_work_item_repair_backfills_legacy_packet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "legacy_packet_project", "--root", str(root)]) == 0
    capsys.readouterr()
    project_root = root / "los" / "02-projects" / "legacy_packet_project"
    work_item_root = project_root / "work-items" / "02-active" / "001_flywl_1404_login_button"
    work_item_root.mkdir(parents=True)
    (work_item_root / "work-item.md").write_text(
        """---
id: 001_flywl_1404_login_button
ticket: FLYWL-1404
title: Add login button
state: validating
lane: 02-active
---

# FLYWL-1404
""",
        encoding="utf-8",
    )

    drift = validate_root(root)
    assert drift.ok
    assert any("logs/conversations" in warning for warning in drift.warnings)
    assert any("SPEC.md" in warning for warning in drift.warnings)

    assert (
        main(
            [
                "project",
                "work-item",
                "repair",
                "los",
                "legacy_packet_project",
                "--work-item",
                "FLYWL-1404",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (work_item_root / "logs" / "conversations").is_dir()
    for filename in ("work.yml", "SPEC.md", "PLAN.md", "HOLDOUT_QA.md", "WORKLOG.md", "NEXT.md"):
        assert (work_item_root / filename).is_file()
    metadata = yaml.safe_load((work_item_root / "work.yml").read_text(encoding="utf-8"))
    assert metadata["ticket"] == "FLYWL-1404"
    assert metadata["state"] == "validating"
    assert metadata["lifecycle"]["required_files"] == ["SPEC.md", "PLAN.md", "HOLDOUT_QA.md", "WORKLOG.md", "NEXT.md"]

    fixed = validate_root(root)
    assert fixed.ok, fixed.errors


def test_validate_accepts_in_place_project_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0

    project_root = root / "los" / "02-projects" / "inplace_project"
    checkout = project_root / "worktrees" / "feature_x"
    (checkout / "app").mkdir(parents=True)
    # a real checkout has a .git pointer and may contain fixtures that are not
    # valid JSON/YAML — the OS control-file lint must not descend into it
    (checkout / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature_x\n", encoding="utf-8")
    (checkout / "app" / "broken.json").write_text("{not json", encoding="utf-8")
    (checkout / "app" / "broken.yml").write_text(":\n\t- {", encoding="utf-8")
    index_path = project_root / "worktrees" / "index.yml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    index["worktrees"] = [
        {
            "id": "feature_x",
            "path": str(checkout.resolve()),
            "link": "worktrees/feature_x",
            "status": "active",
        }
    ]
    index_path.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")

    result = validate_root(root)
    assert result.ok, result.errors

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    index["worktrees"][0]["path"] = str(elsewhere.resolve())
    index_path.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    mismatch = validate_root(root)
    assert not mismatch.ok
    assert any("does not match entry path" in error for error in mismatch.errors)


def test_project_worktree_add_in_place_registers_without_symlink(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    checkout = project_root / "worktrees" / "feature_x"
    checkout.mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature_x\n", encoding="utf-8")

    assert (
        main(
            [
                "project",
                "worktree",
                "add",
                "los",
                "inplace_project",
                "feature_x",
                "--path",
                str(checkout),
                "--root",
                str(root),
            ]
        )
        == 0
    )

    assert checkout.is_dir()
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert not checkout.is_symlink()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"] == [
        {
            "id": "feature_x",
            "path": str(checkout.resolve()),
            "link": "worktrees/feature_x",
            "status": "active",
            "link_policy": "in_place_worktree",
        }
    ]
    config = yaml.safe_load((project_root / "config" / "worktrees.yml").read_text(encoding="utf-8"))
    assert config["worktrees"]["link_policy"] == "in_place_worktree"
    assert config["worktrees"]["registered"] == index["worktrees"]
    assert validate_root(root).ok


def test_project_worktree_add_in_place_rejects_paths_not_at_worktree_name(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    nested = project_root / "worktrees" / "feature_x" / "app"
    nested.mkdir(parents=True)
    add = ["project", "worktree", "add", "los", "inplace_project"]

    assert main([*add, "feature_x", "--path", str(nested), "--root", str(root)]) == 2
    assert main([*add, "feature_y", "--path", str(nested.parent), "--root", str(root)]) == 2
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"] == []


def test_project_worktree_mixed_policies_keep_symlink_config_default(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    external = tmp_path / "external_feature"
    external.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    checkout = project_root / "worktrees" / "feature_x"
    checkout.mkdir(parents=True)
    add = ["project", "worktree", "add", "los", "inplace_project"]

    assert main([*add, "feature_x", "--path", str(checkout), "--root", str(root)]) == 0
    assert main([*add, "external_feature", "--path", str(external), "--root", str(root)]) == 0

    config = yaml.safe_load((project_root / "config" / "worktrees.yml").read_text(encoding="utf-8"))
    assert config["worktrees"]["link_policy"] == "symlink_to_external_worktree"
    policies = {entry["id"]: entry["link_policy"] for entry in config["worktrees"]["registered"]}
    assert policies == {
        "feature_x": "in_place_worktree",
        "external_feature": "symlink_to_external_worktree",
    }
    assert validate_root(root).ok


def _fake_worktree_git_runner(
    calls: list[list[str]],
    destination: Path,
    *,
    branch_exists: bool = False,
    fail_add: bool = False,
):
    """Fake git runner for worktree create: records calls and simulates checkout creation."""

    def _runner(args: list[str], *, timeout: int = 60):
        calls.append(list(args))
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0 if branch_exists else 1, stdout="", stderr="")
        if fail_add:
            return SimpleNamespace(returncode=128, stdout="", stderr="fatal: bad object HEAD")
        destination.mkdir(parents=True, exist_ok=True)
        (destination / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature_x\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return _runner


def test_project_worktree_create_checks_out_new_branch_in_place(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    destination = project_root / "worktrees" / "feature_x"
    calls: list[list[str]] = []

    create_project_worktree(
        root,
        "los",
        "inplace_project",
        "feature_x",
        repo=repo,
        branch="feature-x",
        runner=_fake_worktree_git_runner(calls, destination),
    )

    assert calls[0] == ["git", "-C", str(repo.resolve()), "rev-parse", "--verify", "--quiet", "refs/heads/feature-x"]
    assert calls[1] == ["git", "-C", str(repo.resolve()), "worktree", "add", "-b", "feature-x", str(destination)]
    assert destination.is_dir()
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert not destination.is_symlink()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"][0]["link_policy"] == "in_place_worktree"
    assert validate_root(root).ok


def test_project_worktree_create_reuses_existing_branch(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    destination = root / "los" / "02-projects" / "inplace_project" / "worktrees" / "feature_x"
    calls: list[list[str]] = []

    create_project_worktree(
        root,
        "los",
        "inplace_project",
        "feature_x",
        repo=repo,
        branch="feature-x",
        runner=_fake_worktree_git_runner(calls, destination, branch_exists=True),
    )

    assert calls[1] == ["git", "-C", str(repo.resolve()), "worktree", "add", str(destination), "feature-x"]


def test_project_worktree_create_surfaces_git_failures(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    destination = project_root / "worktrees" / "feature_x"
    calls: list[list[str]] = []

    with pytest.raises(ValueError, match="git worktree add failed"):
        create_project_worktree(
            root,
            "los",
            "inplace_project",
            "feature_x",
            repo=repo,
            branch="feature-x",
            runner=_fake_worktree_git_runner(calls, destination, fail_add=True),
        )

    assert not destination.exists()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"] == []


def test_project_worktree_create_rejects_existing_destination(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    destination = root / "los" / "02-projects" / "inplace_project" / "worktrees" / "feature_x"
    destination.mkdir(parents=True)

    with pytest.raises(ValueError, match="already exists"):
        create_project_worktree(
            root,
            "los",
            "inplace_project",
            "feature_x",
            repo=repo,
            branch="feature-x",
            runner=_fake_worktree_git_runner([], destination),
        )


def test_project_worktree_create_cli_runs_real_git(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        cwd=repo,
        check=True,
    )
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0

    assert (
        main(
            [
                "project",
                "worktree",
                "create",
                "los",
                "inplace_project",
                "--repo",
                str(repo),
                "--branch",
                "feat/63-demo",
                "--root",
                str(root),
            ]
        )
        == 0
    )

    project_root = root / "los" / "02-projects" / "inplace_project"
    checkout = project_root / "worktrees" / "feat-63-demo"
    assert checkout.is_dir()
    assert (project_root / "worktrees" / ".metadata_never_index").is_file()
    assert not checkout.is_symlink()
    assert (checkout / ".git").is_file()
    branch = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "feat/63-demo"
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"][0]["id"] == "feat-63-demo"
    config = yaml.safe_load((project_root / "config" / "worktrees.yml").read_text(encoding="utf-8"))
    assert config["worktrees"]["link_policy"] == "in_place_worktree"
    result = validate_root(root)
    assert result.ok, result.errors


def test_project_worktree_create_derives_name_from_branch(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    destination = project_root / "worktrees" / "feat-63-remote-ssh"
    calls: list[list[str]] = []

    create_project_worktree(
        root,
        "los",
        "inplace_project",
        repo=repo,
        branch="feat/63-remote-ssh",
        runner=_fake_worktree_git_runner(calls, destination),
    )

    assert calls[1] == ["git", "-C", str(repo.resolve()), "worktree", "add", "-b", "feat/63-remote-ssh", str(destination)]
    assert destination.is_dir()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"][0]["id"] == "feat-63-remote-ssh"
    assert index["worktrees"][0]["link"] == "worktrees/feat-63-remote-ssh"
    assert validate_root(root).ok


def test_project_worktree_add_accepts_branch_like_names(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    external = tmp_path / "external_feature"
    external.mkdir()
    assert main(["project", "create", "los", "inplace_project", "--root", str(root)]) == 0
    add = ["project", "worktree", "add", "los", "inplace_project"]

    assert main([*add, "feat-63-remote-ssh", "--path", str(external), "--root", str(root)]) == 0
    project_root = root / "los" / "02-projects" / "inplace_project"
    assert (project_root / "worktrees" / "feat-63-remote-ssh").is_symlink()
    index = yaml.safe_load((project_root / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert index["worktrees"][0]["id"] == "feat-63-remote-ssh"
    assert validate_root(root).ok

    # slashes and uppercase still rejected — a worktree name is a single directory
    assert main([*add, "feat/63-remote-ssh", "--path", str(external), "--root", str(root)]) == 2
    assert main([*add, "Feat-63", "--path", str(external), "--root", str(root)]) == 2


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


def test_project_create_rejects_invalid_names_and_accepts_any_domain(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "work", "bad-name", "--root", str(root)]) == 2
    assert main(["project", "create", "lender_ops", "lender_portal", "--root", str(root)]) == 0
    assert (root / "lender_ops" / "02-projects" / "lender_portal" / "project.yml").is_file()


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


def test_route_matches_project_shorthand_by_tokens(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "los_app_los_django", "--root", str(root)]) == 0
    assert main(["route", "i have an idea for los django", "--root", str(root)]) == 0

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "project"
    assert packet["target_path"].endswith("los/02-projects/los_app_los_django")


def test_idea_capture_routes_to_domain_inbox_even_from_linked_project_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "los_app"
    repo.mkdir()

    assert main(["project", "create", "los", "los_app", "--repo", str(repo), "--root", str(root)]) == 0
    monkeypatch.chdir(repo)
    assert (
        main(
            [
                "here",
                "route",
                "I want to add an idea to LOS. Monitor all recent merged pull requests and build a developer newsletter.",
                "--root",
                str(root),
            ]
        )
        == 0
    )

    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["domain"] == "los"
    assert packet["object_type"] == "inbox"
    assert packet["target_path"].endswith("los/01-inbox")
    assert not packet["target_path"].endswith("02-projects/los_app")
    assert str(root / "los" / "01-inbox" / "raw-ideas.md") in packet["sources_to_load"]
    assert str(root / "los" / "00-control-plane" / "state-index.md") in packet["sources_to_load"]
    assert str(root / "los" / "MEMORY.md") in packet["sources_to_load"]


def test_plan_capture_updates_inbox_control_plane_and_memory(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    title = "Developer Newsletter"
    summary = "Monitor recent merged pull requests and build a developer newsletter."

    assert main(["init", "--target", str(root)]) == 0
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
                "work",
                "--title",
                title,
                "--summary",
                summary,
            ]
        )
        == 0
    )

    result = yaml.safe_load(capsys.readouterr().out)
    assert result["target"].endswith("work/01-inbox/raw-ideas.md")
    raw_ideas = (root / "work" / "01-inbox" / "raw-ideas.md").read_text(encoding="utf-8")
    triage = (root / "work" / "01-inbox" / "triage.md").read_text(encoding="utf-8")
    state_index = (root / "work" / "00-control-plane" / "state-index.md").read_text(encoding="utf-8")
    active_work = (root / "work" / "00-control-plane" / "active-work.md").read_text(encoding="utf-8")
    memory = (root / "work" / "MEMORY.md").read_text(encoding="utf-8")
    assert title in raw_ideas
    assert summary in raw_ideas
    assert title in triage
    assert title in state_index
    assert "`captured`" in state_index
    assert title in active_work
    assert f"Captured domain signal `{title}`" in memory


def test_plan_capture_classifies_research_and_project_bug_activity(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root)]) == 0
    assert main(["project", "create", "los", "los_app", "--root", str(root)]) == 0
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
                "Research PR Signals",
                "--summary",
                "Research ongoing signals from recent merged pull requests.",
            ]
        )
        == 0
    )
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
                "--project",
                "los_app",
                "--title",
                "Fix Routing Bug",
                "--summary",
                "Bug fix for linked project routing.",
            ]
        )
        == 0
    )

    capsys.readouterr()
    state_index = (root / "los" / "00-control-plane" / "state-index.md").read_text(encoding="utf-8")
    memory = (root / "los" / "MEMORY.md").read_text(encoding="utf-8")
    assert "| Research PR Signals | `research` |" in state_index
    assert "| `los_app` bugfix: Fix Routing Bug | `bugfix` |" in state_index
    assert "Captured project signal `Fix Routing Bug`" in memory


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
    assert str(harness(root) / "ROUTER.md") in packet["sources_to_load"]
    assert str(shared_factory(root) / "05-knowledge" / "references" / "tool-index.md") in packet[
        "sources_to_load"
    ]
    assert str(shared_factory(root) / "05-knowledge" / "references" / "source-priority.md") in packet[
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
    # A completely unrecognised request still exits 2 (hard refusal).
    assert main(["route", "Do the thing", "--root", str(root)]) == 2
    # A multi-domain match returns a low-confidence SUGGESTION packet (exit 0)
    # rather than a hard refusal — F-014: route best candidate as advisory output.
    assert main(["route", "Compare los and personal work", "--root", str(root)]) == 0


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

## Invocation Contract

| Field | Value |
| --- | --- |
| Trigger | `manual support queue review` |
| Registry Entry | `support-runbook` |
| Owner | `OS Owner` |

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
    assert (root / "PROFILE.md").is_file()
    assert sidecar_path(root).is_file()
    assert (root / "customer.yml").is_file()
    assert (root / "support" / "domain.yml").is_file()
    assert (root / "support" / "03-workflows" / "support" / "intake_triage" / "workflow.md").is_file()
    assert (root / "support" / "04-automations" / "support" / "thread_intake" / "automation.md").is_file()
    assert not (root / "clarks_consulting").exists()
    assert not (root / "los").exists()

    disallowed = ("genome", "clark", "clarks_consulting", "los", "lenders")
    generated_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in customer_text_files(root))
    assert not any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", generated_text) for term in disallowed)
    customer_role_artifacts = [
        root / "config.toml",
        root / "PROFILE.md",
        sidecar_path(root),
        root / "support" / "config.toml",
        root / "support" / "PROFILE.md",
        sidecar_path(root / "support"),
        root / "support" / "03-workflows" / "support" / "intake_triage" / "config.toml",
        root / "support" / "03-workflows" / "support" / "intake_triage" / "PROFILE.md",
        sidecar_path(root / "support" / "03-workflows" / "support" / "intake_triage"),
        root / "support" / "04-automations" / "support" / "thread_intake" / "config.toml",
        root / "support" / "04-automations" / "support" / "thread_intake" / "PROFILE.md",
        sidecar_path(root / "support" / "04-automations" / "support" / "thread_intake"),
    ]
    assert all(path.is_file() for path in customer_role_artifacts)
    role_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in customer_role_artifacts)
    assert "project_orchestrator" not in role_text
    assert "genome's notion" not in role_text
    assert "/users/genome" not in role_text
    assert "genomes_notion_pat" not in role_text
    root_sidecar = yaml.safe_load(sidecar_path(root).read_text(encoding="utf-8"))
    assert root_sidecar["role"] == "customer_navigator"
    assert root_sidecar["model"] == "gpt-5.4-mini"
    assert root_sidecar["model_verbosity"] == "low"
    assert root_sidecar["model_reasoning_summary"] == "concise"
    automation_sidecar = yaml.safe_load(
        sidecar_path(root / "support" / "04-automations" / "support" / "thread_intake").read_text(encoding="utf-8")
    )
    assert automation_sidecar["profile"] == "automation_guard"
    assert automation_sidecar["model"] == "gpt-5.5"

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
    router = (harness(root) / "ROUTER.md").read_text(encoding="utf-8")
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
    assert (shared_factory(root) / "05-knowledge" / "templates" / "room" / "context.md").is_file()
    assert (shared_factory(root) / "05-knowledge" / "templates" / "stage" / "stage-context.md").is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "reference" / "naming-conventions.md"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "profile" / "customer-os-profile.yml"
    ).is_file()
    assert (
        shared_factory(root) / "05-knowledge" / "templates" / "customer" / "automation-fit-matrix.md"
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

    knowledge_root = shared_factory(root) / "05-knowledge"
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
    assert (shared_factory(root) / "00-control-plane" / "watch-sources.yml").is_file()
    assert (shared_factory(root) / "00-control-plane" / "watch-cursors.yml").is_file()

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
    watch_file = shared_factory(root) / "00-control-plane" / "watch-sources.yml"
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

    systems_file = shared_factory(root) / "00-control-plane" / "connected-systems.yml"
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
    watch_file = shared_factory(root) / "00-control-plane" / "watch-sources.yml"
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
    watch_file = shared_factory(root) / "00-control-plane" / "watch-sources.yml"
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
    watch_file = shared_factory(root) / "00-control-plane" / "watch-sources.yml"
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

    queue = yaml.safe_load((shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
    assert queue["run_queue"][0]["kind"] == "source_trigger"
    assert queue["run_queue"][0]["work_type"] == "source_review"

    assert main(["watch-source", "poll", "local_dropbox", "--root", str(root), "--apply"]) == 0
    repeated = yaml.safe_load(capsys.readouterr().out)
    enqueue = next(action for action in repeated["trigger_actions"] if action["action"] == "enqueue")
    assert enqueue["status"] == "skipped"
    assert len(list((shared_factory(root) / "06-runs-and-logs" / "source-events").glob("*.yml"))) == 1


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
    assert (shared_factory(root) / "06-runs-and-logs" / "events" / "event-ledger-index.md").is_file()

    chain_rules = shared_factory(root) / "00-control-plane" / "chain-rules.yml"
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
    assert not (shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(
        encoding="utf-8"
    ).count("documentation_update")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["actions"][0]["results"][0]["status"] == "queued"
    run_queue = yaml.safe_load((shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
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

    chain_rules = shared_factory(root) / "00-control-plane" / "chain-rules.yml"
    data = yaml.safe_load(chain_rules.read_text(encoding="utf-8"))
    data["chain_rules"][0]["enabled"] = True
    data["chain_rules"][0]["when"]["filters"] = {}
    chain_rules.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert main(["event", "process-due", "--root", str(root), "--apply"]) == 0
    processed = yaml.safe_load(capsys.readouterr().out)
    statuses = [action["results"][0]["status"] for action in processed["actions"]]
    assert statuses == ["queued", "skipped"]
    assert processed["actions"][1]["results"][0]["reason"] == "idempotency key already processed"

    run_queue = yaml.safe_load((shared_factory(root) / "00-control-plane" / "run-queue.yml").read_text(encoding="utf-8"))
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

    chain_rules = shared_factory(root) / "00-control-plane" / "chain-rules.yml"
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
    chain_rules = shared_factory(root) / "00-control-plane" / "chain-rules.yml"
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
    assert list((shared_factory(root) / "06-runs-and-logs" / "events" / "dead-letter").glob("*.yml"))

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
    missing_doc = shared_factory(root) / "05-knowledge" / "templates" / "customer" / "client-automation-brief.md"
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
                "Capture runtime telemetry into run logs.",
            ]
        )
        == 0
    )
    result = yaml.safe_load(capsys.readouterr().out)
    os_plan = Path(result["target"])
    assert os_plan.is_file()
    assert "Capture runtime telemetry into run logs." in os_plan.read_text(encoding="utf-8")
    assert "future-ideas/telemetry-adapter.md" in (
        shared_factory(root) / "05-knowledge" / "plans" / "README.md"
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
    capsys.readouterr()

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
    result = yaml.safe_load(capsys.readouterr().out)
    project_status = (root / "los" / "02-projects" / "losmon_replacement" / "status.md").read_text(
        encoding="utf-8"
    )
    assert "Customer-safe deploy brief" in project_status
    work_item = (
        root
        / "los"
        / "02-projects"
        / "losmon_replacement"
        / "work-items"
        / "01-intake"
        / "001_customer_safe_deploy_brief.md"
    )
    assert work_item.is_file()
    assert result["work_item"] == str(work_item)


def test_project_work_item_create_and_route_lifecycle_context(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "los",
                "losmon_replacement",
                "--title",
                "Build Logger",
                "--summary",
                "Log conversations and tool calls to the routed work item.",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    work_item = (
        root
        / "los"
        / "02-projects"
        / "losmon_replacement"
        / "work-items"
        / "01-intake"
        / "001_build_logger.md"
    )
    assert work_item.is_file()

    assert main(["route", "Implement build logger for losmon_replacement", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["object_type"] == "work_item"
    assert packet["target_path"] == str(work_item)
    assert packet["lifecycle"]["state"] == "captured"
    assert packet["lifecycle"]["lane"] == "01-intake"
    assert packet["lifecycle"]["format"] == "markdown"
    assert str(work_item) in packet["sources_to_load"]
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "los",
                "losmon_replacement",
                "--title",
                "Duel Expanded Idea",
                "--summary",
                "Create a multi-file intake packet for a hardened idea.",
                "--format",
                "packet",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    intake_packet = (
        root
        / "los"
        / "02-projects"
        / "losmon_replacement"
        / "work-items"
        / "01-intake"
        / "002_duel_expanded_idea"
    )
    assert (intake_packet / "work.yml").is_file()
    assert (intake_packet / "SPEC.md").is_file()
    assert not (intake_packet / "IDEA.md").exists()
    intake_metadata = yaml.safe_load((intake_packet / "work.yml").read_text(encoding="utf-8"))
    assert intake_metadata["lane"] == "01-intake"
    assert intake_metadata["format"] == "folder"
    assert "SPEC.md" in intake_metadata["lifecycle"]["required_files"]
    assert "IDEA.md" not in intake_metadata["lifecycle"]["required_files"]
    assert main(["route", "run duel expanded packet for losmon_replacement", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["object_type"] == "work_item"
    assert packet["target_path"] == str(intake_packet)
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "los",
                "losmon_replacement",
                "--title",
                "Active Build",
                "--summary",
                "Create the active full packet.",
                "--status",
                "building",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    active_work_item = root / "los" / "02-projects" / "losmon_replacement" / "work-items" / "02-active" / "003_active_build"
    assert (active_work_item / "work.yml").is_file()
    assert (active_work_item / "logs" / "conversations").is_dir()
    assert main(["validate", "--root", str(root)]) == 0


def test_compat_work_lifecycle_helpers_use_lane_paths(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    created = create_compat_project_work_item(
        root,
        "los",
        "losmon_replacement",
        "legacy_packet",
        title="Legacy Packet",
        summary="Exercise compatibility lifecycle helpers.",
        state="building",
    )
    project_root = root / "los" / "02-projects" / "losmon_replacement"
    active = project_root / "work-items" / "02-active" / "legacy_packet"
    assert created["path"] == str(active)
    assert (active / "work.yml").is_file()
    assert not (project_root / "work-items" / "legacy_packet").exists()

    listed = list_compat_project_work_items(root, "los", "losmon_replacement")
    assert [item["path"] for item in listed["items"]] == [str(active)]

    promoted = promote_compat_project_work_item(
        root,
        "los",
        "losmon_replacement",
        "legacy_packet",
        state="documented",
        note="Close the compatibility packet.",
    )
    complete = project_root / "work-items" / "03-complete" / "legacy_packet"
    assert promoted["path"] == str(complete)
    assert complete.is_dir()
    assert not active.exists()
    metadata = yaml.safe_load((complete / "work.yml").read_text(encoding="utf-8"))
    assert metadata["lane"] == "03-complete"


def test_route_can_resume_source_package_feature_from_linked_repo(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "genomes_agentic_os"
    feature = repo / "features" / "60-memory-driven-toolsmith-loop"
    feature.mkdir(parents=True)
    (feature / "feature.yml").write_text(
        "id: test\nprefix: '60'\nslug: 60-memory-driven-toolsmith-loop\ntitle: 60 Memory Driven Toolsmith Loop\nstatus: planned\n",
        encoding="utf-8",
    )
    (feature / "IDEA.md").write_text("# Idea\n", encoding="utf-8")
    (feature / "WORKLOG.md").write_text("# Worklog\n", encoding="utf-8")
    (feature / "NEXT.md").write_text("# Next\n", encoding="utf-8")

    assert main(["project", "create", "los", "genomes_agentic_os", "--repo", str(repo), "--root", str(root)]) == 0
    assert main(["route", "Let's implement 60-memory-driven-toolsmith-loop", "--root", str(root)]) == 0
    packet = yaml.safe_load(capsys.readouterr().out)
    assert packet["object_type"] == "work_item"
    assert packet["target_path"] == str(feature)
    assert packet["lifecycle"]["source"] == "source_feature"


def test_conversation_auto_log_hook_writes_redacted_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", "los", "losmon_replacement", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "los",
                "losmon_replacement",
                "--title",
                "Build Logger",
                "--summary",
                "Log conversations.",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    work_item = (
        root
        / "los"
        / "02-projects"
        / "losmon_replacement"
        / "work-items"
        / "01-intake"
        / "001_build_logger.md"
    )
    transcript = tmp_path / "session.jsonl"
    secret = "sk-" + "a" * 30
    transcript.write_text(
        json.dumps({"type": "tool_use", "command": f"echo {secret}"}) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "harness/hooks/conversation-auto-log.py"],
        input=json.dumps({"cwd": str(work_item), "transcript_path": str(transcript), "session_id": "test-session"}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"] == "Stop"
    log_dir = work_item.parent / "001_build_logger.logs" / "conversations"
    tool_md = next(log_dir.glob("*_tool_calls.md"))
    tool_jsonl = next(log_dir.glob("*_tool_calls.jsonl"))
    raw_log = next(path for path in log_dir.glob("*.jsonl") if not path.name.endswith("_tool_calls.jsonl"))
    assert "[REDACTED]" in tool_md.read_text(encoding="utf-8")
    assert secret not in tool_md.read_text(encoding="utf-8")
    assert secret not in tool_jsonl.read_text(encoding="utf-8")
    assert secret not in raw_log.read_text(encoding="utf-8")


def test_conversation_auto_log_hook_routes_linked_repo_to_active_work_item(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["project", "create", "los", "los_app", "--repo", str(repo), "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "los",
                "los_app",
                "--title",
                "Build Logger",
                "--summary",
                "Log conversations.",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    work_item = root / "los" / "02-projects" / "los_app" / "work-items" / "01-intake" / "001_build_logger.md"

    proc = subprocess.run(
        [sys.executable, "harness/hooks/conversation-auto-log.py"],
        input=json.dumps({"cwd": str(repo), "session_id": "linked-repo"}),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "AGENTIC_OS_ROOT": str(root)},
    )
    assert proc.returncode == 0
    log_dir = work_item.parent / "001_build_logger.logs" / "conversations"
    assert next(log_dir.glob("*linked_repo*"), None) is None
    assert list(log_dir.glob("*001_build_logger*.jsonl"))


def test_conversation_auto_log_hook_routes_harness_surface_to_harness_logs(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    cwd = root / "harness" / "hooks"
    cwd.mkdir(parents=True)

    proc = subprocess.run(
        [sys.executable, "harness/hooks/conversation-auto-log.py"],
        input=json.dumps({"cwd": str(cwd), "session_id": "harness-session"}),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "AGENTIC_OS_ROOT": str(root)},
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert list((root / "harness" / "logs" / "conversations").glob("*harness*.jsonl"))


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

    assert main(["workflow", "create", "work", "engineering", "feature_dev", "--root", str(root)]) == 0
    assert main(["automation", "create", "work", "support", "production_thread_intake", "--root", str(root)]) == 0
    assert main(["run-log", "create", "work", "feature_dev", "--root", str(root)]) == 0

    workflow_root = root / "work" / "03-workflows" / "engineering" / "feature_dev"
    automation_root = root / "work" / "04-automations" / "support" / "production_thread_intake"
    run_log = next((root / "work" / "06-runs-and-logs" / "runs").glob("*-work-feature_dev/run-log.md"))

    required_sections = {
        harness(root) / "ROUTER.md": ("# Agent Router", "## Routing Table", "## Operating Rules"),
        harness(root) / "AGENTS.md": ("# Agent Entry Point", "## Required Loop", "RULES.md", "TOOLS.md"),
        harness(root) / "CLAUDE.md": ("@AGENTS.md",),
        harness(root) / "CONTEXT.md": ("# Local Context", "## What To Load", "## Done Means"),
        harness(root) / "RULES.md": ("# Rules", "## Approval Gates", "## Operating Rules"),
        harness(root) / "TOOLS.md": ("# Tools", "## Skills", "## Commands", "## MCP Servers"),
        root / "work" / "ROUTER.md": ("# Agent Router: Work", "## Where To Put Work", "## Approval Rules"),
        root / "work" / "AGENTS.md": ("# Agent Entry Point", "## Required Loop", "RULES.md", "TOOLS.md"),
        root / "work" / "CLAUDE.md": ("@AGENTS.md",),
        root / "work" / "CONTEXT.md": ("# Context: Work", "## What To Load", "## Tools And Skills", "## Done Means"),
        root / "work" / "RULES.md": ("# Rules: Work", "## Approval Gates", "## Operating Rules"),
        root / "work" / "TOOLS.md": ("# Tools: Work", "## Skills", "## Commands", "## MCP Servers"),
        root / "work" / "REFERENCES.md": ("# References: Work", "## Source Systems", "## Known Gaps"),
        root / "work" / "03-workflows" / "README.md": ("# Workflows: Work", "## Lane Directories", "## Workflow Folder Format"),
        root / "work" / "03-workflows" / "engineering" / "README.md": (
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
        root / "work" / "04-automations" / "README.md": (
            "# Automations: Work",
            "## Lane Directories",
            "## Automation Folder Format",
        ),
        automation_root / "automation.md": ("# Automation: production_thread_intake", "## Metadata", "## Trigger"),
        automation_root / "inputs.md": ("# Inputs: production_thread_intake", "| Input | Required | Source | Validation |"),
        automation_root / "logs" / "README.md": ("# Automation Logs: production_thread_intake", "## Log Format"),
        root / "work" / "06-runs-and-logs" / "runs" / "README.md": ("# Runs: Work", "## Run Folder Format"),
        root / "work" / "06-runs-and-logs" / "failures" / "README.md": ("# Failures: Work", "## Failure Record Format"),
        run_log: ("# Run Log:", "## Metadata", "## Input", "## Session Continuity", "## Validation", "## Handoff"),
    }

    for path, sections in required_sections.items():
        content = path.read_text(encoding="utf-8")
        if path.name != "CLAUDE.md":
            assert content.startswith("# "), path
        for section in sections:
            assert section in content, path
