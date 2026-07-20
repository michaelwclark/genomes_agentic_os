"""Visible capability registry defaults for installed Agentic OS roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .composio_catalog import composio_tool_entries
from .mcp_catalog import MCP_SERVERS, all_visible_mcp_ids


HARNESS_DIRECTORY = "harness"

VISIBLE_CAPABILITY_DIRECTORIES = (
    "harness/bin",
    "harness/commands",
    "harness/skills",
    "harness/mcp",
    "harness/plugins",
    "harness/libraries",
    "harness/hooks",
    "harness/rules",
    "harness/reports",
    "harness/registries",
)

REGISTRY_FILES = {
    "capabilities": "harness/registries/capabilities.yml",
    "commands": "harness/registries/commands.yml",
    "skills": "harness/registries/skills.yml",
    "mcp_servers": "harness/registries/mcp-servers.yml",
    "libraries": "harness/registries/libraries.yml",
    "hooks": "harness/registries/hooks.yml",
    "plugins": "harness/registries/plugins.yml",
    "rules": "harness/registries/rules.yml",
    "reports": "harness/registries/reports.yml",
    "composio_tools": "harness/registries/composio-tools.yml",
}

CAPABILITY_COLLECTIONS = {
    "command": "commands",
    "skill": "skills",
    "mcp_server": "mcp_servers",
    "library": "libraries",
    "hook": "hooks",
    "plugin": "plugins",
    "rule": "rules",
    "report": "reports",
}


def command_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "auto-dev-detective",
            "command": "/auto-dev-detective",
            "description": "Investigate bugs, QA failures, logs, alerts, incidents, and RCA questions with deployed-version gates, polymorphic evidence sources, pause/resume, and receipts.",
            "source": "harness/commands/auto-dev-detective.md",
        },
        {
            "id": "auto-dev-create-artifacts",
            "command": "/auto-dev-create-artifacts",
            "description": "Create provider-native SDLC artifacts through root/domain/project Markdown contracts, validation, governed apply, and readback.",
            "source": "harness/commands/auto-dev-create-artifacts.md",
        },
        {
            "id": "auto-dev-readiness",
            "command": "/auto-dev-readiness",
            "description": "Resolve tracker, repository/base, policy, worktree, and plan before implementation.",
            "source": "harness/commands/auto-dev-readiness.md",
        },
        {
            "id": "auto-dev-implementation",
            "command": "/auto-dev-implementation",
            "description": "Implement a planned task under effective standards and receipt local validation.",
            "source": "harness/commands/auto-dev-implementation.md",
        },
        {
            "id": "auto-dev-review-repair",
            "command": "/auto-dev-review-repair",
            "description": "Run review, governed PR creation, quiet CI/review repair, and merge-readiness validation.",
            "source": "harness/commands/auto-dev-review-repair.md",
        },
        {
            "id": "auto-dev-release-propagation",
            "command": "/auto-dev-release-propagation",
            "description": "Resolve and execute policy-backed release, hotfix, backport, or forward-port branch families.",
            "source": "harness/commands/auto-dev-release-propagation.md",
        },
        {
            "id": "auto-dev-closeout",
            "command": "/auto-dev-closeout",
            "description": "Merge with approval, validate deployment, reconcile providers, clean up, and prove delivery complete.",
            "source": "harness/commands/auto-dev-closeout.md",
        },
        {
            "id": "project-domain-investigate",
            "command": "/project-domain-investigate",
            "description": "Retrieve bounded project-domain context and emit the receipt consumed by development work.",
            "source": "harness/commands/project-domain-investigate.md",
        },
        {
            "id": "claude-desktop-bridge",
            "command": "harness/bin/agentic-os-claude-desktop-bridge",
            "description": "Build or audit the optional Claude Desktop custom-skill and instruction package.",
            "source": "harness/commands/os-claude-desktop-bridge.md",
        },
        {
            "id": "make-skill",
            "command": "/make-skill",
            "description": "Create or update a reusable Agentic OS skill.",
            "source": "harness/commands/os-create-workflow.md",
        },
        {
            "id": "make-domain",
            "command": "/make-domain",
            "description": "Create a routed Agentic OS domain or room.",
            "source": "agentic-os domain create",
        },
        {
            "id": "make-automation",
            "command": "/make-automation",
            "description": "Create a guarded automation spec and supporting files.",
            "source": "harness/commands/os-create-automation.md",
        },
        {
            "id": "make-workflow",
            "command": "/make-workflow",
            "description": "Create a reusable workflow spec and run contract.",
            "source": "harness/commands/os-create-workflow.md",
        },
        {
            "id": "create-program",
            "command": "/create-program",
            "description": "Create a shared OSProgram contract and context bundle.",
            "source": "harness/commands/os-create-program.md",
        },
        {
            "id": "create-instance-program",
            "command": "/create-instance-program",
            "description": "Create a domain-local InstanceOSProgram contract and context bundle.",
            "source": "harness/commands/os-create-instance-program.md",
        },
        {
            "id": "execution-fabric",
            "command": "/execution-fabric",
            "description": "Inspect, design, or validate the optional named-queue and bounded worker-pool program.",
            "source": "harness/commands/os-execution-fabric.md",
        },
        {
            "id": "orchestrate",
            "command": "/orchestrate",
            "description": "Plan, decompose, delegate, verify, and merge feature work.",
            "source": "harness/skills/orchestrate/SKILL.md",
        },
        {
            "id": "end-chat",
            "command": "/end-chat",
            "description": "Finalize a substantive Agentic OS thread with receipts and next-action capture.",
            "source": "harness/commands/os-end-chat.md",
        },
        {
            "id": "finalize",
            "command": "/finalize",
            "description": "Alias for /end-chat when explicit finalization language is preferred.",
            "source": "harness/commands/os-end-chat.md",
        },
        {
            "id": "cleanup-thread",
            "command": "/cleanup-thread",
            "description": "Finalize the current thread and classify generated dirt before cleanup.",
            "source": "harness/commands/os-end-chat.md",
        },
        {
            "id": "archive",
            "command": "/archive",
            "description": "Finalize and archive only when no unresolved next action remains.",
            "source": "harness/commands/os-end-chat.md",
        },
        {
            "id": "validate",
            "command": "agentic-os validate",
            "description": "Validate an installed OS root against the source package contract.",
            "source": "agentic-os validate",
        },
        {
            "id": "ps",
            "command": "agentic-os ps",
            "description": "Show Agentic OS work running right now; use --active for queued/configured work and stale thread candidates.",
            "source": "harness/commands/os-ps.md",
        },
        {
            "id": "aos",
            "command": "aos",
            "description": "Short alias for the agentic-os CLI.",
            "source": "pyproject.toml",
        },
        {
            "id": "program-create",
            "command": "agentic-os program create",
            "description": "Create a shared OSProgram under harness/shared_factory/00-programs/.",
            "source": "agentic-os program create",
        },
        {
            "id": "instance-program-create",
            "command": "agentic-os instance-program create",
            "description": "Create a domain-local InstanceOSProgram under <domain>/00-programs/.",
            "source": "agentic-os instance-program create",
        },
        {
            "id": "project-onboard",
            "command": "agentic-os project onboard",
            "description": "Create or repair a project-local agent, config, ideas, and worktree surface.",
            "source": "agentic-os project onboard",
        },
        {
            "id": "project-worktree-add",
            "command": "agentic-os project worktree add",
            "description": "Register a visible project worktree symlink and routing index entry.",
            "source": "agentic-os project worktree add",
        },
        {
            "id": "project-worktree-cleanup-closed",
            "command": "agentic-os project worktree cleanup-closed",
            "description": "Close terminal Jira or merged-PR worktree registrations and optionally remove clean in-project worktree directories.",
            "source": "harness/commands/os-clean-worktrees.md",
        },
        {
            "id": "develop",
            "command": "agentic-os develop",
            "description": "Run one or many tracker-backed programming tasks through canonical project-configured delivery.",
            "source": "harness/commands/develop.md",
        },
        {
            "id": "quiet-run",
            "command": "harness/bin/agentic-os-quiet-run",
            "description": "Start and control long-running local commands through the central safety registry, bounded logs, watchdogs, and terminal receipts.",
            "source": "harness/commands/os-quiet-run.md",
        },
        {
            "id": "automation-control",
            "command": "agentic-os automation-control",
            "description": "Gate expensive recurring automations behind cheap source-readiness probes.",
            "source": "harness/commands/os-automation-control.md",
        },
        {
            "id": "status-report",
            "command": "/status-report",
            "description": "Generate recent Agentic OS status reports from logs, OS state, source status, and Notion projection state.",
            "source": "harness/commands/os-status-report.md",
        },
        {
            "id": "cockpit",
            "command": "agentic-os cockpit",
            "description": "Build or open the read-only local engineering cockpit over Agentic OS state.",
            "source": "harness/commands/os-cockpit.md",
        },
        {
            "id": "agentic-os-gui",
            "command": "agentic-os gui",
            "description": "Open or inspect the domain/project-focused local desktop conversation driver.",
            "source": "harness/commands/os-gui.md",
        },
        {
            "id": "config-doctor",
            "command": "agentic-os config doctor",
            "description": "Validate Codex config and MCP registration contracts.",
            "source": "agentic-os config doctor",
        },
        {
            "id": "doc-config",
            "command": "agentic-os doc-config",
            "description": "Plan and validate configurable document routing across filesystem and Notion surfaces.",
            "source": "harness/commands/os-doc-config.md",
        },
        {
            "id": "notion-org",
            "command": "agentic-os notion-org",
            "description": "Check filesystem mirrors and local Notion backup snapshots against the canonical Notion organization convention.",
            "source": "harness/commands/os-notion-org.md",
        },
        {
            "id": "spec-engine",
            "command": "agentic-os spec",
            "description": "Capture, groom, transition, synchronize, and diagnose canonical bug, feature, and config Specs.",
            "source": "harness/commands/os-add-spec.md",
        },
        {
            "id": "add-spec",
            "command": "/add-spec",
            "description": "Capture future work, rough requests, or proposed features through doc-config routing and project work-item intake.",
            "source": "harness/commands/os-add-spec.md",
        },
        {
            "id": "groom-spec",
            "command": "/groom-spec",
            "description": "Groom rough ideas into source-backed implementation specs with intent preservation, discovery, QA, and projection receipts.",
            "source": "harness/commands/os-groom-spec.md",
        },
        {
            "id": "new-feature",
            "command": "/new-feature",
            "description": "Deprecated compatibility alias for /add-spec.",
            "source": "harness/commands/os-new-feature.md",
        },
        {
            "id": "add-feature",
            "command": "/add-feature",
            "description": "Deprecated compatibility alias for /add-spec.",
            "source": "harness/commands/os-new-feature.md",
        },
        {
            "id": "add-bug",
            "command": "/add-bug",
            "description": "Capture a lightweight bug report or missed Agentic OS enforcement into routed project work-items.",
            "source": "harness/commands/os-add-bug.md",
        },
        {
            "id": "auto-add-spec",
            "command": "/auto-add-spec",
            "description": "Create or update a local spec packet for long OS-shaping requests before implementation proceeds.",
            "source": "harness/commands/os-auto-add-spec.md",
        },
        {
            "id": "auto-add-feature",
            "command": "/auto-add-feature",
            "description": "Deprecated compatibility alias for /auto-add-spec.",
            "source": "harness/commands/os-auto-add-feature.md",
        },
        {
            "id": "config-install-tree",
            "command": "agentic-os config install-tree",
            "description": "Install Codex config.toml files across the OS routing tree.",
            "source": "agentic-os config install-tree",
        },
        {
            "id": "hook-sync",
            "command": "agentic-os hook sync",
            "description": "Point active Claude/Codex hook settings at the installed OS hook source of truth.",
            "source": "agentic-os hook sync",
        },
        {
            "id": "self-improvement-run",
            "command": "agentic-os self-improvement run --dry-run",
            "description": "Review durable local evidence for proposal-only OS improvement opportunities.",
            "source": "harness/commands/os-self-improvement.md",
        },
        {
            "id": "docs-upkeep",
            "command": "agentic-os docs upkeep",
            "description": "Run the observe-mode canonical documentation upkeep registry and local drift planner.",
            "source": "harness/commands/os-docs-upkeep.md",
        },
        {
            "id": "composio-debug-bundle",
            "command": "composio-debug-bundle",
            "description": "Set local Composio support/debug identifiers for diagnostics.",
            "source": "harness/commands/composio-debug-bundle.md",
        },
        {
            "id": "capture-plan",
            "command": "agentic-os capture-plan",
            "description": "Capture future ideas, implementation gaps, or validation findings as durable planning material.",
            "source": "harness/commands/os-capture-plan.md",
        },
        {
            "id": "chain",
            "command": "agentic-os chain",
            "description": "Inspect, test, and doctor event chain rules.",
            "source": "harness/commands/os-chain.md",
        },
        {
            "id": "client-automation-brief",
            "command": "agentic-os customer brief",
            "description": "Evaluate repeated customer work as a workflow, automation, or manual runbook.",
            "source": "harness/commands/os-client-automation-brief.md",
        },
        {
            "id": "context-audit",
            "command": "agentic-os context audit",
            "description": "Audit noisy or overbroad room, workflow, automation, or customer OS context.",
            "source": "harness/commands/os-context-audit.md",
        },
        {
            "id": "control-plane-bootstrap",
            "command": "agentic-os notion bootstrap",
            "description": "Plan or apply a Notion/file-backed control plane for the OS.",
            "source": "harness/commands/os-control-plane-bootstrap.md",
        },
        {
            "id": "discover-rooms",
            "command": "agentic-os room",
            "description": "Create room-first OS structures from discovery material.",
            "source": "harness/commands/os-discover-rooms.md",
        },
        {
            "id": "doctor",
            "command": "agentic-os doctor",
            "description": "Check installed OS health and structural drift.",
            "source": "harness/commands/os-doctor.md",
        },
        {
            "id": "event",
            "command": "agentic-os event",
            "description": "Append, list, summarize, process, or replay durable OS events.",
            "source": "harness/commands/os-event.md",
        },
        {
            "id": "heartbeat",
            "command": "agentic-os heartbeat",
            "description": "Operate runtime heartbeats from file-backed registries.",
            "source": "harness/commands/os-heartbeat.md",
        },
        {
            "id": "notify",
            "command": "/notify",
            "description": "Send one governed local macOS notification for an operator-actionable Agentic OS condition.",
            "source": "harness/commands/os-notify.md",
        },
        {
            "id": "integration-setup",
            "command": "agentic-os integration",
            "description": "Prepare and diagnose approval-gated runtime integrations.",
            "source": "harness/commands/os-integration-setup.md",
        },
        {
            "id": "operator-resource",
            "command": "agentic-os operator-resource",
            "description": "Query typed read-only Program and Automation operator projections.",
            "source": "harness/commands/os-operator-resource.md",
        },
        {
            "id": "resource-registry",
            "command": "agentic-os resource-registry",
            "description": "Refresh or query the atomic first-class resource snapshot used by operator surfaces.",
            "source": "harness/commands/os-resource-registry.md",
        },
        {
            "id": "route",
            "command": "agentic-os route",
            "description": "Route a request to the correct installed OS layer.",
            "source": "harness/commands/os-route.md",
        },
        {
            "id": "run-build-runner",
            "command": "agentic-os run-build-runner",
            "description": "Drive queued source work through the shared build-runner skill.",
            "source": "harness/commands/os-run-build-runner.md",
        },
        {
            "id": "run-log",
            "command": "agentic-os run-log",
            "description": "Create and close run logs for non-trivial OS work.",
            "source": "harness/commands/os-run-log.md",
        },
        {
            "id": "runtime-init",
            "command": "agentic-os runtime init",
            "description": "Initialize file-backed runtime state for an installed OS.",
            "source": "harness/commands/os-runtime-init.md",
        },
        {
            "id": "run-queue",
            "command": "agentic-os run-queue",
            "description": "Prune stale runtime run-queue rows and old queue backup files.",
            "source": "harness/commands/os-run-queue.md",
        },
        {
            "id": "sync-notion",
            "command": "agentic-os notion sync",
            "description": "Prepare filesystem-to-Notion control-plane sync plans.",
            "source": "harness/commands/os-sync-notion.md",
        },
        {
            "id": "update",
            "command": "agentic-os update",
            "description": "Plan, apply, and report installed OS updates.",
            "source": "harness/commands/os-update.md",
        },
        {
            "id": "watch-source",
            "command": "agentic-os watch-source",
            "description": "Configure and audit provider-agnostic connected source watchers.",
            "source": "harness/commands/os-watch-source.md",
        },
        {
            "id": "system-tool-registry",
            "command": "system-tool-registry",
            "description": "Use the host tool registry before non-trivial host work.",
            "source": "harness/commands/system-tool-registry.md",
        },
        {
            "id": "object-library",
            "command": "agentic-os library",
            "description": "Read, create, migrate, refresh, and validate the versioned installed object library.",
            "source": "harness/commands/os-library.md",
        },
        {
            "id": "artifact-naming",
            "command": "agentic-os naming",
            "description": "Inspect, migrate, and restore configurable date-prefixed durable entity names.",
            "source": "harness/commands/os-artifact-naming.md",
        },
        {
            "id": "work-state",
            "command": "agentic-os work",
            "description": "Read and mutate canonical lifecycle, attention, resume context, and active work state.",
            "source": "harness/commands/os-work-state.md",
        },
    ]


def skill_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "artifact-naming",
            "name": "Artifact Naming",
            "description": "Inspect, migrate, or restore configurable date-prefixed durable Agentic OS entity names.",
            "source": "harness/skills/artifact-naming/SKILL.md",
        },
        {
            "id": "project-domain-investigate",
            "name": "Project Domain Investigate",
            "description": "Retrieve bounded, evidence-backed project-domain context and emit a development context receipt.",
            "source": "harness/skills/project-domain-investigate/SKILL.md",
        },
        {
            "id": "agentic-os-operating-contract",
            "name": "Agentic OS Operating Contract",
            "description": "Apply the shared Agentic OS routing, context, tool-use, workflow, automation, and closeout contract across Claude and Codex.",
            "source": "harness/skills/agentic-os-operating-contract/SKILL.md",
        },
        {
            "id": "notification-operator",
            "name": "Notification Operator",
            "description": "Send one governed local macOS notification for an operator-actionable Agentic OS condition without creating alert noise.",
            "source": "harness/skills/notification-operator/SKILL.md",
        },
        {
            "id": "os-navigator",
            "name": "OS Navigator",
            "description": "Route work through installed Agentic OS rooms.",
            "source": "harness/skills/os-navigator/SKILL.md",
        },
        {
            "id": "workflow-builder",
            "name": "Workflow Builder",
            "description": "Create or refine reusable workflow contracts.",
            "source": "harness/skills/workflow-builder/SKILL.md",
        },
        {
            "id": "program-builder",
            "name": "Program Builder",
            "description": "Create or refine OSProgram and InstanceOSProgram context bundles.",
            "source": "harness/skills/program-builder/SKILL.md",
        },
        {
            "id": "execution-fabric",
            "name": "Execution Fabric",
            "description": "Inspect, design, and validate optional named queues and bounded worker pools while preserving the filesystem queue default.",
            "source": "harness/skills/execution-fabric/SKILL.md",
        },
        {
            "id": "status-report",
            "name": "Status Report",
            "description": "Generate recent-work Agentic OS status reports with filesystem and guarded Notion projection receipts.",
            "source": "harness/skills/status-report/SKILL.md",
        },
        {
            "id": "doc-config-router",
            "name": "Doc Config Router",
            "description": "Route document captures to the configured Agentic OS filesystem and Notion destinations.",
            "source": "harness/skills/doc-config-router/SKILL.md",
        },
        {
            "id": "spec-engine",
            "name": "Spec Engine",
            "description": "Operate the canonical idea-to-built Spec lifecycle across layered project policy and filesystem, Linear, or Jira adapters.",
            "source": "harness/skills/spec-engine/SKILL.md",
        },
        {
            "id": "spec-intake-router",
            "name": "Spec Intake Router",
            "description": "Compatibility adapter for canonical Spec Engine add operations.",
            "source": "harness/skills/spec-intake-router/SKILL.md",
        },
        {
            "id": "spec-groomer",
            "name": "Spec Groomer",
            "description": "Groom rough software ideas into source-backed implementation specs with original intent, discovery, tracker hierarchy, QA, Gherkin, and Notion projection.",
            "source": "harness/skills/spec-groomer/SKILL.md",
        },
        {
            "id": "feature-intake-router",
            "name": "Feature Intake Router",
            "description": "Deprecated compatibility alias for spec intake routing.",
            "source": "harness/skills/feature-intake-router/SKILL.md",
        },
        {
            "id": "bug-intake-router",
            "name": "Bug Intake Router",
            "description": "Capture bug reports and missed enforcement through doc-config and project work-items.",
            "source": "harness/skills/bug-intake-router/SKILL.md",
        },
        {
            "id": "auto-spec-intake",
            "name": "Auto Spec Intake",
            "description": "Create or update local spec packets for long OS-shaping requests.",
            "source": "harness/skills/auto-spec-intake/SKILL.md",
        },
        {
            "id": "auto-feature-intake",
            "name": "Auto Feature Intake",
            "description": "Deprecated compatibility alias for auto spec intake.",
            "source": "harness/skills/auto-feature-intake/SKILL.md",
        },
        {
            "id": "os-authoring-guard",
            "name": "OS Authoring Guard",
            "description": "Apply compact Agentic OS authoring rules to commands, skills, workflows, automations, tools, registries, and worktrees.",
            "source": "harness/skills/os-authoring-guard/SKILL.md",
        },
        {
            "id": "os-doctor",
            "name": "OS Doctor",
            "description": "Validate installed OS structure and report drift.",
            "source": "harness/skills/os-doctor/SKILL.md",
        },
        {
            "id": "automation-qualifier",
            "name": "Automation Qualifier",
            "description": "Decide whether a process is safe to automate.",
            "source": "harness/skills/automation-qualifier/SKILL.md",
        },
        {
            "id": "quiet-async-runner",
            "name": "Quiet Async Runner",
            "description": "Run long commands, tests, Docker setup, PR checks, and watchers through artifact-backed async state instead of chat polling.",
            "source": "harness/skills/quiet-async-runner/SKILL.md",
        },
        {
            "id": "add-env",
            "name": "Add Env",
            "description": "Append environment variables to ~/.zshenv on every registered host in one step.",
            "source": "harness/skills/add-env/SKILL.md",
        },
        {
            "id": "commitall",
            "name": "Commit All",
            "description": "Commit all local changes in logical groups until the repository is clean.",
            "source": "harness/skills/commitall/SKILL.md",
        },
        {
            "id": "thread-finalizer",
            "name": "Thread Finalizer",
            "description": "Finalize substantive Agentic OS threads with worklog, next-action, memory, evidence, and Notion projection receipts.",
            "source": "harness/skills/thread-finalizer/SKILL.md",
        },
        {
            "id": "os-cleaner",
            "name": "OS Cleaner",
            "description": "Reconcile Agentic OS worktree and work-item state after terminal tracker states or merged pull requests.",
            "source": "harness/skills/os-cleaner/SKILL.md",
        },
        {
            "id": "orchestrate",
            "name": "Orchestrate",
            "description": "Coordinate subagents, verification, and integration.",
            "source": "harness/skills/orchestrate/SKILL.md",
        },
        {
            "id": "cockpit",
            "name": "Agentic OS Cockpit",
            "description": "Build or open the local engineering cockpit for conversations, work, reviews, reports, sources, hosts, automations, and hygiene.",
            "source": "harness/skills/cockpit/SKILL.md",
        },
        {
            "id": "agentic-os-gui",
            "name": "AgenticOSGui",
            "description": "Operate the domain/project-focused desktop conversation driver over native Claude and Codex task state.",
            "source": "harness/skills/agentic-os-gui/SKILL.md",
        },
        {
            "id": "quiet-workon-orchestrate",
            "name": "Quiet Workon Orchestrate",
            "description": "Preferred coding/testing orchestration entrypoint with quiet chat and receipt-backed artifacts.",
            "source": "harness/skills/quiet-workon-orchestrate/SKILL.md",
        },
        {
            "id": "pull-request",
            "name": "Pull Request",
            "description": "Run a senior, blocker-focused GitHub PR review with multi-lane evidence.",
            "source": "harness/skills/pull-request/SKILL.md",
        },
        {
            "id": "watch-pr-quiet",
            "name": "Watch PR Quiet",
            "description": "Monitor GitHub pull request checks through file-based watcher artifacts instead of repeated chat polling.",
            "source": "harness/skills/watch-pr-quiet/SKILL.md",
        },
        {
            "id": "composio-cli",
            "name": "Composio CLI",
            "description": "Operate the published Composio CLI for tool discovery, account links, schema inspection, execution, and troubleshooting.",
            "source": "harness/skills/composio-cli/SKILL.md",
        },
        {
            "id": "toolsmith-reviewer",
            "name": "Toolsmith Reviewer",
            "description": "Review redacted evidence bundles and propose draft-only OS improvements.",
            "source": "harness/skills/toolsmith-reviewer/SKILL.md",
        },
        {
            "id": "build-runner",
            "name": "Build Runner",
            "description": "Drive a Kanban-backed implementation queue through orchestrated build phases.",
            "source": "harness/skills/build-runner/SKILL.md",
        },
        {
            "id": "client-automation-brief",
            "name": "Client Automation Brief",
            "description": "Turn customer workflow discovery into an automation or workflow brief.",
            "source": "harness/skills/client-automation-brief/SKILL.md",
        },
        {
            "id": "context-audit",
            "name": "Context Audit",
            "description": "Audit room, workflow, automation, or customer OS context load contracts.",
            "source": "harness/skills/context-audit/SKILL.md",
        },
        {
            "id": "context-pack-builder",
            "name": "Context Pack Builder",
            "description": "Assemble focused context packs for repeatable OS workflows.",
            "source": "harness/skills/context-pack-builder/SKILL.md",
        },
        {
            "id": "control-plane-bootstrap",
            "name": "Control Plane Bootstrap",
            "description": "Plan a Notion-backed or file-backed operating control plane.",
            "source": "harness/skills/control-plane-bootstrap/SKILL.md",
        },
        {
            "id": "domain-setup",
            "name": "Domain Setup",
            "description": "Create or improve a domain room inside the OS.",
            "source": "harness/skills/domain-setup/SKILL.md",
        },
        {
            "id": "event-graph-operator",
            "name": "Event Graph Operator",
            "description": "Append events, inspect the ledger, test chain rules, and process follow-up work.",
            "source": "harness/skills/event-graph-operator/SKILL.md",
        },
        {
            "id": "integration-setup",
            "name": "Integration Setup",
            "description": "Prepare, dry-run, or diagnose runtime integrations before automation uses them.",
            "source": "harness/skills/integration-setup/SKILL.md",
        },
        {
            "id": "learning-promoter",
            "name": "Learning Promoter",
            "description": "Promote durable run learnings into the right OS knowledge surface.",
            "source": "harness/skills/learning-promoter/SKILL.md",
        },
        {
            "id": "room-builder",
            "name": "Room Builder",
            "description": "Turn discovery answers into OS rooms, routers, references, and context contracts.",
            "source": "harness/skills/room-builder/SKILL.md",
        },
        {
            "id": "run-logger",
            "name": "Run Logger",
            "description": "Record non-trivial OS execution into run logs and closeout surfaces.",
            "source": "harness/skills/run-logger/SKILL.md",
        },
        {
            "id": "runtime-operator",
            "name": "Runtime Operator",
            "description": "Operate runtime registries, heartbeats, schedules, run queues, and tracking.",
            "source": "harness/skills/runtime-operator/SKILL.md",
        },
        {
            "id": "source-watcher",
            "name": "Source Watcher",
            "description": "Configure or audit provider-agnostic connected source watchers.",
            "source": "harness/skills/source-watcher/SKILL.md",
        },
        {
            "id": "aos-product-orchestrator",
            "name": "AOS Product Orchestrator",
            "description": "Groom Agentic OS self-improvement proposals into spec packets and Linear issues.",
            "source": "harness/skills/aos-product-orchestrator/SKILL.md",
        },
        {
            "id": "auto-dev",
            "name": "Auto Dev",
            "description": "Route programming work through the canonical polymorphic investigation, artifact, delivery, review, release, deployment, and closeout family.",
            "source": "harness/skills/auto-dev/SKILL.md",
        },
        {
            "id": "auto-dev-create-artifacts",
            "name": "Auto-Dev Create Artifacts",
            "description": "Resolve polymorphic provider/type contracts and render, validate, apply, and read back excellent Jira, Linear, Notion, Confluence, GitHub, Slack, or filesystem artifacts.",
            "source": "harness/skills/auto-dev-create-artifacts/SKILL.md",
        },
        {
            "id": "auto-dev-detective",
            "name": "Auto-Dev Detective",
            "description": "Investigate reported bugs, failed QA, logs, alerts, incidents, and suspected causes against the exact deployed version with governed source evidence and resumable receipts.",
            "source": "harness/skills/auto-dev-detective/SKILL.md",
        },
        {
            "id": "auto-dev-readiness",
            "name": "Auto-Dev Readiness",
            "description": "Prepare tracker truth, repository/base, policy, worktree, and implementation plan.",
            "source": "harness/skills/auto-dev-readiness/SKILL.md",
        },
        {
            "id": "auto-dev-implementation",
            "name": "Auto-Dev Implementation",
            "description": "Implement and locally validate a planned task under effective engineering policy.",
            "source": "harness/skills/auto-dev-implementation/SKILL.md",
        },
        {
            "id": "auto-dev-review-repair",
            "name": "Auto-Dev Review and Repair",
            "description": "Review, create the governed PR, repair checks/findings, and prove merge readiness.",
            "source": "harness/skills/auto-dev-review-repair/SKILL.md",
        },
        {
            "id": "auto-dev-release-propagation",
            "name": "Auto-Dev Release Propagation",
            "description": "Operate configured release and hotfix branch families with exact receipts.",
            "source": "harness/skills/auto-dev-release-propagation/SKILL.md",
        },
        {
            "id": "auto-dev-closeout",
            "name": "Auto-Dev Closeout",
            "description": "Merge, validate deployment, reconcile provider state, clean up, and close delivery.",
            "source": "harness/skills/auto-dev-closeout/SKILL.md",
        },
        {
            "id": "develop",
            "name": "Develop",
            "description": "Run one or many programming tasks through the canonical project-configured development-delivery program.",
            "source": "harness/skills/develop/SKILL.md",
        },
        {
            "id": "finishing-touches-review",
            "name": "Finishing Touches Review",
            "description": "Run a deterministic cross-model finishing review loop before PR readiness or after PR creation when checks are the final validation signal.",
            "source": "harness/skills/finishing-touches-review/SKILL.md",
        },
        {
            "id": "initiative-context-resume",
            "name": "Initiative Context Resume",
            "description": "Create or refresh durable context packs and discovery indexes for long-running initiatives or subprojects.",
            "source": "harness/skills/initiative-context-resume/SKILL.md",
        },
        {
            "id": "memory-analytics-viewer",
            "name": "Memory Analytics Viewer",
            "description": "Inspect unified-memory retrieval analytics from the live memory_ops store. Read-only and redacted.",
            "source": "harness/skills/memory-analytics-viewer/SKILL.md",
        },
        {
            "id": "os-health",
            "name": "OS Health",
            "description": "Inspect host speed risks and Agentic OS generated-artifact hygiene with observe-only reports and approval-gated cleanup classes.",
            "source": "harness/skills/os-health/SKILL.md",
        },
    ]


def mcp_server_entries() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for server_id in all_visible_mcp_ids():
        server = MCP_SERVERS[server_id]
        rows.append(
            {
                "id": server.id,
                "name": server.display_name,
                "use_when": server.use_when,
                "boundary": server.boundary,
                "install_scope": server.install_scope,
            }
        )
    return rows


def library_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "context_mode",
            "name": "Context Mode",
            "description": "Large-output and file analysis without flooding agent context.",
            "source": "context-mode MCP and CLI",
        },
        {
            "id": "unified_memory",
            "name": "Unified Memory",
            "description": "Durable cross-session memory plane backed by the configured memory MCP service.",
            "source": "memory MCP",
        },
        {
            "id": "pyyaml",
            "name": "PyYAML",
            "description": "Structured YAML parsing for registries, runtime state, and templates.",
            "source": "pyproject.toml",
        },
    ]


def hook_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "session-prayer-start",
            "name": "Session Prayer Start",
            "description": "Commits the session and work to Jesus before startup work begins.",
            "status": "available",
            "source": "harness/hooks/session-prayer-start.sh",
            "events": "SessionStart",
        },
        {
            "id": "memory-write-router",
            "name": "Memory Write Router",
            "description": "Routes durable memory writes to the correct substrate without writing CLAUDE.md.",
            "status": "available",
            "source": "harness/hooks/memory-session-start.sh",
            "events": "SessionStart, Stop",
        },
        {
            "id": "memory-session-start",
            "name": "Memory Session Start",
            "description": "Injects memory discipline at session start, resume, or clear.",
            "status": "available",
            "source": "harness/hooks/memory-session-start.sh",
            "events": "SessionStart",
        },
        {
            "id": "memory-stop",
            "name": "Memory Stop Reminder",
            "description": "Reminds agents to write durable memory before ending substantive turns.",
            "status": "available",
            "source": "harness/hooks/memory-stop.sh",
            "events": "Stop",
        },
        {
            "id": "harness-trace-emitter",
            "name": "Harness Trace Emitter",
            "description": "Emits non-blocking AGENT_TRACE memory records from Stop hook payloads.",
            "status": "available",
            "source": "harness/hooks/harness-emit-trace.sh",
            "events": "Stop",
        },
        {
            "id": "conversation-auto-log",
            "name": "Conversation Auto Log",
            "description": "Writes redacted conversation transcripts and tool-call sidecars to the routed project or work item.",
            "status": "available",
            "source": "harness/hooks/conversation-auto-log.py",
            "events": "Stop",
        },
        {
            "id": "context-mode-cache-heal",
            "name": "Context Mode Cache Heal",
            "description": "Repairs stale Claude context-mode plugin cache symlinks after auto-updates.",
            "status": "available",
            "source": "harness/hooks/context-mode-cache-heal.mjs",
            "events": "SessionStart",
        },
        {
            "id": "context-mode-codex-hooks",
            "name": "Context Mode Codex Hooks",
            "description": "Preserves context-mode Codex event hooks for session, tool, prompt, compaction, and stop capture.",
            "status": "available",
            "source": "context-mode hook codex",
            "events": "SessionStart, Stop, PreToolUse, PostToolUse, PreCompact, UserPromptSubmit",
        },
        {
            "id": "mempalace-claude-hooks",
            "name": "MemPalace Claude Hooks",
            "description": "Preserves MemPalace Claude hooks for session-start, stop, and precompact capture.",
            "status": "available",
            "source": "~/.local/share/mempalace-venv/bin/mempalace hook run",
            "events": "SessionStart, Stop, PreCompact",
        },
        {
            "id": "quiet-pr-watch",
            "name": "Quiet PR Watch",
            "description": "Writes PR check status artifacts instead of long-polling in chat.",
            "status": "available",
        },
    ]


def plugin_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "browser",
            "name": "Browser",
            "description": "In-app browser automation for local targets and screenshots.",
            "status": "visible",
        },
        {
            "id": "chrome",
            "name": "Chrome",
            "description": "Chrome automation when user cookies or existing profile state are required.",
            "status": "visible",
        },
        {
            "id": "computer-use",
            "name": "Computer Use",
            "description": "Local desktop app operation through Computer Use.",
            "status": "visible",
        },
    ]


def rule_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "route-read-cd-repeat",
            "name": "Route, read, cd, repeat",
            "description": "Read local routing, context, rules, and tools before acting at each layer.",
            "source": "AGENTS.md",
        },
        {
            "id": "strictest-rule-wins",
            "name": "Strictest rule wins",
            "description": "Narrower rules override broader rules unless the broader rule is stricter for safety.",
            "source": "RULES.md",
        },
        {
            "id": "no-secret-registry-values",
            "name": "No secret registry values",
            "description": "Registry and config files reference secret environment variable names only.",
            "source": "RULES.md",
        },
        {
            "id": "agentic-os-convention-authoring",
            "name": "Agentic OS Convention Authoring",
            "description": "Feature, workflow, automation, command, and skill authors follow the compact convention policy.",
            "source": "harness/rules/os-authoring-rules.md",
        },
        {
            "id": "auto-dev-artifact-producers",
            "name": "Auto-Dev Artifact Producers",
            "description": "All nested and standalone human-facing outputs resolve shared artifact contracts, validate, apply with approval, and read back.",
            "source": "harness/rules/auto-dev-artifact-producers.md",
        },
    ]


def capability_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for collection_type, getter in (
        ("command", command_entries),
        ("skill", skill_entries),
        ("mcp_server", mcp_server_entries),
        ("library", library_entries),
        ("hook", hook_entries),
        ("plugin", plugin_entries),
        ("rule", rule_entries),
    ):
        for entry in getter():
            entries.append(
                {
                    "id": f"{collection_type}:{entry['id']}",
                    "type": collection_type,
                    "ref": entry["id"],
                    "name": entry.get("name") or entry.get("command") or entry["id"],
                    "description": entry.get("description") or entry.get("use_when") or "",
                }
            )
    return entries


def registry_payloads() -> dict[str, dict[str, Any]]:
    return {
        "capabilities": {"capabilities": capability_entries()},
        "commands": {"commands": command_entries()},
        "skills": {"skills": skill_entries()},
        "mcp_servers": {"mcp_servers": mcp_server_entries()},
        "libraries": {"libraries": library_entries()},
        "hooks": {"hooks": hook_entries()},
        "plugins": {"plugins": plugin_entries()},
        "rules": {"rules": rule_entries()},
        "reports": {"reports": []},
        "composio_tools": {"composio_tools": composio_tool_entries()},
    }


def registry_file_payloads() -> dict[str, dict[str, Any]]:
    payloads = registry_payloads()
    return {REGISTRY_FILES[name]: payload for name, payload in payloads.items()}


def registry_yaml(name: str) -> str:
    return yaml.safe_dump(registry_payloads()[name], sort_keys=False)


def inventory_markdown(payloads: dict[str, dict[str, Any]] | None = None) -> str:
    payloads = payloads or registry_payloads()
    sections = ["# Agentic OS Inventory", "", "Generated from visible capability registries.", ""]
    for registry_name, payload in payloads.items():
        collection = payload.get(registry_name) or []
        title = registry_name.replace("_", " ").title()
        sections.extend([f"## {title}", "", "| ID | Name | Description |", "| --- | --- | --- |"])
        for entry in collection:
            name = entry.get("name") or entry.get("command") or entry.get("id") or ""
            description = entry.get("description") or entry.get("use_when") or ""
            sections.append(f"| `{entry.get('id', '')}` | {name} | {description} |")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def load_registry(path: Path, collection: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    values = data.get(collection) or []
    return [entry for entry in values if isinstance(entry, dict)]
