"""Validation for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import yaml

from .artifact_contracts import artifact_contract_doctor
from .investigation_contracts import investigation_contract_doctor
from .runtime_backend import runtime_queue_items
from .artifact_naming import CONFIG_RELATIVE_PATH, load_artifact_naming_policy
from .capability_registry import CAPABILITY_COLLECTIONS, REGISTRY_FILES, VISIBLE_CAPABILITY_DIRECTORIES, load_registry
from .config_ops import CONFIG_FILENAME
from .context_compaction import check_context_contracts
from .lifecycle import (
    WORK_ITEM_LANES,
    WORK_ITEM_DIRECTORIES,
    WORK_ITEM_METADATA_FILES,
    WORK_LIFECYCLE_STATES,
    WorkItemRecord,
    contains_token_shaped_value,
    conversation_log_files,
    lifecycle_status,
    load_yaml_mapping,
    local_work_item_candidates,
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
    _remotes_from_config,
    domain_path,
    expand_path,
    harness_path,
    installed_domain_names,
    shared_factory_path,
)
from .hosts import load_hosts


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
    "workflows",
    "automations",
    "inbox",
    "runs",
    "context",
    "memory",
    "notion",
    "templates",
    "lenders",
    "shared_factory",
    "artifact-config",
    "bin",
    "commands",
    "skills",
    "mcp",
    "plugins",
    "libraries",
    "hooks",
    "investigation-config",
    "reports",
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
    "session-prayer-start",
    "memory-write-router",
    "memory-session-start",
    "memory-stop",
    "harness-trace-emitter",
    "conversation-auto-log",
    "context-mode-cache-heal",
    "context-mode-codex-hooks",
    "mempalace-claude-hooks",
)


SHARED_KNOWLEDGE_FILES = (
    "templates/domain/context.md",
    "templates/workflow/workflow.md",
    "templates/room/context.md",
    "templates/room/router.md",
    "templates/room/routing-table.md",
    "templates/stage/stage-context.md",
    "templates/reference/naming-conventions.md",
    "templates/reference/os-conventions.md",
    "templates/reference/tool-index.md",
    "templates/reference/style-and-output-rules.md",
    "templates/reference/source-priority.md",
    "templates/reference/decision-log.md",
    "references/naming-conventions.md",
    "references/os-conventions.md",
    "references/tool-index.md",
    "references/style-and-output-rules.md",
    "references/source-priority.md",
    "references/decision-log.md",
    "templates/profile/customer-os-profile.yml",
    "templates/customer/client-automation-brief.md",
    "templates/customer/automation-fit-matrix.md",
    "templates/customer/customer-handoff-checklist.md",
    "templates/planning/bug-report.md",
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
    "templates/runtime/documentation-upkeep.yml",
    "templates/runtime/doc-config.yml",
    "templates/runtime/notion-organization.yml",
    "templates/runtime/spec-intake-workflow.md",
    "templates/runtime/feature-intake-workflow.md",
    "templates/runtime/bug-intake-workflow.md",
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
    "commands/os-run-queue.md",
    "commands/os-ps.md",
    "commands/os-heartbeat.md",
    "commands/os-integration-setup.md",
    "commands/os-self-improvement.md",
    "commands/os-docs-upkeep.md",
    "commands/os-doc-config.md",
    "commands/os-notion-org.md",
    "commands/os-add-spec.md",
    "commands/os-groom-spec.md",
    "commands/os-new-feature.md",
    "commands/os-add-bug.md",
    "commands/os-auto-add-spec.md",
    "commands/os-auto-add-feature.md",
    "commands/os-end-chat.md",
    "commands/system-tool-registry.md",
    "skills/os-navigator/SKILL.md",
    "skills/room-builder/SKILL.md",
    "skills/workflow-builder/SKILL.md",
    "skills/doc-config-router/SKILL.md",
    "skills/spec-intake-router/SKILL.md",
    "skills/spec-groomer/SKILL.md",
    "skills/feature-intake-router/SKILL.md",
    "skills/bug-intake-router/SKILL.md",
    "skills/auto-spec-intake/SKILL.md",
    "skills/auto-feature-intake/SKILL.md",
    "skills/os-authoring-guard/SKILL.md",
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
    "rules/os-authoring-rules.md",
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
    compact = (layer_root / "context-contract.yml").is_file()
    required = (
        (CONFIG_FILENAME, "AGENTS.md", "CLAUDE.md", "PROFILE.md", "context-contract.yml")
        if compact
        else (CONFIG_FILENAME, "AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md")
    )
    for filename in required:
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
        target_path = Path(path_value).expanduser()
        if link_path.is_symlink():
            pass
        elif link_path.is_dir():
            # in-place worktree: the checkout itself lives under worktrees/
            if link_path.resolve() != target_path.resolve():
                result.errors.append(
                    f"project worktree directory does not match entry path: {link_path}"
                )
        else:
            result.warnings.append(
                f"project worktree link is missing or not a symlink or directory: {link_path}"
            )
        if not target_path.exists():
            result.warnings.append(f"project worktree target is missing: {target_path}")


def validate_project_code_settings(project_root: Path, result: ValidationResult) -> None:
    """Validate the project-wide code/worktree policy in development.yml."""
    path = project_root / "config" / "development.yml"
    data = load_control_yaml(path, result)
    if not data:
        return
    if not isinstance(data.get("enabled", True), bool):
        result.errors.append(f"project code setting enabled must be a boolean: {path}")
    repository = data.get("repository")
    if not isinstance(repository, dict):
        result.errors.append(f"project code setting repository must be a mapping: {path}")
    else:
        root = repository.get("root", "")
        if root is not None and not isinstance(root, str):
            result.errors.append(f"project code setting repository.root must be a path string: {path}")
        base_branch = repository.get("base_branch", "main")
        if not isinstance(base_branch, str) or not base_branch.strip():
            result.errors.append(f"project code setting repository.base_branch must be non-empty: {path}")
    worktrees = data.get("worktrees")
    if not isinstance(worktrees, dict):
        result.errors.append(f"project code setting worktrees must be a mapping: {path}")
        return
    directory = worktrees.get("directory", "worktrees")
    if not isinstance(directory, str) or not directory.strip():
        result.errors.append(f"project code setting worktrees.directory must be a non-empty path: {path}")
    date_prefix = worktrees.get("date_prefix", "inherit")
    if date_prefix != "inherit" and not isinstance(date_prefix, bool):
        result.errors.append(
            f"project code setting worktrees.date_prefix must be 'inherit', true, or false: {path}"
        )
    branch_template = worktrees.get("branch_template", "feature/{ticket}-{slug}")
    if not isinstance(branch_template, str):
        result.errors.append(f"project code setting worktrees.branch_template must be a string: {path}")
    else:
        try:
            branch_template.format(ticket="ticket", slug="slug")
        except (KeyError, ValueError) as exc:
            result.errors.append(f"invalid project code setting worktrees.branch_template in {path}: {exc}")
    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        result.errors.append(f"project code setting runtime must be a mapping: {path}")
        return
    ownership = str(runtime.get("ownership") or "").strip()
    provider = str(runtime.get("provider") or "").strip()
    if ownership == "not_managed":
        if provider != "none":
            result.errors.append(
                f"project code setting runtime.provider must be none when ownership is not_managed: {path}"
            )
        if runtime.get("identity") != "not-managed":
            result.errors.append(
                f"project code setting runtime.identity must be not-managed when ownership is not_managed: {path}"
            )
    elif ownership == "managed":
        identity_template = str(runtime.get("identity_template") or "").strip()
        if not provider or provider == "none":
            result.errors.append(
                f"project code setting managed runtime.provider must name the provider: {path}"
            )
        if not identity_template:
            result.errors.append(
                f"project code setting managed runtime.identity_template is required: {path}"
            )
        else:
            required_fields = ("{domain}", "{project}", "{worktree}")
            if not all(field in identity_template for field in required_fields):
                result.errors.append(
                    "project code setting managed runtime.identity_template must include "
                    f"{{domain}}, {{project}}, and {{worktree}} for globally item-unique ownership: {path}"
                )
            try:
                resolved_identity = identity_template.format(
                    domain="domain",
                    project="project",
                    worktree="worktree",
                    worktree_path="/worktree/path",
                    ticket="ticket",
                )
                if not resolved_identity.strip() or resolved_identity == "not-managed":
                    result.errors.append(
                        f"project code setting managed runtime.identity_template must resolve to a managed identity: {path}"
                    )
            except (KeyError, ValueError) as exc:
                result.errors.append(
                    f"invalid project code setting managed runtime.identity_template in {path}: {exc}"
                )
        for field in ("teardown_command", "readback_command"):
            command = str(runtime.get(field) or "").strip()
            if not command:
                result.errors.append(
                    f"project code setting managed runtime.{field} is required: {path}"
                )
            elif "{runtime_identity}" not in command:
                result.errors.append(
                    f"project code setting managed runtime.{field} must include "
                    f"{{runtime_identity}} for exact-target execution: {path}"
                )
            elif any(
                forbidden in command.lower()
                for forbidden in (
                    "system prune",
                    "container prune",
                    "volume prune",
                    "worktree prune",
                    "--all",
                    "delete all",
                )
            ):
                result.errors.append(
                    f"project code setting managed runtime.{field} contains a forbidden global cleanup operation: {path}"
                )
    else:
        result.errors.append(
            f"project code setting runtime.ownership must be managed or not_managed: {path}"
        )
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    authorship = review.get("authorship") if isinstance(review.get("authorship"), dict) else {}
    ours = authorship.get("ours")
    if not (
        isinstance(ours, list)
        and all(isinstance(identity, str) and identity.strip() and ":" in identity for identity in ours)
    ):
        result.errors.append(
            "project code setting review.authorship.ours must contain only "
            f"provider-qualified identities: {path}"
        )
    elif not ours:
        result.warnings.append(
            "project review.authorship.ours is empty; PR-authority Auto-Dev stages "
            f"will fail closed until domain/project setup records a real identity: {path}"
        )


def validate_project_layer(project_root: Path, result: ValidationResult) -> None:
    validate_agent_layer(project_root, result)
    for filename in ("README.md", "project.yml", "status.md", "source-map.md", "decisions.md"):
        require_file(project_root / filename, result)
    for directory in ("artifacts", "config", "ideas", "work-items", "worktrees"):
        require_dir(project_root / directory, result)
    if not ((project_root / "worklogs").is_dir() or (project_root / "WORKLOGS").is_dir()):
        result.warnings.append(f"missing recommended worklogs folder: {project_root / 'worklogs'} or {project_root / 'WORKLOGS'}")
    for legacy_bucket in ("features", ".features", "PLANS", "BUILD_LOGS"):
        legacy_path = project_root / legacy_bucket
        if legacy_path.exists():
            result.warnings.append(
                f"legacy project bucket present; prefer work-items/ or worklogs/: {legacy_path}"
            )
    for filename in PROJECT_CONFIG_FILES:
        require_file(project_root / "config" / filename, result)
    if (project_root / "SPECS").exists():
        result.warnings.append(
            f"legacy project bucket present; verify Jira/Linear truth before removal: {project_root / 'SPECS'}"
        )
    require_file(project_root / "ideas" / "README.md", result)
    require_file(project_root / "ideas" / "raw-ideas.md", result)
    if (project_root / "WORKLOGS").is_dir():
        require_file(project_root / "WORKLOGS" / "README.md", result)
    elif (project_root / "worklogs").is_dir():
        require_file(project_root / "worklogs" / "README.md", result)
    lifecycle_path = project_root / "config" / "work-lifecycle.yml"
    lifecycle = load_control_yaml(lifecycle_path, result).get("work_lifecycle") or {}
    if lifecycle.get("source_of_truth") != "state_db":
        for lane in WORK_ITEM_LANES:
            require_dir(project_root / "work-items" / lane, result)
    require_file(project_root / "worktrees" / "README.md", result)
    require_file(project_root / "worktrees" / "index.yml", result)
    validate_project_code_settings(project_root, result)
    validate_project_worktrees(project_root, result)
    validate_project_work_items(project_root, result)
    # Load hosts registry for remote validation (best-effort; errors surfaced below).
    # root_candidate: <os-root>/<domain>/02-projects/<project> → parent×3 = <os-root>
    root_candidate = project_root.parent.parent.parent
    hosts_yml = root_candidate / "config" / "hosts.yml"
    if hosts_yml.is_file():
        try:
            hosts: dict[str, Any] | None = load_hosts(root_candidate)
        except Exception:
            hosts = {}
    else:
        # hosts.yml not yet created (pre-migration); skip host-reference check
        hosts = None
    validate_project_remotes(project_root, result, hosts)


def validate_project_remotes(
    project_root: Path,
    result: ValidationResult,
    hosts: dict[str, Any] | None,
) -> None:
    """Validate declared remote sources for a single project.

    Parameters
    ----------
    hosts:
        The loaded hosts registry (alias → entry dict).  Pass ``None`` to
        indicate that ``config/hosts.yml`` does not exist yet (pre-migration);
        in that case the host-reference check is skipped.  Pass ``{}`` to
        indicate the file exists but has no entries (all references unknown).

    Checks:
    - Every ``sources.remotes`` entry has ``host`` and ``path`` fields (error).
    - Every declared host exists in hosts.yml (error) — skipped when hosts is None.
    - ``remote/<name>/REMOTE.md`` and ``remote/<name>/manifest.yml`` exist (error).
    - manifest ``synced_at`` is None or older than 14 days (warning).
    """
    project_yml = project_root / "project.yml"
    if not project_yml.is_file():
        return
    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return
    if not isinstance(data, dict):
        return

    remotes = _remotes_from_config(data)
    for remote in remotes:
        name = remote.get("name", "")
        host = remote.get("host", "")
        path = remote.get("path", "")

        # (a) Required fields
        if not host or not path:
            result.errors.append(
                f"project remote {name!r} in {project_yml} is missing required "
                f"field(s): {'host' if not host else ''} {'path' if not path else ''}".strip()
            )
            continue

        # (b) Host must be in hosts.yml (only when the file exists; hosts=None → skip)
        if hosts is not None and host not in hosts:
            result.errors.append(
                f"project remote {name!r} in {project_yml} references unknown "
                f"host {host!r} (not in config/hosts.yml)"
            )

        # (c) Marker files must exist
        remote_dir = project_root / "remote" / name
        remote_md = remote_dir / "REMOTE.md"
        manifest_yml = remote_dir / "manifest.yml"
        if not remote_md.is_file():
            result.errors.append(
                f"project remote {name!r}: missing marker file {remote_md}"
            )
        if not manifest_yml.is_file():
            result.errors.append(
                f"project remote {name!r}: missing manifest file {manifest_yml}"
            )
            continue

        # (d) Staleness warning
        try:
            manifest_data = yaml.safe_load(manifest_yml.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            manifest_data = {}
        synced_at = manifest_data.get("synced_at") if isinstance(manifest_data, dict) else None
        if synced_at is None:
            result.warnings.append(
                f"project remote {name!r}: manifest has never been synced "
                f"(synced_at is null): {manifest_yml}"
            )
        else:
            try:
                synced_dt = datetime.datetime.fromisoformat(str(synced_at).rstrip("Z")).replace(
                    tzinfo=datetime.timezone.utc
                )
                age = datetime.datetime.now(datetime.timezone.utc) - synced_dt
                if age.days > 14:
                    result.warnings.append(
                        f"project remote {name!r}: manifest is stale "
                        f"({age.days} days since last sync): {manifest_yml}"
                    )
            except (ValueError, TypeError):
                pass  # unparseable synced_at — skip staleness check


def validate_project_remotes_connectivity(
    root: Path,
    hosts: dict[str, Any],
    *,
    runner: Any | None = None,
) -> list[str]:
    """Probe each registered host with a no-op SSH command.

    Used by ``config doctor --check-remotes``.  Returns a list of warning
    strings; never raises.  No network calls when *hosts* is empty.

    The injectable *runner* follows the same shape as remote_ops: callable
    ``(args: list[str], *, timeout: int) -> result-with-returncode``.
    """
    import subprocess  # noqa: PLC0415

    if runner is None:
        def runner(args: list[str], *, timeout: int = 10) -> Any:  # type: ignore[misc]
            try:
                return subprocess.run(args, capture_output=True, text=True, timeout=timeout)  # noqa: S603
            except Exception as exc:
                class _Fail:
                    returncode = 1
                    stderr = str(exc)
                return _Fail()

    warnings: list[str] = []
    for alias, entry in hosts.items():
        if not isinstance(entry, dict):
            continue
        ssh_alias = entry.get("ssh_alias") or alias
        ssh_options: list[str] = entry.get("ssh_options") or []
        args = ["ssh", "-o", "BatchMode=yes"] + list(ssh_options) + [ssh_alias, "true"]
        try:
            result = runner(args, timeout=10)
            if result.returncode != 0:
                warnings.append(
                    f"host {alias!r} (ssh_alias={ssh_alias!r}) is unreachable: "
                    f"ssh exited {result.returncode}"
                )
        except Exception as exc:
            warnings.append(f"host {alias!r} (ssh_alias={ssh_alias!r}) probe failed: {exc}")
    return warnings


def validate_project_work_items(project_root: Path, result: ValidationResult) -> None:
    work_items_root = project_root / "work-items"
    if not work_items_root.is_dir():
        return
    records: list[WorkItemRecord] = []
    for work_item_root in local_work_item_candidates(work_items_root):
        metadata_path = metadata_path_for(work_item_root)
        if metadata_path is None:
            result.errors.append(
                f"work item missing metadata file ({', '.join(WORK_ITEM_METADATA_FILES)}): {work_item_root}"
            )
            continue
        try:
            metadata = load_yaml_mapping(metadata_path)
        except (OSError, yaml.YAMLError) as exc:
            result.errors.append(f"invalid work item metadata: {metadata_path}: {exc}")
            continue
        status = lifecycle_status(metadata)
        if status not in WORK_LIFECYCLE_STATES:
            result.errors.append(f"work item has invalid lifecycle status {status!r}: {metadata_path}")
        records.append(
            WorkItemRecord(
                path=work_item_root,
                metadata_path=metadata_path,
                status=status,
                title=str(metadata.get("title") or work_item_root.name),
                slug=str(metadata.get("slug") or metadata.get("id") or work_item_root.stem),
                source="project_work_item",
                metadata=metadata,
            )
        )
        if work_item_root.is_dir():
            for directory in WORK_ITEM_DIRECTORIES:
                path = work_item_root / directory
                if not path.is_dir():
                    result.warnings.append(f"work item missing recommended folder: {path}")
    for record in records:
        for path in record.missing_required_files:
            message = f"work item {record.path.name} status {record.status!r} missing required file: {path}"
            result.warnings.append(message)
        for log_file in conversation_log_files(record.path):
            try:
                if log_file.stat().st_size > CONVERSATION_LOG_TOKEN_SCAN_MAX_BYTES:
                    result.warnings.append(
                        f"conversation log skipped token scan because file is larger than "
                        f"{CONVERSATION_LOG_TOKEN_SCAN_MAX_BYTES} bytes: {log_file}"
                    )
                    continue
            except OSError:
                continue
            content = log_file.read_text(encoding="utf-8", errors="replace")
            if contains_token_shaped_value(content):
                result.errors.append(f"conversation log contains token-shaped value: {log_file}")


def validate_domain(
    domain_root: Path,
    result: ValidationResult,
    *,
    layout_v2: bool = False,
) -> None:
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

    required_directories = (
        directory
        for directory in DOMAIN_DIRECTORIES
        if not (layout_v2 and directory == "05-knowledge")
    )
    for directory in required_directories:
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

    if not layout_v2:
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
        registry_paths = [path] if path.is_file() else []
        if capability_type in {"command", "skill", "rule", "report"}:
            scoped_patterns = (
                f"domains/*/00-control-plane/resource-registries/{collection}.yml",
                f"domains/*/02-projects/*/config/resource-registries/{collection}.yml",
                f"*/00-control-plane/resource-registries/{collection}.yml",
                f"*/02-projects/*/config/resource-registries/{collection}.yml",
            )
            registry_paths.extend(
                candidate
                for pattern in scoped_patterns
                for candidate in root.glob(pattern)
                if candidate.is_file()
            )
        typed_ids[capability_type] = {
            str(entry.get("id"))
            for registry_path in registry_paths
            for entry in load_registry(registry_path, collection)
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


def _registry_sources(root: Path, registry_name: str, collection: str) -> set[str]:
    path = root / REGISTRY_FILES[registry_name]
    if not path.is_file():
        return set()
    return {str(entry.get("source") or "") for entry in load_registry(path, collection)}


def _registry_ids(root: Path, registry_name: str, collection: str) -> set[str]:
    path = root / REGISTRY_FILES[registry_name]
    if not path.is_file():
        return set()
    return {str(entry.get("id") or "") for entry in load_registry(path, collection)}


def _library_registry_aliases(root: Path, *, kind: str) -> set[str]:
    """Return visible adapter paths owned by manifest-backed library objects."""

    path = root / "lib/registry/objects.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    objects = payload.get("objects") if isinstance(payload, dict) else None
    if not isinstance(objects, list):
        return set()
    aliases: set[str] = set()
    for item in objects:
        if not isinstance(item, dict) or item.get("kind") != kind:
            continue
        raw_aliases = item.get("aliases")
        if not isinstance(raw_aliases, list):
            continue
        aliases.update(alias for alias in raw_aliases if isinstance(alias, str) and alias)
    return aliases


def validate_command_skill_registry_coverage(root: Path, result: ValidationResult) -> None:
    command_sources = _registry_sources(root, "commands", "commands")
    command_ids = _registry_ids(root, "commands", "commands")
    for command_doc in sorted(harness_path(root, "commands").glob("*.md")):
        if command_doc.name == "README.md":
            continue
        relative = command_doc.relative_to(root).as_posix()
        if relative not in command_sources and command_doc.stem not in command_ids:
            result.errors.append(f"command doc missing registry entry: {relative}")

    skill_sources = _registry_sources(root, "skills", "skills")
    library_skill_aliases = _library_registry_aliases(root, kind="skill")
    for skill_doc in sorted(harness_path(root, "skills").glob("*/SKILL.md")):
        relative = skill_doc.relative_to(root).as_posix()
        if relative not in skill_sources and relative not in library_skill_aliases:
            result.errors.append(f"skill doc missing registry entry: {relative}")


def _markdown_table_field(content: str, field: str) -> str:
    prefix = f"| {field} |"
    for line in content.splitlines():
        if line.startswith(prefix):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2:
                return cells[1]
    return ""


def _runtime_invocation_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    control = shared_factory_path(root, "00-control-plane")

    runtime_path = control / "runtime-registry.yml"
    if runtime_path.is_file():
        try:
            runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            runtime = {}
        for collection in ("schedules", "heartbeats", "execution_targets"):
            for entry in runtime.get(collection, []) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    ids.add(str(entry["id"]))

    watch_sources_path = control / "watch-sources.yml"
    if watch_sources_path.is_file():
        try:
            watch_sources = yaml.safe_load(watch_sources_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            watch_sources = {}
        for source in watch_sources.get("watch_sources", []) or []:
            if not isinstance(source, dict):
                continue
            if source.get("id"):
                ids.add(str(source["id"]))
            for rule in source.get("trigger_rules", []) or []:
                if isinstance(rule, dict) and rule.get("id"):
                    ids.add(str(rule["id"]))

    for item in runtime_queue_items(root):
        if item.get("ref") is not None:
            ids.add(str(item["ref"]))

    return ids


def _has_registered_invocation(
    root: Path,
    relative_folder: str,
    object_id: str,
    *,
    include_runtime: bool = False,
    command_sources: set[str] | None = None,
    skill_sources: set[str] | None = None,
    command_ids: set[str] | None = None,
    skill_ids: set[str] | None = None,
    runtime_ids: set[str] | None = None,
) -> bool:
    command_sources = (
        command_sources
        if command_sources is not None
        else _registry_sources(root, "commands", "commands")
    )
    skill_sources = (
        skill_sources
        if skill_sources is not None
        else _registry_sources(root, "skills", "skills")
    )
    if any(source.startswith(f"{relative_folder}/") for source in command_sources | skill_sources):
        return True
    command_ids = (
        command_ids
        if command_ids is not None
        else _registry_ids(root, "commands", "commands")
    )
    skill_ids = (
        skill_ids
        if skill_ids is not None
        else _registry_ids(root, "skills", "skills")
    )
    candidates = {object_id, object_id.replace("_", "-")}
    if include_runtime:
        parts = relative_folder.split("/")
        if len(parts) >= 4:
            domain, lane = parts[0], parts[2]
            candidates.add(f"{domain}_{lane}_{object_id}")
            candidates.add(f"{domain}-{lane}-{object_id.replace('_', '-')}")
        runtime_ids = runtime_ids if runtime_ids is not None else _runtime_invocation_ids(root)
        if candidates & runtime_ids:
            return True
        if any(runtime_id.endswith(f"_{object_id}") for runtime_id in runtime_ids):
            return True
    return bool(candidates & command_ids or candidates & skill_ids)


def validate_workflow_automation_invocations(root: Path, result: ValidationResult) -> None:
    workflow_specs = sorted(
        {
            *root.glob("*/03-workflows/*/*/workflow.md"),
            *root.glob("domains/*/03-workflows/*/*/workflow.md"),
        }
    )
    automation_specs = sorted(
        {
            *root.glob("*/04-automations/*/*/automation.md"),
            *root.glob("domains/*/04-automations/*/*/automation.md"),
        }
    )
    command_sources = _registry_sources(root, "commands", "commands")
    skill_sources = _registry_sources(root, "skills", "skills")
    command_ids = _registry_ids(root, "commands", "commands")
    skill_ids = _registry_ids(root, "skills", "skills")
    runtime_ids = _runtime_invocation_ids(root) if automation_specs else set()

    invocation_snapshot = {
        "command_sources": command_sources,
        "skill_sources": skill_sources,
        "command_ids": command_ids,
        "skill_ids": skill_ids,
        "runtime_ids": runtime_ids,
    }

    for workflow_spec in workflow_specs:
        relative_folder = workflow_spec.parent.relative_to(root).as_posix()
        workflow_id = workflow_spec.parent.name
        content = workflow_spec.read_text(encoding="utf-8", errors="replace")
        status = _markdown_table_field(content, "Status") or "draft"
        if _has_registered_invocation(root, relative_folder, workflow_id, **invocation_snapshot):
            continue
        message = (
            f"workflow `{workflow_id}` missing matching command or skill registry entry: "
            f"{relative_folder}"
        )
        result.warnings.append(message)

    for automation_spec in automation_specs:
        relative_folder = automation_spec.parent.relative_to(root).as_posix()
        automation_id = automation_spec.parent.name
        content = automation_spec.read_text(encoding="utf-8", errors="replace")
        status = _markdown_table_field(content, "Status") or "draft"
        level = _markdown_table_field(content, "Level") or "observe"
        if _has_registered_invocation(
            root,
            relative_folder,
            automation_id,
            include_runtime=True,
            **invocation_snapshot,
        ):
            continue
        message = (
            f"automation `{automation_id}` missing matching command, skill, trigger, or runtime registry entry: "
            f"{relative_folder}"
        )
        result.warnings.append(message)


def validate_automation_projection_registry(root: Path, result: ValidationResult) -> None:
    tracking_path = (
        root / "harness/shared_factory/00-control-plane/automation-run-tracking.yml"
    )
    if not tracking_path.is_file():
        return

    data = load_control_yaml(tracking_path, result)
    automations = data.get("automations") or {}
    excluded = data.get("excluded_automations") or {}
    if not isinstance(automations, dict):
        result.errors.append(
            f"automation run tracking automations must be a mapping: {tracking_path}"
        )
        automations = {}
    if not isinstance(excluded, dict):
        result.errors.append(
            f"automation run tracking excluded_automations must be a mapping: {tracking_path}"
        )
        excluded = {}

    def canonical_tracking_path(value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(root)
            except ValueError:
                return value.rstrip("/")
        parts = candidate.parts
        if parts and parts[0] != "domains" and (root / "domains" / parts[0]).exists():
            candidate = Path("domains") / candidate
        return candidate.as_posix().rstrip("/")

    represented_ids: set[str] = set()
    represented_paths: set[str] = set()
    for section_name, entries in (
        ("automations", automations),
        ("excluded_automations", excluded),
    ):
        for entry_id, entry in entries.items():
            represented_ids.add(str(entry_id))
            if not isinstance(entry, dict):
                result.errors.append(
                    "automation tracking entry must be a mapping: "
                    f"{tracking_path}#{section_name}.{entry_id}"
                )
                continue
            cwd = str(entry.get("cwd") or "").strip()
            if cwd and cwd != ".":
                represented_paths.add(canonical_tracking_path(cwd))
            if (
                section_name == "automations"
                and not entry.get("page_id")
                and not entry.get("external_projection_blocker")
            ):
                result.errors.append(
                    f"automation tracking entry {entry_id!r} missing page_id "
                    f"or external_projection_blocker: {tracking_path}"
                )

    automation_candidates = {
        *root.glob("*/04-automations/*/*/automation.md"),
        *root.glob("domains/*/04-automations/*/*/automation.md"),
    }
    automation_specs: dict[str, Path] = {}
    for candidate in sorted(automation_candidates):
        key = str(candidate.resolve())
        relative = candidate.relative_to(root)
        current = automation_specs.get(key)
        if current is None or relative.parts[0] == "domains":
            automation_specs[key] = candidate
    for automation_md in sorted(automation_specs.values()):
        automation_root = automation_md.parent
        automation_id = automation_root.name
        automation_path = automation_root.relative_to(root).as_posix()
        if (
            automation_id in represented_ids
            or canonical_tracking_path(automation_path) in represented_paths
        ):
            continue
        result.errors.append(
            "automation folder missing automation-run-tracking representation "
            f"(add to automations or excluded_automations): {automation_path}"
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


# ---------------------------------------------------------------------------
# F-011: JSON schema enforcement (strict mode)
# ---------------------------------------------------------------------------

# Explicit schema → installed-root target-glob mapping.
# Keys are schema filenames (relative to schemas/); values are glob patterns
# relative to the installed OS root that produce matching structured files.
# Files that do not exist are not strict errors (missing-file errors already
# come from the structural validator above).
_SCHEMA_DIR = Path(__file__).parent.parent.parent / "schemas"

SCHEMA_TARGETS: dict[str, list[str]] = {
    "auto-dev-work-item.schema.json": [
        "domains/*/02-projects/*/work-items/*/autodev.json",
        "domains/*/02-projects/*/work-items/*/*/autodev.json",
    ],
    "auto-dev-review-receipt.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-review/receipts/*.json",
    ],
    "auto-dev-health-evidence.schema.json": [
        "domains/*/02-projects/*/work-items/*/*/artifacts/auto-dev-health/evidence.json",
    ],
    "auto-dev-health-preflight.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-health/preflight.json",
    ],
    "auto-dev-packet-manifest.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-health/receipts/packet-manifest.json",
    ],
    "auto-dev-resource-cleanup.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-health/receipts/resource-cleanup.json",
    ],
    "auto-dev-runtime-cleanup.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-health/receipts/runtime-cleanup.json",
    ],
    "auto-dev-reopen.schema.json": [
        "**/work-items/02-active/*/artifacts/auto-dev-reopen/reopen.json",
    ],
    "auto-dev-stage-policy-decision.schema.json": [
        "**/work-items/*/*/artifacts/auto-dev-orchestration/proofs/*/policy-decision-*.json",
    ],
    "program-run-packet.schema.json": [
        "harness/shared_factory/06-runs-and-logs/program-runs/*/*.json",
    ],
    "analytics-metrics.schema.json": ["harness/registries/analytics-metrics.yml"],
    "capability-registry.schema.json": [REGISTRY_FILES["capabilities"]],
    "command-registry.schema.json": [REGISTRY_FILES["commands"]],
    "skill-visibility-registry.schema.json": [REGISTRY_FILES["skills"]],
    "skill-registry.schema.json": [
        "harness/skills/skill-registry.yml",
        "harness/shared_factory/05-knowledge/skills/skill-registry.yml",
    ],
    "mcp-server-registry.schema.json": [REGISTRY_FILES["mcp_servers"]],
    "library-registry.schema.json": [REGISTRY_FILES["libraries"]],
    "hook-registry.schema.json": [REGISTRY_FILES["hooks"]],
    "plugin-registry.schema.json": [REGISTRY_FILES["plugins"]],
    "rule-registry.schema.json": [REGISTRY_FILES["rules"]],
    "report-registry.schema.json": [REGISTRY_FILES["reports"]],
    "composio-tool-routing.schema.json": [REGISTRY_FILES["composio_tools"]],
    "update-grant.schema.json": ["harness/registries/update-grant.json"],
    "backup-policy.schema.json": ["harness/registries/backup-policy.yml"],
    "execution-fabric.schema.json": ["harness/config/execution-fabric.yml"],
    "run-evidence-config.schema.json": ["harness/config/run-evidence.yml"],
    "documentation-upkeep.schema.json": ["harness/shared_factory/00-control-plane/documentation-upkeep.yml"],
    "doc-config.schema.json": ["harness/shared_factory/00-control-plane/doc-config.yml"],
    "automation.schema.json": ["**/04-automations/*/*/automation.yml"],
    "domain.schema.json": ["**/domain.yml"],
    "run.schema.json": ["**/06-runs-and-logs/runs/*/run.yml"],
    "workflow.schema.json": ["**/03-workflows/*/*/workflow.yml"],
    "context-contract.schema.json": [
        "**/03-workflows/*/*/context-contract.yml",
        "**/04-automations/*/*/context-contract.yml",
    ],
    "update-manifest.schema.json": [],  # generated; no installed glob
    "hosts.schema.json": ["config/hosts.yml"],
    "doc-config.schema.json": [
        "harness/shared_factory/00-control-plane/doc-config.yml",
        "**/02-projects/*/config/doc-config.yml",
    ],
}


@dataclass
class StrictFinding:
    """A schema-validation finding produced by --strict mode."""

    schema: str
    path: Path
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"schema": self.schema, "path": str(self.path), "message": self.message}


def _load_schema(schema_file: Path) -> dict[str, Any] | None:
    """Load a JSON schema from disk, returning None on failure."""
    try:
        return json.loads(schema_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_document(path: Path) -> Any | None:
    """Parse a YAML or JSON document, returning None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError):
        return None


def _schema_target_candidates(root: Path, pattern: str) -> list[Path]:
    """Resolve schema targets only across declared OS ownership layers."""
    if pattern.startswith("**/"):
        suffix = pattern.removeprefix("**/")
        candidates = [
            *root.glob(f"*/{suffix}"),
            *root.glob(f"harness/shared_factory/{suffix}"),
        ]
    elif "*" in pattern:
        candidates = list(root.glob(pattern))
    else:
        candidates = [root / pattern]
    return list(dict.fromkeys(candidates))


def validate_schemas_strict(root: Path) -> list[StrictFinding]:
    """Validate installed files against their JSON schemas.

    Only reports findings for files that exist.  Missing files are already
    reported by the structural validator and are not re-reported here.
    """
    try:
        import jsonschema  # noqa: PLC0415
        from jsonschema import Draft202012Validator  # noqa: PLC0415
    except ImportError:
        return [
            StrictFinding(
                schema="(jsonschema library)",
                path=root,
                message="jsonschema package is not installed; run: pip install 'jsonschema>=4'",
            )
        ]

    findings: list[StrictFinding] = []
    # Resolution order: prefer schemas bundled with the install at
    # harness/schemas/ (written by scaffold/customer init so installs are
    # self-contained), fall back to the source-repo schemas/ directory so
    # that older roots that pre-date this feature keep working.
    _install_schemas = root / "harness" / "schemas"
    schemas_dir = _install_schemas if _install_schemas.is_dir() else _SCHEMA_DIR

    for schema_filename, target_patterns in SCHEMA_TARGETS.items():
        schema_path = schemas_dir / schema_filename
        if not schema_path.is_file():
            continue
        schema = _load_schema(schema_path)
        if schema is None:
            findings.append(
                StrictFinding(
                    schema=schema_filename,
                    path=schema_path,
                    message=f"could not parse schema file: {schema_path}",
                )
            )
            continue

        try:
            validator_cls = Draft202012Validator
            validator_cls.check_schema(schema)
        except Exception:
            # If the schema itself is invalid, skip without reporting — it's a
            # source-package authoring problem, not an install-root problem.
            continue

        for pattern in target_patterns:
            for target_path in _schema_target_candidates(root, pattern):
                if not target_path.is_file():
                    continue
                doc = _load_document(target_path)
                if doc is None:
                    continue

                errors = list(
                    jsonschema.Draft202012Validator(schema).iter_errors(doc)
                )
                for error in errors:
                    path_str = " -> ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
                    findings.append(
                        StrictFinding(
                            schema=schema_filename,
                            path=target_path,
                            message=f"schema violation at {path_str}: {error.message}",
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# Plan-22: lifecycle staleness checks
# ---------------------------------------------------------------------------

# 50/50 DECISION: staleness threshold for "building" state.
# Plan-22 does not specify a numeric threshold; I chose 7 calendar days
# (based on mtime of the work-item directory).  Rationale: a week is long
# enough to be meaningful work-in-progress; any longer without a WORKLOG.md
# update is genuinely stale.  This constant is the single place to change it.
BUILDING_STALE_DAYS = 7
CONVERSATION_LOG_TOKEN_SCAN_MAX_BYTES = 1_000_000

GENERATED_DATA_DIR_NAMES = {
    ".features",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "artifacts",
    "BUILD_LOGS",
    "features",
    "logs",
    "node_modules",
    "remote",
    "runtime",
    "runs",
    "snapshots",
    "worker-runs",
    "worklogs",
    "WORKLOGS",
    "worktrees",
}


def _canonical_work_items_roots(root: Path) -> list[Path]:
    """Return OS-owned project work-items roots without scanning source checkouts."""
    roots: list[Path] = []
    patterns = (
        "*/02-projects/*/work-items",
        "harness/*/02-projects/*/work-items",
        "harness/shared_factory/02-projects/*/work-items",
    )
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_dir():
                continue
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            roots.append(path)
    return roots


def _iter_structured_control_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Collect JSON/YAML control files while pruning generated run artifacts."""
    json_paths: list[Path] = []
    yaml_paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in GENERATED_DATA_DIR_NAMES
            and not (current / dirname / ".git").exists()
        ]
        for filename in filenames:
            path = current / filename
            if filename.endswith(".json"):
                json_paths.append(path)
            elif filename.endswith((".yml", ".yaml")):
                yaml_paths.append(path)
    return json_paths, yaml_paths


def _work_item_mtime(work_item_root: Path) -> datetime.datetime | None:
    """Return the most recent mtime among all files in a work-item directory."""
    latest: float | None = None
    try:
        for child in work_item_root.rglob("*"):
            try:
                mtime = child.stat().st_mtime
                if latest is None or mtime > latest:
                    latest = mtime
            except OSError:
                pass
    except OSError:
        pass
    if latest is None:
        return None
    return datetime.datetime.fromtimestamp(latest, tz=datetime.timezone.utc)


def lifecycle_staleness_findings(root: Path) -> list[dict[str, str]]:
    """Scan all project work-items for staleness conditions.

    Returns a list of finding dicts with keys: severity, path, message.

    Two conditions are detected (plan-22 AC):
      (a) Work items stuck in ``building`` state past BUILDING_STALE_DAYS.
      (b) Work items in ``finished`` state that are missing SUMMARY.md.
    """
    findings: list[dict[str, str]] = []
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    for work_items_root in _canonical_work_items_roots(root):
        if not work_items_root.is_dir():
            continue
        for work_item_root in sorted(path for path in work_items_root.iterdir() if path.is_dir()):
            metadata_path = metadata_path_for(work_item_root)
            if metadata_path is None:
                continue
            metadata = load_yaml_mapping(metadata_path)
            # Extract state directly from common work.yml/feature.yml keys.
            # work.yml written by work_lifecycle.py uses "state" at root;
            # feature.yml uses "lifecycle.state" or "status".
            # lifecycle_status() does not check root-level "state", so we
            # fall back to it only after checking "state" directly.
            status = str(
                metadata.get("state")
                or metadata.get("status")
                or (
                    metadata.get("lifecycle", {}).get("state")
                    if isinstance(metadata.get("lifecycle"), dict)
                    else None
                )
                or "captured"
            )

            if status == "building":
                mtime = _work_item_mtime(work_item_root)
                if mtime is not None:
                    age_days = (now - mtime).days
                    if age_days >= BUILDING_STALE_DAYS:
                        findings.append(
                            {
                                "severity": "fix-soon",
                                "path": str(work_item_root),
                                "message": (
                                    f"work item stuck in 'building' state for {age_days} days "
                                    f"(threshold: {BUILDING_STALE_DAYS}): {work_item_root.name}"
                                ),
                            }
                        )

            elif status == "finished":
                summary_path = work_item_root / "SUMMARY.md"
                if not summary_path.is_file():
                    findings.append(
                        {
                            "severity": "fix-soon",
                            "path": str(work_item_root),
                            "message": (
                                f"work item is 'finished' but missing required SUMMARY.md: "
                                f"{work_item_root.name}"
                            ),
                        }
                    )
                qa_results_path = work_item_root / "HOLDOUT_QA_RESULTS.md"
                if not qa_results_path.is_file():
                    findings.append(
                        {
                            "severity": "fix-soon",
                            "path": str(work_item_root),
                            "message": (
                                f"work item is 'finished' but missing validation evidence "
                                f"(HOLDOUT_QA_RESULTS.md): {work_item_root.name}"
                            ),
                        }
                    )

            elif status == "documented":
                memory_path = work_item_root / "MEMORY.md"
                if not memory_path.is_file():
                    findings.append(
                        {
                            "severity": "observation",
                            "path": str(work_item_root),
                            "message": (
                                f"work item is 'documented' but missing MEMORY.md "
                                f"(no memory evidence): {work_item_root.name}"
                            ),
                        }
                    )

    return findings


def lifecycle_closeout_readiness_check(work_item_root: Path) -> list[dict[str, str]]:
    """Return advisory closeout findings for one work-item packet."""
    findings: list[dict[str, str]] = []

    metadata_path = metadata_path_for(work_item_root)
    if metadata_path is None:
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(work_item_root),
                "message": (
                    f"work item missing metadata file "
                    f"({', '.join(WORK_ITEM_METADATA_FILES)}): {work_item_root.name}"
                ),
            }
        )
        return findings

    metadata = load_yaml_mapping(metadata_path)
    status = lifecycle_status(metadata)
    record = WorkItemRecord(
        path=work_item_root,
        metadata_path=metadata_path,
        status=status,
        title=str(metadata.get("title") or work_item_root.name),
        slug=str(metadata.get("slug") or metadata.get("id") or work_item_root.name),
        source="project_work_item",
        metadata=metadata,
    )
    for missing_path in record.missing_required_files:
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(work_item_root),
                "message": (
                    f"work item {work_item_root.name!r} status {status!r} "
                    f"missing required file: {missing_path.name}"
                ),
            }
        )

    return findings


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
    naming_config = os_root / CONFIG_RELATIVE_PATH
    require_file(naming_config, result)
    if naming_config.is_file():
        try:
            load_artifact_naming_policy(os_root)
        except ValueError as exc:
            result.errors.append(f"invalid artifact naming config: {naming_config}: {exc}")
    validate_claude_adapter(harness_root / "CLAUDE.md", result)
    warn_legacy_agent(harness_root / "AGENT.md", result)
    validate_canonical_domain_layout(os_root, result)

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
    validate_command_skill_registry_coverage(os_root, result)
    validate_workflow_automation_invocations(os_root, result)
    validate_automation_projection_registry(os_root, result)
    validate_registered_hooks(os_root, result)
    validate_object_library(os_root, result)
    validate_work_state(os_root, result)
    validate_required_runtime_integrations(os_root, result)
    validate_update_backup_contract(os_root, result)
    artifact_config = os_root / "harness" / "artifact-config"
    if artifact_config.is_dir():
        artifact_health = artifact_contract_doctor(os_root)
        for finding in artifact_health["diagnostics"]:
            message = (
                f"artifact contract {finding.get('code')}: "
                f"{finding.get('source_ref') or finding.get('provider') or 'unknown'}: {finding.get('message')}"
            )
            if finding.get("severity") == "error":
                result.errors.append(message)
            elif finding.get("severity") == "warning":
                result.warnings.append(message)
    else:
        result.warnings.append(
            "artifact contract library is not installed; run `agentic-os update apply` or install current docs/assets"
        )
    investigation_config = os_root / "harness" / "investigation-config"
    if investigation_config.is_dir():
        investigation_health = investigation_contract_doctor(os_root)
        for finding in investigation_health["findings"]:
            message = (
                f"investigation contract {finding.get('code')}: "
                f"{finding.get('source_ref') or 'unknown'}: {finding.get('message')}"
            )
            if finding.get("severity") == "error":
                result.errors.append(message)
            elif finding.get("severity") == "warning":
                result.warnings.append(message)
    else:
        result.warnings.append(
            "investigation contract library is not installed; run `agentic-os update apply` or install current docs/assets"
        )
    context_check = check_context_contracts(os_root)
    result.errors.extend(context_check.errors)
    if context_check.legacy_fallbacks or context_check.duplicate_groups:
        result.warnings.append(
            "context contracts need compaction: "
            f"legacy_fallbacks={context_check.legacy_fallbacks}, "
            f"duplicate_groups={context_check.duplicate_groups}; "
            "run `agentic-os context check` and `context compact --dry-run`"
        )

    profile_domains = profile_domain_names(os_root)
    # Derive the domain list from the tree on disk (directories carrying a
    # domain.yml marker) so installs with any operator-chosen domain names
    # validate as-is. Fall back to the neutral defaults only when the tree
    # has no domains at all, which keeps missing-domain errors for broken or
    # half-created roots.
    domains_to_validate = profile_domains or installed_domain_names(os_root) or list(DEFAULT_DOMAINS)
    layout_v2 = (os_root / "lib").is_dir()
    for domain in domains_to_validate:
        validate_domain(domain_path(os_root, domain), result, layout_v2=layout_v2)
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

    json_paths, yaml_paths = _iter_structured_control_files(os_root)

    for path in sorted(json_paths):
        if not path.is_file():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.errors.append(f"invalid JSON: {path}: {exc}")

    for path in sorted(yaml_paths):
        if not path.is_file():
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            result.errors.append(f"invalid YAML: {path}: {exc}")

    # Plan-22: lifecycle staleness checks (warnings, not blockers)
    for finding in lifecycle_staleness_findings(os_root):
        result.warnings.append(finding["message"])

    return result


def validate_canonical_domain_layout(root: Path, result: ValidationResult) -> None:
    """Reject domain directories and aliases outside the canonical domains/ root."""

    domains_root = root / "domains"
    if not domains_root.is_dir():
        return

    for candidate in sorted(root.iterdir()):
        if candidate.name == "domains":
            continue
        marker = candidate / "domain.yml"
        is_domain_entry = marker.is_file()
        is_domain_alias = False
        if candidate.is_symlink():
            target = Path(os.readlink(candidate))
            is_domain_alias = target == Path("domains") / candidate.name
        if not is_domain_entry and not is_domain_alias:
            continue
        result.errors.append(
            "non-canonical root domain entry: "
            f"{candidate}; move it to {domains_root / candidate.name} and remove the root alias"
        )


def validate_object_library(root: Path, result: ValidationResult) -> None:
    """Validate lib/ only when an install has opted into layout v2."""

    if not (root / "lib").exists():
        return
    from .library import library_doctor

    doctor = library_doctor(root)
    for diagnostic in doctor.get("diagnostics") or []:
        if not isinstance(diagnostic, dict):
            continue
        detail = diagnostic.get("message") or diagnostic.get("path") or ""
        message = f"object library {diagnostic.get('code', 'invalid')}: {detail}".rstrip()
        if diagnostic.get("severity") == "error":
            result.errors.append(message)
        else:
            result.warnings.append(message)


def validate_work_state(root: Path, result: ValidationResult) -> None:
    """Validate canonical work truth only after active-now opt-in."""

    projection_path = root / "harness/shared_factory/00-control-plane/active-now.json"
    if not projection_path.is_file():
        return
    db_path = root / "harness/shared_factory/00-control-plane/state.db"
    if not db_path.is_file():
        result.errors.append(f"active work projection exists without state database: {db_path}")
        return
    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"invalid active work projection: {projection_path}: {exc}")
        return
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT id FROM active_now ORDER BY priority DESC, updated_at DESC, id"
        ).fetchall()
    except sqlite3.Error as exc:
        result.errors.append(f"invalid canonical work state: {db_path}: {exc}")
        return
    finally:
        if "connection" in locals():
            connection.close()
    if not integrity or integrity[0] != "ok":
        result.errors.append(f"canonical work state integrity failed: {db_path}")
    if int(version) < 2:
        result.errors.append(f"canonical work state schema is older than v2: {db_path}")
    projected_ids = [str(item.get("id")) for item in projection.get("items") or []]
    database_ids = [str(row["id"]) for row in rows]
    if projected_ids != database_ids or projection.get("active_count") != len(database_ids):
        result.errors.append(f"active work projection is stale: {projection_path}")


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
