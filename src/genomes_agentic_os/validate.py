"""Validation for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import yaml

from .capability_registry import CAPABILITY_COLLECTIONS, REGISTRY_FILES, VISIBLE_CAPABILITY_DIRECTORIES, load_registry
from .config_ops import CONFIG_FILENAME
from .lifecycle import (
    WORK_ITEM_DIRECTORIES,
    WORK_ITEM_METADATA_FILES,
    WORK_LIFECYCLE_STATES,
    contains_token_shaped_value,
    conversation_log_files,
    lifecycle_status,
    load_yaml_mapping,
    local_project_work_items,
    metadata_path_for,
)
from .scaffold import (
    CONTROL_PLANE_FILES,
    DEFAULT_DOMAINS,
    DOMAIN_DIRECTORIES,
    INBOX_FILES,
    KNOWLEDGE_FILES,
    METRIC_FILES,
    PROJECT_CONFIG_FILES,
    ROOT_MARKER_FILENAME,
    STANDARD_LANES,
    domain_path,
    expand_path,
    harness_path,
    shared_factory_path,
)


ROOT_FILES = (
    ROOT_MARKER_FILENAME,
)

HARNESS_ROOT_FILES = (
    CONFIG_FILENAME,
    "README.md",
    "ROUTER.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTEXT.md",
    "RULES.md",
    "TOOLS.md",
    "MEMORY.md",
    "agentic-os.lock.json",
    "UPDATE_POLICY.md",
)

LEGACY_ROOT_FOLDERS = (
    "domains",
    "workflows",
    "automations",
    "inbox",
    "runs",
    "context",
    "memory",
    "notion",
    "config",
    "templates",
    "lenders",
    "shared_factory",
    "bin",
    "commands",
    "skills",
    "mcp",
    "plugins",
    "libraries",
    "hooks",
    "rules",
    "registries",
    "logs",
    "security",
)

REQUIRED_CORE_MCP_SERVERS = (
    "context_mode",
    "genomes_brain",
)

REQUIRED_CORE_LIBRARIES = (
    "context_mode",
    "unified_memory",
)

REQUIRED_CORE_HOOKS = (
    "memory-write-router",
    "memory-session-start",
    "memory-stop",
    "harness-trace-emitter",
    "context-mode-cache-heal",
)


SHARED_KNOWLEDGE_FILES = (
    "templates/domain/context.md",
    "templates/workflow/workflow.md",
    "templates/room/context.md",
    "templates/room/router.md",
    "templates/room/routing-table.md",
    "templates/stage/stage-context.md",
    "templates/reference/naming-conventions.md",
    "templates/reference/tool-index.md",
    "templates/reference/style-and-output-rules.md",
    "templates/reference/source-priority.md",
    "templates/reference/decision-log.md",
    "references/naming-conventions.md",
    "references/tool-index.md",
    "references/style-and-output-rules.md",
    "references/source-priority.md",
    "references/decision-log.md",
    "templates/profile/customer-os-profile.yml",
    "templates/customer/client-automation-brief.md",
    "templates/customer/automation-fit-matrix.md",
    "templates/customer/customer-handoff-checklist.md",
    "templates/planning/feature-spec.md",
    "templates/planning/future-idea.md",
    "templates/system/host-tool-registry.yml",
    "templates/system/shell-shape.yml",
    "templates/runtime/heartbeat.yml",
    "templates/runtime/schedule.yml",
    "templates/runtime/execution-target.yml",
    "templates/runtime/integration.yml",
    "templates/runtime/run-queue-item.yml",
    "templates/notion/control-plane-database-spec.md",
    "templates/notion/runtime-tracking-database-spec.md",
    "templates/runtime/connected-system.yml",
    "templates/runtime/source-provider.yml",
    "templates/runtime/watch-source.yml",
    "templates/runtime/watch-cursor.yml",
    "templates/runtime/source-event.yml",
    "templates/runtime/trigger-rule.yml",
    "templates/runtime/event-envelope.yml",
    "templates/runtime/event-ledger-index.md",
    "templates/runtime/chain-rule.yml",
    "templates/runtime/event-processing-result.yml",
    "templates/runtime/dead-letter-event.yml",
    "templates/runtime/update-grant.json",
    "templates/runtime/backup-policy.yml",
    "templates/runtime/managed-templates.yml",
    "templates/runtime/self-improvement.yml",
    "templates/runtime/self-improvement-workflow.md",
    "templates/runtime/self-improvement-review.yml",
    "templates/runtime/self-improvement-proposal.yml",
    "templates/runtime/self-improvement-usage-sidecar.json",
    "templates/agent-config/AGENTS.md",
    "templates/agent-config/CLAUDE.md",
    "templates/agent-config/ROUTER.md",
    "templates/agent-config/CONTEXT.md",
    "templates/agent-config/RULES.md",
    "templates/agent-config/TOOLS.md",
    "templates/agent-config/codex-config-layer-map.yml",
    "templates/agent-config/codex-profile-manifest.yml",
    "templates/agent-config/codex-profiles.toml",
    "templates/agent-config/prompt-stitching-map.yml",
    "templates/agent-config/otel-mcp-contract.yml",
    "operating-manual/README.md",
    "operating-manual/index.html",
    "operating-manual/manual-manifest.yml",
    "operating-manual/00-start-here/update-contract.md",
    "operating-manual/03-file-formats/README.md",
    "operating-manual/04-recipes/README.md",
    "operating-manual/07-diagrams/layer-map.svg",
    "operating-manual/07-diagrams/running-os-loop.svg",
    "commands/os-route.md",
    "commands/os-create-workflow.md",
    "commands/os-create-automation.md",
    "commands/os-doctor.md",
    "commands/os-update.md",
    "commands/os-client-automation-brief.md",
    "commands/os-control-plane-bootstrap.md",
    "commands/os-context-audit.md",
    "commands/os-watch-source.md",
    "commands/os-event.md",
    "commands/os-chain.md",
    "commands/os-capture-plan.md",
    "commands/os-discover-rooms.md",
    "commands/os-runtime-init.md",
    "commands/os-heartbeat.md",
    "commands/os-integration-setup.md",
    "commands/os-self-improvement.md",
    "commands/system-tool-registry.md",
    "plans/README.md",
    "plans/00-current-state-and-gap-map.md",
    "plans/09-future-ideas-intake.md",
    "plans/11-room-first-installer-and-routing.md",
    "plans/12-factory-template-import-backlog.md",
    "plans/13-reference-and-skill-index-layer.md",
    "plans/14-client-automation-and-control-plane-playbooks.md",
    "plans/15-always-on-runtime-heartbeats-schedules-and-integrations.md",
    "plans/16-connected-source-watch-registry.md",
    "plans/17-event-graph-and-chained-automations.md",
    "plans/22-project-work-lifecycle-and-conversation-auto-logging.md",
    "skills/os-navigator/SKILL.md",
    "skills/room-builder/SKILL.md",
    "skills/workflow-builder/SKILL.md",
    "skills/automation-qualifier/SKILL.md",
    "skills/os-doctor/SKILL.md",
    "skills/client-automation-brief/SKILL.md",
    "skills/control-plane-bootstrap/SKILL.md",
    "skills/context-audit/SKILL.md",
    "skills/runtime-operator/SKILL.md",
    "skills/integration-setup/SKILL.md",
    "skills/source-watcher/SKILL.md",
    "skills/event-graph-operator/SKILL.md",
    "skills/toolsmith-reviewer/SKILL.md",
)

SELF_IMPROVEMENT_REQUIRED_FILES = (
    "harness/shared_factory/00-control-plane/self-improvement.yml",
    "harness/shared_factory/00-control-plane/managed-templates.yml",
    "harness/shared_factory/04-workflows/self-improvement-review.md",
)

SELF_IMPROVEMENT_REQUIRED_DIRS = (
    "harness/shared_factory/06-runs-and-logs/self-improvement/runs",
    "harness/shared_factory/06-runs-and-logs/self-improvement/proposals",
    "harness/shared_factory/06-runs-and-logs/self-improvement/approvals",
    "harness/shared_factory/06-runs-and-logs/self-improvement/drafts",
)


@dataclass
class ValidationResult:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def require_file(path: Path, result: ValidationResult) -> None:
    if not path.is_file():
        result.errors.append(f"missing required file: {path}")


def require_dir(path: Path, result: ValidationResult) -> None:
    if not path.is_dir():
        result.errors.append(f"missing required folder: {path}")


def validate_claude_adapter(path: Path, result: ValidationResult) -> None:
    if not path.is_file():
        return
    content = path.read_text(encoding="utf-8").strip()
    if content != "@AGENTS.md":
        result.errors.append(f"CLAUDE.md must be an @AGENTS.md adapter: {path}")


def warn_legacy_agent(path: Path, result: ValidationResult) -> None:
    if path.exists():
        result.warnings.append(f"legacy AGENT.md present without compatibility mode: {path}")


def validate_agent_layer(layer_root: Path, result: ValidationResult) -> None:
    for filename in (CONFIG_FILENAME, "AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
        require_file(layer_root / filename, result)
    validate_claude_adapter(layer_root / "CLAUDE.md", result)
    warn_legacy_agent(layer_root / "AGENT.md", result)


def validate_project_worktrees(project_root: Path, result: ValidationResult) -> None:
    index_path = project_root / "worktrees" / "index.yml"
    data = load_control_yaml(index_path, result)
    worktrees = data.get("worktrees")
    if worktrees is None:
        result.errors.append(f"project worktree index missing worktrees list: {index_path}")
        return
    if not isinstance(worktrees, list):
        result.errors.append(f"project worktree index worktrees must be a list: {index_path}")
        return

    seen_ids: set[str] = set()
    for entry in worktrees:
        if not isinstance(entry, dict):
            result.errors.append(f"project worktree entry must be a mapping: {index_path}")
            continue
        worktree_id = str(entry.get("id") or "")
        path_value = str(entry.get("path") or "")
        link_value = str(entry.get("link") or "")
        if not worktree_id or not path_value or not link_value:
            result.errors.append(f"project worktree entry missing id, path, or link: {index_path}")
            continue
        if worktree_id in seen_ids:
            result.errors.append(f"duplicate project worktree id {worktree_id!r}: {index_path}")
        seen_ids.add(worktree_id)
        link_path = project_root / link_value
        if not link_path.is_symlink():
            result.errors.append(f"project worktree link is missing or not a symlink: {link_path}")
        target_path = Path(path_value).expanduser()
        if not target_path.exists():
            result.warnings.append(f"project worktree target is missing: {target_path}")


def validate_project_layer(project_root: Path, result: ValidationResult) -> None:
    validate_agent_layer(project_root, result)
    for filename in ("README.md", "project.yml", "status.md", "source-map.md", "decisions.md"):
        require_file(project_root / filename, result)
    for directory in ("artifacts", "config", "ideas", "work-items", "worktrees"):
        require_dir(project_root / directory, result)
    for filename in PROJECT_CONFIG_FILES:
        require_file(project_root / "config" / filename, result)
    require_file(project_root / "ideas" / "README.md", result)
    require_file(project_root / "ideas" / "raw-ideas.md", result)
    require_file(project_root / "worktrees" / "README.md", result)
    require_file(project_root / "worktrees" / "index.yml", result)
    validate_project_worktrees(project_root, result)
    validate_project_work_items(project_root, result)


def validate_project_work_items(project_root: Path, result: ValidationResult) -> None:
    work_items_root = project_root / "work-items"
    if not work_items_root.is_dir():
        return
    for work_item_root in sorted(path for path in work_items_root.iterdir() if path.is_dir()):
        metadata_path = metadata_path_for(work_item_root)
        if metadata_path is None:
            result.errors.append(
                f"work item missing metadata file ({', '.join(WORK_ITEM_METADATA_FILES)}): {work_item_root}"
            )
            continue
        metadata = load_yaml_mapping(metadata_path)
        status = lifecycle_status(metadata)
        if status not in WORK_LIFECYCLE_STATES:
            result.errors.append(f"work item has invalid lifecycle status {status!r}: {metadata_path}")
        for directory in WORK_ITEM_DIRECTORIES:
            require_dir(work_item_root / directory, result)
    for record in local_project_work_items(project_root):
        for path in record.missing_required_files:
            result.errors.append(f"work item {record.path.name} status {record.status!r} missing required file: {path}")
        for log_file in conversation_log_files(record.path):
            content = log_file.read_text(encoding="utf-8", errors="replace")
            if contains_token_shaped_value(content):
                result.errors.append(f"conversation log contains token-shaped value: {log_file}")


def validate_domain(domain_root: Path, result: ValidationResult) -> None:
    require_dir(domain_root, result)
    require_file(domain_root / CONFIG_FILENAME, result)
    require_file(domain_root / "README.md", result)
    require_file(domain_root / "ROUTER.md", result)
    require_file(domain_root / "AGENTS.md", result)
    require_file(domain_root / "CLAUDE.md", result)
    require_file(domain_root / "CONTEXT.md", result)
    require_file(domain_root / "RULES.md", result)
    require_file(domain_root / "TOOLS.md", result)
    require_file(domain_root / "MEMORY.md", result)
    require_file(domain_root / "REFERENCES.md", result)
    require_file(domain_root / "domain.yml", result)
    validate_claude_adapter(domain_root / "CLAUDE.md", result)
    warn_legacy_agent(domain_root / "AGENT.md", result)

    for directory in DOMAIN_DIRECTORIES:
        require_dir(domain_root / directory, result)

    for filename in CONTROL_PLANE_FILES:
        require_file(domain_root / "00-control-plane" / filename, result)

    for filename in INBOX_FILES:
        require_file(domain_root / "01-inbox" / filename, result)

    require_file(domain_root / "02-projects" / "README.md", result)
    require_file(domain_root / "03-workflows" / "README.md", result)
    require_file(domain_root / "04-automations" / "README.md", result)

    for lane in STANDARD_LANES:
        require_dir(domain_root / "03-workflows" / lane, result)
        require_dir(domain_root / "04-automations" / lane, result)
        require_file(domain_root / "03-workflows" / lane / "README.md", result)
        require_file(domain_root / "04-automations" / lane / "README.md", result)

    for filename in KNOWLEDGE_FILES:
        require_file(domain_root / "05-knowledge" / filename, result)

    require_file(domain_root / "06-runs-and-logs" / "activity-log.md", result)
    require_file(domain_root / "06-runs-and-logs" / "runs" / "README.md", result)
    require_file(domain_root / "06-runs-and-logs" / "failures" / "README.md", result)

    for filename in METRIC_FILES:
        require_file(domain_root / "07-metrics" / filename, result)

    require_file(domain_root / "08-archive" / "README.md", result)

    for project_config in sorted((domain_root / "02-projects").glob("*/project.yml")):
        validate_project_layer(project_config.parent, result)
    for workflow_spec in sorted((domain_root / "03-workflows").glob("*/*/workflow.md")):
        validate_agent_layer(workflow_spec.parent, result)
    for automation_spec in sorted((domain_root / "04-automations").glob("*/*/automation.md")):
        validate_agent_layer(automation_spec.parent, result)


def load_control_yaml(path: Path, result: ValidationResult) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        result.errors.append(f"invalid YAML: {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def validate_watch_registries(root: Path, result: ValidationResult) -> None:
    control = shared_factory_path(root, "00-control-plane")
    connected_path = control / "connected-systems.yml"
    providers_path = control / "source-providers.yml"
    sources_path = control / "watch-sources.yml"
    if not any(path.exists() for path in (connected_path, providers_path, sources_path)):
        return

    providers = load_control_yaml(providers_path, result).get("source_providers") or []
    provider_status = {
        str(provider.get("id")): provider.get("status")
        for provider in providers
        if isinstance(provider, dict) and provider.get("id")
    }
    systems = load_control_yaml(connected_path, result).get("connected_systems") or []
    systems_by_id = {
        str(system.get("id")): system for system in systems if isinstance(system, dict) and system.get("id")
    }

    for system in systems_by_id.values():
        system_id = system.get("id")
        priority = [str(provider) for provider in system.get("provider_priority") or []]
        if not priority:
            result.errors.append(f"connected system {system_id} missing provider_priority: {connected_path}")
            continue
        missing = [provider for provider in priority if provider not in provider_status]
        if missing:
            result.errors.append(f"connected system {system_id} references missing providers {', '.join(missing)}: {connected_path}")
        if not any(provider_status.get(provider) != "unavailable" for provider in priority if provider in provider_status):
            result.errors.append(f"connected system {system_id} has no healthy provider: {connected_path}")

    sources = load_control_yaml(sources_path, result).get("watch_sources") or []
    for source in [source for source in sources if isinstance(source, dict)]:
        source_id = source.get("id") or "<missing>"
        system_id = str(source.get("connected_system") or "")
        system = systems_by_id.get(system_id)
        if not system:
            result.errors.append(f"watch source {source_id} references missing connected_system: {sources_path}")
        elif not any(provider_status.get(provider) != "unavailable" for provider in system.get("provider_priority") or []):
            result.errors.append(f"watch source {source_id} connected_system has no healthy provider: {sources_path}")
        if not source.get("source_type"):
            result.errors.append(f"watch source {source_id} missing source_type: {sources_path}")
        if not source.get("external_ref"):
            result.errors.append(f"watch source {source_id} missing external_ref: {sources_path}")
        cursor = source.get("cursor") or {}
        if not cursor.get("type") or not cursor.get("state_ref"):
            result.errors.append(f"watch source {source_id} missing cursor type or state_ref: {sources_path}")
        if not (source.get("dedupe") or {}).get("idempotency_key"):
            result.errors.append(f"watch source {source_id} missing dedupe idempotency_key: {sources_path}")
        route = source.get("route") or {}
        if not route.get("command") or not route.get("context_command") or not route.get("fallback_domain"):
            result.errors.append(f"watch source {source_id} missing route command, context_command, or fallback_domain: {sources_path}")
        outputs = source.get("outputs") or {}
        if not outputs.get("source_events_dir") or not outputs.get("run_queue_ref"):
            result.errors.append(f"watch source {source_id} missing source_events_dir or run_queue_ref: {sources_path}")
        if source.get("enabled") and source.get("watch_method") not in {"poll", "manual_replay", "file_watch"}:
            result.errors.append(f"watch source {source_id} has unsafe enabled watch_method: {sources_path}")
        trigger_rules = source.get("trigger_rules") or []
        if source.get("enabled") and not trigger_rules:
            result.errors.append(f"watch source {source_id} enabled without trigger_rules: {sources_path}")
        for rule in trigger_rules:
            if isinstance(rule, str):
                continue
            if not isinstance(rule, dict):
                result.errors.append(f"watch source {source_id} has invalid trigger rule: {sources_path}")
                continue
            if not rule.get("enabled"):
                continue
            rule_id = rule.get("id") or "<missing>"
            if not rule.get("id"):
                result.errors.append(f"watch source {source_id} enabled trigger rule missing id: {sources_path}")
            if not (rule.get("when") or {}).get("event_type"):
                result.errors.append(f"watch source {source_id} trigger rule {rule_id} missing event_type: {sources_path}")
            then = rule.get("then") or {}
            if not (then.get("emit_event") or then.get("enqueue")):
                result.errors.append(f"watch source {source_id} trigger rule {rule_id} missing action: {sources_path}")
            if not (rule.get("idempotency") or {}).get("key"):
                result.errors.append(f"watch source {source_id} trigger rule {rule_id} missing idempotency key: {sources_path}")


def validate_capability_registries(root: Path, result: ValidationResult) -> None:
    capabilities_path = root / REGISTRY_FILES["capabilities"]
    if not capabilities_path.is_file():
        return

    typed_ids: dict[str, set[str]] = {}
    for capability_type, collection in CAPABILITY_COLLECTIONS.items():
        relative_path = REGISTRY_FILES[collection]
        path = root / relative_path
        if not path.is_file():
            continue
        typed_ids[capability_type] = {
            str(entry.get("id"))
            for entry in load_registry(path, collection)
            if entry.get("id")
        }

    for entry in load_registry(capabilities_path, "capabilities"):
        capability_id = str(entry.get("id") or "<missing>")
        capability_type = str(entry.get("type") or "")
        ref = str(entry.get("ref") or "")
        if capability_type not in CAPABILITY_COLLECTIONS:
            result.errors.append(f"capability {capability_id} has unknown type {capability_type!r}: {capabilities_path}")
            continue
        if not ref:
            result.errors.append(f"capability {capability_id} missing ref: {capabilities_path}")
            continue
        if ref not in typed_ids.get(capability_type, set()):
            registry_name = CAPABILITY_COLLECTIONS[capability_type]
            result.errors.append(
                f"capability {capability_id} references missing {capability_type} {ref!r} in {REGISTRY_FILES[registry_name]}"
            )


def validate_registered_hooks(root: Path, result: ValidationResult) -> None:
    hooks_path = root / REGISTRY_FILES["hooks"]
    if not hooks_path.is_file():
        return
    for entry in load_registry(hooks_path, "hooks"):
        source = str(entry.get("source") or "")
        if not source.startswith("harness/hooks/"):
            continue
        path = root / source
        if not path.is_file():
            result.errors.append(f"registered hook file is missing: {path}")
            continue
        mode = path.stat().st_mode & 0o777
        if not mode & 0o111:
            result.errors.append(f"registered hook file is not executable: {path}")


def validate_required_runtime_integrations(root: Path, result: ValidationResult) -> None:
    checks = (
        ("mcp_servers", REQUIRED_CORE_MCP_SERVERS, "required runtime MCP server"),
        ("libraries", REQUIRED_CORE_LIBRARIES, "required runtime library"),
        ("hooks", REQUIRED_CORE_HOOKS, "required runtime hook"),
    )
    for registry_name, required_ids, label in checks:
        relative_path = REGISTRY_FILES[registry_name]
        path = root / relative_path
        if not path.is_file():
            continue
        present = {
            str(entry.get("id"))
            for entry in load_registry(path, registry_name)
            if entry.get("id")
        }
        for required_id in required_ids:
            if required_id not in present:
                result.errors.append(f"missing {label} {required_id!r}: {path}")


def validate_update_backup_contract(root: Path, result: ValidationResult) -> None:
    backup_policy_path = harness_path(root, "registries", "backup-policy.yml")
    backup_policy = load_control_yaml(backup_policy_path, result).get("backup_policy") or {}
    if backup_policy:
        if not backup_policy.get("include"):
            result.errors.append(f"backup policy missing include list: {backup_policy_path}")
        if not backup_policy.get("exclude"):
            result.errors.append(f"backup policy missing exclude list: {backup_policy_path}")

    grant_path = harness_path(root, "registries", "update-grant.json")
    if not grant_path.is_file():
        return
    try:
        grant = json.loads(grant_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"invalid JSON: {grant_path}: {exc}")
        return
    remotes = grant.get("remotes") or {}
    if not (remotes.get("update") or {}).get("url"):
        result.errors.append(f"update grant missing update remote URL: {grant_path}")
    if not (remotes.get("backup") or {}).get("url"):
        result.errors.append(f"update grant missing backup remote URL: {grant_path}")
    if (remotes.get("update") or {}).get("url") == (remotes.get("backup") or {}).get("url"):
        result.errors.append(f"update and backup remotes must be separate: {grant_path}")
    for key_name in ("update_ed25519", "backup_ed25519"):
        key_path = harness_path(root, "security", "ssh", key_name)
        if not key_path.is_file():
            result.errors.append(f"missing private key for update grant: {key_path}")
            continue
        mode = key_path.stat().st_mode & 0o777
        if mode != 0o600:
            result.errors.append(f"private key must use mode 0600: {key_path}")


def validate_root(root: str | Path) -> ValidationResult:
    os_root = expand_path(root)
    result = ValidationResult(root=os_root)
    if not os_root.exists():
        result.errors.append(f"missing root: {os_root}")
        return result
    if not os_root.is_dir():
        result.errors.append(f"root is not a directory: {os_root}")
        return result

    for filename in ROOT_FILES:
        require_file(os_root / filename, result)
    harness_root = harness_path(os_root)
    for filename in HARNESS_ROOT_FILES:
        require_file(harness_root / filename, result)
    validate_claude_adapter(harness_root / "CLAUDE.md", result)
    warn_legacy_agent(harness_root / "AGENT.md", result)

    for directory in VISIBLE_CAPABILITY_DIRECTORIES:
        require_dir(os_root / directory, result)
    require_file(harness_path(os_root, "INVENTORY.md"), result)
    for relative_path in REGISTRY_FILES.values():
        require_file(os_root / relative_path, result)
    require_file(harness_path(os_root, "registries", "updates.yml"), result)
    require_file(harness_path(os_root, "registries", "customer-identity.json"), result)
    require_file(harness_path(os_root, "registries", "backup-policy.yml"), result)
    require_dir(harness_path(os_root, "security", "ssh"), result)
    require_dir(harness_path(os_root, "logs", "updates"), result)
    require_dir(harness_path(os_root, "logs", "backups"), result)
    validate_capability_registries(os_root, result)
    validate_registered_hooks(os_root, result)
    validate_required_runtime_integrations(os_root, result)
    validate_update_backup_contract(os_root, result)

    profile_domains = profile_domain_names(os_root)
    domains_to_validate = profile_domains or list(DEFAULT_DOMAINS)
    for domain in domains_to_validate:
        validate_domain(domain_path(os_root, domain), result)
    if not profile_domains:
        validate_domain(shared_factory_path(os_root), result)

    shared_knowledge = shared_factory_path(os_root, "05-knowledge")
    for filename in SHARED_KNOWLEDGE_FILES:
        require_file(shared_knowledge / filename, result)
    for relative_path in SELF_IMPROVEMENT_REQUIRED_FILES:
        require_file(os_root / relative_path, result)
    for relative_path in SELF_IMPROVEMENT_REQUIRED_DIRS:
        require_dir(os_root / relative_path, result)
    validate_watch_registries(os_root, result)

    for folder in LEGACY_ROOT_FOLDERS:
        path = os_root / folder
        if path.exists():
            result.warnings.append(f"legacy root folder present: {path}")

    for path in sorted(os_root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.errors.append(f"invalid JSON: {path}: {exc}")

    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(os_root.rglob(pattern)):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                result.errors.append(f"invalid YAML: {path}: {exc}")

    return result


def profile_domain_names(root: Path) -> list[str]:
    for filename in ("profile.yml", "customer.yml"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return []
        if filename == "profile.yml":
            rooms = data.get("rooms") or []
            return [str(room.get("slug")) for room in rooms if isinstance(room, dict) and room.get("slug")]
        customer = data.get("customer") or {}
        domains = customer.get("approved_domains") or []
        return [str(domain) for domain in domains]
    return []
