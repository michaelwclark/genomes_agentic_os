"""Filesystem scaffolding for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import yaml

from .artifact_naming import (
    ArtifactNamingPolicy,
    CONFIG_RELATIVE_PATH,
    dated_name,
    load_artifact_naming_policy,
    render_default_artifact_naming_config,
)
from .capability_registry import (
    HARNESS_DIRECTORY,
    REGISTRY_FILES,
    VISIBLE_CAPABILITY_DIRECTORIES,
    command_entries,
    hook_entries,
    inventory_markdown,
    registry_file_payloads,
)
from .config_ops import install_config
from .composio_catalog import composio_tools_markdown
from .hosts import load_hosts
from .mcp_catalog import mcp_tools_markdown
from . import __version__


DEFAULT_DOMAINS = (
    "personal",
    "work",
)

ROOT_MARKER_FILENAME = ".agentic_root"
SHARED_FACTORY_DOMAIN = "shared_factory"
# Backward-compatible default for the deprecated --projects-source flag.
DEFAULT_PROJECTS_SOURCE = "~/projects"
SOURCE_PACKAGE_VERSION = __version__
DEFAULT_UPDATE_CHANNEL = "stable"
DEFAULT_UPDATE_POLICY = "operator_approved"

# Optional alias map: alternate spellings that normalize to an installed
# domain slug. Intentionally empty in the generic product; operators can
# extend it in a fork or downstream configuration.
DOMAIN_ALIASES: dict[str, str] = {}

STANDARD_LANES = (
    "engineering",
    "marketing",
    "sales",
    "support",
    "operations",
    "finance",
    "personal_admin",
    "learning",
)

AUTO_DEV_CHILD_POLICY_PLANES = (
    "dev_standards",
    "qa_gates",
    "gitflow_topology",
    "environment_access",
)

AUTO_DEV_POLICY_COMPATIBILITY_BREADCRUMB = """<!-- generated-by: agentic-os auto-dev-policy-migration -->
# Auto-Dev policy compatibility breadcrumb

The active policy files moved beneath `auto_dev/`. This managed file exists
only so an interrupted compatibility migration can safely recognize and remove
the obsolete sibling directory.
"""

_MANAGED_LEGACY_AUTO_DEV_READMES = (
    """# Development Standards Policy Plane

Every development, own-PR finalization, and others'-PR review run loads every
Markdown file in this folder, followed by the routed domain and project
folders. Files are ordered lexicographically within each folder. Later scopes
may add precision; the strictest safety and quality requirement still wins.

Conventional folders:

```text
harness/shared_factory/05-knowledge/dev_standards/
domains/<domain>/05-knowledge/dev_standards/
domains/<domain>/02-projects/<project>/config/dev_standards/
```

Projects may replace the ordered folder list through
`config/development.yml policies.dev_standards.paths`. Adding a Markdown file
changes the next run without a code or registry edit. `README.md` is explanatory
and is not loaded as policy.
""",
)

MANAGED_RUNTIME_FILES = (
    (
        "templates/runtime/activity-sources.yml",
        "harness/shared_factory/00-control-plane/activity-sources.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/analytics-metrics.yml",
        "harness/registries/analytics-metrics.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/spec-engine.yml",
        "harness/shared_factory/00-control-plane/spec-engine.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/spec-intake-workflow.md",
        "harness/shared_factory/04-workflows/spec-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/feature-intake-workflow.md",
        "harness/shared_factory/04-workflows/feature-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/bug-intake-workflow.md",
        "harness/shared_factory/04-workflows/bug-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement.yml",
        "harness/shared_factory/00-control-plane/self-improvement.yml",
        "create_if_missing",
    ),
    (
        "templates/runtime/self-improvement-workflow.md",
        "harness/shared_factory/04-workflows/self-improvement-review.md",
        "create_if_missing",
    ),
    (
        "templates/runtime/self-improvement-review.yml",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement-proposal.yml",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement-usage-sidecar.json",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-usage-sidecar.json",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-self-improvement.md",
        "harness/shared_factory/05-knowledge/commands/os-self-improvement.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-quiet-run.md",
        "harness/shared_factory/05-knowledge/commands/os-quiet-run.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-groom-spec.md",
        "harness/shared_factory/05-knowledge/commands/os-groom-spec.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-add-spec.md",
        "harness/shared_factory/05-knowledge/commands/os-add-spec.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/notion-organization.yml",
        "harness/shared_factory/00-control-plane/notion-organization.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-notion-org.md",
        "harness/shared_factory/05-knowledge/commands/os-notion-org.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/toolsmith-reviewer/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/quiet-async-runner/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/quiet-async-runner/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/spec-groomer/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/spec-groomer/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/spec-engine/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/spec-engine/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/project-domain-investigate.md",
        "harness/shared_factory/05-knowledge/commands/project-domain-investigate.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/project-domain-investigate/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/project-domain-investigate/SKILL.md",
        "replace_if_managed_unchanged",
    ),
)

EXECUTION_FABRIC_MARKER_START = "<!-- agentic-os-execution-fabric:start -->"
EXECUTION_FABRIC_MARKER_END = "<!-- agentic-os-execution-fabric:end -->"
EXECUTION_FABRIC_ROUTING_BLOCK = f"""{EXECUTION_FABRIC_MARKER_START}
## Managed Execution Fabric

- Route managed asynchronous work through the shared Execution Fabric using a
  declared task type and named queue. Folder counts, detached processes, and
  direct vendor queue writes are not concurrency controls.
- Inspect configuration with `agentic-os runtime config show|status|diff`,
  validate before activation, and use guarded `reconcile` (local) or `reload`
  (remote) operations. The one mutable instance policy is
  `harness/config/execution-fabric.yml`.
- Monitor queue depth, workers, runs, attempts, effects, alarms, healing, and
  host leadership through `agentic-os runtime status` or `runtime snapshot`.
  Admission and terminal receipts, not a trigger or process id, prove a run.
- Queue, capacity, retry, dead-letter, health, and failover policy is owned by
  `harness/shared_factory/00-programs/execution_fabric/`; narrower layers may
  select declared routes but must not copy or weaken the root policy.
{EXECUTION_FABRIC_MARKER_END}
"""

# Source-owned first-class resources are copied additively into an installed
# root.  Unlike run state and operator configuration, these directories are
# product definitions: a fresh install must be able to discover and execute
# them without reaching back into the source checkout.  ``copy_tree`` and
# ``copy_file`` deliberately preserve an existing destination so upgrades do
# not overwrite operator-owned changes.
MANAGED_RESOURCE_TREES = (
    (
        "harness/shared_factory/00-programs/auto_dev",
        "lib/programs/root/auto-dev",
    ),
    (
        "harness/shared_factory/04-automations/operations/work_item_archive",
        "harness/shared_factory/04-automations/operations/work_item_archive",
    ),
    (
        "harness/shared_factory/00-programs/execution_fabric",
        "harness/shared_factory/00-programs/execution_fabric",
    ),
    (
        "harness/shared_factory/00-programs/project_domain_intelligence",
        "harness/shared_factory/00-programs/project_domain_intelligence",
    ),
    (
        "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis",
        "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis",
    ),
    (
        "harness/shared_factory/05-knowledge/auto_dev",
        "harness/shared_factory/05-knowledge/auto_dev",
    ),
    (
        "harness/shared_factory/03-workflows/engineering/os_cleanup",
        "harness/shared_factory/03-workflows/engineering/os_cleanup",
    ),
    (
        "harness/shared_factory/04-workflows/project-domain-architecture-analysis",
        "harness/shared_factory/04-workflows/project-domain-architecture-analysis",
    ),
    (
        "harness/shared_factory/04-workflows/auto_dev/library_self_hosting",
        "lib/workflows/root/library_self_hosting",
    ),
    (
        "harness/skills/auto-dev",
        "lib/skills/root/auto-dev",
    ),
    (
        "harness/skills/auto-dev-everything",
        "lib/skills/root/auto-dev-everything",
    ),
    (
        "harness/skills/auto-dev-grooming",
        "lib/skills/root/auto-dev-grooming",
    ),
    (
        "harness/skills/auto-dev-create-artifacts",
        "lib/skills/root/auto-dev-create-artifacts",
    ),
    (
        "harness/skills/auto-dev-detective",
        "lib/skills/root/auto-dev-detective",
    ),
    (
        "harness/skills/auto-dev-readiness",
        "lib/skills/root/auto-dev-readiness",
    ),
    (
        "harness/skills/auto-dev-implementation",
        "lib/skills/root/auto-dev-implementation",
    ),
    (
        "harness/skills/auto-dev-develop",
        "lib/skills/root/auto-dev-develop",
    ),
    (
        "harness/skills/auto-dev-document",
        "lib/skills/root/auto-dev-document",
    ),
    (
        "harness/skills/auto-dev-qa",
        "lib/skills/root/auto-dev-qa",
    ),
    (
        "harness/skills/auto-dev-review-repair",
        "lib/skills/root/auto-dev-review-repair",
    ),
    (
        "harness/skills/auto-dev-review-self",
        "lib/skills/root/auto-dev-review-self",
    ),
    (
        "harness/skills/auto-dev-review-self-opposing-model",
        "lib/skills/root/auto-dev-review-self-opposing-model",
    ),
    (
        "harness/skills/auto-dev-review-others",
        "lib/skills/root/auto-dev-review-others",
    ),
    (
        "harness/skills/auto-dev-pr-create",
        "lib/skills/root/auto-dev-pr-create",
    ),
    (
        "harness/skills/gitflow-pr-create",
        "lib/skills/root/gitflow-pr-create",
    ),
    (
        "harness/skills/auto-dev-finalize",
        "lib/skills/root/auto-dev-finalize",
    ),
    (
        "harness/skills/auto-dev-merge",
        "lib/skills/root/auto-dev-merge",
    ),
    (
        "harness/skills/auto-dev-release-propagation",
        "lib/skills/root/auto-dev-release-propagation",
    ),
    (
        "harness/skills/auto-dev-release",
        "lib/skills/root/auto-dev-release",
    ),
    (
        "harness/skills/auto-dev-deploy",
        "lib/skills/root/auto-dev-deploy",
    ),
    (
        "harness/skills/auto-dev-closeout",
        "lib/skills/root/auto-dev-closeout",
    ),
    (
        "harness/skills/auto-dev-health",
        "lib/skills/root/auto-dev-health",
    ),
    (
        "harness/skills/auto-dev-dep-updater",
        "lib/skills/root/auto-dev-dep-updater",
    ),
    (
        "harness/skills/auto-dev-continuous-release",
        "lib/skills/root/auto-dev-continuous-release",
    ),
    (
        "harness/skills/os-cleaner",
        "lib/skills/root/os-cleaner",
    ),
    (
        "harness/skills/pr-review",
        "lib/skills/root/pr-review",
    ),
    (
        "harness/skills/pull-request",
        "lib/skills/root/pull-request",
    ),
    (
        "harness/skills/object-library",
        "lib/skills/root/object-library",
    ),
)
MANAGED_LIBRARY_FALLBACK_ROOT = Path(
    "harness/shared_factory/05-knowledge/library-bootstrap"
)

PROJECT_STATUSES = (
    "active",
    "waiting",
    "blocked",
    "done",
)

PROJECT_CONFIG_FILES = (
    "project-profile.yml",
    "development.yml",
    "workflows.yml",
    "work-lifecycle.yml",
    "spec-engine.yml",
    "output-artifacts.yml",
    "validation.yml",
    "worktrees.yml",
    "memory.yml",
    "mcps.yml",
    "tools.yml",
)

CONTROL_PLANE_FILES = (
    "README.md",
    "active-work.md",
    "state-index.md",
    "decisions.md",
    "routing-rules.md",
    "approval-rules.md",
)

INBOX_FILES = (
    "raw-ideas.md",
    "triage.md",
)

KNOWLEDGE_FILES: tuple[str, ...] = ()

METRIC_FILES = (
    "baselines.md",
    "scorecards.md",
)

DOMAIN_DIRECTORIES = (
    "00-programs",
    "00-control-plane",
    "01-inbox",
    "02-projects",
    "03-workflows",
    "04-automations",
    "06-runs-and-logs",
    "06-runs-and-logs/runs",
    "06-runs-and-logs/failures",
    "07-metrics",
    "08-archive",
)

WORKFLOW_FILES = (
    "context-contract.yml",
    "workflow.md",
    "outcome-brief.md",
    "alignment-questions.md",
    "prd.md",
    "implementation-plan.md",
    "dispatch-handoff.md",
    "progress.md",
    "quick-reference.md",
    "state-machine.md",
    "context-pack.md",
    "approval-rules.md",
    "output-contract.md",
    "runbook.md",
)

AUTOMATION_FILES = (
    "context-contract.yml",
    "automation.md",
    "inputs.md",
    "outputs.md",
    "permissions.md",
    "failure-modes.md",
    "runbook.md",
    "tests.md",
)

PROGRAM_FILES = (
    "program.md",
    "components.yml",
    "context-pack.md",
    "crud.md",
    "documentation.md",
    "runbook.md",
    "tests.md",
    "worklog.md",
)

NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
WORKTREE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SPOTLIGHT_NEVER_INDEX_FILENAME = ".metadata_never_index"


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)

    def extend(self, other: "ScaffoldResult") -> None:
        self.created.extend(other.created)
        self.skipped.extend(other.skipped)
        self.updated.extend(other.updated)

    def messages(self) -> list[str]:
        lines: list[str] = []
        for label, paths in (
            ("created", self.created),
            ("updated", self.updated),
        ):
            for path in paths:
                lines.append(f"{label}: {path}")
        return lines


def expand_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def harness_path(root: str | Path, *parts: str) -> Path:
    return expand_path(root) / HARNESS_DIRECTORY / Path(*parts)


def shared_factory_path(root: str | Path, *parts: str) -> Path:
    return harness_path(root, SHARED_FACTORY_DOMAIN, *parts)


def domain_path(root: str | Path, domain: str) -> Path:
    normalized = normalize_domain(domain)
    if normalized == SHARED_FACTORY_DOMAIN:
        return shared_factory_path(root)
    os_root = expand_path(root)
    conventional = os_root / "domains" / normalized
    legacy = os_root / normalized
    if conventional.exists() or (os_root / "domains").is_dir():
        return conventional
    return legacy


def installed_domain_names(root: str | Path) -> list[str]:
    """Return the domain slugs actually installed under *root*.

    A domain is any top-level directory carrying a ``domain.yml`` marker.
    Structural roots (``harness/``, and ``shared_factory`` inside it) never
    appear here because they do not live at the top level of the OS root.
    This keeps validation and routing keyed to the operator's real tree
    instead of any built-in default domain list.
    """
    os_root = expand_path(root)
    if not os_root.is_dir():
        return []
    candidates = [
        path
        for path in os_root.iterdir()
        if path.is_dir() and (path / "domain.yml").is_file()
    ]
    domains_root = os_root / "domains"
    if domains_root.is_dir():
        candidates.extend(
            path
            for path in domains_root.iterdir()
            if path.is_dir() and (path / "domain.yml").is_file()
        )
    return sorted({path.name for path in candidates})


def validate_name(value: str, label: str = "name") -> str:
    if not NAME_PATTERN.fullmatch(value):
        # If the only problem is hyphens, suggest the snake_case form.
        snake = value.replace("-", "_")
        if NAME_PATTERN.fullmatch(snake):
            raise ValueError(
                f"{label} must use lowercase letters, numbers, and underscores only: {value!r}"
                f" — did you mean {snake!r}?"
            )
        raise ValueError(f"{label} must use lowercase letters, numbers, and underscores only: {value!r}")
    return value


def validate_worktree_name(value: str) -> str:
    if not WORKTREE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "worktree name must start with a lowercase letter or number and use lowercase letters, "
            f"numbers, dots, hyphens, and underscores only: {value!r}"
        )
    return value


def worktree_name_from_branch(branch: str) -> str:
    name = re.sub(r"[^a-z0-9._-]+", "-", branch.lower()).strip("-.")
    if not name:
        raise ValueError(f"cannot derive a worktree name from branch: {branch!r}")
    return validate_worktree_name(name)


def load_project_code_settings(project_root: Path) -> dict[str, object]:
    """Load the project's canonical code settings from ``development.yml``.

    ``config/development.yml`` remains the single project code/delivery
    contract. Older projects that do not yet have the file inherit safe
    defaults from ``project.yml`` rather than gaining another config source.
    """
    config_path = project_root / "config" / "development.yml"
    data: dict[str, object] = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"project code settings must be a mapping: {config_path}")
        data = loaded
    project_data: dict[str, object] = {}
    project_path = project_root / "project.yml"
    if project_path.is_file():
        loaded_project = yaml.safe_load(project_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded_project, dict):
            project_data = loaded_project
    sources = project_data.get("sources") if isinstance(project_data.get("sources"), dict) else {}
    if "enabled" in data and not isinstance(data["enabled"], bool):
        raise ValueError(f"project code setting enabled must be a boolean: {config_path}")
    repository_value = data.get("repository")
    if repository_value is not None and not isinstance(repository_value, dict):
        raise ValueError(f"project code setting repository must be a mapping: {config_path}")
    worktrees_value = data.get("worktrees")
    if worktrees_value is not None and not isinstance(worktrees_value, dict):
        raise ValueError(f"project code setting worktrees must be a mapping: {config_path}")
    repository = repository_value or {}
    worktrees = worktrees_value or {}
    return {
        "enabled": data.get("enabled", True),
        "repository": {
            "root": repository.get("root") or sources.get("repo") or "",
            "base_branch": repository.get("base_branch") or "main",
        },
        "worktrees": {
            "directory": worktrees.get("directory") or "worktrees",
            "branch_template": worktrees.get("branch_template") or "feature/{ticket}-{slug}",
            "date_prefix": worktrees.get("date_prefix", "inherit"),
        },
    }


def project_worktree_root(project_root: Path, settings: dict[str, object] | None = None) -> Path:
    code_settings = settings or load_project_code_settings(project_root)
    worktrees = code_settings.get("worktrees") if isinstance(code_settings.get("worktrees"), dict) else {}
    raw_directory = worktrees.get("directory") or "worktrees"
    if not isinstance(raw_directory, str) or not raw_directory.strip():
        raise ValueError("project code setting worktrees.directory must be a non-empty path")
    directory = Path(raw_directory).expanduser()
    if not directory.is_absolute():
        directory = project_root / directory
    return directory.resolve()


def project_worktree_naming_policy(
    os_root: str | Path,
    settings: dict[str, object] | None = None,
) -> ArtifactNamingPolicy:
    """Resolve project worktree naming, inheriting the OS default by default."""
    policy = load_artifact_naming_policy(os_root)
    worktrees = settings.get("worktrees") if isinstance(settings, dict) and isinstance(settings.get("worktrees"), dict) else {}
    override = worktrees.get("date_prefix", "inherit")
    if override == "inherit" or override is None:
        return policy
    if not isinstance(override, bool):
        raise ValueError("project code setting worktrees.date_prefix must be 'inherit', true, or false")
    scopes = dict(policy.scopes)
    scopes["worktrees"] = override
    return ArtifactNamingPolicy(
        enabled=True if override else policy.enabled,
        date_format=policy.date_format,
        separator=policy.separator,
        scopes=scopes,
    )


def normalize_domain(value: str) -> str:
    domain = validate_name(value, "domain")
    return DOMAIN_ALIASES.get(domain, domain)


def repo_root() -> Path:
    source_checkout = Path(__file__).resolve().parents[2]
    if all((source_checkout / name).is_dir() for name in ("harness", "templates", "schemas")):
        return source_checkout
    bundled = Path(__file__).resolve().parent / "_resources"
    if bundled.is_dir():
        return bundled
    return source_checkout


def template_source_dir() -> Path:
    candidate = repo_root() / "templates"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository templates directory")


def operating_manual_source_dir() -> Path:
    candidate = repo_root() / "operating-manual"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository operating-manual directory")


def harness_source_dir() -> Path:
    candidate = repo_root() / "harness"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository harness directory")


def ensure_dir(path: Path, result: ScaffoldResult) -> None:
    if path.is_dir():
        result.skipped.append(path)
        return
    path.mkdir(parents=True, exist_ok=True)
    result.created.append(path)


def _is_managed_auto_dev_compatibility_readme(path: Path) -> bool:
    """Return whether ``path`` is an exact package-owned migration README."""

    if path.is_symlink() or not path.is_file():
        return False
    content = path.read_bytes()
    managed = (
        AUTO_DEV_POLICY_COMPATIBILITY_BREADCRUMB,
        *_MANAGED_LEGACY_AUTO_DEV_READMES,
    )
    if any(content == item.encode("utf-8") for item in managed):
        return True
    # These two pre-migration package-owned planes predate the generated
    # breadcrumb. Keep their narrowly identifiable headings collapsible while
    # preserving every other user-authored README as a conflict.
    return content.startswith(
        b"# DEV_STANDARDS (Composable Markdown Contract)\n\nCreated: 2026-07-18."
    ) or content.startswith(
        b"# QA Gates (Composable Markdown Contract)\n\nCreated: 2026-07-19."
    )


def migrate_auto_dev_policy_directories(parent: Path, result: ScaffoldResult) -> None:
    """Move legacy sibling policy folders beneath the single Auto-Dev parent.

    The move is additive and conflict-safe. Identical files and explicitly
    managed compatibility READMEs collapse to one canonical copy. Any other
    collision stops the scaffold instead of silently choosing one.
    """

    operations: list[tuple[str, Path, Path]] = []
    legacy_roots: list[Path] = []
    auto_dev = parent / "auto_dev"
    for plane in AUTO_DEV_CHILD_POLICY_PLANES:
        legacy = parent / plane
        if not legacy.is_dir():
            continue
        legacy_roots.append(legacy)
        canonical = auto_dev / plane
        files = sorted(
            (path for path in legacy.rglob("*") if path.is_file() or path.is_symlink()),
            key=lambda path: path.relative_to(legacy).as_posix(),
        )
        for source in files:
            destination = canonical / source.relative_to(legacy)
            if destination.exists() or destination.is_symlink():
                if (
                    source.is_file()
                    and destination.is_file()
                    and not source.is_symlink()
                    and not destination.is_symlink()
                    and source.read_bytes() == destination.read_bytes()
                ):
                    operations.append(("collapse", source, destination))
                    continue
                if (
                    source.name.casefold() == "readme.md"
                    and _is_managed_auto_dev_compatibility_readme(source)
                ):
                    operations.append(("collapse", source, destination))
                    continue
                raise ValueError(
                    "Auto-Dev policy migration conflict: "
                    f"{source} and {destination} contain different content"
                )
            operations.append(("move", source, destination))

    # Preflight every collision before mutating any plane.
    for action, source, destination in operations:
        if action == "collapse":
            source.unlink()
            result.skipped.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        result.updated.append(destination)

    for legacy in legacy_roots:
        for directory in sorted(
            (path for path in legacy.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.rmdir()
        legacy.rmdir()


def write_file_once(path: Path, content: str, result: ScaffoldResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(path)


def ensure_spotlight_never_index(directory: Path, result: ScaffoldResult) -> None:
    write_file_once(directory / SPOTLIGHT_NEVER_INDEX_FILENAME, "", result)


def ensure_codex_config(
    root: Path,
    layer: str,
    result: ScaffoldResult,
    *,
    compact_context: bool = False,
) -> None:
    config_result = install_config(
        root,
        layer=layer,
        dry_run=False,
        confirm_conflicts=True,
        compact_context=compact_context,
    )
    result.created.extend(config_result.created)
    result.updated.extend(config_result.updated)
    result.skipped.extend(config_result.skipped)


def root_marker_content(_projects_source: str | Path = DEFAULT_PROJECTS_SOURCE) -> str:
    return f"""# Agentic OS root marker

kind = "genomes_agentic_os_root"
version = "1"
source_package_version = "{SOURCE_PACKAGE_VERSION}"
project_link_scope = "domain_project_src"
harness_entrypoint = "harness/AGENTS.md"
update_channel = "{DEFAULT_UPDATE_CHANNEL}"
update_policy = "{DEFAULT_UPDATE_POLICY}"
update_registry = "harness/registries/updates.yml"
"""


def write_root_marker(root: Path, result: ScaffoldResult, projects_source: str | Path = DEFAULT_PROJECTS_SOURCE) -> None:
    write_file_once(root / ROOT_MARKER_FILENAME, root_marker_content(projects_source), result)


def update_lock_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_package": "genomes-agentic-os",
        "installed_version": SOURCE_PACKAGE_VERSION,
        "update_channel": DEFAULT_UPDATE_CHANNEL,
        "update_policy": DEFAULT_UPDATE_POLICY,
        "status": "installed",
    }


def update_policy_markdown() -> str:
    return """# Update Policy

Updates are additive by default. Local edits, customer files, prompts, source
code, logs, and secrets are not collected or overwritten by automated update
commands.

## Approval Required

- Executable changes
- Hook changes
- MCP server registration changes
- Rule or permission changes
- Any destructive operation

## Safe Without Additional Approval

- Missing templates
- Missing docs
- Missing registry entries
- Missing command definitions
"""


def updates_registry_payload() -> dict[str, object]:
    return {
        "updates": {
            "installed_version": SOURCE_PACKAGE_VERSION,
            "channel": DEFAULT_UPDATE_CHANNEL,
            "policy": DEFAULT_UPDATE_POLICY,
            "latest_known_version": SOURCE_PACKAGE_VERSION,
            "status_ref": "harness/registries/update-status.yml",
        }
    }


def ensure_update_metadata(root: Path, result: ScaffoldResult) -> None:
    write_file_once(harness_path(root, "agentic-os.lock.json"), json.dumps(update_lock_payload(), indent=2) + "\n", result)
    write_file_once(harness_path(root, "UPDATE_POLICY.md"), update_policy_markdown(), result)
    write_file_once(harness_path(root, "registries", "updates.yml"), yaml.safe_dump(updates_registry_payload(), sort_keys=False), result)


def customer_identity_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "install_id": "local",
        "license": {
            "status": "inactive",
            "activated_at": "",
            "key_hash": "",
        },
        "update_grant": {
            "status": "not_registered",
            "path": "harness/registries/update-grant.json",
        },
    }


def backup_policy_payload() -> dict[str, object]:
    return {
        "backup_policy": {
            "enabled": True,
            "include": [
                ".agentic_root",
                "lib/",
                "harness/AGENTS.md",
                "harness/artifact-config/",
                "harness/ROUTER.md",
                "harness/CONTEXT.md",
                "harness/RULES.md",
                "harness/TOOLS.md",
                "harness/bin/",
                "harness/commands/",
                "harness/investigation-config/",
                "harness/registries/",
                "harness/reports/",
                "harness/rules/",
                "harness/skills/",
                "harness/shared_factory/00-control-plane/",
            ],
            "exclude": [
                "projects/",
                "harness/logs/",
                "harness/security/ssh/*",
                "**/.env",
                "**/*secret*",
                "**/*token*",
            ],
            "remote": {
                "name": "agentic-os-backup",
                "url": "",
            },
        }
    }


def ensure_customer_update_contract(root: Path, result: ScaffoldResult) -> None:
    ensure_dir(harness_path(root, "security"), result)
    ensure_dir(harness_path(root, "security", "ssh"), result)
    ensure_dir(harness_path(root, "logs"), result)
    ensure_dir(harness_path(root, "logs", "updates"), result)
    ensure_dir(harness_path(root, "logs", "backups"), result)
    write_file_once(harness_path(root, "registries", "customer-identity.json"), json.dumps(customer_identity_payload(), indent=2) + "\n", result)
    write_file_once(
        harness_path(root, "registries", "backup-policy.yml"),
        yaml.safe_dump(backup_policy_payload(), sort_keys=False),
        result,
    )


def append_once(path: Path, content: str, result: ScaffoldResult) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if content in existing:
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(f"{existing}{separator}{content}", encoding="utf-8")
    result.updated.append(path)


def write_managed_marker_block(
    path: Path,
    block: str,
    result: ScaffoldResult,
) -> None:
    """Insert or replace one package-owned block without touching local prose."""
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    start = existing.find(EXECUTION_FABRIC_MARKER_START)
    end = existing.find(EXECUTION_FABRIC_MARKER_END)
    if (start >= 0) != (end >= 0) or (start >= 0 and end < start):
        conflict = path.with_name(f"{path.name}.execution-fabric.new")
        conflict.write_text(block, encoding="utf-8")
        if conflict in result.created or conflict in result.updated:
            return
        result.created.append(conflict)
        return
    if start >= 0:
        end += len(EXECUTION_FABRIC_MARKER_END)
        candidate = f"{existing[:start]}{block.rstrip()}{existing[end:]}"
    else:
        separator = "\n" if existing.endswith("\n") else "\n\n"
        candidate = f"{existing}{separator}{block}"
    if candidate == existing:
        result.skipped.append(path)
        return
    path.write_text(candidate, encoding="utf-8")
    result.updated.append(path)


def ensure_execution_fabric_routing_blocks(
    root: Path,
    result: ScaffoldResult,
) -> None:
    """Reconcile managed queue guidance across installed routing layers."""
    layers: list[Path] = [harness_path(root)]
    domains_root = root / "domains"
    if domains_root.is_dir():
        layers.extend(
            path for path in sorted(domains_root.iterdir()) if path.is_dir()
        )
    shared_factory = harness_path(root, "shared_factory")
    if shared_factory.is_dir():
        layers.append(shared_factory)
    for domain_root in list(layers[1:]):
        projects_root = domain_root / "02-projects"
        if projects_root.is_dir():
            layers.extend(
                path
                for path in sorted(projects_root.iterdir())
                if path.is_dir() and (path / "project.yml").is_file()
            )
    seen: set[Path] = set()
    for layer in layers:
        resolved = layer.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        for filename in ("AGENTS.md", "ROUTER.md", "RULES.md", "TOOLS.md"):
            write_managed_marker_block(
                layer / filename,
                EXECUTION_FABRIC_ROUTING_BLOCK,
                result,
            )


def copy_file(source: Path, destination: Path, result: ScaffoldResult) -> None:
    if destination.exists():
        result.skipped.append(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def ensure_schemas_dir(root: Path, result: ScaffoldResult) -> None:
    """Upgrade package-owned schemas while preserving any local override."""
    try:
        schemas_source = repo_root() / "schemas"
    except FileNotFoundError:
        # Running from a non-editable pip install that has no repo checkout;
        # ship the schemas from the package data directory instead.
        schemas_source = Path(__file__).parent.parent.parent / "schemas"
    if not schemas_source.is_dir():
        return
    dest = harness_path(root, "schemas")
    ensure_dir(dest, result)
    manifest_path = dest / "package-manifest.yml"
    previous: dict[str, dict[str, object]] = {}
    if manifest_path.is_file():
        try:
            payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            payload = {}
        entries = payload.get("entries") if isinstance(payload, dict) else []
        if isinstance(entries, list):
            previous = {
                str(entry.get("destination")): entry
                for entry in entries
                if isinstance(entry, dict) and entry.get("destination")
            }
    manifest_entries: list[dict[str, object]] = []
    for schema_file in sorted(schemas_source.glob("*.json")):
        destination = dest / schema_file.name
        relative = f"harness/schemas/{schema_file.name}"
        source_checksum = file_sha256(schema_file)
        prior = previous.get(relative, {})
        managed_checksum = str(prior.get("managed_checksum") or "")
        status = "current"
        if not destination.exists():
            shutil.copy2(schema_file, destination)
            result.created.append(destination)
        else:
            installed_checksum = file_sha256(destination)
            if installed_checksum == source_checksum:
                result.skipped.append(destination)
            elif managed_checksum and installed_checksum == managed_checksum:
                shutil.copy2(schema_file, destination)
                result.updated.append(destination)
            else:
                conflict = destination.with_name(f"{destination.name}.new")
                if not conflict.exists() or file_sha256(conflict) != source_checksum:
                    existed = conflict.exists()
                    shutil.copy2(schema_file, conflict)
                    (result.updated if existed else result.created).append(conflict)
                else:
                    result.skipped.append(conflict)
                status = "local_override"
        observed_checksum = file_sha256(destination)
        manifest_entries.append(
            {
                "source": f"schemas/{schema_file.name}",
                "destination": relative,
                "source_checksum": source_checksum,
                "managed_checksum": (
                    source_checksum
                    if observed_checksum == source_checksum
                    else managed_checksum or None
                ),
                "observed_checksum": observed_checksum,
                "status": status,
            }
        )
    desired_manifest = yaml.safe_dump(
        {
            "schema_version": 1,
            "managed_by": "genomes-agentic-os package",
            "entries": manifest_entries,
        },
        sort_keys=False,
    )
    if not manifest_path.exists():
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.created.append(manifest_path)
    elif manifest_path.read_text(encoding="utf-8") != desired_manifest:
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.updated.append(manifest_path)
    else:
        result.skipped.append(manifest_path)


def ensure_report_engine_contract(root: Path, result: ScaffoldResult) -> None:
    """Install additive, empty first-class report registries.

    Report content belongs to the installed OS, so source-package upgrades must
    never overwrite these registries after their first creation.
    """
    registries = {
        "report-definitions.yml": {"api_version": "report-registry/v1", "definitions": []},
        "report-runs.yml": {"api_version": "report-run-registry/v1", "runs": []},
        "report-artifacts.yml": {"api_version": "report-artifact-registry/v1", "artifacts": []},
    }
    for filename, payload in registries.items():
        write_file_once(
            harness_path(root, "registries", filename),
            yaml.safe_dump(payload, sort_keys=False),
            result,
        )


def ensure_context_migration_contract(root: Path, result: ScaffoldResult) -> None:
    """Install the empty operator-owned named context migration registry."""
    write_file_once(
        shared_factory_path(root, "00-control-plane", "context-migrations.yml"),
        yaml.safe_dump({"schema_version": 1, "migrations": []}, sort_keys=False),
        result,
    )


def copy_file_once(source: Path, destination: Path, result: ScaffoldResult) -> None:
    copy_file(source, destination, result)


def source_relative_path(relative_path: str) -> Path:
    return repo_root() / relative_path


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def managed_templates_payload() -> dict[str, object]:
    entries = []
    for source, destination, merge_policy in MANAGED_RUNTIME_FILES:
        source_path = source_relative_path(source)
        checksum = file_sha256(source_path) if source_path.is_file() else "sha256:missing"
        entries.append(
            {
                "source": source,
                "destination": destination,
                "source_version": 1,
                "source_checksum": checksum,
                "installed_checksum": checksum,
                "merge_policy": merge_policy,
            }
        )
    return {
        "schema_version": 1,
        "managed_by": "agentic-os self-improvement",
        "entries": entries,
    }


def previous_managed_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    entries = data.get("entries") if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return {}
    checksums = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        destination = entry.get("destination")
        installed_checksum = entry.get("installed_checksum")
        if destination and installed_checksum:
            checksums[str(destination)] = str(installed_checksum)
    return checksums


def write_managed_file(source: Path, destination: Path, previous_checksum: str | None, result: ScaffoldResult) -> None:
    source_checksum = file_sha256(source)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        result.created.append(destination)
        return
    destination_checksum = file_sha256(destination)
    if destination_checksum == source_checksum:
        result.skipped.append(destination)
        return
    if previous_checksum and destination_checksum == previous_checksum:
        shutil.copy2(source, destination)
        result.updated.append(destination)
        return
    conflict_path = destination.with_name(f"{destination.name}.new")
    if conflict_path.exists() and file_sha256(conflict_path) == source_checksum:
        result.skipped.append(conflict_path)
        return
    existed = conflict_path.exists()
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, conflict_path)
    if existed:
        result.updated.append(conflict_path)
    else:
        result.created.append(conflict_path)


def ensure_notion_tracking_config(root: Path, result: ScaffoldResult) -> None:
    """Install the notion-tracking.yml config file into 00-control-plane if absent.

    This is a write-once install — existing operator edits are never overwritten.
    The template lives at ``templates/runtime/notion-tracking.yml`` in the source tree.
    """
    destination = shared_factory_path(root, "00-control-plane", "notion-tracking.yml")
    if destination.exists():
        result.skipped.append(destination)
        return
    source = source_relative_path("templates/runtime/notion-tracking.yml")
    if not source.is_file():
        return  # source package missing template — skip silently
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def ensure_runtime_control_config(root: Path, template_name: str, destination_name: str, result: ScaffoldResult) -> None:
    destination = shared_factory_path(root, "00-control-plane", destination_name)
    if destination.exists():
        result.skipped.append(destination)
        return
    source = source_relative_path(f"templates/runtime/{template_name}")
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def ensure_self_improvement_surface(root: Path, result: ScaffoldResult) -> None:
    for directory in ("runs", "proposals", "approvals", "drafts"):
        ensure_dir(shared_factory_path(root, "06-runs-and-logs", "self-improvement", directory), result)

    manifest_path = shared_factory_path(root, "00-control-plane", "managed-templates.yml")
    previous_checksums = previous_managed_checksums(manifest_path)
    for source, destination, _merge_policy in MANAGED_RUNTIME_FILES:
        source_path = source_relative_path(source)
        destination_path = root / destination
        write_managed_file(source_path, destination_path, previous_checksums.get(destination), result)

    desired_manifest = yaml.safe_dump(managed_templates_payload(), sort_keys=False)
    if not manifest_path.exists():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.created.append(manifest_path)
    elif manifest_path.read_text(encoding="utf-8") == desired_manifest:
        result.skipped.append(manifest_path)
    else:
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.updated.append(manifest_path)

    ensure_notion_tracking_config(root, result)
    ensure_runtime_control_config(root, "documentation-upkeep.yml", "documentation-upkeep.yml", result)
    ensure_runtime_control_config(root, "doc-config.yml", "doc-config.yml", result)
    ensure_runtime_control_config(root, "notion-organization.yml", "notion-organization.yml", result)
    ensure_runtime_control_config(root, "automation-control.yml", "automation-control.yml", result)
    ensure_runtime_control_config(
        root,
        "adaptive-routing-observation-report.yml",
        "adaptive-routing-observation-report.yml",
        result,
    )
    ensure_runtime_control_config(
        root,
        "adaptive-routing-pricing.yml",
        "adaptive-routing-pricing.yml",
        result,
    )


def copy_tree(
    source: Path,
    destination: Path,
    *,
    excluded: tuple[Path, ...] = (),
) -> ScaffoldResult:
    result = ScaffoldResult()
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if (
            "__pycache__" in relative.parts
            or relative.suffix in {".pyc", ".pyo"}
        ):
            continue
        if any(relative == prefix or prefix in relative.parents for prefix in excluded):
            continue
        target = destination / relative
        if item.is_dir():
            ensure_dir(target, result)
        else:
            copy_file(item, target, result)
    return result


def copy_tree_missing(source: Path, destination: Path) -> ScaffoldResult:
    return copy_tree(source, destination)


def ensure_managed_resource_surfaces(root: Path, result: ScaffoldResult) -> None:
    """Install source-owned programs, workflows, and toolkits additively.

    Runtime state is intentionally absent from these allowlists.  Each source
    path is a reusable definition required for cross-harness discovery; local
    receipts, schedules, articles, and project data remain operator-owned.
    """
    for source, destination in MANAGED_RESOURCE_TREES:
        source_path = source_relative_path(source)
        if source_path.is_dir():
            destination_path = Path(destination)
            # The external object library is a receipt-backed projection. The
            # GAOS wheel may carry a first-install fallback, but update/init
            # must never add files directly to an installed external revision.
            # Keep package fallbacks outside lib/ and let library.init project
            # them only into a new, unreceipted managed placeholder.
            if destination_path.parts[:1] == ("lib",):
                destination_path = (
                    MANAGED_LIBRARY_FALLBACK_ROOT / destination_path
                )
            result.extend(copy_tree(source_path, root / destination_path))
    ensure_object_library_command_projection(root, result)


def ensure_object_library_command_projection(root: Path, result: ScaffoldResult) -> None:
    """Project the Python-registered library command into object discovery."""

    command = next(entry for entry in command_entries() if entry["id"] == "object-library")
    target = (
        root
        / MANAGED_LIBRARY_FALLBACK_ROOT
        / "lib"
        / "commands"
        / "root"
        / "object-library"
    )
    copy_file(source_relative_path(command["source"]), target / "command.md", result)
    manifest = {
        "api_version": "agentic-os-library-object/v1",
        "kind": "command",
        "id": "object-library",
        "title": "Object Library",
        "description": command["description"],
        "status": "active",
        "scope": {"level": "root", "domain": None, "project": None},
        "owner": {"type": "package", "id": "genomes_agentic_os"},
        "entrypoint": "command.md",
        "tags": ["command", "object-library", "auto-dev"],
        "dependencies": [],
        "aliases": [command["source"]],
        "runtime": {"root": "runtime/objects/commands/command/root/object-library"},
        "validation": {"commands": ["agentic-os library --help"]},
    }
    write_file_once(
        target / "object.yml",
        yaml.safe_dump(manifest, sort_keys=False),
        result,
    )


def ensure_auto_dev_program_alias(root: Path, result: ScaffoldResult) -> None:
    """Expose the canonical library program at its historical routed path."""

    canonical = root / "lib" / "programs" / "root" / "auto-dev"
    alias = shared_factory_path(root, "00-programs", "auto_dev")
    if not canonical.is_dir():
        return
    if alias.is_symlink():
        if alias.resolve() == canonical.resolve():
            result.skipped.append(alias)
        else:
            result.skipped.append(alias)
        return
    if alias.exists():
        # Existing operator-owned physical folders are never removed during an
        # additive update. ``library migrate`` can reconcile them explicitly.
        result.skipped.append(alias)
        return
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to("../../../lib/programs/root/auto-dev", target_is_directory=True)
    result.created.append(alias)


def ensure_visible_capability_directories(root: Path, result: ScaffoldResult) -> None:
    for directory in VISIBLE_CAPABILITY_DIRECTORIES:
        ensure_dir(root / directory, result)


def ensure_capability_registries(root: Path, result: ScaffoldResult) -> None:
    for relative_path, payload in registry_file_payloads().items():
        merge_registry_file(root / relative_path, payload, result)
    write_file_once(harness_path(root, "INVENTORY.md"), inventory_markdown(), result)


def merge_registry_file(path: Path, payload: dict[str, list[dict[str, str]]], result: ScaffoldResult) -> None:
    if not path.exists():
        write_file_once(path, yaml.safe_dump(payload, sort_keys=False), result)
        return
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(existing, dict):
        result.skipped.append(path)
        return
    changed = False
    for key, entries in payload.items():
        current = existing.get(key)
        if not isinstance(current, list):
            existing[key] = []
            current = existing[key]
            changed = True
        current_by_id = {entry.get("id"): entry for entry in current if isinstance(entry, dict)}
        existing_ids = set(current_by_id)
        for entry in entries:
            if entry.get("id") not in existing_ids:
                current.append(entry)
                existing_ids.add(entry.get("id"))
                changed = True
                continue
            existing_entry = current_by_id.get(entry.get("id"))
            if not isinstance(existing_entry, dict):
                continue
            source = entry.get("source")
            if source and existing_entry.get("source") != source:
                existing_entry["source"] = source
                changed = True
    if changed:
        path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
        result.updated.append(path)
    else:
        result.skipped.append(path)


def ensure_visible_capability_surface(root: Path, result: ScaffoldResult) -> None:
    ensure_visible_capability_directories(root, result)
    ensure_capability_registries(root, result)
    hooks_root = harness_source_dir() / "hooks"
    if hooks_root.is_dir():
        result.extend(copy_tree_missing(hooks_root, harness_path(root, "hooks")))


def mirror_visible_capability_assets(root: Path) -> ScaffoldResult:
    result = ScaffoldResult()
    harness_root = harness_source_dir()
    for directory in (
        "artifact-config",
        "investigation-config",
        "bin",
        "commands",
        "skills",
        "mcp",
        "plugins",
        "libraries",
        "hooks",
        "reports",
        "rules",
        "shared_factory",
    ):
        source = harness_root / directory
        if source.is_dir():
            if directory == "shared_factory":
                result.extend(
                    copy_tree(
                        source,
                        harness_path(root, directory),
                        excluded=(Path("00-programs/auto_dev"),),
                    )
                )
            else:
                result.extend(copy_tree_missing(source, harness_path(root, directory)))
    return result


def titleize_name(name: str) -> str:
    known_names = {
        "personal": "Personal",
        "work": "Work",
        "shared_factory": "Shared Factory",
        "archive": "Archive",
    }
    return known_names.get(name, name.replace("_", " ").title())


def domain_purpose(domain: str) -> str:
    purposes = {
        "personal": "Personal administration, household operations, learning, planning, and life logistics.",
        "work": "Professional work: product delivery, client engagements, operations, and reusable service workflows.",
        "shared_factory": "Shared patterns, templates, routers, reusable automations, schemas, and cross-domain tools.",
        "archive": "Inactive work, retired projects, historical runs, and preserved decisions.",
    }
    return purposes.get(domain, "Describe the operating boundary this domain owns.")


def root_readme(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in domains_list)
    return f"""# Installed Agentic OS

This is the live operating system root for agentic work. It is domain-first: choose the domain, then use that domain's control plane, inbox, projects, workflows, automations, knowledge, runs, metrics, and archive. OS brains and harness-visible capabilities live under `harness/`.

## Domains

{domains}

## Harness Brain

- `harness/` - root router, tools, commands, skills, hooks, MCP declarations, registries, logs, update metadata, and the shared factory.
- `harness/shared_factory/` - reusable patterns, templates, workflow and automation building blocks, runtime registries, and cross-domain knowledge.

## Standard Domain Shape

Each domain uses the same numbered operating lanes:

- `00-control-plane/` - active work, routing, approvals, and decisions.
- `01-inbox/` - raw capture and triage.
- `02-projects/` - active project folders.
- `03-workflows/` - repeatable human-and-agent workflow specs.
- `04-automations/` - trigger-driven automation specs and logs.
- `05-knowledge/` - source maps, glossary, memory policy, and reference material.
- `06-runs-and-logs/` - execution records, artifacts, failures, and activity logs.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - closed or inactive material.

## Agent Entry Point

Start with `harness/AGENTS.md`. It tells every harness to read
`ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`, route to the narrowest
directory, and repeat the same local read loop before acting.

`CLAUDE.md` is a Claude adapter that includes `AGENTS.md`. `AGENT.md` is not
generated by default; create it only for a compatibility harness that proves it
needs that exact filename.
"""


def root_router(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    routing_rows = "\n".join(
        f"| `{domain}` | {domain_purpose(domain)} | `{domain}/01-inbox/` |"
        for domain in domains_list
    )
    return f"""# Agent Router

Use this file before touching work inside the installed Agentic OS.
After choosing a domain or narrower layer, change to that directory and read its
`ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting.

## Routing Table

| Domain | Use For | Intake Path |
| --- | --- | --- |
{routing_rows}
| `harness/shared_factory` | Shared OS templates, schemas, routers, reusable automations, runtime registries, cross-domain tools, and installed harness capabilities. | `harness/shared_factory/01-inbox/` |

## SDLC Intent Routing

| Intent | Canonical workflow |
| --- | --- |
| Bug, QA failure, ticket comment, log, alert, incident, suspected cause, or RCA | Auto-Dev Detective |
| Jira, Linear, Notion, Confluence, GitHub, Slack, RCA, report, or local artifact authoring | Auto-Dev Create Artifacts |
| Take one tracker item through every applicable SDLC step | Auto-Dev Everything |
| Renovate or Dependabot dependency-update pull request | Auto-Dev Dep Updater |
| Our pull request through governed merge, release, and documentation | Auto-Dev Continuous Release |
| Implement, review, validate, release, deploy, or close out code | Auto-Dev over Development Delivery |
| Audit receipts and retire reconstructable local resources after verified delivery | Auto-Dev Health |
| Queue admission, worker capacity, run state, retries, dead letters, effects, alarms, healing, or host failover | `harness/shared_factory/00-programs/execution_fabric/` |

Select these workflows by intent even when the user does not name Auto-Dev.
Route to the domain/project before resolving its policy additions.

## Domain Classification

- First identify the project, product, client, or life area named in the request.
- Route explicit project or product names to their domain before deciding whether the work is an idea, project, workflow, automation, run, or knowledge update.
- Examples: requests mentioning a professional project, product, or client engagement route to that work domain; requests about household, learning, or life logistics route to `personal/`.
- If a request says `add an idea`, `capture an idea`, `idea for`, or similar, route to the matching domain's `01-inbox/` unless the user explicitly asks to create a project, workflow, automation, tracker ticket, or implementation branch.

## Operating Rules

- Pick a domain before creating projects, workflows, automations, or run logs.
- Repeat the route-read-cd loop after changing directories.
- Do not create new root-level work folders for active work.
- Put workflow specs in `<domain>/03-workflows/<lane>/<workflow>/`.
- Put automation specs in `<domain>/04-automations/<lane>/<automation>/`.
- Put execution records in `<domain>/06-runs-and-logs/runs/`.
- Use `harness/shared_factory` for reusable templates, schemas, and cross-domain operating patterns.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read `harness/shared_factory/05-knowledge/host-tool-registry.<host>.yml` when it exists.
- Close or park inactive work in canonical state; use an owning domain's
  `08-archive/` only for retained historical material.

## Standard Lanes

{chr(10).join(f"- `{lane}`" for lane in STANDARD_LANES)}

## Approval Defaults

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval unless a domain rule narrows the restriction further.
"""


def agent_entrypoint(scope: str = "this Agentic OS layer") -> str:
    return f"""# Agent Entry Point

This is the harness-neutral entry point for {scope}.

## Required Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.
2. Classify the request against `ROUTER.md`.
3. If the router points to a narrower directory, change to that directory.
4. Repeat the local read and routing loop until no narrower route applies.
5. Act only after loading the final layer's context, rules, and tool registry.
6. Record unclear routes, missing tools, and durable follow-up in the run log or closeout artifact.

## Auto-Dev SDLC Routing

Use Auto-Dev Detective for causal investigation, Auto-Dev Create Artifacts for
governed provider output, and Auto-Dev over Development Delivery for coding
through release. Invoke them by intent; the user does not need to remember the
program name. Resolve root → domain → project → invocation Markdown policies
before each workflow.

Route Renovate or Dependabot pull requests through `auto-dev-dep-updater`.
Route our own pull requests that should continue through merge, release, and
documentation through `auto-dev-continuous-release`. Their authority comes
from the routed project's `dep_updater`, `continuous_release`, and `release`
policy blocks.

## Adaptive Observe Receipt

When the installed adaptive observation config is enabled and `CODEX_THREAD_ID`
is available, run `agentic-os adaptive-routing observe --root <root> "<original
user request>"` once per substantive user task before its first action. The command analyzes
locally, never executes the route, never persists task text, and treats a
duplicate turn correlation as an idempotent no-op.

## Context Precedence

- User instructions override local defaults.
- Narrower `RULES.md` files override broader rules unless the broader rule is stricter for safety, privacy, production, billing, legal, or customer-visible work.
- `TOOLS.md` is the visible tool contract. Harness-specific install folders only implement that contract.
"""


def claude_adapter() -> str:
    return "@AGENTS.md\n"


def root_instruction_adapter(filename: str) -> str:
    """Return a root-level discovery adapter for the canonical harness contract.

    The installed root is a conversation launch point for both Claude and
    Codex.  Keep the complete contract under ``harness/``, but leave a small,
    portable entry surface at the root so neither harness starts without a
    route-read context contract after the harness-layout migration.
    """

    if filename == "AGENTS.md":
        return """# Agentic OS Root Entry Point

This directory is the automatic entry point for the installed Agentic OS.
Before replying, selecting a tool, or changing state for Agentic OS work, read
the canonical root contract in this order:

1. `harness/AGENTS.md`
2. `harness/ROUTER.md`, `harness/CONTEXT.md`, `harness/RULES.md`, and `harness/TOOLS.md`
3. The routed domain's local `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`

Route to the narrowest domain, project, workflow, automation, or run before
acting, then repeat the local route-read loop. `harness/` owns the canonical
root contract; these root adapters exist solely so Claude and Codex discover it
when a conversation starts in this directory.
"""
    if filename == "CLAUDE.md":
        return claude_adapter()
    title = filename.removesuffix(".md").replace("_", " ").title()
    return f"""# Agentic OS Root {title} Adapter

The canonical root `{filename}` is `harness/{filename}`. Read that file before
acting on Agentic OS work started from this directory.
"""


def ensure_root_instruction_adapters(root: Path, result: ScaffoldResult) -> None:
    for filename in ("AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        write_file_once(root / filename, root_instruction_adapter(filename), result)


def legacy_agent_adapter() -> str:
    return """# Legacy Agent Adapter

Load `AGENTS.md` first, then follow the local route-read-cd loop.
"""


def root_context(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in domains_list)
    return f"""# Local Context

This installed harness directory is the entry layer for Genome's Agentic OS runtime. It
routes work into domain rooms, shared factory materials, workflows,
automations, projects, run logs, and archived material.

## Domains

{domains}

## What To Load

| Need | Read First | Read When Needed | Skip By Default |
| --- | --- | --- | --- |
| Route new work | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md` | domain router | unrelated domains |
| Shared template or skill work | `shared_factory/05-knowledge/` index files | relevant template, command, skill, or plan | active domain state |
| Shell or runtime work | host tool registry under `shared_factory/05-knowledge/` | installed command docs | customer data |
| Resume active domain work | routed domain `CONTEXT.md` and active work files | project status, workflow context pack, run logs | unrelated projects |
| Investigate a signal | `investigation-config/`, then routed domain/project additions | deployed version and selected evidence adapters | unrelated product evidence |
| Author an artifact | `artifact-config/`, then routed domain/project additions | provider target and readback tool | direct provider write before validation |
| Deliver code | Auto-Dev program plus development/QA/gitflow policy planes | selected repository and deployed/release context | guessed repository or branch |

## Done Means

- Work was routed to the narrowest correct layer.
- Source evidence and validation are recorded.
- Approval gates in `RULES.md` were followed.
- Missing route or tool information was recorded before handoff.
"""


def root_rules() -> str:
    return """# Rules

These root rules apply unless a narrower layer provides a stricter rule.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- Route before acting.
- Prefer the narrowest applicable domain, project, workflow, automation, or run log.
- Preserve source links and validation evidence.
- Keep secrets out of prompts, logs, docs, generated config, and run artifacts.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read the host tool registry when it exists.
- When creating or changing Agentic OS commands, skills, workflows,
  automations, tools, registries, feature intake, bug intake, or project
  worktrees, follow `harness/rules/os-authoring-rules.md`.
- External source checkouts used for project work must be visible through the
  project `worktrees/` registry/link surface.

## Auto-Dev Rules

- Resolve and receipt root, domain, project, and invocation policy before SDLC execution.
- Establish the affected environment's deployed version before causal code analysis.
- Keep investigation facts, hypotheses, contradictions, gaps, and confidence distinct.
- Pause and resume the same run for unavailable VPN, environment, provider, authentication, rate limit, or operator decision; do not create retry-failure storms.
- Render and validate governed artifacts before approved external apply, then read back and receipt the provider result.

## Managed Execution Rules

- When Execution Fabric is enabled, every managed workflow and automation
  admits work through its configured named queue; folder counts, detached
  processes, and direct vendor queue writes are not concurrency controls.
- Route queue selection, capacity, worker, retry, dead-letter, effect,
  observability, healing, and failover questions to
  `harness/shared_factory/00-programs/execution_fabric/`. Do not copy that
  program's policy into domains or projects.
- Treat admission, assignment, attempt, effect, and terminal run receipts as
  the execution record. A trigger, health check, or process id alone does not
  prove that requested work ran.

## Precedence

Narrower rules override broader rules unless the broader rule is stricter for
safety, privacy, production, billing, legal, or customer-visible work.
"""


def root_tools() -> str:
    hooks = "\n".join(
        f"| `{entry['id']}` | {entry['description']} | `{entry.get('source', '')}` |"
        for entry in hook_entries()
    )
    return f"""# Tools

This harness registry names the visible tool surface for the installed Agentic OS.
Folders under `harness/` and config files implement this contract; they are not
the source of truth by themselves.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route work through installed OS rooms. | `shared_factory/05-knowledge/skills/os-navigator/` |
| `workflow-builder` | Create or improve reusable workflows. | `shared_factory/05-knowledge/skills/workflow-builder/` |
| `doc-config-router` | Decide where docs belong before filesystem or Notion projection work. | `shared_factory/05-knowledge/skills/doc-config-router/` |
| `spec-intake-router` | Capture new specs and future work through doc-config and work-item intake. | `shared_factory/05-knowledge/skills/spec-intake-router/` |
| `spec-groomer` | Groom rough ideas into implementation-ready specs with intent preservation, discovery, QA, and projection receipts. | `shared_factory/05-knowledge/skills/spec-groomer/` |
| `feature-intake-router` | Deprecated alias for spec intake. | `shared_factory/05-knowledge/skills/feature-intake-router/` |
| `bug-intake-router` | Capture bugs and missed enforcement through doc-config and work-item intake. | `shared_factory/05-knowledge/skills/bug-intake-router/` |
| `auto-spec-intake` | Create/update spec packets for long OS-shaping requests. | `shared_factory/05-knowledge/skills/auto-spec-intake/` |
| `auto-feature-intake` | Deprecated alias for auto spec intake. | `shared_factory/05-knowledge/skills/auto-feature-intake/` |
| `os-authoring-guard` | Apply compact OS authoring rules to reusable surface changes. | `shared_factory/05-knowledge/skills/os-authoring-guard/` |
| `automation-qualifier` | Decide whether a process is safe to automate. | `shared_factory/05-knowledge/skills/automation-qualifier/` |
| `quiet-async-runner` | Run long waits through artifact-backed async state instead of chat polling. | `shared_factory/05-knowledge/skills/quiet-async-runner/` |
| `cockpit` | Build or open the local engineering cockpit over canonical OS state. | `shared_factory/05-knowledge/skills/cockpit/` |
| `agentic-os-gui` | Open or build the domain/project-focused desktop conversation driver. | `shared_factory/05-knowledge/skills/agentic-os-gui/` |
| `execution-fabric` | Inspect named queues, worker pools, run receipts, health, configuration, and cross-host failover. | `skills/execution-fabric/SKILL.md` |
| `os-doctor` | Audit installed OS structure and contracts. | `shared_factory/05-knowledge/skills/os-doctor/` |
| `auto-dev` | Run a code change through the canonical SDLC family. | `skills/auto-dev/SKILL.md` |
| `auto-dev-everything` | Run every applicable workflow against one resumable `autodev.json`. | `skills/auto-dev-everything/SKILL.md` |
| `auto-dev-grooming` | Groom rough work into a source-backed implementation-ready specification. | `skills/auto-dev-grooming/SKILL.md` |
| `auto-dev-create-artifacts` | Author a configured Jira, Linear, Notion, Confluence, GitHub, Slack, RCA, report, or filesystem artifact. | `skills/auto-dev-create-artifacts/SKILL.md` |
| `auto-dev-detective` | Investigate a bug, failed QA, log, incident, suspected cause, or RCA with versioned evidence. | `skills/auto-dev-detective/SKILL.md` |
| `auto-dev-readiness` | Resolve tracker, repository, policy, worktree, and plan readiness. | `skills/auto-dev-readiness/SKILL.md` |
| `auto-dev-implementation` | Own canonical implementation and local validation behind the Develop entrypoint. | `skills/auto-dev-implementation/SKILL.md` |
| `auto-dev-develop` | Run the plain-English implementation and local-validation workflow. | `skills/auto-dev-develop/SKILL.md` |
| `auto-dev-document` | Document code, issues, architecture, operations, QA, releases, or handoffs. | `skills/auto-dev-document/SKILL.md` |
| `auto-dev-pr-create` | Resolve and create or reuse the complete pull-request family before review. | `skills/auto-dev-pr-create/SKILL.md` |
| `gitflow-pr-create` | Compatibility alias for Auto-Dev PR Create family mode. | `skills/gitflow-pr-create/SKILL.md` |
| `auto-dev-review-self` | Review and repair our own active delivery. | `skills/auto-dev-review-self/SKILL.md` |
| `auto-dev-review-self-opposing-model` | Run the canonical receipt-backed opposing-model review checkpoint. | `skills/auto-dev-review-self-opposing-model/SKILL.md` |
| `auto-dev-review-others` | Review another author's live pull request. | `skills/auto-dev-review-others/SKILL.md` |
| `auto-dev-qa` | Run project-configured QA independently. | `skills/auto-dev-qa/SKILL.md` |
| `auto-dev-review-repair` | Own canonical review and repair behind Review Self. | `skills/auto-dev-review-repair/SKILL.md` |
| `auto-dev-finalize` | Converge our ticket's pull-request family and record merge readiness without merging. | `skills/auto-dev-finalize/SKILL.md` |
| `auto-dev-merge` | Run the final live merge gate. | `skills/auto-dev-merge/SKILL.md` |
| `auto-dev-release-propagation` | Compatibility alias for Auto-Dev PR Create family mode and its lower-level recorder. | `skills/auto-dev-release-propagation/SKILL.md` |
| `auto-dev-release` | Create and verify the project release. | `skills/auto-dev-release/SKILL.md` |
| `auto-dev-deploy` | Deploy or monitor the exact artifact and verify behavior. | `skills/auto-dev-deploy/SKILL.md` |
| `auto-dev-closeout` | Reconcile provider state and prove delivery complete. | `skills/auto-dev-closeout/SKILL.md` |
| `auto-dev-health` | Audit final receipts, prune scoped local resources, and preserve the packet in the finished lane. | `skills/auto-dev-health/SKILL.md` |
| `auto-dev-dep-updater` | Take one Renovate or Dependabot pull request through project-configured validation and governed merge. | `skills/auto-dev-dep-updater/SKILL.md` |
| `auto-dev-continuous-release` | Take one of our pull requests through governed merge, project release, and documentation. | `skills/auto-dev-continuous-release/SKILL.md` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `/make-skill` | Create or improve a reusable skill. | Declared in `registries/commands.yml`. |
| `/make-domain` | Create a routed OS domain or room. | Declared in `registries/commands.yml`. |
| `/make-automation` | Create a guarded automation spec. | Declared in `registries/commands.yml`. |
| `/make-workflow` | Create a reusable workflow contract. | Declared in `registries/commands.yml`. |
| `/add-spec` | Capture future work through the configured spec intake workflow. | Declared in `registries/commands.yml`. |
| `/groom-spec` | Groom rough ideas into complete implementation specs with discovery and projection receipts. | Declared in `registries/commands.yml`. |
| `/new-feature` | Deprecated alias for `/add-spec`. | Declared in `registries/commands.yml`. |
| `/add-bug` | Capture a bug or missed OS enforcement into a routed work item. | Declared in `registries/commands.yml`. |
| `/auto-add-spec` | Create/update a spec packet for long OS-shaping requests. | Declared in `registries/commands.yml`. |
| `/auto-add-feature` | Deprecated alias for `/auto-add-spec`. | Declared in `registries/commands.yml`. |
| `/orchestrate` | Decompose, delegate, verify, and merge feature work. | Declared in `registries/commands.yml`. |
| `/auto-dev` | Route to Everything or one named Auto-Dev workflow. | Selects by intent after project routing. |
| `/auto-dev-everything` | Run every applicable stage against one `autodev.json`. | Stops at real gates and completes through Health. |
| `/auto-dev-grooming` | Groom rough work into an implementation-ready source of truth. | Standalone stage. |
| `/auto-dev-create-artifacts` | Resolve, render, validate, apply, and read back a governed artifact. | External apply remains explicit. |
| `/auto-dev-detective` | Run a deployed-version-aware, resumable evidence investigation. | Investigation stays read-only. |
| `/auto-dev-readiness` | Resolve tracker, repository, policy, worktree, and plan readiness. | Delivery-managed stage. |
| `/auto-dev-implementation` | Invoke the canonical implementation owner directly. | Compatibility/manual expert entrypoint behind Develop. |
| `/auto-dev-develop` | Implement and locally validate a planned task. | Friendly route to canonical implementation. |
| `/auto-dev-document` | Create verified code and delivery documentation. | Standalone stage. |
| `/auto-dev-pr-create` | Resolve and create or reuse the complete pull-request family. | Runs before Review Self. |
| `/gitflow-pr-create` | Invoke PR Create with GitFlow-family compatibility defaults. | Alias only; owns no policy. |
| `/auto-dev-review-self` | Review and repair our own change. | Friendly route to canonical review/repair. |
| `/auto-dev-review-self-opposing-model` | Run the canonical opposing-model review checkpoint. | Shared Claude/Codex receipt route for one ticket. |
| `/auto-dev-review-others` | Review another author's live pull request. | Uses canonical PR Review. |
| `/auto-dev-qa` | Run project-configured QA independently. | Records exact-revision evidence. |
| `/auto-dev-review-repair` | Invoke the canonical review-and-repair owner directly. | Compatibility/manual expert entrypoint behind Review Self. |
| `/auto-dev-finalize` | Converge our ticket's pull-request family. | Leaves immutable merge readiness or an exact hold; never merges. |
| `/auto-dev-merge` | Execute the final merge gate. | Requires PR-owner readiness and live provider readback. |
| `/auto-dev-release-propagation` | Run PR Create family mode through the legacy name. | Compatibility alias. |
| `/auto-dev-release` | Create and verify the project release. | Uses release policy and provider readback. |
| `/auto-dev-deploy` | Deploy and verify the exact artifact. | Records deployed-version evidence or policy skip. |
| `/auto-dev-closeout` | Reconcile provider state and prove delivery complete. | Lifecycle cleanup follows in Health. |
| `/auto-dev-health` | Audit receipts, retire scoped local resources, and finish the preserved packet. | Existing state only; global prune is forbidden. |
| `agentic-os artifacts` | Resolve, render, validate, apply, read back, or doctor artifact contracts. | Policies compose across root/domain/project/invocation. |
| `agentic-os detective` | Resolve/start/status, record version/evidence, pause/resume, analyze/conclude/render, or doctor investigations. | Resume the same run after availability returns. |
| `agentic-os develop` | Plan/start Development Delivery or explain dev/QA/gitflow policy. | Multi-repository projects require `--repository`. |
| `agentic-os validate` | Validate the installed root. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |
| `agentic-os context build` | Build a deterministic context packet. | Use for handoffs and repeatable runs. |
| `agentic-os project onboard` | Create or repair a project-local agent/config surface. | Additive by default. |
| `harness/bin/agentic-os-quiet-run` | Run long local commands with file-backed state. | Use for tests, setup, watchers, and slow waits. |
| `agentic-os cockpit snapshot/build/open` | Build or open the read-only local engineering cockpit. | Generates disposable JSON/HTML under the canonical report root. |
| `agentic-os gui snapshot/transcript/open` | Inspect or open AgenticOSGui's native Claude/Codex conversation surface. | Provider stores remain read-only; interactive actions stay behind desktop IPC. |
| `agentic-os runtime snapshot` | Inspect queue depth, workers, task/run states, retries, dead letters, and current health. | Backend-neutral read; Command Center consumes this same projection. |
| `agentic-os runtime config status/validate/reconcile` | Inspect or reconcile the canonical Execution Fabric configuration. | Reconcile is guarded and dry-run first. |
| `agentic-os runtime queue-mode` | Inspect or explicitly change the selected execution backend. | Never infer activation from installed files. |
| `agentic-os project worktree cleanup-closed` | Move terminal-status or merged-PR worktree registrations to `worktrees/closed.yml`. | Physical removal requires exact domain, project, worktree, packet-local Health preflight, and preflight-bound runtime receipt; failed or `REOPEN.md` cleanup remains registered. |
| `agentic-os project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. | Use before `finalize-lingering` in cleanup workflows. |
| `agentic-os project work-item finalize-lingering` | Move terminal-status packets out of active lanes and refresh the global active symlink container. | Use after closeout/stale-finalization cleanup. |
| `agentic-os project work-item set` | Move one filesystem packet into the lane for an explicit lifecycle state. | Use before reconciling canonical SQLite `packet_path` after a governed move. |
| `agentic-os project work-item sync-active` | Rebuild the root `00-control-plane/active/` symlink view. | Uses filesystem work-items, project worktrees, and active automations. |
| `agentic-os thread stale-finalize --dry-run` | List work items untouched for more than 3 days before applying conservative closeout. | Dry-run by default. |
| `agentic-os config doctor` | Check Codex config contracts. | Does not store secrets. |
| `agentic-os doc-config plan` | Resolve filesystem and Notion projection destinations for documents. | Dry-run planner; external writes still require verification. |
| `agentic-os config install-tree` | Install Codex config across routed OS layers. | Dry-run by default. |

## Programs

| Program | Use When | Source |
| --- | --- | --- |
| `execution_fabric` | Design or validate optional named queues, bounded worker pools, and explicit migration from the filesystem queue. Installed inactive by default. | `harness/shared_factory/00-programs/execution_fabric/` |
| `spec_grooming` | Turn rough ideas into implementation-ready specs while preserving original intent, discovering existing capability, and projecting to filesystem, tracker, and Notion surfaces. | `harness/shared_factory/00-programs/spec_grooming/` |
| `auto_dev` | One polymorphic SDLC family for investigation, artifact authoring, implementation, review, release, deployment, closeout, and lifecycle health. | `harness/shared_factory/00-programs/auto_dev/` |

## MCP Servers

{mcp_tools_markdown()}

## Composio Tool Routes

{composio_tools_markdown()}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
| host tool registry | Shell, terminal, runtime, package-manager, and cleanup work. | `shared_factory/05-knowledge/host-tool-registry.<host>.yml` |
| agentic-os quiet run | Detached local commands with `state.json`, `events.jsonl`, `summary.md`, and `output.log`. | `harness/bin/agentic-os-quiet-run` |

## Hooks

| Hook | Use When | Source |
| --- | --- | --- |
{hooks}

## When To Use What

- Use skills for repeatable agent workflows.
- Use commands for deterministic filesystem or runtime operations.
- Use MCP servers only when the current layer's rules and source boundaries allow them.

## Missing Or Disabled

| Capability | Needed For | Status |
| --- | --- | --- |
|  |  |  |
"""


def domain_config(domain: str) -> str:
    lanes = "\n".join(f"  - {lane}" for lane in STANDARD_LANES)
    return f"""id: {domain}
name: {titleize_name(domain)}
owner: OS Owner
status: active

purpose: >
  {domain_purpose(domain)}

lanes:
{lanes}

directories:
  programs: 00-programs
  control_plane: 00-control-plane
  inbox: 01-inbox
  projects: 02-projects
  workflows: 03-workflows
  automations: 04-automations
  knowledge: 05-knowledge
  runs_and_logs: 06-runs-and-logs
  metrics: 07-metrics
  archive: 08-archive

source_systems:
  - name: Notion
    role: control_plane
    url: ""
  - name: GitHub
    role: code_and_prs
    url: ""

approval_policy:
  external_writes_require_approval: true
  customer_visible_output_requires_approval: true
  production_changes_require_approval: true
  destructive_actions_require_approval: true

notion:
  domain_home_page_id: ""
  inbox_database_id: ""
  work_items_database_id: ""
  runs_database_id: ""
  approvals_database_id: ""

storage:
  active_state: filesystem
  artifacts: filesystem
  cockpit: notion
  memory: agent_memory

context_loading:
  map_file: ROUTER.md
  room_file: CONTEXT.md
  rules_file: RULES.md
  tools_file: TOOLS.md
  reference_file: REFERENCES.md
  default_rule: read the map, context, rules, and tools first, then load only task-specific references
  skip_by_default:
    - unrelated domains
    - unrelated projects
    - workflow internals unless running that workflow
    - automation logs unless reviewing that automation
"""


def domain_readme(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# {display_name}

## Purpose

{domain_purpose(domain)}

## Context Files

- `CONTEXT.md` defines how this domain works and what good output looks like.
- `RULES.md` defines safety, approval, and local operating constraints.
- `TOOLS.md` lists intended local and inherited skills, commands, MCP servers, plugins, and wrappers.
- `REFERENCES.md` points to source systems, docs, repos, tools, and recurring examples.

## Active Outcomes

-

## Main Systems

| System | Role | Link |
| --- | --- | --- |
| Notion | Control plane |  |
| GitHub | Code and pull requests |  |

## Repositories / Notion / Jira

- Repositories:
- Notion:
- Jira:

## Approval Rules

See `00-control-plane/approval-rules.md`.

## Sensitive Data Rules

- Record what can be read.
- Record what can be written.
- Require approval for external writes, production changes, secrets, billing, and legal records.

## Common Workflows

Workflow definitions live in `lib/workflows/domains/{domain}/`.

## Active Automations

Automation definitions live in `lib/automations/domains/{domain}/`; mutable runtime remains under the domain runtime surface.

## Source Map

Query `lib/registry/objects.json` for domain reference objects.

## Current Risks

-
"""


def domain_router(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Agent Router: {display_name}

## First Decision

Classify the request into one of this domain's operating lanes, then choose the narrowest matching project, workflow, or automation.

## Where To Put Work

| Work Type | Path |
| --- | --- |
| Idea or rough request | Jira/Linear intake plus `agentic-os work upsert` |
| Raw capture | `01-inbox/raw-ideas.md` |
| Triage notes | `01-inbox/triage.md` |
| Domain context | `CONTEXT.md` |
| Domain references | `REFERENCES.md` |
| Active project | `domains/{domain}/projects/<project>/` |
| Workflow definition | `lib/workflows/domains/{domain}/<workflow>/` |
| Automation definition | `lib/automations/domains/{domain}/<automation>/` |
| Reference | `lib/references/domains/{domain}/<reference>/` |
| Run log | `06-runs-and-logs/runs/<run-id>/run-log.md` |
| Failure record | `06-runs-and-logs/failures/` |
| Metrics | `07-metrics/` |
| Archive | `08-archive/` |
| Bug, failed QA, log, incident, or RCA | Auto-Dev Detective plus `investigation-config/` |
| Jira, Linear, Notion, Confluence, GitHub, report, or RCA output | Auto-Dev Create Artifacts plus `artifact-config/` |
| Code implementation through release | Auto-Dev plus the selected project development profile |
| Queue admission, worker capacity, run/effect state, health, or failover | shared Execution Fabric program |

## Routing Rules

- Read `AGENTS.md`, then `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`.
- If the prompt says `add an idea`, `capture an idea`, `idea for`, or similar, use the configured Jira/Linear intake and reconcile a queued work row; do not create a stateful filesystem spec.
- Treat ideas as pre-routing inputs. A systems idea is different from a code feature, Jira implementation task, or active project.
- If a project, workflow, automation, or run-log directory narrows the route, change there and repeat the local context-file load before acting.
- Read `lib/registry/objects.json` before creating or selecting a workflow or automation.
- Read `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and `REFERENCES.md` before doing domain-specific work.
- Use `agentic-os library create workflow` when judgment, context assembly, or approval gates are central.
- Use `agentic-os library create automation` when a trigger can safely run a repeatable action with declared permissions.
- Use `shared_factory` when a pattern should be reused by multiple domains.
- Route managed execution through the shared Execution Fabric program. Domain
  workflows select a declared task type and named queue; they do not create
  local worker-count or queue-health rules.

## Context Loading

| Need | Load | Skip By Default |
| --- | --- | --- |
| Understand the room | `CONTEXT.md`, `domain.yml` | Other domains |
| Find source truth | matching reference object from `lib/registry/objects.json` | Full private docs unless needed |
| Resume active work | `active-now.json`, then `agentic-os work show` | Unrelated project folders |
| Run a workflow | Matching workflow `quick-reference.md`, `context-pack.md`, `runbook.md` | Automation logs |
| Review an automation | Matching automation spec, permissions, tests, logs | Workflow internals outside the linked process |
| Investigate a signal | root/domain/project `investigation-config/` and deployed-version source | unrelated product evidence |
| Author an artifact | root/domain/project `artifact-config/` and target provider tool | provider mutation before local validation |

## Approval Rules

- Follow `00-control-plane/approval-rules.md`.
- Escalate before external writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records.
- Write a run log before ending any non-trivial execution.
"""


def domain_context(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Context: {display_name}

This file teaches agents how work inside `{domain}` should be understood before they execute a task. Treat this domain as a room: load the room guide, route to the right object, then read only the sources the task requires.

## Purpose

{domain_purpose(domain)}

## Inputs

- Raw requests, notes, tickets, messages, or ideas.
- Existing project state under `domains/{domain}/projects/`.
- Workflow and automation definitions selected from `lib/registry/objects.json`.
- Source systems listed in `REFERENCES.md` and registered reference objects.

## Process

1. Read `ROUTER.md`, this file, `RULES.md`, `TOOLS.md`, and the matching row in `## What To Load`.
2. Check `harness/shared_factory/00-control-plane/active-now.json` before creating new work.
3. Reuse an existing project, workflow, automation, or run log when one fits.
4. Read only the references required for the routed task.
5. Record validation, next action, and durable learning before ending.
6. Reconcile new work with `agentic-os work` and reusable definitions with `agentic-os library`.

## Output Folders

- `00-control-plane/` - routing, approvals, active work, and decisions.
- `01-inbox/` - untriaged capture and routing notes.
- `projects/` - conventional alias for project packets, source maps, status, and artifacts.
- `03-workflows/`, `04-automations/`, `05-knowledge/` - legacy compatibility/runtime paths; reusable definitions live in `lib`.
- `06-runs-and-logs/` - execution records, failures, and activity history.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - inactive or historical material.

## What To Load

| Task Type | Read First | Read When Needed | Do Not Load By Default | Output Path |
| --- | --- | --- | --- | --- |
| Raw capture | `01-inbox/raw-ideas.md` | `REFERENCES.md` | workflow internals | `01-inbox/raw-ideas.md` |
| Route work | `ROUTER.md`, `00-control-plane/routing-rules.md` | `00-control-plane/active-work.md` | unrelated domain folders | `01-inbox/triage.md` or target object |
| Project work | active work row, `projects/<project>/status.md` | linked repo, linked tracker | unrelated projects | stable project packet |
| Workflow run | selected library workflow entrypoint | runbook, examples, references | unrelated objects | `06-runs-and-logs/runs/` |
| Automation review | selected library automation entrypoint | runtime receipts and failure evidence | unrelated objects | owning runtime path |
| Investigation/RCA | Auto-Dev Detective and effective investigation policy | deployed version, selected sources | undeclared sources | routed investigation run |
| Artifact authoring | Auto-Dev Create Artifacts and effective provider/type contract | verified provider target | copied formatting prompts | routed artifact receipts |

## Tools And Skills

| Tool Or Skill | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Done Means

- It routes work to the correct project, workflow, automation, or run log.
- It preserves source links and evidence.
- It follows approval rules before external, production, destructive, billing, legal, or customer-visible action.
- It updates active state or records a next action before the session ends.

## Standing Context

- Main people:
- Main systems:
- Main repositories:
- Main Notion pages:
- Main Jira or issue trackers:

## Work Style

- Preferred level of detail:
- Required terminology:
- Formatting expectations:
- Things to avoid:

## Common Tasks

| Task Type | Route | Read First | Output |
| --- | --- | --- | --- |
|  |  |  |  |

## Update Rule

Update this file when a stable domain rule, source system, work style preference, routing pattern, tool trigger, or repeated failure mode becomes durable.
"""


def domain_rules(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Rules: {display_name}

These rules apply to work routed into `{domain}` unless a narrower project,
workflow, or automation defines a stricter rule.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting in this domain.
- Check `00-control-plane/active-work.md` before creating new active work.
- Keep `00-control-plane/state-index.md` current for ideas, workflow opportunities, automation states, project features, bug fixes, and research threads.
- Update `MEMORY.md` for durable, non-secret routing and operating learnings.
- Record material execution in `06-runs-and-logs/`.
- Preserve source links and validation evidence.
- Keep secrets out of run logs, docs, prompts, and generated config.

## Auto-Dev Rules

- Add domain behavior through 1-N Markdown policy files; do not fork the shared workflow state machine.
- Resolve deployed version before causal code claims and record evidence authority, freshness, and limitations.
- Pause the same Detective run when a declared dependency is unavailable; resume only with availability evidence.
- Validate and sanitize artifacts before approved external apply; verify target and read back the result.
- When Execution Fabric is enabled, use its admission API and terminal receipts
  for managed work. Do not infer capacity from work-item folders or process
  listings, and do not bypass the named queue with a detached launch.

## Precedence

Narrower rules override these rules unless this file is stricter for safety,
privacy, production, billing, legal, or customer-visible work.
"""


def domain_tools(domain: str, *, public_customer: bool = False) -> str:
    display_name = titleize_name(domain)
    mcp_markdown = mcp_tools_markdown(domain, include_inactive=not public_customer, public_customer=public_customer)
    composio_markdown = composio_tools_markdown(public_customer=public_customer)
    return f"""# Tools: {display_name}

This registry names the intended skills, commands, MCP servers, plugins,
libraries, and wrappers for `{domain}`.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route domain work to the correct project, workflow, automation, or run log. | inherited from `harness/shared_factory` |
| `workflow-builder` | Create or refine repeatable workflows. | inherited from `harness/shared_factory` |
| `automation-qualifier` | Decide whether a repeatable process should become an automation. | inherited from `harness/shared_factory` |
| `auto-dev` | Implement, review, release, deploy, and close out code through shared SDLC stages. | inherited from `harness/skills` |
| `auto-dev-create-artifacts` | Author governed provider/type outputs with domain/project policy. | inherited from `harness/skills` |
| `auto-dev-detective` | Investigate bugs, failed QA, logs, incidents, and RCA questions with versioned evidence. | inherited from `harness/skills` |
| `execution-fabric` | Inspect or troubleshoot named queues, workers, run receipts, health, and host failover. | inherited from `harness/skills` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os project create` | Create a domain project. | Use after checking active work. |
| `agentic-os workflow create` | Create a reusable workflow. | Use when the pattern should repeat. |
| `agentic-os automation create` | Create a guarded automation spec. | Start in observe or prepare mode. |
| `agentic-os validate` | Validate domain and root structure. | Run before handoff after structural changes. |
| `agentic-os artifacts ...` | Resolve/render/validate/apply/readback/doctor artifact contracts. | External writes require target verification and approval. |
| `agentic-os detective ...` | Resolve/start/status/version/evidence/pause/resume/analyze/conclude/render/doctor investigations. | Read-only and resumable. |
| `agentic-os develop ...` | Plan/start code delivery or explain development policy. | Select a repository explicitly when the project catalog requires it. |
| `agentic-os runtime snapshot` | Inspect queue, worker, task/run, retry, dead-letter, and health state. | Reads the selected backend's canonical projection. |
| `agentic-os runtime config status` | Find the effective Execution Fabric config and detect drift. | The editable instance file remains `harness/config/execution-fabric.yml`. |

## MCP Servers

{mcp_markdown}

## Composio Tool Routes

{composio_markdown}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
|  |  |  |

## Missing Or Disabled

| Capability | Needed For | Status |
| --- | --- | --- |
|  |  |  |
"""


def domain_references(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# References: {display_name}

Use this file as the domain's durable source map. Link to the source; do not paste whole private documents unless they are intentionally part of this OS.

## Source Systems

| Source | Location | What It Contains | When To Use |
| --- | --- | --- | --- |
| Notion |  | Control plane, docs, status |  |
| GitHub |  | Repositories, PRs, issues |  |
| Local files |  | Working artifacts and installed OS state |  |

## Example Outputs

| Example | Location | Why It Is Useful |
| --- | --- | --- |
|  |  |  |

## Reusable Prompts Or Briefs

| Name | Location | Use For |
| --- | --- | --- |
|  |  |  |

## Known Gaps

-
"""


def control_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    headings = {
        "README.md": f"""# {display_name} Control Plane

This folder owns routing, approvals, active work, and durable decisions for `{domain}`.
""",
        "active-work.md": f"""# Active Work: {display_name}

| Work | Status | Owner | Next Action | Link |
| --- | --- | --- | --- | --- |
""",
        "state-index.md": f"""# State Index: {display_name}

Use this file as the domain control-plane ledger. Update it whenever an idea is captured, a workflow opportunity appears, an automation is running or disabled, a project feature or bug changes state, or research starts or closes.

## Ideas

| Date | Item | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Workflow Opportunities

| Date | Workflow Or Pattern | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Automation Status

| Date | Automation | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Project Activity

| Date | Project Or Work | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Research

| Date | Topic | Status | Link | Notes |
| --- | --- | --- | --- | --- |
""",
        "decisions.md": f"""# Decisions: {display_name}

| Date | Decision | Why | Impact | Link |
| --- | --- | --- | --- | --- |
""",
        "routing-rules.md": f"""# Routing Rules: {display_name}

## Default Route

1. Identify the domain.
2. If the request is an idea capture, write it to `01-inbox/` before routing it further.
3. Identify the lane.
4. Check active projects.
5. Reuse an existing workflow or automation when one fits.
6. Create a new workflow only when the process should be repeated.

## Idea Capture

- Treat `add an idea`, `capture an idea`, `idea for`, `rough idea`, and similar phrasing as inbox work.
- Keep the first artifact in `01-inbox/` as a markdown idea/spec unless the user asks for a table-only capture.
- Do not promote an idea into a project, workflow, automation, Jira, or repository feature until the user asks to route or escalate it.
- When capturing an idea, update `01-inbox/raw-ideas.md`, `01-inbox/triage.md`, `00-control-plane/state-index.md`, and `MEMORY.md` in the same pass.

## Control-Plane Writeback

- Update `00-control-plane/state-index.md` for ideas, workflow opportunities, automation enabled/disabled/running states, project features, bug fixes, and research.
- Update `00-control-plane/active-work.md` when work is active, waiting, blocked, or ready for owner review.
- Update `MEMORY.md` for durable, non-secret routing decisions, repeated patterns, source maps, and stable project/domain learnings.

## Lane Hints

{chr(10).join(f"- `{lane}` -" for lane in STANDARD_LANES)}
""",
        "approval-rules.md": f"""# Approval Rules: {display_name}

## Default Rule

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval.

## Approval Matrix

| Action | Approval Required | Approver | Notes |
| --- | --- | --- | --- |
| Read source systems | no |  |  |
| Draft internal summary | no |  |  |
| Create internal work item | no |  |  |
| Send external message | yes |  |  |
| Comment on customer-visible ticket | yes |  |  |
| Merge PR | yes |  |  |
| Deploy production change | yes |  |  |

## Never Allowed Without Explicit Human Instruction

- Delete customer data.
- Rotate or expose secrets.
- Merge or deploy production code.
- Send customer-visible messages.
- Modify billing or legal records.
""",
    }
    return headings[filename]


def inbox_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "raw-ideas.md":
        return f"""# Raw Ideas: {display_name}

Capture untriaged ideas, notes, messages, and prompts here before routing them.

| Date | Source | Raw Input | Next Step |
| --- | --- | --- | --- |
"""
    return f"""# Triage: {display_name}

| Date | Input | Domain | Lane | Intent | Risk | Confidence | Routed To |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def knowledge_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "source-map.md":
        return f"""# Source Map: {display_name}

| Source | Location | Purpose | Owner | Notes |
| --- | --- | --- | --- | --- |
| Notion |  | Control plane |  |  |
| GitHub |  | Source and PRs |  |  |
| Local files |  | Working artifacts |  |  |
"""
    if filename == "glossary.md":
        return f"""# Glossary: {display_name}

| Term | Meaning | Source |
| --- | --- | --- |
"""
    return f"""# Memory Policy: {display_name}

## Record In Memory

- Durable preferences.
- Repeated workflow decisions.
- Stable source maps.

## Do Not Record In Memory

- Secrets.
- Temporary credentials.
- Sensitive customer data unless explicitly approved and sanitized.

## Refresh Rules

- Verify drift-prone facts before acting.
- Cite source files, tickets, pages, or run logs when recording durable facts.
"""


def metric_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "baselines.md":
        return f"""# Baselines: {display_name}

| Metric | Current Baseline | Source | Date |
| --- | --- | --- | --- |
"""
    return f"""# Scorecards: {display_name}

| Period | Workflow / Automation | Result | Notes |
| --- | --- | --- | --- |
"""


def workflows_readme(domain: str) -> str:
    return f"""# Workflows: {titleize_name(domain)}

Workflow specs live here when the work needs judgment, context assembly, validation, or approval gates.

## Lane Directories

{chr(10).join(f"- `{lane}/`" for lane in STANDARD_LANES)}

## Workflow Folder Format

```text
<lane>/<workflow>/
  workflow.md
  outcome-brief.md
  alignment-questions.md
  prd.md
  implementation-plan.md
  dispatch-handoff.md
  progress.md
  quick-reference.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
  runs/
```

## Creation Rule

Use `agentic-os workflow create {domain} <lane> <workflow> --root ~/agentic_os`.
"""


def workflow_lane_readme(domain: str, lane: str) -> str:
    return f"""# Workflow Lane: {lane}

## Domain

`{domain}`

## Purpose

Create reusable workflow folders here for `{lane}` work inside `{domain}`.

## Workflow Folder Format

```text
<workflow>/
  workflow.md
  outcome-brief.md
  alignment-questions.md
  prd.md
  implementation-plan.md
  dispatch-handoff.md
  progress.md
  quick-reference.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
  runs/
```

## Routing Rule

If the work can be repeated and still needs judgment, create a workflow. If the trigger and action are stable enough to run unattended, create an automation under `04-automations/{lane}/`.
"""


def automations_readme(domain: str) -> str:
    return f"""# Automations: {titleize_name(domain)}

Automation specs live here when a trigger can safely run a guarded process with declared permissions, idempotency, logs, and approval gates.

## Lane Directories

{chr(10).join(f"- `{lane}/`" for lane in STANDARD_LANES)}

## Automation Folder Format

```text
<lane>/<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Creation Rule

Use `agentic-os automation create {domain} <lane> <automation> --root ~/agentic_os`.
"""


def automation_lane_readme(domain: str, lane: str) -> str:
    return f"""# Automation Lane: {lane}

## Domain

`{domain}`

## Purpose

Create guarded automation folders here for `{lane}` work inside `{domain}`.

## Automation Folder Format

```text
<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Safety Rule

Start automations at `observe` or `prepare`. External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require approval.
"""


def runs_readme(domain: str) -> str:
    return f"""# Runs: {titleize_name(domain)}

Each folder records one workflow, automation, or skill execution.

## Run Folder Format

```text
MMDDYY-<time>-<run-id>/
  run-log.md
  artifacts/
```

The prefix is controlled by `harness/config/artifact-naming.yml`; `MMDDYY-`
is the default.

## Required Run Evidence

- Input reference.
- Context loaded.
- Actions taken.
- Validation performed.
- Artifacts created or changed.
- Final state and next action.
"""


def failures_readme(domain: str) -> str:
    return f"""# Failures: {titleize_name(domain)}

Use this folder for failed runs, recovery notes, and repeated failure modes that need redesign.

## Failure Record Format

```text
<date>-<short-name>.md
```

Each record should include the source run, failure mode, impact, attempted recovery, and next action.
"""


def simple_readme(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


def render_template(content: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        content = content.replace(key, value)
    return content


def ensure_root_files(
    root: Path,
    result: ScaffoldResult,
    projects_source: str | Path = DEFAULT_PROJECTS_SOURCE,
    *,
    include_legacy_agent: bool = False,
    domains: tuple[str, ...] | list[str] | None = None,
) -> None:
    domains_list = tuple(domains) if domains else DEFAULT_DOMAINS
    ensure_dir(root, result)
    ensure_dir(root / "domains", result)
    write_root_marker(root, result, projects_source)
    ensure_dir(harness_path(root), result)
    write_file_once(root / CONFIG_RELATIVE_PATH, render_default_artifact_naming_config(), result)
    ensure_visible_capability_surface(root, result)
    ensure_schemas_dir(root, result)
    ensure_report_engine_contract(root, result)
    ensure_context_migration_contract(root, result)
    ensure_update_metadata(root, result)
    ensure_customer_update_contract(root, result)
    harness_root = harness_path(root)
    write_file_once(harness_root / "README.md", root_readme(domains_list), result)
    router = root_router(domains_list)
    write_file_once(harness_root / "ROUTER.md", router, result)
    write_file_once(harness_root / "AGENTS.md", agent_entrypoint("the installed Agentic OS root harness"), result)
    write_file_once(harness_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(harness_root / "CONTEXT.md", root_context(domains_list), result)
    write_file_once(harness_root / "RULES.md", root_rules(), result)
    write_file_once(harness_root / "TOOLS.md", root_tools(), result)
    ensure_root_instruction_adapters(root, result)
    if include_legacy_agent:
        write_file_once(harness_root / "AGENT.md", legacy_agent_adapter(), result)
    ensure_codex_config(harness_root, "agentic_os_root", result)


def create_domain_structure(
    os_root: Path,
    domain: str,
    result: ScaffoldResult,
    *,
    include_legacy_agent: bool = False,
    public_customer_tools: bool = False,
) -> None:
    domain = validate_name(domain, "domain")
    domain_root = domain_path(os_root, domain)
    ensure_dir(domain_root, result)
    write_file_once(domain_root / "README.md", domain_readme(domain), result)
    router = domain_router(domain)
    write_file_once(domain_root / "ROUTER.md", router, result)
    write_file_once(domain_root / "AGENTS.md", agent_entrypoint(f"the `{domain}` domain"), result)
    write_file_once(domain_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(domain_root / "CONTEXT.md", domain_context(domain), result)
    write_file_once(domain_root / "RULES.md", domain_rules(domain), result)
    write_file_once(domain_root / "TOOLS.md", domain_tools(domain, public_customer=public_customer_tools), result)
    if include_legacy_agent:
        write_file_once(domain_root / "AGENT.md", legacy_agent_adapter(), result)
    write_file_once(domain_root / "REFERENCES.md", domain_references(domain), result)
    write_file_once(domain_root / "domain.yml", domain_config(domain), result)
    ensure_codex_config(domain_root, "domain_or_lane", result)

    for directory in DOMAIN_DIRECTORIES:
        ensure_dir(domain_root / directory, result)
    migrate_auto_dev_policy_directories(domain_root / "05-knowledge", result)

    write_file_once(domain_root / "00-programs" / "README.md", programs_readme(domain), result)

    for filename in CONTROL_PLANE_FILES:
        write_file_once(domain_root / "00-control-plane" / filename, control_file_content(domain, filename), result)

    for filename in INBOX_FILES:
        write_file_once(domain_root / "01-inbox" / filename, inbox_file_content(domain, filename), result)

    write_file_once(
        domain_root / "02-projects" / "README.md",
        simple_readme(
            f"Projects: {titleize_name(domain)}",
            "Create one folder per active project. Project folders should link back to workflows, automations, source systems, and run logs.",
        ),
        result,
    )

    write_file_once(domain_root / "03-workflows" / "README.md", workflows_readme(domain), result)
    write_file_once(domain_root / "04-automations" / "README.md", automations_readme(domain), result)
    write_file_once(
        domain_root / "05-knowledge" / "auto_dev" / "README.md",
        f"""# Auto-Dev: {titleize_name(domain)}

This directory is the domain policy layer between shared Auto-Dev behavior and
project-specific behavior. `README.md` is an index and is not active policy.

Create numbered Markdown addenda for every stage whose tracker, investigation,
runtime, quality, release, deployment, documentation, or cleanup behavior is
different in this domain. Write plain-English inputs, actions, guardrails,
evidence, receipts, recovery, and done criteria. Do not leave the domain
"configured" with only this README.

Verify the effective root -> domain -> project selection with
`agentic-os develop policy {domain} <project> --plane auto_dev --root <os-root> --json`.
""",
        result,
    )
    plane_guidance = {
        "dev_standards": "coding, architecture, security, review, and documentation expectations",
        "qa_gates": "test layers, acceptance evidence, regression gates, and QA handoff",
        "gitflow_topology": "branch, worktree, pull-request, merge, and release topology",
        "environment_access": "host ownership, VPN, identity, cloud/runtime access, mutation boundaries, and recovery",
    }
    for plane, guidance in plane_guidance.items():
        write_file_once(
            domain_root / "05-knowledge" / "auto_dev" / plane / "README.md",
            f"""# {plane.replace("_", " ").title()}: {titleize_name(domain)}

This is the domain layer for {guidance}. Add numbered, plain-English Markdown
only when this domain differs from the shared Auto-Dev contract. Never store
credentials, tokens, private keys, kubeconfig content, or customer data here.

Verify selection with `agentic-os develop policy {domain} <project> --plane {plane} --root <os-root> --json`.
""",
            result,
        )

    for lane in STANDARD_LANES:
        ensure_dir(domain_root / "03-workflows" / lane, result)
        ensure_dir(domain_root / "04-automations" / lane, result)
        write_file_once(domain_root / "03-workflows" / lane / "README.md", workflow_lane_readme(domain, lane), result)
        write_file_once(domain_root / "04-automations" / lane / "README.md", automation_lane_readme(domain, lane), result)

    write_file_once(
        domain_root / "06-runs-and-logs" / "activity-log.md",
        simple_readme(
            f"Activity Log: {titleize_name(domain)}",
            "| Date | Actor | Action | Result | Link |\n| --- | --- | --- | --- | --- |",
        ),
        result,
    )
    write_file_once(domain_root / "06-runs-and-logs" / "runs" / "README.md", runs_readme(domain), result)
    write_file_once(domain_root / "06-runs-and-logs" / "failures" / "README.md", failures_readme(domain), result)

    for filename in METRIC_FILES:
        write_file_once(domain_root / "07-metrics" / filename, metric_file_content(domain, filename), result)

    write_file_once(
        domain_root / "08-archive" / "README.md",
        simple_readme(
            f"Archive: {titleize_name(domain)}",
            "Move inactive or historical material here when it should no longer appear in active routing.",
        ),
        result,
    )


def ensure_default_domains(
    os_root: Path,
    result: ScaffoldResult,
    *,
    include_legacy_agent: bool = False,
    domains: tuple[str, ...] | list[str] | None = None,
) -> None:
    for domain in tuple(domains) if domains else DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result, include_legacy_agent=include_legacy_agent)
    create_domain_structure(os_root, SHARED_FACTORY_DOMAIN, result, include_legacy_agent=include_legacy_agent)
    result.extend(copy_tree_missing(template_source_dir(), shared_factory_path(os_root, "05-knowledge", "templates")))
    result.extend(install_docs(os_root))


def init_os(
    target: str | Path,
    *,
    projects_source: str | Path = DEFAULT_PROJECTS_SOURCE,
    include_legacy_agent: bool = False,
    domains: tuple[str, ...] | list[str] | None = None,
) -> ScaffoldResult:
    """Create (or additively repair) an installed OS tree.

    ``domains`` overrides the built-in neutral ``DEFAULT_DOMAINS`` with an
    explicit domain list; each name is validated as a domain slug.
    """
    root = expand_path(target)
    domains_list = tuple(normalize_domain(domain) for domain in domains) if domains else None
    result = ScaffoldResult()
    ensure_root_files(root, result, projects_source, include_legacy_agent=include_legacy_agent, domains=domains_list)
    ensure_default_domains(root, result, include_legacy_agent=include_legacy_agent, domains=domains_list)
    return result


def install_docs(root: str | Path) -> ScaffoldResult:
    os_root = expand_path(root)
    result = ScaffoldResult()
    result.extend(mirror_visible_capability_assets(os_root))
    write_file_once(
        harness_path(
            os_root,
            "shared_factory",
            "04-automations",
            "engineering",
            "gitflow-topology-drift",
            "MEMORY.md",
        ),
        "# Memory\n\n"
        "Durable, non-secret findings and operator decisions for this proposal-only "
        "automation belong here.\n",
        result,
    )
    copy_file(
        harness_source_dir() / "config" / "long-running-execution.yml",
        harness_path(os_root, "config", "long-running-execution.yml"),
        result,
    )
    copy_file(
        harness_source_dir() / "config" / "execution-fabric.yml",
        harness_path(os_root, "config", "execution-fabric.yml"),
        result,
    )
    ensure_capability_registries(os_root, result)
    # Existing roots predate harness/schemas/; docs update is their delivery path.
    ensure_schemas_dir(os_root, result)
    ensure_report_engine_contract(os_root, result)
    ensure_context_migration_contract(os_root, result)
    copy_file(
        template_source_dir() / "runtime" / "doc-config.yml",
        shared_factory_path(os_root, "00-control-plane", "doc-config.yml"),
        result,
    )
    copy_file(
        template_source_dir() / "runtime" / "notion-organization.yml",
        shared_factory_path(os_root, "00-control-plane", "notion-organization.yml"),
        result,
    )
    result.extend(
        copy_tree(
            template_source_dir(),
            shared_factory_path(os_root, "05-knowledge", "templates"),
        )
    )
    result.extend(
        copy_tree(
            operating_manual_source_dir(),
            shared_factory_path(os_root, "05-knowledge", "operating-manual"),
        )
    )
    result.extend(
        copy_tree(
            harness_source_dir() / "commands",
            shared_factory_path(os_root, "05-knowledge", "commands"),
        )
    )
    result.extend(
        copy_tree(
            harness_source_dir() / "skills",
            shared_factory_path(os_root, "05-knowledge", "skills"),
        )
    )
    result.extend(
        copy_tree(
            harness_source_dir() / "rules",
            shared_factory_path(os_root, "05-knowledge", "rules"),
        )
    )
    hooks_root = harness_source_dir() / "hooks"
    if hooks_root.is_dir():
        result.extend(
            copy_tree(
                hooks_root,
                shared_factory_path(os_root, "05-knowledge", "hooks"),
            )
        )
    result.extend(
        copy_tree(
            template_source_dir() / "reference",
            shared_factory_path(os_root, "05-knowledge", "references"),
        )
    )
    ensure_managed_resource_surfaces(os_root, result)
    migrate_auto_dev_policy_directories(
        shared_factory_path(os_root, "05-knowledge"),
        result,
    )
    # The package-owned Auto-Dev program is installed into the canonical
    # object library above. Initialize and refresh that library here so every
    # bootstrap path (init, domain/project creation, profile install, docs
    # update) gets the same complete registry rather than a partial ``lib/``.
    # Local import avoids the library module's import of ``expand_path`` while
    # this module is loading.
    from .library import init_library

    init_library(os_root, dry_run=False)
    ensure_auto_dev_program_alias(os_root, result)
    ensure_self_improvement_surface(os_root, result)
    ensure_execution_fabric_routing_blocks(os_root, result)
    return result


def create_domain(root: str | Path, domain: str, *, include_legacy_agent: bool = False) -> ScaffoldResult:
    domain = normalize_domain(domain)
    os_root = expand_path(root)
    # Additive on existing trees: reuse the domains already installed on disk
    # instead of planting the built-in defaults next to an operator's custom
    # domain set. A fresh target falls back to DEFAULT_DOMAINS.
    existing = installed_domain_names(os_root)
    result = init_os(os_root, include_legacy_agent=include_legacy_agent, domains=existing or None)
    if domain not in (existing or DEFAULT_DOMAINS):
        create_domain_structure(os_root, domain, result, include_legacy_agent=include_legacy_agent)
    return result


def project_readme(domain: str, project: str, status: str, lane: str | None) -> str:
    lane_label = lane or ""
    return f"""# Project: {project}

## Metadata

| Field | Value |
| --- | --- |
| Domain | `{domain}` |
| Status | `{status}` |
| Lane | `{lane_label}` |

## Purpose

Describe the project outcome, boundaries, source systems, and active workflows.

## Start Here

- `status.md` records current state and next action.
- `source-map.md` records repos, Notion pages, Jira projects, and other source links.
- `src/` points to the local repository when `--repo` is a local path.
- `decisions.md` records durable project decisions.
- `artifacts/` stores project-specific outputs that do not belong in a workflow run.
"""


def project_config(
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    repo: str | None,
    notion: str | None,
    jira: str | None,
    remotes: list[dict[str, str]] | None = None,
) -> str:
    remotes_block = ""
    if remotes:
        remotes_block = "\n  remotes:\n"
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            kind = r.get("kind", "git")
            authority = r.get("authority", "remote")
            remotes_block += (
                f"    - name: {name}\n"
                f"      host: {host}\n"
                f"      path: {path}\n"
                f"      kind: {kind}\n"
                f"      authority: {authority}\n"
            )
    linear_block = (
        "  linear: https://linear.app/genomes/project/genomes-agentic-os-2c6a1847b558\n"
        if project == "genomes_agentic_os"
        else ""
    )
    auto_dev_block = (
        """

auto_dev:
  enabled: true
  tracker:
    mode: provider
    primary: linear
  finishing_review:
    required: false
    preferred: claude
    unavailable_policy: continue_with_receipt
  merge:
    auto_merge: true
    policy: auto_after_gates
  release:
    required: true
    provider: github
  documentation:
    required_after_release: true
  projection:
    notion_operator_projection: required
    public_site_projection: required
"""
        if project == "genomes_agentic_os"
        else ""
    )
    return f"""id: {project}
name: {project}
domain: {domain}
status: {status}
lane: {lane or ""}

sources:
  repo: {repo or ""}
  notion: {notion or ""}
  jira: {jira or ""}
{linear_block}{remotes_block}

routing:
  project_root: 02-projects/{project}
  status_file: status.md
  source_map: source-map.md
  decisions: decisions.md

work_lifecycle:
  enabled: true
  source_of_truth: state_db
  state_db: harness/shared_factory/00-control-plane/state.db
  active_projection: harness/shared_factory/00-control-plane/active-now.json
  work_items_root: work-items
  packet_policy: stable
  layout: single_canonical_root
  archive:
    enabled: true
    directory: 99-archived
    retention: {{value: 7, unit: days}}
    retention_days: 7
    terminal_states: [finished, documented, archived]
  default_state: captured
  legacy_import_lanes:
    intake: 01-intake
    active: 02-active
    complete: 03-complete
  lane_state_map:
    01-intake: [captured, triaged]
    02-active: [specified, ready, building, validating, blocked]
    03-complete: [finished, documented, archived]
  naming:
    intake_pattern: "{{index:03d}}_{{slug}}.md"
    expanded_intake_pattern: "{{index:03d}}_{{slug}}/"
    packet_pattern: "{{index:03d}}_{{slug}}/"
    subtask_pattern: "{{parent_index:03d}}_{{subindex:02d}}_{{slug}}.md"
    default_intake_format: single_markdown
  transcript_logging:
    enabled: true
    include_raw_transcript: true
    include_tool_call_jsonl: true
    include_tool_call_markdown: true
    redaction_policy: strict
  spec_destination:
    type: external_tracker
  external_tracker:
    type: configured_jira_or_linear
    required: true
{auto_dev_block}"""


def project_status(project: str, status: str) -> str:
    return f"""# Status: {project}

| Field | Value |
| --- | --- |
| Status | `{status}` |
| Owner | OS Owner |
| Next Action |  |

## Current State

-

## Recent Activity

| Date | Update | Link |
| --- | --- | --- |
"""


def project_decisions(project: str) -> str:
    return f"""# Decisions: {project}

| Date | Decision | Why | Impact | Link |
| --- | --- | --- | --- | --- |
"""


def project_source_map(project: str, repo: str | None, notion: str | None, jira: str | None) -> str:
    rows = ["| Source | Location | Purpose | Notes |", "| --- | --- | --- | --- |"]
    if repo:
        rows.append(f"| Repo | {repo} | Code and working tree |  |")
    if notion:
        rows.append(f"| Notion | {notion} | Control plane or docs |  |")
    if jira:
        rows.append(f"| Jira | {jira} | Issues, roadmap, or delivery tracking |  |")
    if len(rows) == 2:
        rows.append("|  |  |  |  |")
    return f"""# Source Map: {project}

{chr(10).join(rows)}
"""


def project_agents(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    remote_section = ""
    if remotes:
        lines = ["\n## Remote Sources\n"]
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            authority = r.get("authority", "remote")
            auth_note = (
                "Code is authoritative on the remote host."
                if authority == "remote"
                else "Local copy is authoritative; remote is a deploy/reference copy."
            )
            mount = r.get("mount") or {}
            mount_note = ""
            if isinstance(mount, dict) and mount.get("namespace"):
                ns = mount["namespace"]
                local_path = mount.get("local_path", f"~/{ns}/{name}")
                mount_note = (
                    f"\n  SSHFS namespace: `{local_path}` -> `{host}:{path}`."
                    " Files may be read/edited locally; repo commands run remotely."
                )
            lines.append(
                f"- **{name}** (`{host}:{path}`): {auth_note}\n"
                f"  Reach via commands in `remote/{name}/REMOTE.md`.\n"
                f"  Artifacts, work-items, and decisions stay local in this room."
                f"{mount_note}"
            )
        ssh_rule = _ssh_namespace_rule_section(remotes)
        if ssh_rule:
            lines.append(ssh_rule)
        remote_section = "\n".join(lines)
    return f"""# Agent Entry Point: {project}

This file is the harness-neutral entrypoint for this Agentic OS layer.

This is the project-local entrypoint for `domains/{domain}/projects/{project}`.

## Required Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `project.yml`, and `config/*.yml`.
2. Read `harness/shared_factory/00-control-plane/active-now.json`; use `agentic-os work show` when this project has an active row.
3. If source work is required, use `src/` for the canonical checkout or `worktrees/<name>` for an active branch-specific checkout.
4. Follow local `RULES.md` and tool boundaries before touching source files.
5. For lifecycle work, update the SQLite row through `agentic-os work`; packet paths stay stable across state changes.
6. Keep specifications in Jira or Linear, reusable definitions in `lib`, outputs in `artifacts/`, and execution evidence in the domain run log.

## Source Priority

- `project.yml` and `source-map.md` identify the project and canonical sources.
- `config/development.yml` is the canonical project code settings file; repository,
  branch, worktree directory, and date-prefix overrides live there for every domain.
- `state.db` is authoritative for lifecycle state and attention; `config/work-lifecycle.yml` declares compatibility mappings and naming rules.
- `config/output-artifacts.yml` declares project artifact roots.
- Source repository `features/` and `.features/` folders are mirrors/artifact locations unless project config explicitly assigns lifecycle ownership there.
- `worktrees/index.yml` lists visible worktrees and their real filesystem targets.
{remote_section}
"""


def project_router(domain: str, project: str) -> str:
    return f"""# Agent Router: {project}

Route project work to the narrowest local surface before acting.

| Request Type | Route |
| --- | --- |
| New project-known idea, product thought, rough note | External Jira/Linear intake plus `agentic-os work upsert` |
| Domain-level idea without a known project | `<domain>/01-inbox/raw-ideas.md` |
| Lifecycle work item | `agentic-os work show/set`; packet location does not encode state |
| Expanded implementation packet | stable `work-items/<work-item-id>/` packet linked from the registry row |
| Project status or next action | `status.md` |
| Source map, repo, Notion, Jira, or MCP setup | `source-map.md` and `config/*.yml` |
| Feature implementation | active registry row, stable packet, then `src/` or the row's verified worktree |
| Queue admission, worker/run health, or failover | shared Execution Fabric program; project config only selects declared task type/queue |
| Feature artifact or generated output | `artifacts/` or configured source artifact root |
| Durable decision | `decisions.md` |

## Worktree Rule

Use `worktrees/index.yml` before assuming where active branch checkouts live.
Create new code worktrees with `agentic-os project worktree create {domain} {project}
--branch <branch>`; it reads `config/development.yml`, uses the project-visible
`worktrees/` surface, and inherits the OS date-prefix policy by default.
Register visible worktrees with `agentic-os project worktree add {domain} {project} <name> --path <path>`.
"""


def project_context(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    remote_section = ""
    if remotes:
        lines = ["\n## Remote Sources\n"]
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            authority = r.get("authority", "remote")
            auth_note = (
                "Code is authoritative on the remote host."
                if authority == "remote"
                else "Local copy is authoritative; remote is a deploy/reference copy."
            )
            lines.append(
                f"- **{name}** (`{host}:{path}`): {auth_note}\n"
                f"  Reach via commands in `remote/{name}/REMOTE.md`.\n"
                f"  Artifacts, work-items, and decisions stay local in this room."
            )
        remote_section = "\n".join(lines)
    return f"""# Context: {project}

Describe the local room, source systems, and routing hints for `domains/{domain}/projects/{project}`.

This project layer is the operating surface for `domains/{domain}/projects/{project}`.
It connects project state, source links, worktrees, ideas, output artifacts, and local rules.

## Load Order

1. `project.yml`
2. `source-map.md`
3. `config/project-profile.yml` and `config/development.yml` for code projects
4. `config/workflows.yml`, `config/output-artifacts.yml`, and `config/validation.yml`
5. the matching SQLite work row and stable packet when lifecycle work is active
6. `worktrees/index.yml` when source work may use a branch checkout

## Markdown vs YAML

- Markdown files explain intent, decisions, source maps, and human-readable context.
- YAML files under `config/` are for parsed defaults, paths, validation commands, MCP boundaries, and tool declarations.
- Use Jira or Linear for specification truth. Local Markdown is bounded execution evidence or resume context, not a second spec state machine.
{remote_section}
"""


def _ssh_namespace_rule_section(remotes: list[dict[str, str]] | None) -> str:
    """Return the SSH_<host> managed rule section when any remote has a mount block."""
    if not remotes:
        return ""
    has_mount = any(r.get("mount") for r in remotes)
    if not has_mount:
        return ""
    return (
        "\n## SSH Remote Namespace Rule\n\n"
        "Any path component named `SSH_<host>` is an SSHFS remote namespace. "
        "Files under it may be read or edited locally, but repo commands run on "
        "`<host>` with the remote cwd from the project manifest. "
        "Do not run builds, tests, package installs, git, or watchers locally "
        "from an SSHFS path unless the operator explicitly asks for local-mount execution.\n"
    )


def project_rules(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    ssh_section = _ssh_namespace_rule_section(remotes)
    return f"""# Rules: {project}

These rules apply to `domains/{domain}/projects/{project}` unless a narrower source
checkout or feature artifact defines a stricter rule.

## Operating Rules

- Do not move source repositories into the OS; keep `src` and `worktrees/*` as links unless the operator explicitly requests otherwise.
- Preserve `project.yml`, `source-map.md`, `config/*.yml`, and `worktrees/index.yml` as the project control surface.
- For code in any domain, create isolated worktrees through `agentic-os project worktree create`; `config/development.yml` owns the repository, worktree directory, branch template, and project date-prefix override.
- Use Jira or Linear for future work and specification truth. `ideas/` and numbered lane folders are compatibility indexes.
- Use `WORKLOGS/` or `worklogs/` for human-readable work history; lowercase `logs/` is reserved for raw system output and transcripts.
- Keep one stable packet per work item and one canonical SQLite row. Use `agentic-os work` for lifecycle/attention changes; never move packets to express state.
- Treat source repo `features/`, `.features/`, and legacy lane folders as mirrors or artifact locations, never lifecycle truth.
- Keep secrets out of markdown, YAML, generated config, logs, and artifacts.
- Follow the strictest applicable parent, project, source-repo, and workflow rule.
- When managed execution is enabled, submit through the shared Execution Fabric
  contract and retain its admission and terminal receipts in the owning run
  evidence. Never use folder counts as a concurrency semaphore.
{ssh_section}
"""


def project_tools(domain: str, project: str) -> str:
    return f"""# Tools: {project}

This registry names project-local capabilities for `domains/{domain}/projects/{project}`.

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os project src` | Create or repair the canonical `src` link. | The link stays scoped inside this project folder. |
| `agentic-os project onboard` | Repair missing project layer files. | Additive; preserves local edits. |
| `agentic-os project worktree create` | Create and register an isolated code worktree in any domain. | Reads `config/development.yml`; the global dated-name policy is inherited unless the project overrides it. |
| `agentic-os project worktree add` | Register a visible worktree symlink and index entry. | Use for active branch-specific source checkouts. |
| `agentic-os project worktree cleanup-closed` | Move terminal-status or merged-PR worktree registrations to `worktrees/closed.yml`. | Physical removal requires exact domain, project, worktree, packet-local Health preflight, and preflight-bound runtime receipt; failed or `REOPEN.md` cleanup remains registered. |
| `agentic-os work upsert` | Capture or reconcile a tracker-backed project work item. | Writes canonical SQLite state; use a stable packet path when local evidence is needed. |
| `agentic-os work show/set` | Read or change lifecycle, attention, context, blockers, and verification. | Folder movement is not a state transition. |
| `agentic-os project work-item repair` | Backfill missing lifecycle packet files and log folders on legacy or partial work items. | Use before full validation when a `work-item.md`-only packet blocks the OS. |
| `agentic-os project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. | Use before `finalize-lingering`; stale-only work stays active. |
| `agentic-os project work-item finalize-lingering` | Legacy compatibility cleanup for pre-registry lane packets. | Do not use it as the normal state transition path. |
| `agentic-os project work-item set` | Move one filesystem packet into the lane for an explicit lifecycle state. | Use before reconciling canonical SQLite `packet_path` after a governed move. |
| `agentic-os project work-item sync-active` | Rebuild disposable active links from SQLite-active rows and their verified worktrees. | Use after canonical work-state changes. |
| `agentic-os context build --project {project}` | Build a deterministic project context packet from this routed project or a unique project match. | Use `--domain {domain}` when outside the project route or when project names could collide. |
| `agentic-os validate` | Validate OS and project layer structure. | Run before handoff after scaffold changes. |
| `agentic-os runtime snapshot` | Inspect this project's queued and running work through the shared backend projection. | Filter by the declared named queue or task identity; do not inspect vendor state directly. |
| `agentic-os runtime config status` | Locate the canonical fabric config and inspect fingerprint/drift. | Project config references task types/queues but does not copy the root fabric config. |
| `/add-spec` | Compatibility intake that must land specification truth in Jira or Linear. | Do not create a filesystem source of truth. |
| `/auto-add-spec` | Compatibility intake that must land specification truth in Jira or Linear. | Do not create a filesystem source of truth. |
| `/new-feature` | Deprecated alias for `/add-spec`. | Compatibility only. |
| `/auto-add-feature` | Deprecated alias for `/auto-add-spec`. | Compatibility only. |

## Local Paths

| Path | Use When |
| --- | --- |
| `src/` | Canonical source checkout for this project. |
| `worktrees/` | Visible links to active worktrees. |
| `config/development.yml` | Canonical code settings: repository, base branch, worktree directory, branch template, and date-prefix inheritance or override. |
| `config/` | Other parsed project defaults and tool/workflow configuration. |
| `worklogs/` or `WORKLOGS/` | Human-readable work history and receipt summaries, matching local folder casing. |
| `ideas/` | Legacy compatibility index for project ideas; do not use as the lifecycle source of truth. |
| `work-items/<work-item-id>/` | Stable packet for bounded local evidence and resume context. |
| `work-items/99-archived/` | Retained terminal packets; search here before creating work for a returned ticket. |
| `work-items/01-intake/`, `02-active/`, `03-complete/` | Legacy import/read surfaces only; state lives in SQLite. |
| `artifacts/` | Project outputs that do not belong in a run log. |

## Composio Tool Routes

{composio_tools_markdown()}
"""


def project_memory_policy(project: str) -> str:
    return f"""# Memory Policy: {project}

Record durable, non-secret project learnings here when they are useful for
future work in this project. Keep temporary branch status in `status.md` or
`worktrees/index.yml`.
"""


def domain_memory_policy(domain: str) -> str:
    return f"""# Memory: {titleize_name(domain)}

Record durable, non-secret domain learnings here. Use this for routing decisions,
stable source maps, repeated workflow findings, project-level conventions, and
control-plane changes that future sessions should not rediscover.
"""


def project_config_file_content(
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    filename: str,
    *,
    repo: str | None = None,
) -> str:
    lane_value = lane or ""
    if filename == "project-profile.yml":
        return yaml.safe_dump(
            {
                "project": {
                    "id": project,
                    "domain": domain,
                    "status": status,
                    "lane": lane_value,
                    "entrypoint": "AGENTS.md",
                    "canonical_source": "src",
                    "specs": "external_tracker",
                    "worklogs": "worklogs",
                    "ideas": "external_tracker",
                    "artifacts": "artifacts",
                }
            },
            sort_keys=False,
        )
    if filename == "development.yml":
        if project == "genomes_agentic_os":
            return yaml.safe_dump(
                {
                    "version": 1,
                    "enabled": True,
                    "tracker": {
                        "primary": "linear",
                        "fallback": "filesystem",
                        "create_during_grooming": True,
                        "require_write_readback": True,
                        "linear": {
                            "workspace": "genomes",
                            "team": "Clarks Consulting",
                            "team_id": "2225b211-a962-4392-98ef-b2e78a26669f",
                            "project": "Genomes Agentic OS",
                            "project_id": "5812f46f-f7a5-4518-8a59-593aaa45f418",
                            "statuses": {
                                "groomed": "Todo",
                                "developing": "In Progress",
                                "ready_for_merge": "In Progress",
                                "delivered": "Done",
                                "blocked": "Blocked",
                            },
                        },
                    },
                    "repository": {
                        "id": "git:configured/genomes_agentic_os",
                        "provider": "github",
                        "owner": "configured_from_repository_remote",
                        "name": "genomes_agentic_os",
                        "root": repo or "~/projects/genomes_agentic_os",
                        "base_branch": "main",
                    },
                    "worktrees": {
                        "directory": "worktrees",
                        "branch_template": "feature/{ticket}-{slug}",
                        "date_prefix": "inherit",
                    },
                    "work_items": {
                        "active_status": "building",
                        "root": "work-items",
                        "archive": "work-items/99-archived",
                        "reopen_lookup_order": ["work-items", "work-items/99-archived"],
                    },
                    "runtime": {
                        "ownership": "not_managed",
                        "provider": "none",
                        "identity": "not-managed",
                    },
                    "validation": {
                        "commands": [
                            "uv sync --extra dev",
                            "uv run pytest -q",
                            "scripts/qa/reinstall-agentic-os.sh --root ~/agentic_os_qa",
                        ],
                        "test_policy": "risk_based_triangle",
                        "ci_fallback_on_environment_failure": True,
                        "secondary_install": {
                            "root": "~/agentic_os_qa",
                            "command": "scripts/qa/reinstall-agentic-os.sh --root ~/agentic_os_qa",
                            "required_passes": 3,
                            "preserve_operator_sentinel": True,
                            "validate_after_each_pass": True,
                        },
                    },
                    "review": {
                        "authorship": {"ours": ["github:configured_operator"]},
                        "opposing_harness": {
                            "required": False,
                            "preferred": "claude",
                            "fallback": "codex",
                            "unavailable_policy": "continue_with_receipt",
                        },
                        "self_review": {
                            "command": "claude",
                            "skill": "auto-dev-review-self-opposing-model",
                            "failure_policy": "continue_with_receipt",
                        },
                    },
                    "pull_request": {
                        "provider": "github",
                        "repository": "configured_from_repository_remote",
                        "draft": False,
                        "target": "main",
                    },
                    "merge": {
                        "policy": "never_auto",
                        "method": "squash",
                        "required_approvals": 0,
                        "require_acceptance_evidence": True,
                        "require_local_qa": True,
                        "require_ci_green": True,
                        "require_mergeable_readback": True,
                        "reviewer_unavailable_blocks": False,
                    },
                    "release": {
                        "required": True,
                        "provider": "github",
                        "repository": "configured_from_repository_remote",
                        "branch": "main",
                        "version_files": ["pyproject.toml", "src/genomes_agentic_os/__init__.py"],
                        "default_bump": "patch",
                        "tag_template": "v{version}",
                        "release_notes": "generated_from_merged_pr_and_changelog",
                        "create_github_release": True,
                        "require_tag_readback": True,
                        "require_release_readback": True,
                    },
                    "deployment": {"required": False, "monitor_after_merge": True},
                    "documentation": {
                        "required_after_release": True,
                        "source_repository": {"root": repo or "~/projects/genomes_agentic_os", "handbook": "docs"},
                        "notion": {
                            "required": True,
                            "workspace": "Genome's Notion",
                            "parent_surface": "genomes_agentic_os_hub",
                            "parent_page_id": "363683b48dab807baca1c468a45b269b",
                            "require_workspace_verification": True,
                            "require_write_readback": True,
                        },
                        "public_site": {
                            "required": True,
                            "repository": "~/projects/clark_consulting",
                            "base_branch": "main",
                            "public_path": "/genomes_agentic_os/",
                            "validation_command": "npm run build",
                            "require_pull_request": True,
                            "require_public_readback": True,
                        },
                    },
                    "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
                    "retention": {"raw_logs_days": 4, "merged_worktree_grace_days": 3},
                },
                sort_keys=False,
            )
        return yaml.safe_dump(
            {
                "version": 1,
                "enabled": True,
                "tracker": {"primary": "state_db", "spec_source": "jira_or_linear"},
                "repository": {"root": repo or "", "base_branch": "main"},
                "worktrees": {
                    "directory": "worktrees",
                    "branch_template": "feature/{ticket}-{slug}",
                    "date_prefix": "inherit",
                },
                "work_items": {"active_status": "building"},
                "runtime": {
                    "ownership": "not_managed",
                    "provider": "none",
                    "identity": "not-managed",
                },
                "validation": {
                    "commands": [],
                    "test_policy": "risk_based_triangle",
                    "ci_fallback_on_environment_failure": True,
                },
                "review": {
                    "authorship": {"ours": []},
                    "opposing_harness": {
                        "required": True,
                        "preferred": "claude",
                        "fallback": "codex",
                        "unavailable_policy": "continue_with_receipt",
                    }
                },
                "merge": {"policy": "never_auto"},
                "release": {"fix_version_drives_targets": True},
                "deployment": {"required": False, "monitor_after_merge": True},
                "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
                "policies": {
                    "dev_standards": {
                        "paths": [
                            "harness/shared_factory/05-knowledge/auto_dev/dev_standards",
                            f"domains/{domain}/05-knowledge/auto_dev/dev_standards",
                            "config/auto_dev/dev_standards",
                        ]
                    },
                    "qa_gates": {
                        "paths": [
                            "harness/shared_factory/05-knowledge/auto_dev/qa_gates",
                            f"domains/{domain}/05-knowledge/auto_dev/qa_gates",
                            "config/auto_dev/qa_gates",
                        ]
                    },
                    "gitflow_topology": {
                        "paths": [
                            "harness/shared_factory/05-knowledge/auto_dev/gitflow_topology",
                            f"domains/{domain}/05-knowledge/auto_dev/gitflow_topology",
                            "config/auto_dev/gitflow_topology",
                        ]
                    },
                    "auto_dev": {
                        "paths": [
                            "harness/shared_factory/05-knowledge/auto_dev",
                            f"domains/{domain}/05-knowledge/auto_dev",
                            "config/auto_dev",
                        ]
                    },
                    "environment_access": {
                        "paths": [
                            "harness/shared_factory/05-knowledge/auto_dev/environment_access",
                            f"domains/{domain}/05-knowledge/auto_dev/environment_access",
                            "config/auto_dev/environment_access",
                        ]
                    },
                },
                "retention": {"raw_logs_days": 4, "merged_worktree_grace_days": 3},
            },
            sort_keys=False,
        )
    if filename == "workflows.yml":
        auto_dev = (
            {
                "tracker": "linear",
                "stages": [
                    "groom", "detective", "create_artifacts", "readiness", "develop", "document",
                    "pr_create", "review_self", "review_others", "qa", "finalize", "merge", "release",
                    "deploy", "closeout", "health",
                ],
                "completion": "delivery_complete",
            }
            if project == "genomes_agentic_os"
            else None
        )
        workflows = {
            "default_lane": lane_value,
            "auto_dev": {
                "full_workflow_skill": "auto-dev-everything",
                "single_stage_skill_pattern": "auto-dev-<stage>",
                "state_file": "autodev.json",
                "policy_directory": "config/auto_dev",
                "health_skill": "auto-dev-health",
            },
            "feature_development": {
                "artifacts_ref": "config/output-artifacts.yml",
                "validation_ref": "config/validation.yml",
            },
        }
        if auto_dev:
            workflows["auto_dev_everything"] = auto_dev
        return yaml.safe_dump(
            {"workflows": workflows},
            sort_keys=False,
        )
    if filename == "work-lifecycle.yml":
        return yaml.safe_dump(
            {
                "work_lifecycle": {
                    "enabled": True,
                    "source_of_truth": "state_db",
                    "state_db": "harness/shared_factory/00-control-plane/state.db",
                    "active_projection": "harness/shared_factory/00-control-plane/active-now.json",
                    "work_items_root": "work-items",
                    "worklogs_root": "worklogs",
                    "packet_policy": "stable",
                    "layout": "single_canonical_root",
                    "archive": {
                        "enabled": True,
                        "directory": "99-archived",
                        "retention": {"value": 7, "unit": "days"},
                        "retention_days": 7,
                        "terminal_states": ["finished", "documented", "archived"],
                    },
                    "default_state": "captured",
                    "legacy_import_lanes": {
                        "intake": "01-intake",
                        "active": "02-active",
                        "complete": "03-complete",
                    },
                    "lane_state_map": {
                        "01-intake": ["captured", "triaged"],
                        "02-active": ["specified", "ready", "building", "validating", "blocked"],
                        "03-complete": ["finished", "documented", "archived"],
                    },
                    "naming": {
                        "intake_pattern": "{index:03d}_{slug}.md",
                        "expanded_intake_pattern": "{index:03d}_{slug}/",
                        "packet_pattern": "{index:03d}_{slug}/",
                        "subtask_pattern": "{parent_index:03d}_{subindex:02d}_{slug}.md",
                        "default_intake_format": "single_markdown",
                        "default_packet_capture_file": "SPEC.md",
                        "legacy_capture_file": "IDEA.md",
                    },
                    "states": [
                        "captured",
                        "triaged",
                        "specified",
                        "ready",
                        "building",
                        "validating",
                        "finished",
                        "documented",
                        "blocked",
                        "archived",
                    ],
                    "transcript_logging": {
                        "enabled": True,
                        "include_raw_transcript": True,
                        "include_tool_call_jsonl": True,
                        "include_tool_call_markdown": True,
                        "redaction_policy": "strict",
                    },
                    "spec_destination": {
                        "type": "external_tracker",
                    },
                    "external_tracker": {
                        "type": "configured_jira_or_linear",
                        "required": True,
                    },
                }
            },
            sort_keys=False,
        )
    if filename == "spec-engine.yml":
        linear_enabled = project == "genomes_agentic_os"
        linear_target = (
            {
                "workspace": "genomes",
                "team_id": "2225b211-a962-4392-98ef-b2e78a26669f",
                "project_id": "5812f46f-f7a5-4518-8a59-593aaa45f418",
            }
            if linear_enabled
            else {}
        )
        return yaml.safe_dump(
            {
                "schema_version": 1,
                "spec_engine": {
                    "enabled": True,
                    "authority": {
                        "content": "linear" if linear_enabled else "filesystem",
                        "lifecycle": "linear" if linear_enabled else "filesystem",
                    },
                    "defaults": {"type": "feature", "status": "idea", "disposition": "active"},
                    "adapters": {
                        "primary": "linear" if linear_enabled else "filesystem",
                        "mirrors": ["filesystem"] if linear_enabled else [],
                        "filesystem": {"enabled": True, "work_items_root": "work-items"},
                        "linear": {
                            "enabled": linear_enabled,
                            "mode": "backlog",
                            "target": linear_target,
                            "status_map": {},
                        },
                        "jira": {
                            "enabled": False,
                            "mode": "sprint",
                            "target": {},
                            "placement": {"default": "backlog", "allow_active_sprint_override": True},
                            "issue_type_map": {"bug": "Bug", "feature": "Story", "config": "Task"},
                            "status_map": {},
                        },
                    },
                    "sync": {"conflict_policy": "authority_wins", "local_identity_required": True},
                },
            },
            sort_keys=False,
        )
    if filename == "output-artifacts.yml":
        return yaml.safe_dump(
            {
                "output_artifacts": {
                    "feature_root": "work-items/{ticket_or_slug}/artifacts",
                    "spec_root": "external_tracker",
                    "worklog_root": "worklogs/{ticket_or_slug}",
                    "project_artifacts": "artifacts",
                    "run_logs": "../../06-runs-and-logs/runs",
                    "front_matter": True,
                    "source_repo_feature_root": "src/features/{ticket_or_slug}",
                    "legacy_source_feature_root": "src/.features/{ticket_or_slug}",
                    "source_of_truth": "state_db",
                }
            },
            sort_keys=False,
        )
    if filename == "validation.yml":
        commands = (
            [
                "uv sync --extra dev",
                "uv run pytest -q",
                "scripts/qa/reinstall-agentic-os.sh --root ~/agentic_os_qa",
            ]
            if project == "genomes_agentic_os"
            else []
        )
        return yaml.safe_dump(
            {
                "validation": {
                    "source_root": "src",
                    "commands": commands,
                    "required_before_handoff": ["agentic-os validate --root <os-root>"],
                }
            },
            sort_keys=False,
        )
    if filename == "worktrees.yml":
        return yaml.safe_dump(
            {
                "worktrees": {
                    "directory": "worktrees",
                    "index": "worktrees/index.yml",
                    "link_policy": "symlink_to_external_worktree",
                }
            },
            sort_keys=False,
        )
    if filename == "memory.yml":
        return yaml.safe_dump(
            {
                "memory": {
                    "local_file": "MEMORY.md",
                    "policy": "non_secret_durable_project_learnings_only",
                }
            },
            sort_keys=False,
        )
    if filename == "mcps.yml":
        return yaml.safe_dump(
            {
                "mcps": {
                    "availability": "project-approved systems only",
                    "declared_in": "TOOLS.md",
                    "codex_config": "config.toml",
                }
            },
            sort_keys=False,
        )
    if filename == "tools.yml":
        return yaml.safe_dump(
            {
                "tools": {
                    "registry": "TOOLS.md",
                    "commands": [
                        "agentic-os project src",
                        "agentic-os project onboard",
                        "agentic-os project worktree create",
                        "agentic-os project worktree add",
                        "agentic-os context build",
                        "agentic-os validate",
                    ],
                }
            },
            sort_keys=False,
        )
    raise ValueError(f"unknown project config file: {filename}")


def ensure_project_code_settings_defaults(
    project_root: Path,
    result: ScaffoldResult,
    *,
    repo: str | None = None,
) -> None:
    """Add new code-setting defaults without replacing project-owned choices."""
    path = project_root / "config" / "development.yml"
    if not path.is_file():
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project code settings must be a YAML mapping: {path}")
    changed = False
    repository = data.get("repository")
    if not isinstance(repository, dict):
        raise ValueError(f"project code setting repository must be a mapping: {path}")
    if not repository.get("root"):
        local_repo = local_repo_link_target(repo)
        src = project_root / "src"
        if local_repo is None and src.is_symlink() and src.resolve().is_dir():
            local_repo = src.resolve()
        if local_repo is not None:
            repository["root"] = str(local_repo)
            changed = True
    worktrees = data.get("worktrees")
    if not isinstance(worktrees, dict):
        raise ValueError(f"project code setting worktrees must be a mapping: {path}")
    if "date_prefix" not in worktrees:
        worktrees["date_prefix"] = "inherit"
        changed = True
    domain = project_root.parent.parent.name
    policies = data.get("policies")
    if policies is None:
        policies = {}
        data["policies"] = policies
        changed = True
    if not isinstance(policies, dict):
        raise ValueError(f"project code setting policies must be a mapping: {path}")
    conventional_policy_paths = {
        "dev_standards": [
            "harness/shared_factory/05-knowledge/auto_dev/dev_standards",
            f"domains/{domain}/05-knowledge/auto_dev/dev_standards",
            "config/auto_dev/dev_standards",
        ],
        "qa_gates": [
            "harness/shared_factory/05-knowledge/auto_dev/qa_gates",
            f"domains/{domain}/05-knowledge/auto_dev/qa_gates",
            "config/auto_dev/qa_gates",
        ],
        "gitflow_topology": [
            "harness/shared_factory/05-knowledge/auto_dev/gitflow_topology",
            f"domains/{domain}/05-knowledge/auto_dev/gitflow_topology",
            "config/auto_dev/gitflow_topology",
        ],
        "auto_dev": [
            "harness/shared_factory/05-knowledge/auto_dev",
            f"domains/{domain}/05-knowledge/auto_dev",
            "config/auto_dev",
        ],
        "environment_access": [
            "harness/shared_factory/05-knowledge/auto_dev/environment_access",
            f"domains/{domain}/05-knowledge/auto_dev/environment_access",
            "config/auto_dev/environment_access",
        ],
    }
    legacy_policy_paths = {
        plane: [
            path.replace("/auto_dev", "")
            for path in paths
        ]
        for plane, paths in conventional_policy_paths.items()
        if plane != "auto_dev"
    }
    for plane, paths in conventional_policy_paths.items():
        current = policies.get(plane)
        if plane not in policies:
            policies[plane] = {"paths": paths}
            changed = True
        elif (
            isinstance(current, dict)
            and current.get("paths") == legacy_policy_paths.get(plane)
        ):
            current["paths"] = paths
            changed = True
    if not changed:
        return
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result.updated.append(path)


def worktrees_readme(project: str) -> str:
    return f"""# Worktrees: {project}

This folder is the canonical visible registry for active code worktrees in this
project, regardless of domain. New worktrees default here and receive the OS
date prefix. `config/development.yml` can override the physical directory and
date-prefix inheritance; external checkouts still appear here as links.

Create a worktree from the configured repository:

```bash
agentic-os project worktree create <domain> {project} --branch <branch>
```

Register a worktree:

```bash
agentic-os project worktree add <domain> {project} <name> --path <path>
```

`index.yml` is the machine-readable list used by routing.
"""


def worktrees_index(project: str) -> str:
    return yaml.safe_dump({"project": project, "worktrees": []}, sort_keys=False)


def ideas_readme(project: str) -> str:
    return f"""# Ideas: {project}

Project-known ideas start in the configured Jira or Linear tracker and are
reconciled into canonical SQLite work state.

This folder is a compatibility index for older tools. Do not create a separate
filesystem backlog here.
"""


def ideas_raw(project: str) -> str:
    return f"""# Raw Ideas: {project}

Project-known ideas should be captured in Jira or Linear, then reconciled with
`agentic-os work upsert`. Use this table only as a compatibility index.

| Date | Source | Idea | Next Step |
| --- | --- | --- | --- |
"""


def worklogs_dir_name(project_root: Path) -> str:
    uppercase_markers = {"PLANS", "BUILD_LOGS", "WORKLOGS"}
    existing_names = {path.name for path in project_root.iterdir()} if project_root.exists() else set()
    if uppercase_markers.intersection(existing_names):
        return "WORKLOGS"
    return "worklogs"


def worklogs_readme(project: str) -> str:
    return f"""# Worklogs: {project}

Use this folder for human-readable work history, status receipts, and links to
evidence.

Raw command output, transcripts, async state, and large machine artifacts belong
under lowercase `logs/` or `artifacts/`, not here.
"""


def ensure_project_index(projects_readme: Path, domain: str, project: str, status: str, result: ScaffoldResult) -> None:
    table = "\n## Project Index\n\n| Project | Status | Folder |\n| --- | --- | --- |\n"
    if "## Project Index" not in projects_readme.read_text(encoding="utf-8"):
        append_once(projects_readme, table, result)
    append_once(projects_readme, f"| `{project}` | `{status}` | `{project}/` |\n", result)


def ensure_active_work(active_work: Path, project: str, status: str, result: ScaffoldResult) -> None:
    append_once(
        active_work,
        f"| `{project}` | `{status}` | OS Owner | Define next action. | `02-projects/{project}/` |\n",
        result,
    )


def append_control_signal(
    domain_root: Path,
    section: str,
    item: str,
    status: str,
    link: str,
    notes: str,
    result: ScaffoldResult,
) -> None:
    state_index = domain_root / "00-control-plane" / "state-index.md"
    if not state_index.exists():
        write_file_once(state_index, control_file_content(domain_root.name, "state-index.md"), result)
    row = (
        f"| {datetime.now(timezone.utc).date().isoformat()} | {item} | `{status}` | "
        f"{link} | {notes} |\n"
    )
    content = state_index.read_text(encoding="utf-8") if state_index.exists() else ""
    if row in content:
        result.skipped.append(state_index)
        return
    marker = f"## {section}"
    start = content.find(marker)
    if start == -1:
        append_once(state_index, f"\n{marker}\n\n| Date | Item | Status | Link | Notes |\n| --- | --- | --- | --- | --- |\n{row}", result)
        return
    next_section = content.find("\n## ", start + len(marker))
    insert_at = len(content) if next_section == -1 else next_section
    prefix = content[:insert_at]
    suffix = content[insert_at:]
    separator = "" if prefix.endswith("\n") else "\n"
    state_index.write_text(f"{prefix}{separator}{row}{suffix}", encoding="utf-8")
    result.updated.append(state_index)


def append_domain_memory(domain_root: Path, entry: str, result: ScaffoldResult) -> None:
    memory_file = domain_root / "MEMORY.md"
    if not memory_file.exists():
        write_file_once(memory_file, domain_memory_policy(domain_root.name), result)
    append_once(
        memory_file,
        f"\n## {datetime.now(timezone.utc).date().isoformat()}\n\n- {entry}\n",
        result,
    )


def append_project_source_refs(source_map: Path, repo: str | None, notion: str | None, jira: str | None, result: ScaffoldResult) -> None:
    rows = []
    if repo:
        rows.append(f"| Repo | {repo} | Code and working tree |  |\n")
    if notion:
        rows.append(f"| Notion | {notion} | Control plane or docs |  |\n")
    if jira:
        rows.append(f"| Jira | {jira} | Issues, roadmap, or delivery tracking |  |\n")
    for row in rows:
        append_once(source_map, row, result)


def append_project_remote_refs(
    source_map: Path,
    remotes: list[dict[str, str]],
    result: ScaffoldResult,
) -> None:
    """Append one source-map row per declared remote."""
    for r in remotes:
        name = r.get("name", "")
        host = r.get("host", "")
        path = r.get("path", "")
        authority = r.get("authority", "remote")
        purpose = (
            "Authoritative working tree"
            if authority == "remote"
            else "Reference working tree (local is authoritative)"
        )
        row = f"| Remote ({host}) | {host}:{path} | {purpose} | pending sync |\n"
        append_once(source_map, row, result)


def _remote_ssh_connect_cmd(host: str, root: str | Path, ssh_options: list[str] | None = None) -> str:
    """Return the interactive connect command for *host*, pulling ssh_options from hosts.yml if available."""
    if ssh_options is None:
        try:
            hosts = load_hosts(root)
            entry = hosts.get(host, {})
            ssh_options = entry.get("ssh_options") or []
        except Exception:
            ssh_options = []
    if ssh_options:
        opts_str = " ".join(ssh_options)
        return f"ssh {opts_str} {host}"
    return f"ssh {host}"


def remote_readme_content(
    project: str,
    remote: dict[str, str],
    root: str | Path,
    local_repo: str | None = None,
) -> str:
    """Return the managed REMOTE.md content for one remote entry."""
    name = remote.get("name") or project
    host = remote.get("host", "")
    path = remote.get("path", "")
    authority = remote.get("authority", "remote")

    connect_cmd = _remote_ssh_connect_cmd(host, root)
    batch_cmd = f"ssh -o BatchMode=yes {host} '<cmd>'"

    authority_stmt = (
        f"Code is **authoritative on {host}**. The local room is a read-only reference."
        if authority == "remote"
        else f"Local copy is **authoritative**. `{host}:{path}` is a deploy or reference copy."
    )
    mirror_warning = ""
    if local_repo and authority == "remote":
        mirror_warning = (
            f"\n> **Reference-only warning**: `src/` points to `{local_repo}` (local mirror). "
            f"The authoritative working tree is `{host}:{path}`. "
            f"Edits must be made on the remote; the local mirror is a reference snapshot."
        )

    return f"""# Remote: {name}

## Authority

{authority_stmt}{mirror_warning}

## Connect

Interactive session:

```sh
{connect_cmd}
cd {path}
```

Non-interactive (agent-safe):

```sh
{batch_cmd}
```

## Notes

- Sync state is tracked in `manifest.yml` alongside this file.
- Run `agentic-os project sync-remote` to refresh the manifest.
- Never commit credentials, keys, or hostnames-with-passwords here.
  All connectivity lives in `~/.ssh/config` under the alias `{host}`.
"""


def remote_manifest_stub(project: str, remote: dict[str, str]) -> str:
    """Return the initial manifest.yml stub content for one remote."""
    name = remote.get("name") or project
    host = remote.get("host", "")
    path = remote.get("path", "")
    kind = remote.get("kind", "git")
    authority = remote.get("authority", "remote")
    payload = {
        "name": name,
        "host": host,
        "path": path,
        "kind": kind,
        "authority": authority,
        "reachable": "unknown",
        "synced_at": None,
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def ensure_project_remote_dirs(
    project_root: Path,
    project: str,
    remotes: list[dict[str, str]],
    root: str | Path,
    result: ScaffoldResult,
    local_repo: str | None = None,
) -> None:
    """Materialize remote/<name>/ for every declared remote."""
    for r in remotes:
        name = r.get("name") or project
        remote_dir = project_root / "remote" / name
        ensure_dir(remote_dir, result)
        # REMOTE.md is a managed file — refreshed on re-runs if the marker phrase appears
        write_project_file(
            remote_dir / "REMOTE.md",
            remote_readme_content(project, r, root, local_repo=local_repo),
            result,
            replace_markers=("Never commit credentials, keys, or hostnames-with-passwords here.",),
        )
        # manifest.yml is a stub written once; sync-remote owns it after creation
        write_file_once(
            remote_dir / "manifest.yml",
            remote_manifest_stub(project, r),
            result,
        )


def write_project_file(path: Path, content: str, result: ScaffoldResult, *, replace_markers: tuple[str, ...] = ()) -> None:
    if not path.exists():
        write_file_once(path, content, result)
        return
    existing = path.read_text(encoding="utf-8")
    if existing == content:
        result.skipped.append(path)
        return
    if replace_markers and any(marker in existing for marker in replace_markers):
        path.write_text(content, encoding="utf-8")
        result.updated.append(path)
        return
    result.skipped.append(path)


def ensure_project_operating_surface(
    project_root: Path,
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    result: ScaffoldResult,
    *,
    remotes: list[dict[str, str]] | None = None,
    root: str | Path | None = None,
    repo: str | None = None,
) -> None:
    worklogs_dir = worklogs_dir_name(project_root)
    ensure_dir(project_root / "artifacts", result)
    ensure_dir(project_root / "config", result)
    migrate_auto_dev_policy_directories(project_root / "config", result)
    write_file_once(
        project_root / "config" / "auto_dev" / "README.md",
        f"""# Auto-Dev: {project}

This project inherits shared and domain Auto-Dev policy. `README.md` is an index,
not active policy. Add numbered Markdown files that describe the verified
repository-specific behavior for each applicable stage: tracker and branches,
architecture, implementation, tests, review, PR family, release/deploy,
documentation, runtime cleanup, receipts, recovery, and done criteria.

Do not call the project configured while this README is the only file. Verify
selection with `agentic-os develop policy {domain} {project} --plane auto_dev
--root <os-root> --json`.
""",
        result,
    )
    plane_guidance = {
        "dev_standards": "repository-specific coding, architecture, security, review, and documentation expectations",
        "qa_gates": "repository-specific tests, acceptance evidence, regression gates, and QA handoff",
        "gitflow_topology": "repository-specific branch, worktree, pull-request, merge, and release topology",
        "environment_access": "verified local runtime, item-owned resources, hosts, VPN, cloud access, readback, cleanup, and recovery",
    }
    for plane, guidance in plane_guidance.items():
        write_file_once(
            project_root / "config" / "auto_dev" / plane / "README.md",
            f"""# {plane.replace("_", " ").title()}: {project}

Add numbered, plain-English Markdown for {guidance}. Never store credentials or
customer data here.

Verify selection with `agentic-os develop policy {domain} {project} --plane {plane} --root <os-root> --json`.
""",
            result,
        )
    ensure_dir(project_root / worklogs_dir, result)
    ensure_dir(project_root / "ideas", result)
    ensure_dir(project_root / "work-items", result)
    ensure_dir(project_root / "worktrees", result)
    ensure_spotlight_never_index(project_root / "worktrees", result)
    write_project_file(
        project_root / "AGENTS.md",
        project_agents(domain, project, remotes=remotes),
        result,
        replace_markers=("This file is the harness-neutral entrypoint for this Agentic OS layer",),
    )
    write_project_file(
        project_root / "ROUTER.md",
        project_router(domain, project),
        result,
        replace_markers=("Route work to the narrowest correct domain, workflow, automation, or run log",),
    )
    write_project_file(
        project_root / "CONTEXT.md",
        project_context(domain, project, remotes=remotes),
        result,
        replace_markers=(
            "Describe the local room, source systems, and routing hints",
            "Describe the local room, source systems, routing hints",
        ),
    )
    write_project_file(
        project_root / "RULES.md",
        project_rules(domain, project, remotes=remotes),
        result,
        replace_markers=("Record local constraints, approval gates, safety boundaries",),
    )
    write_project_file(
        project_root / "TOOLS.md",
        project_tools(domain, project),
        result,
        replace_markers=("List the visible capabilities intended for this layer",),
    )
    for filename in ("AGENTS.md", "ROUTER.md", "RULES.md", "TOOLS.md"):
        write_managed_marker_block(
            project_root / filename,
            EXECUTION_FABRIC_ROUTING_BLOCK,
            result,
        )
    write_project_file(
        project_root / "MEMORY.md",
        project_memory_policy(project),
        result,
        replace_markers=("Record only durable, useful, non-secret learnings",),
    )
    write_file_once(project_root / "worktrees" / "README.md", worktrees_readme(project), result)
    write_file_once(project_root / "worktrees" / "index.yml", worktrees_index(project), result)
    write_file_once(project_root / worklogs_dir / "README.md", worklogs_readme(project), result)
    write_file_once(project_root / "ideas" / "README.md", ideas_readme(project), result)
    write_file_once(project_root / "ideas" / "raw-ideas.md", ideas_raw(project), result)
    for filename in PROJECT_CONFIG_FILES:
        write_file_once(
            project_root / "config" / filename,
            project_config_file_content(domain, project, status, lane, filename, repo=repo),
            result,
        )
    ensure_project_code_settings_defaults(project_root, result, repo=repo)
    ensure_codex_config(project_root, "project", result)
    if remotes:
        ensure_project_remote_dirs(
            project_root,
            project,
            remotes,
            root if root is not None else project_root,
            result,
            local_repo=repo,
        )


def is_remote_repo_reference(repo: str) -> bool:
    return "://" in repo or repo.startswith("git@")


def local_repo_link_target(repo: str | None) -> Path | None:
    if not repo or is_remote_repo_reference(repo):
        return None
    candidate = Path(repo).expanduser()
    if not candidate.is_absolute() and not candidate.exists() and not str(repo).startswith("."):
        return None
    return expand_path(repo)


def ensure_project_source_link(
    project_root: Path,
    repo: str | None,
    result: ScaffoldResult,
    *,
    replace: bool = False,
    fail_on_conflict: bool = False,
) -> None:
    target = local_repo_link_target(repo)
    if target is None:
        return
    link_path = project_root / "src"
    if link_path.is_symlink():
        if link_path.resolve() == target:
            result.skipped.append(link_path)
            return
        if not replace:
            if fail_on_conflict:
                raise ValueError(f"project src already points elsewhere: {link_path}")
            result.skipped.append(link_path)
            return
        link_path.unlink()
        link_path.symlink_to(target, target_is_directory=True)
        result.updated.append(link_path)
        return
    if link_path.exists():
        if fail_on_conflict:
            raise ValueError(f"project src exists and is not a symlink: {link_path}")
        result.skipped.append(link_path)
        return
    link_path.symlink_to(target, target_is_directory=True)
    result.created.append(link_path)


def project_repo_from_config(project_root: Path) -> str:
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    return str(sources.get("repo") or "")


def set_project_repo(project_root: Path, repo: str, result: ScaffoldResult) -> None:
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project config must be a YAML mapping: {config}")
    sources = data.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        data["sources"] = sources
    if sources.get("repo") == repo:
        result.skipped.append(config)
        return
    sources["repo"] = repo
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result.updated.append(config)


def set_project_code_repo(project_root: Path, repo: str, result: ScaffoldResult) -> None:
    """Keep the canonical project code settings aligned with ``project src``."""
    config = project_root / "config" / "development.yml"
    if not config.is_file():
        return
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project code settings must be a YAML mapping: {config}")
    repository = data.get("repository")
    if not isinstance(repository, dict):
        repository = {}
        data["repository"] = repository
    if repository.get("root") == repo:
        result.skipped.append(config)
        return
    repository["root"] = repo
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result.updated.append(config)


def link_project_source(
    root: str | Path,
    domain: str,
    project: str,
    *,
    repo: str | None = None,
    force: bool = False,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")

    result = ScaffoldResult()
    repo = repo or project_repo_from_config(project_root)
    if not repo:
        raise ValueError("repo is required because project.yml has no sources.repo")
    if local_repo_link_target(repo) is None:
        raise ValueError(f"repo must be a local path to create a project src symlink: {repo}")

    ensure_project_source_link(project_root, repo, result, replace=force, fail_on_conflict=True)
    set_project_repo(project_root, repo, result)
    set_project_code_repo(project_root, repo, result)
    append_project_source_refs(project_root / "source-map.md", repo, None, None, result)
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    ensure_project_operating_surface(
        project_root,
        domain,
        project,
        str(data.get("status") or "active"),
        str(data.get("lane") or "") or None,
        result,
    )
    return result


def _remotes_from_config(data: dict) -> list[dict[str, str]]:
    """Extract sources.remotes list from a parsed project.yml data dict."""
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return []
    remotes = sources.get("remotes")
    if not isinstance(remotes, list):
        return []
    result = []
    for r in remotes:
        if isinstance(r, dict):
            result.append({str(k): str(v) for k, v in r.items() if v is not None})
    return result


def _upsert_remote_in_config(
    project_root: Path,
    project: str,
    remote: dict[str, str],
    *,
    force: bool = False,
) -> dict[str, str]:
    """Add or replace a remote entry in project.yml sources.remotes.

    Returns the final remote dict that was written.
    Raises ValueError on name conflict when force=False.
    """
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project config must be a YAML mapping: {config}")
    sources = data.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        data["sources"] = sources
    existing_remotes: list[dict] = []
    if isinstance(sources.get("remotes"), list):
        existing_remotes = sources["remotes"]

    name = remote.get("name") or project
    conflict_index = next(
        (i for i, r in enumerate(existing_remotes) if (r.get("name") or project) == name),
        None,
    )
    if conflict_index is not None and not force:
        raise ValueError(
            f"Remote {name!r} already exists in {config}. Use --force to replace."
        )
    if conflict_index is not None:
        existing_remotes[conflict_index] = remote
    else:
        existing_remotes.append(remote)
    sources["remotes"] = existing_remotes
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return remote


def link_project_remote(
    root: str | Path,
    domain: str,
    project: str,
    *,
    host: str,
    path: str,
    name: str | None = None,
    kind: str = "git",
    authority: str = "remote",
    force: bool = False,
) -> ScaffoldResult:
    """Attach a remote to an existing project: update project.yml, materialize remote dir, append source-map row."""
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")

    remote: dict[str, str] = {
        "name": name or project,
        "host": host,
        "path": path,
        "kind": kind,
        "authority": authority,
    }
    result = ScaffoldResult()
    _upsert_remote_in_config(project_root, project, remote, force=force)
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    repo = str(data.get("sources", {}).get("repo") or "") or None

    ensure_project_remote_dirs(project_root, project, [remote], os_root, result, local_repo=repo)
    append_project_remote_refs(project_root / "source-map.md", [remote], result)
    # Re-run AGENTS.md and CONTEXT.md with the updated full remotes list so the section is refreshed
    all_remotes = _remotes_from_config(data)
    write_project_file(
        project_root / "AGENTS.md",
        project_agents(domain, project, remotes=all_remotes),
        result,
        replace_markers=("This file is the harness-neutral entrypoint for this Agentic OS layer",),
    )
    write_project_file(
        project_root / "CONTEXT.md",
        project_context(domain, project, remotes=all_remotes),
        result,
        replace_markers=(
            "Describe the local room, source systems, and routing hints",
            "Describe the local room, source systems, routing hints",
        ),
    )
    return result


def onboard_project(root: str | Path, domain: str, project: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    remotes = _remotes_from_config(data) or None
    repo = str(data.get("sources", {}).get("repo") or "") or None
    result = ScaffoldResult()
    ensure_project_operating_surface(
        project_root,
        domain,
        project,
        str(data.get("status") or "active"),
        str(data.get("lane") or "") or None,
        result,
        remotes=remotes,
        root=os_root,
        repo=repo,
    )
    return result


def project_worktree_index_path(project_root: Path) -> Path:
    return project_root / "worktrees" / "index.yml"


def load_project_worktree_index(project_root: Path, project: str) -> dict[str, object]:
    index_path = project_worktree_index_path(project_root)
    if not index_path.is_file():
        return {"project": project, "worktrees": []}
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"project": project, "worktrees": []}
    worktrees = data.get("worktrees")
    if not isinstance(worktrees, list):
        data["worktrees"] = []
    data.setdefault("project", project)
    return data


def write_project_worktree_index(project_root: Path, data: dict[str, object], result: ScaffoldResult) -> None:
    index_path = project_worktree_index_path(project_root)
    before = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    after = yaml.safe_dump(data, sort_keys=False)
    if before == after:
        result.skipped.append(index_path)
        return
    index_path.write_text(after, encoding="utf-8")
    result.updated.append(index_path) if before else result.created.append(index_path)


def sync_project_worktree_config(project_root: Path, index_data: dict[str, object], result: ScaffoldResult) -> None:
    config_path = project_root / "config" / "worktrees.yml"
    entries = [entry for entry in index_data.get("worktrees") or [] if isinstance(entry, dict)]
    link_policy = (
        "symlink_to_external_worktree"
        if any(entry.get("link_policy") == "symlink_to_external_worktree" for entry in entries)
        else "in_place_worktree"
    )
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    after = yaml.safe_dump(
        {
            "worktrees": {
                "directory": "worktrees",
                "index": "worktrees/index.yml",
                "link_policy": link_policy,
                "registered": entries,
            }
        },
        sort_keys=False,
    )
    if before == after:
        result.skipped.append(config_path)
        return
    config_path.write_text(after, encoding="utf-8")
    result.updated.append(config_path) if before else result.created.append(config_path)


def register_project_worktree(
    root: str | Path,
    domain: str,
    project: str,
    name: str,
    *,
    path: str | Path,
    force: bool = False,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    name = validate_worktree_name(name)
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    target = expand_path(path)
    if not target.is_dir():
        raise ValueError(f"worktree path must be an existing directory: {target}")

    code_settings = load_project_code_settings(project_root)
    storage_root = project_worktree_root(project_root, code_settings)
    link_root = (project_root / "worktrees").resolve()
    in_place = storage_root == link_root and target.is_relative_to(storage_root)
    # Existing in-place checkouts are renamed only by the transactional
    # migration command because git metadata must move with the directory.
    if not in_place:
        name = dated_name(
            name,
            when=datetime.now(timezone.utc),
            policy=project_worktree_naming_policy(os_root, code_settings),
            scope="worktrees",
        )
    result = onboard_project(os_root, domain, project)
    link_path = link_root / name
    if in_place:
        if target != link_root / name:
            raise ValueError(
                "in-place worktree path must be the visible "
                f"worktrees/{name} entry itself: {target}"
            )
        result.skipped.append(link_path)
    elif link_path.is_symlink():
        if link_path.resolve() == target:
            result.skipped.append(link_path)
        elif force:
            link_path.unlink()
            link_path.symlink_to(target, target_is_directory=True)
            result.updated.append(link_path)
        else:
            raise ValueError(f"worktree link already points elsewhere: {link_path}")
    elif link_path.exists():
        raise ValueError(f"worktree link exists and is not a symlink: {link_path}")
    else:
        link_path.parent.mkdir(parents=True, exist_ok=True)
        link_path.symlink_to(target, target_is_directory=True)
        result.created.append(link_path)

    registered_link = str(link_path.relative_to(project_root))

    index_data = load_project_worktree_index(project_root, project)
    entries = [entry for entry in index_data.get("worktrees", []) if isinstance(entry, dict)]
    branch_probe = subprocess.run(
        ["git", "-C", str(target), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch = branch_probe.stdout.strip() if branch_probe.returncode == 0 else ""
    repository_settings = (
        code_settings.get("repository")
        if isinstance(code_settings.get("repository"), dict)
        else {}
    )
    entry = {
        "id": name,
        "path": str(target),
        "link": registered_link,
        "status": "active",
        "link_policy": "in_place_worktree" if in_place else "symlink_to_external_worktree",
        **({"branch": branch} if branch else {}),
        **(
            {"base_branch": str(repository_settings.get("base_branch"))}
            if repository_settings.get("base_branch")
            else {}
        ),
    }
    replaced = False
    for offset, existing in enumerate(entries):
        if existing.get("id") == name:
            if existing != entry:
                entries[offset] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    index_data["worktrees"] = entries
    write_project_worktree_index(project_root, index_data, result)
    sync_project_worktree_config(project_root, index_data, result)
    return result


def create_project_worktree(
    root: str | Path,
    domain: str,
    project: str,
    name: str | None = None,
    *,
    repo: str | Path | None = None,
    branch: str,
    runner: object | None = None,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    code_settings = load_project_code_settings(project_root)
    if code_settings.get("enabled") is not True:
        raise ValueError(f"project code is disabled in {project_root / 'config' / 'development.yml'}")
    name = worktree_name_from_branch(branch) if name is None else validate_worktree_name(name)
    name = dated_name(
        name,
        when=datetime.now(timezone.utc),
        policy=project_worktree_naming_policy(os_root, code_settings),
        scope="worktrees",
    )
    repository = code_settings.get("repository") if isinstance(code_settings.get("repository"), dict) else {}
    configured_repo = repository.get("root")
    selected_repo = repo or configured_repo
    if not selected_repo:
        raise ValueError(
            "worktree repo is required; pass --repo or set repository.root in config/development.yml"
        )
    repo_path = expand_path(selected_repo)
    if not repo_path.is_dir():
        raise ValueError(f"worktree repo must be an existing local directory: {repo_path}")
    destination = project_worktree_root(project_root, code_settings) / name
    if destination.is_symlink() or destination.exists():
        raise ValueError(f"worktree destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    run = runner or (lambda args: subprocess.run(args, capture_output=True, text=True, timeout=120))  # noqa: S603
    probe = run(["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    if probe.returncode == 0:
        command = ["git", "-C", str(repo_path), "worktree", "add", str(destination), branch]
    else:
        command = ["git", "-C", str(repo_path), "worktree", "add", "-b", branch, str(destination)]
    created = run(command)
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "").strip()
        raise ValueError(f"git worktree add failed for {destination}: {detail}")
    if not destination.is_dir():
        raise ValueError(f"git worktree add did not produce a directory: {destination}")
    return register_project_worktree(os_root, domain, project, name, path=destination)


def create_project(
    root: str | Path,
    domain: str,
    project: str,
    *,
    repo: str | None = None,
    notion: str | None = None,
    jira: str | None = None,
    status: str = "active",
    lane: str | None = None,
    remotes: list[dict[str, str]] | None = None,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    if status not in PROJECT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(PROJECT_STATUSES)}: {status!r}")
    if lane is not None:
        lane = validate_name(lane, "lane")

    result = create_domain(root, domain)
    domain_root = domain_path(root, domain)
    project_root = domain_root / "02-projects" / project
    ensure_dir(project_root, result)
    write_file_once(project_root / "README.md", project_readme(domain, project, status, lane), result)
    write_file_once(project_root / "project.yml", project_config(domain, project, status, lane, repo, notion, jira, remotes=remotes), result)
    write_file_once(project_root / "status.md", project_status(project, status), result)
    write_file_once(project_root / "decisions.md", project_decisions(project), result)
    write_file_once(project_root / "source-map.md", project_source_map(project, repo, notion, jira), result)
    ensure_project_source_link(project_root, repo, result)
    ensure_project_operating_surface(project_root, domain, project, status, lane, result, remotes=remotes, root=root, repo=repo)

    ensure_project_index(domain_root / "02-projects" / "README.md", domain, project, status, result)
    ensure_active_work(domain_root / "00-control-plane" / "active-work.md", project, status, result)
    append_control_signal(
        domain_root,
        "Project Activity",
        f"`{project}`",
        status,
        f"`02-projects/{project}/`",
        "Project scaffold created or repaired.",
        result,
    )
    append_project_source_refs(project_root / "source-map.md", repo, notion, jira, result)
    if remotes:
        append_project_remote_refs(project_root / "source-map.md", remotes, result)
    return result


def programs_readme(scope: str) -> str:
    display_name = titleize_name(scope)
    return f"""# Programs: {display_name}

This folder contains OSProgram and InstanceOSProgram contracts for discrete
capabilities that span multiple skills, commands, workflows, automations,
scripts, templates, schedules, documentation, or external state surfaces.

Create one folder per program and keep `components.yml`, `documentation.md`,
`runbook.md`, `tests.md`, and `worklog.md` current with the owned surfaces.
"""


def program_agent_entrypoint(program_type: str, name: str) -> str:
    return f"""# Agent Entry Point: {name}

This layer owns the `{name}` {program_type}.

## Startup Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and `program.md`.
2. Classify the request as create, read, update, delete, investigate, operate,
   validate, document, or promote.
3. Load `components.yml` and only the linked surfaces needed for that operation.
4. Make the requested change across every affected component.
5. Update `documentation.md`, `worklog.md`, and validation receipts before handoff.

## Precedence

Active user instructions win. The strictest safety, approval, privacy, Notion,
secret-handling, and destructive-action rule wins across all loaded files.
"""


def program_router(program_type: str, name: str) -> str:
    return f"""# Router: {name}

Use this router when a prompt names `{name}` or any alias listed in `program.md`.

## CRUD Routes

| Intent | Load First | Also Inspect | Required Output |
| --- | --- | --- | --- |
| Create capability surface | `program.md`, `components.yml`, `documentation.md` | command docs, skill adapters, workflow/automation specs | scaffolded files plus updated docs |
| Read or explain behavior | `context-pack.md`, `components.yml` | source scripts, run logs, Notion/database links | concise source-backed explanation |
| Update or tweak behavior | `crud.md`, `components.yml`, owning component specs | scripts, commands, schedules, templates, tests | changed component plus docs/worklog/tests |
| Delete or retire | `RULES.md`, `components.yml`, `runbook.md` | schedules, Notion pages, archives | explicit approval before destructive action |
| Investigate failure | `runbook.md`, `tests.md`, latest logs/state | external source receipts | root cause, fix, validation receipt |
| Promote to shared OS | `documentation.md`, `components.yml` | source package docs/templates/tests | source-package patch and migration notes |

## Routing Rules

- Treat the program as the ownership boundary for named capability changes.
- Route to the narrowest linked workflow, automation, skill, command, or script
  only after this program context is loaded.
- Update surrounding docs, tests, routing, schedules, and registries when a
  behavior change affects them.
"""


def program_context(program_type: str, name: str) -> str:
    return f"""# Context: {name}

`{name}` is a {program_type}: a discrete OS capability that may span multiple
execution and documentation surfaces.

## Load Order

1. `program.md` for purpose, aliases, owner, status, and linked surfaces.
2. `components.yml` for canonical component paths.
3. `crud.md` for how create/read/update/delete work should propagate.
4. `runbook.md` and `tests.md` for operation and validation.
5. Linked component files only as needed.

## Documentation Contract

Every material OS-level feature change must update filesystem docs, affected
linked surfaces, Notion projection notes when present, and `worklog.md`.
"""


def program_rules(program_type: str, name: str) -> str:
    return f"""# Rules: {name}

The strictest applicable rule wins across parent domain, shared factory,
component, and program files.

## Program Boundaries

- This folder owns context and documentation for the `{name}` {program_type}.
- Do not update a linked skill, command, workflow, automation, schedule, Notion
  database, script, or template without updating this program's documentation.
- Do not create undocumented OS-level behavior.

## Safety

- Secrets stay out of prompts, docs, logs, code, generated config, and Notion.
- External writes, destructive actions, production changes, billing/legal
  changes, and customer-visible output require approval gates.
"""


def program_tools(program_type: str, name: str) -> str:
    return f"""# Tools: {name}

List the tools, commands, skills, scripts, and external systems this {program_type}
is allowed to use.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `program-builder` | Creating or updating OSProgram / InstanceOSProgram contracts. | `harness/skills/program-builder/SKILL.md` |
| `os-authoring-guard` | Editing OS commands, skills, workflows, automations, tools, registries, or templates. | `harness/skills/os-authoring-guard/SKILL.md` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os program create` | Create a shared OSProgram. | Writes under `harness/shared_factory/00-programs/`. |
| `agentic-os instance-program create` | Create an instance/domain program. | Writes under `<domain>/00-programs/`. |
"""


def program_components(name: str, program_type: str) -> str:
    return yaml.safe_dump(
        {
            "schema_version": 1,
            "name": name,
            "type": program_type,
            "aliases": [],
            "components": {
                "skills": [],
                "commands": [],
                "workflows": [],
                "automations": [],
                "scripts": [],
                "templates": [],
                "documentation": [],
                "notion": [],
                "schedules": [],
                "state": [],
            },
            "context_routes": {
                "create": ["program.md", "components.yml", "documentation.md"],
                "read": ["context-pack.md", "components.yml"],
                "update": ["crud.md", "components.yml", "tests.md"],
                "delete": ["RULES.md", "components.yml", "runbook.md"],
                "investigate": ["runbook.md", "tests.md", "worklog.md"],
            },
            "documentation_required": True,
        },
        sort_keys=False,
    )


def program_scaffold_content(
    name: str,
    filename: str,
    *,
    program_type: str,
    domain: str | None = None,
) -> str:
    scope = domain or "shared_factory"
    created = datetime.now(timezone.utc).date().isoformat()
    if filename == "program.md":
        return f"""# {program_type}: {name}

## Status

- Status: scaffolded
- Owner: OS Owner
- Created: {created}
- Scope: `{scope}`
- Documentation required: yes

## Purpose

Explain what discrete OS capability this program owns and why it exists.

## Aliases

- `{name}`

## Owned Surfaces

List every skill, command, workflow, automation, script, template, Notion page or
database, schedule, state file, and documentation surface this program owns.
Keep `components.yml` as the machine-readable source of truth.
"""
    if filename == "components.yml":
        return program_components(name, program_type)
    if filename == "context-pack.md":
        return f"""# Context Pack: {name}

## Load First

1. `program.md`
2. `components.yml`
3. `crud.md`
4. `runbook.md`
5. `tests.md`
"""
    if filename == "crud.md":
        return f"""# CRUD Contract: {name}

## Create

- Add the new component surface.
- Register it in `components.yml`.
- Add routing/docs/tests before use.

## Read

- Explain behavior from `program.md`, `components.yml`, source scripts, and latest receipts.

## Update

- Patch the owning component.
- Update linked docs, commands, skills, workflows, automations, templates,
  schedules, state docs, and tests affected by the change.
- Record validation in `worklog.md`.

## Delete / Retire

- Require explicit approval before destructive changes.
- Disable schedules before removing files or external surfaces.
"""
    if filename == "documentation.md":
        return f"""# Documentation Map: {name}

## Filesystem Documentation

| Surface | Path | Update Trigger |
| --- | --- | --- |
| Program contract | `program.md` | Any ownership or behavior change |
| Components registry | `components.yml` | Any linked surface change |
| CRUD contract | `crud.md` | Any routing/update policy change |
| Runbook/tests | `runbook.md`, `tests.md` | Any operation or validation change |
"""
    if filename == "runbook.md":
        return f"""# Runbook: {name}

## Investigate

1. Load the program startup loop.
2. Read `components.yml`.
3. Inspect latest logs/state for linked automations or workflows.
4. Identify whether the issue is routing, source data, permissions, schedule,
   code, documentation drift, or external system access.

## Update

1. Patch the narrowest owning component.
2. Update surrounding docs and registries.
3. Run focused validation.
4. Record the receipt in `worklog.md`.
"""
    if filename == "tests.md":
        return f"""# Tests: {name}

## Static Checks

- `components.yml` lists every owned surface.
- `program.md`, `crud.md`, `documentation.md`, and `runbook.md` are current.
- Linked command/skill/workflow/automation docs match implementation.
"""
    return f"""# Worklog: {name}

| Date | Actor | Change | Validation | Follow-up |
| --- | --- | --- | --- | --- |
"""


def create_program(root: str | Path, name: str) -> ScaffoldResult:
    name = validate_name(name, "program")
    os_root = expand_path(root)
    result = ScaffoldResult()
    programs_root = shared_factory_path(os_root, "00-programs")
    ensure_dir(programs_root, result)
    write_file_once(programs_root / "README.md", programs_readme("shared_factory"), result)
    program_root = programs_root / name
    ensure_dir(program_root, result)
    ensure_dir(program_root / "artifacts", result)
    write_file_once(program_root / "AGENTS.md", program_agent_entrypoint("OSProgram", name), result)
    write_file_once(program_root / "ROUTER.md", program_router("OSProgram", name), result)
    write_file_once(program_root / "CONTEXT.md", program_context("OSProgram", name), result)
    write_file_once(program_root / "RULES.md", program_rules("OSProgram", name), result)
    write_file_once(program_root / "TOOLS.md", program_tools("OSProgram", name), result)
    for filename in PROGRAM_FILES:
        write_file_once(program_root / filename, program_scaffold_content(name, filename, program_type="OSProgram"), result)
    ensure_codex_config(program_root, "workflow_or_task", result)
    return result


def create_instance_program(root: str | Path, domain: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    name = validate_name(name, "instance program")
    result = create_domain(root, domain)
    domain_root = domain_path(root, domain)
    programs_root = domain_root / "00-programs"
    ensure_dir(programs_root, result)
    write_file_once(programs_root / "README.md", programs_readme(domain), result)
    program_root = programs_root / name
    ensure_dir(program_root, result)
    ensure_dir(program_root / "artifacts", result)
    write_file_once(program_root / "AGENTS.md", program_agent_entrypoint("InstanceOSProgram", name), result)
    write_file_once(program_root / "ROUTER.md", program_router("InstanceOSProgram", name), result)
    write_file_once(program_root / "CONTEXT.md", program_context("InstanceOSProgram", name), result)
    write_file_once(program_root / "RULES.md", program_rules("InstanceOSProgram", name), result)
    write_file_once(program_root / "TOOLS.md", program_tools("InstanceOSProgram", name), result)
    for filename in PROGRAM_FILES:
        write_file_once(
            program_root / filename,
            program_scaffold_content(name, filename, program_type="InstanceOSProgram", domain=domain),
            result,
        )
    ensure_codex_config(program_root, "workflow_or_task", result)
    append_control_signal(
        domain_root,
        "Program Status",
        f"`{name}`",
        "scaffolded",
        f"`00-programs/{name}/`",
        "InstanceOSProgram scaffold owns context routing for a discrete capability.",
        result,
    )
    return result


def workflow_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<workflow_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
        "<work_item_or_run>": name,
        "<workflow>": name,
        "<work_item_id>": "",
        "<workflow_or_domain>": name,
    }
    template_dir = template_source_dir() / "workflow"
    if filename == "context-contract.yml":
        return (template_source_dir() / "context-contract" / "workflow.yml").read_text(encoding="utf-8")
    if filename == "workflow.md":
        return render_template((template_dir / "workflow.md").read_text(encoding="utf-8"), replacements)
    if filename == "outcome-brief.md":
        return render_template((template_dir / "outcome-brief.md").read_text(encoding="utf-8"), replacements)
    if filename == "alignment-questions.md":
        return render_template((template_dir / "alignment-questions.md").read_text(encoding="utf-8"), replacements)
    if filename == "prd.md":
        return render_template((template_dir / "prd.md").read_text(encoding="utf-8"), replacements)
    if filename == "implementation-plan.md":
        return render_template((template_dir / "implementation-plan.md").read_text(encoding="utf-8"), replacements)
    if filename == "dispatch-handoff.md":
        return render_template((template_dir / "dispatch-handoff.md").read_text(encoding="utf-8"), replacements)
    if filename == "progress.md":
        return render_template((template_dir / "progress.md").read_text(encoding="utf-8"), replacements)
    if filename == "quick-reference.md":
        return render_template((template_dir / "quick-reference.md").read_text(encoding="utf-8"), replacements)
    if filename == "context-pack.md":
        return render_template((template_dir / "context-pack.md").read_text(encoding="utf-8"), replacements)
    if filename == "approval-rules.md":
        return render_template((template_dir / "approval-rules.md").read_text(encoding="utf-8"), replacements)
    if filename == "state-machine.md":
        return f"""# State Machine: {name}

| From | To | Condition |
| --- | --- | --- |
| `new` | `triaged` | Domain and lane selected. |
| `triaged` | `ready` | Required context is present. |
| `ready` | `running` | Agent starts execution. |
| `running` | `needs_approval` | Output crosses an approval gate. |
| `running` | `done` | Output validated and recorded. |
| `running` | `failed` | Execution cannot safely continue. |
"""
    if filename == "output-contract.md":
        return f"""# Output Contract: {name}

## Required Outputs

- Run log.
- Links to artifacts.
- State update.
- Next action or closure reason.

## Quality Bar

- Source links are preserved.
- Approval gates are followed.
- The output can be resumed by another agent or human.
"""
    return f"""# Runbook: {name}

## Before Running

- Confirm the request belongs to `{domain}`.
- Confirm the lane is `{lane}`.
- Load the workflow spec, context pack, and approval rules.

## During The Run

- Record material actions.
- Preserve evidence links.
- Stop at approval gates.

## After Running

- Write or update the run log.
- Store artifacts in the run folder.
- Update active work or project state.
"""


def workflow_examples_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Examples: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Store sanitized example inputs, expected outputs, and edge cases for this workflow.

## Example Format

```text
<short-case-name>.md
```

Each example should include input, expected routing, required context, approval behavior, and expected output.
"""


def workflow_runs_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Workflow Runs: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Use this folder for workflow-local run notes when they are useful. The audit record still belongs under `{domain}/06-runs-and-logs/runs/`.
"""


def create_workflow(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    name = validate_name(name, "workflow")
    result = create_domain(root, domain)
    workflow_root = domain_path(root, domain) / "03-workflows" / lane / name
    ensure_dir(workflow_root, result)
    ensure_dir(workflow_root / "examples", result)
    ensure_dir(workflow_root / "runs", result)
    write_file_once(workflow_root / "examples" / "README.md", workflow_examples_readme(domain, lane, name), result)
    write_file_once(workflow_root / "runs" / "README.md", workflow_runs_readme(domain, lane, name), result)
    for filename in WORKFLOW_FILES:
        write_file_once(workflow_root / filename, workflow_scaffold_content(domain, lane, name, filename), result)
    ensure_codex_config(workflow_root, "workflow_or_task", result, compact_context=True)
    append_control_signal(
        domain_path(root, domain),
        "Workflow Opportunities",
        f"`{name}`",
        "scaffolded",
        f"`03-workflows/{lane}/{name}/`",
        "Workflow opportunity now has a reusable spec scaffold.",
        result,
    )
    return result


def automation_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<automation_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
    }
    template_dir = template_source_dir() / "automation"
    if filename == "context-contract.yml":
        return (template_source_dir() / "context-contract" / "automation.yml").read_text(encoding="utf-8")
    if filename == "automation.md":
        return render_template((template_dir / "automation.md").read_text(encoding="utf-8"), replacements)
    if filename == "permissions.md":
        return (template_dir / "permissions.md").read_text(encoding="utf-8")
    if filename == "failure-modes.md":
        return (template_dir / "failure-modes.md").read_text(encoding="utf-8")
    if filename == "inputs.md":
        return f"""# Inputs: {name}

| Input | Required | Source | Validation |
| --- | --- | --- | --- |
| Trigger payload | yes |  |  |
| Domain | yes | `{domain}` | Must match this automation's domain. |
| Lane | yes | `{lane}` | Must match this automation's lane. |
"""
    if filename == "outputs.md":
        return f"""# Outputs: {name}

| Output | Destination | Required | Notes |
| --- | --- | --- | --- |
| Run log | `logs/` and domain runs folder | yes |  |
| State update | Control plane or project | yes |  |
| Artifact |  | no |  |
"""
    if filename == "tests.md":
        return f"""# Tests: {name}

## Dry Run

- Confirm the automation can classify input without writing externally.
- Confirm idempotency behavior.
- Confirm approval-required actions stop before write.

## Failure Tests

- Missing input.
- Duplicate input.
- Unavailable source system.
- Permission denied.
"""
    return f"""# Runbook: {name}

## Start

- Confirm trigger source.
- Confirm declared permissions.
- Run in dry-run mode before enabling writes.

## Operate

- Validate inputs.
- Execute only safe actions.
- Stop at approval gates.

## Recover

- Preserve the failing input reference.
- Write a failure log.
- Route to manual review or retry.
"""


def automation_logs_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Automation Logs: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Store automation-local logs, dry-run outputs, and failure snapshots here. Durable audit records still belong under `{domain}/06-runs-and-logs/runs/`.

## Log Format

```text
<timestamp>-<result>.md
```

Each log should include trigger reference, idempotency key, action level, validation result, and next action.
"""


def create_automation(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    name = validate_name(name, "automation")
    result = create_domain(root, domain)
    automation_root = domain_path(root, domain) / "04-automations" / lane / name
    ensure_dir(automation_root, result)
    ensure_dir(automation_root / "logs", result)
    write_file_once(automation_root / "logs" / "README.md", automation_logs_readme(domain, lane, name), result)
    for filename in AUTOMATION_FILES:
        write_file_once(automation_root / filename, automation_scaffold_content(domain, lane, name, filename), result)
    ensure_codex_config(automation_root, "automation", result, compact_context=True)
    append_control_signal(
        domain_path(root, domain),
        "Automation Status",
        f"`{name}`",
        "observe",
        f"`04-automations/{lane}/{name}/`",
        "Automation scaffold starts in observe mode until explicitly advanced.",
        result,
    )
    return result


def unique_run_log_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = runs_dir / run_id
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = runs_dir / f"{run_id}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def create_run_log(root: str | Path, domain: str, workflow_or_automation: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    workflow_or_automation = validate_name(workflow_or_automation, "workflow_or_automation")
    result = create_domain(root, domain)
    started_at = datetime.now(timezone.utc)
    run_id = dated_name(
        f"{started_at.strftime('%H%M%SZ')}-{domain}-{workflow_or_automation}",
        when=started_at,
        policy=load_artifact_naming_policy(root),
        scope="run_logs",
    )
    iso_timestamp = started_at.isoformat()
    template = template_source_dir() / "workflow" / "run-log.md"
    content = render_template(
        template.read_text(encoding="utf-8"),
        {
            "<run_id>": run_id,
            "<domain>": domain,
            "<name>": workflow_or_automation,
            "<codex_or_claude_or_automation>": "codex",
            "<timestamp>": iso_timestamp,
            "<done_waiting_failed_needs_approval>": "running",
        },
    )
    run_root = unique_run_log_dir(domain_path(root, domain) / "06-runs-and-logs" / "runs", run_id)
    ensure_dir(run_root, result)
    ensure_dir(run_root / "artifacts", result)
    write_file_once(run_root / "run-log.md", content, result)
    return result
