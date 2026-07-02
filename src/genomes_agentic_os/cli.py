"""Command-line interface for Genome's Agentic OS."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .cli_help import AosHelpFormatter, env_epilog

from .automation_ops import (
    AUTOMATION_MATURITY_LEVELS,
    attach_automation,
    check_automation,
    format_automation_check,
    set_automation_maturity,
)
from .automation_control import (
    automation_control_doctor,
    format_automation_control_result,
    list_automation_control,
    run_automation_control,
)
from .config_ops import LAYERS as CONFIG_LAYERS
from .config_ops import doctor_config, install_config, install_config_tree
from .customer import customer_init, customer_update, customer_validate, format_customer_result, scaffold_customer_brief
from .doc_config import build_doc_config_plan, doc_config_doctor, format_doc_config_result, init_doc_config
from .documentation_upkeep import build_documentation_upkeep_plan, format_documentation_upkeep_result
from .doctor import doctor, doctor_all, format_doctor_result
from .event_graph import (
    append_event,
    chain_doctor,
    chain_list,
    emit_run_close_event,
    format_event_graph_result,
    list_events,
    process_due,
    replay_event,
    summarize_events,
    test_chain_rule,
)
from .hook_ops import hook_doctor, hook_sync
from .losmon import format_losmon_result, losmon_validate
from .lifecycle import WORK_LIFECYCLE_STATES, cleanup_terminal_worktrees, create_project_work_item, infer_complete_work_items, repair_project_work_item
from .lifecycle import finalize_lingering_work_items, sync_active_container
from .migrations import format_migration_result, migrate_apply, migrate_plan
from .notion_sync import (
    apply_active_work_sync,
    apply_bootstrap_plan,
    apply_sync_plan,
    build_active_work_sync_plan,
    build_bootstrap_plan,
    build_sync_plan,
    format_sync_result,
)
from .notion_org import doctor_notion_org, format_notion_org_result
from .plans import capture_plan, format_plan_result
from .ps_ops import format_ps_result, ps_snapshot
from .room_profile import format_profile_result, install_profile_os, load_os_profile, write_profile_template
from .routing import build_context, context_from_here, detect_from_cwd, format_packet, project_records, route_request
from .runtime_ops import (
    apply_runtime_tracking,
    build_runtime_tracking_plan,
    format_runtime_result,
    heartbeat_list,
    heartbeat_run,
    integration_doctor,
    integration_list,
    integration_setup,
    runtime_doctor,
    runtime_init,
    runtime_run_next,
    schedule_create,
    schedule_run_due,
)
from .self_improvement import (
    approve_self_improvement_proposal,
    format_self_improvement_result,
    list_self_improvement_proposals,
    process_self_improvement_actions,
    promote_self_improvement_proposal,
    reconcile_self_improvement_queue,
    reject_self_improvement_proposal,
    run_self_improvement,
    self_improvement_status,
    show_self_improvement_proposal,
)
from .supervisor import format_supervise_result, supervise_tick
from .scaffold import (
    DEFAULT_PROJECTS_SOURCE,
    create_automation,
    create_domain,
    create_instance_program,
    create_program,
    create_project,
    create_project_worktree,
    create_run_log,
    create_workflow,
    install_docs,
    init_os,
    link_project_remote,
    link_project_source,
    onboard_project,
    register_project_worktree,
)
from .hosts import upsert_host, list_hosts
from .remote_ops import sync_project_remote
from .remote_mounts import exec_remote, mount_remote, unmount_remote
from .source_watch import (
    create_watch_source,
    doctor_connected_system,
    doctor_watch_source,
    format_source_watch_result,
    list_connected_systems,
    list_watch_sources,
    parse_external_refs,
    poll_watch_source,
    run_due_watch_sources,
)
from .thread_closeout import (
    DEFAULT_STALE_DAYS,
    WORK_LEVELS,
    close_thread,
    format_thread_closeout_result,
    stale_finalize_threads,
)
from .metrics_ops import format_metrics_result, metrics_refresh
from .update_ops import (
    activate_license,
    backup_push,
    backup_run,
    fleet_push,
    format_update_result,
    phone_home_payload,
    update_apply,
    update_check,
    update_plan,
    update_pull,
    update_register,
    update_rollback,
    update_status,
)
from .capability_registry import (
    REGISTRY_FILES,
    inventory_markdown,
    load_registry,
    registry_payloads,
)
from .validate import StrictFinding, validate_root, validate_schemas_strict
from .workflow_ops import check_workflow, close_run_log, format_findings


DEFAULT_ROOT = "~/agentic_os"


def handle_capability_list(args: argparse.Namespace) -> int:
    """List capabilities from installed registry files, optionally filtered by type."""
    root = Path(args.root).expanduser()
    cap_type = getattr(args, "type", None)
    payloads = registry_payloads()
    if cap_type:
        if cap_type not in payloads:
            print(f"Unknown capability type '{cap_type}'. Known types: {', '.join(sorted(payloads))}")
            return 1
        types_to_show = {cap_type: payloads[cap_type]}
    else:
        types_to_show = payloads
    for name, payload in types_to_show.items():
        collection_key = next(iter(payload))
        entries = payload[collection_key]
        print(f"\n## {name} ({len(entries)})")
        for entry in entries:
            entry_id = entry.get("id") or entry.get("command") or "(unknown)"
            description = entry.get("description", "")
            print(f"  {entry_id}" + (f" — {description}" if description else ""))
    installed_path = root / REGISTRY_FILES.get("capabilities", "harness/registries/capabilities.yml")
    if installed_path.exists():
        installed = load_registry(installed_path, "capabilities")
        if installed:
            print(f"\n## installed capabilities ({len(installed)})")
            for cap in installed:
                ref = cap.get("ref", "")
                cap_type_label = cap.get("type", "")
                print(f"  {ref}" + (f" [{cap_type_label}]" if cap_type_label else ""))
    return 0


def handle_capability_inventory(args: argparse.Namespace) -> int:
    """Show or regenerate INVENTORY.md from installed registry state."""
    root = Path(args.root).expanduser()
    content = inventory_markdown()
    if getattr(args, "regenerate", False):
        from .scaffold import harness_path, write_file_once
        from .scaffold import ScaffoldResult

        result = ScaffoldResult()
        write_file_once(harness_path(root) / "INVENTORY.md", content, result)
        for msg in result.messages():
            print(msg)
        if not result.messages():
            print("INVENTORY.md already up to date")
    else:
        inventory_path = root / "harness" / "INVENTORY.md"
        if inventory_path.exists():
            print(inventory_path.read_text(encoding="utf-8"))
        else:
            print(content)
    return 0


def build_parser(prog: str = "agentic-os") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Scaffold, validate, and operate an Agentic OS root.\n\n"
            "Run 'agentic-os <command> --help' for per-command options."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (used as --root default when set). Default: ~/agentic_os."),
            ],
            config_files=[
                ("~/agentic_os/harness/registries/", "Central registries (automations, skills, commands, etc.)."),
                ("~/agentic_os/harness/shared_factory/", "Shared factory outputs (metrics, run logs, etc.)."),
                ("~/agentic_os/config/hosts.yml", "SSH host registry read by project remote commands."),
            ],
            examples=[
                ("agentic-os init", "Create the base OS tree at ~/agentic_os."),
                ("agentic-os doctor", "Run OS health checks."),
                ("agentic-os validate", "Validate OS root structure."),
                ("agentic-os ps --active", "Show active work dashboard."),
                ("agentic-os self-improvement run --apply", "Run and persist a self-improvement review."),
                ("agentic-os runtime supervise --apply", "Run one full supervisor tick."),
                ("agentic-os config install-tree --apply", "Install config.toml across the OS tree."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_thread_closeout_args(closeout_parser: argparse.ArgumentParser, mode: str) -> None:
        closeout_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
        closeout_parser.add_argument("--domain", help="Domain that owns the work item.")
        closeout_parser.add_argument("--project", help="Project that owns the work item.")
        closeout_parser.add_argument("--work-item", help="Work item id, slug, title, or ticket.")
        closeout_parser.add_argument("--thread-id", help="Stable closeout id. Defaults to a timestamped id.")
        closeout_parser.add_argument("--work-level", choices=WORK_LEVELS, help="Closeout work level.")
        closeout_parser.add_argument("--summary", help="One-line closeout result.")
        closeout_parser.add_argument("--next-action", help="Concrete next action, or None.")
        closeout_parser.add_argument("--validation", action="append", default=[], help="Validation receipt to record.")
        closeout_parser.add_argument("--artifact", action="append", default=[], help="Artifact path or identifier to record.")
        closeout_parser.add_argument("--receipt", action="append", default=[], help="Command, PR, ticket, or external receipt.")
        closeout_parser.add_argument("--memory-receipt", action="append", default=[], help="Durable memory write or skip receipt.")
        closeout_parser.add_argument("--notion-url", help="Verified Genome's Notion projection URL to record.")
        closeout_parser.add_argument("--notion-warning", help="Non-blocking Notion projection warning to record.")
        closeout_parser.add_argument(
            "--verified-notion-workspace",
            help="Workspace verified for a supplied Notion projection. Must be Genome's Notion.",
        )
        closeout_parser.add_argument("--skip-notion", action="store_true", help="Record Notion projection as skipped.")
        closeout_parser.add_argument(
            "--allow-blocked-archive",
            action="store_true",
            help="Allow archive mode even when --next-action is unresolved.",
        )
        closeout_parser.add_argument("--request", help="Optional request text used for work-item disambiguation.")
        closeout_parser.add_argument("--cwd", help="Current working directory for context detection. Defaults to process cwd.")
        closeout_parser.set_defaults(handler=handle_thread_closeout, closeout_mode=mode)

    def add_stale_finalize_args(stale_parser: argparse.ArgumentParser) -> None:
        stale_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
        stale_parser.add_argument("--domain", help="Limit stale sweep to a domain.")
        stale_parser.add_argument("--project", help="Limit stale sweep to a project.")
        stale_parser.add_argument(
            "--older-than-days",
            type=int,
            default=DEFAULT_STALE_DAYS,
            help=f"Finalize candidates untouched for more than this many days (default: {DEFAULT_STALE_DAYS}).",
        )
        stale_mode = stale_parser.add_mutually_exclusive_group()
        stale_mode.add_argument("--dry-run", action="store_true", default=True, help="List candidates without writing.")
        stale_mode.add_argument("--apply", action="store_true", help="Write conservative status-only closeouts.")
        stale_parser.set_defaults(handler=handle_thread_stale_finalize)

    init_parser = subparsers.add_parser("init", help="Create the base installed OS tree.")
    init_parser.add_argument("--target", default=DEFAULT_ROOT, help="Installed OS target path.")
    init_parser.add_argument("--profile", help="Room-first OS profile YAML.")
    init_parser.add_argument(
        "--projects-source",
        default=DEFAULT_PROJECTS_SOURCE,
        help="Deprecated compatibility flag; project repo links now live under domain 02-projects entries.",
    )
    init_parser.add_argument(
        "--include-legacy-agent",
        action="store_true",
        help="Also create AGENT.md compatibility adapters for harnesses that require that exact filename.",
    )
    init_parser.set_defaults(handler=handle_init)

    domain_parser = subparsers.add_parser("domain", help="Manage domains.")
    domain_subparsers = domain_parser.add_subparsers(dest="domain_command", required=True)
    domain_create = domain_subparsers.add_parser("create", help="Create a domain scaffold.")
    domain_create.add_argument("name")
    domain_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    domain_create.add_argument(
        "--include-legacy-agent",
        action="store_true",
        help="Also create AGENT.md compatibility adapters for harnesses that require that exact filename.",
    )
    domain_create.set_defaults(handler=handle_domain_create)

    profile_parser = subparsers.add_parser("profile", help="Manage room-first OS profiles.")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_create = profile_subparsers.add_parser("create", help="Create an editable profile template.")
    profile_create.add_argument("--target", required=True)
    profile_create.set_defaults(handler=handle_profile_create)
    profile_validate = profile_subparsers.add_parser("validate", help="Validate a room-first profile.")
    profile_validate.add_argument("profile")
    profile_validate.set_defaults(handler=handle_profile_validate)

    room_parser = subparsers.add_parser("room", help="Manage rooms.")
    room_subparsers = room_parser.add_subparsers(dest="room_command", required=True)
    room_create = room_subparsers.add_parser("create", help="Create a room scaffold.")
    room_create.add_argument("room_slug")
    room_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    room_create.set_defaults(handler=handle_room_create)
    room_update = room_subparsers.add_parser("update", help="Update a room from a profile.")
    room_update.add_argument("room_slug")
    room_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    room_update.add_argument("--from-profile", required=True)
    room_update.set_defaults(handler=handle_room_update)

    project_parser = subparsers.add_parser(
        "project",
        help="Manage projects.",
        description=(
            "Create and manage OS projects, worktrees, remote sources, and lifecycle work items. "
            "Projects live under <domain>/<project>/ inside the OS root."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("<domain>/<project>/project.yml", "Project metadata and remote source declarations."),
                ("<domain>/<project>/worktrees/", "Registered worktree links."),
            ],
            examples=[
                ("agentic-os project create acme myproj --repo ~/repos/myproj", "Create a project scaffold."),
                ("agentic-os project work-item create acme myproj --title 'Fix bug' --summary 'Fix the thing'", "Create a work item."),
                ("agentic-os project sync-remote acme myproj", "Sync remote SSH sources."),
                ("agentic-os project worktree cleanup-closed --apply", "Close terminal worktree entries."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_create = project_subparsers.add_parser("create", help="Create a project scaffold.")
    project_create.add_argument("domain")
    project_create.add_argument("project")
    project_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_create.add_argument("--repo", help="Repository path or URL.")
    project_create.add_argument("--notion", help="Notion page, database, or URL.")
    project_create.add_argument("--jira", help="Jira project, issue, or URL.")
    project_create.add_argument("--status", default="active", choices=("active", "waiting", "blocked", "done"))
    project_create.add_argument("--lane", help="Primary operating lane for this project.")
    project_create.add_argument("--remote-host", help="Remote SSH host alias for the primary remote source.")
    project_create.add_argument("--remote-path", help="Absolute path on the remote host.")
    project_create.add_argument("--remote-name", help="Name for the remote (defaults to project name).")
    project_create.add_argument("--remote-kind", default="git", choices=("git", "folder"), help="Remote source kind (default: git).")
    project_create.add_argument("--authority", default="remote", choices=("remote", "local"), help="Which side owns truth (default: remote).")
    project_create.set_defaults(handler=handle_project_create)
    project_link_source = project_subparsers.add_parser(
        "link-source",
        aliases=["src"],
        help="Create or repair a project-local src symlink to a local repository.",
    )
    project_link_source.add_argument("domain")
    project_link_source.add_argument("project")
    project_link_source.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_link_source.add_argument("--repo", help="Local repository path. Defaults to project.yml sources.repo.")
    project_link_source.add_argument("--force", action="store_true", help="Replace an existing src symlink that points elsewhere.")
    project_link_source.set_defaults(handler=handle_project_link_source)
    project_onboard = project_subparsers.add_parser("onboard", help="Create or repair the project-local agent/config surface.")
    project_onboard.add_argument("domain")
    project_onboard.add_argument("project")
    project_onboard.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_onboard.set_defaults(handler=handle_project_onboard)
    project_link_remote = project_subparsers.add_parser(
        "link-remote",
        help="Attach a remote SSH source to an existing project.",
    )
    project_link_remote.add_argument("domain")
    project_link_remote.add_argument("project")
    project_link_remote.add_argument("--host", required=True, help="Remote SSH host alias (key in config/hosts.yml).")
    project_link_remote.add_argument("--path", required=True, help="Absolute path on the remote host.")
    project_link_remote.add_argument("--name", help="Name for the remote (defaults to project name).")
    project_link_remote.add_argument("--kind", default="git", choices=("git", "folder"), help="Remote source kind (default: git).")
    project_link_remote.add_argument("--authority", default="remote", choices=("remote", "local"), help="Which side owns truth (default: remote).")
    project_link_remote.add_argument("--force", action="store_true", help="Replace an existing remote of the same name.")
    project_link_remote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_link_remote.set_defaults(handler=handle_project_link_remote)
    project_worktree = project_subparsers.add_parser("worktree", help="Manage visible project worktree links.")
    project_worktree_subparsers = project_worktree.add_subparsers(dest="project_worktree_command", required=True)
    project_worktree_add = project_worktree_subparsers.add_parser("add", help="Register a project-visible worktree.")
    project_worktree_add.add_argument("domain")
    project_worktree_add.add_argument("project")
    project_worktree_add.add_argument("name")
    project_worktree_add.add_argument(
        "--path",
        required=True,
        help="Existing worktree directory; paths inside the project worktrees directory register in place, others get a symlink.",
    )
    project_worktree_add.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_worktree_add.add_argument("--force", action="store_true", help="Replace an existing worktree symlink that points elsewhere.")
    project_worktree_add.set_defaults(handler=handle_project_worktree_add)
    project_worktree_create = project_worktree_subparsers.add_parser(
        "create", help="Create an in-place git worktree under the project worktrees directory and register it."
    )
    project_worktree_create.add_argument("domain")
    project_worktree_create.add_argument("project")
    project_worktree_create.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Worktree directory name; defaults to the branch name with slashes replaced by hyphens.",
    )
    project_worktree_create.add_argument("--repo", required=True, help="Existing local git repository to create the worktree from.")
    project_worktree_create.add_argument("--branch", required=True, help="Branch to check out; created from HEAD when it does not exist.")
    project_worktree_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_worktree_create.set_defaults(handler=handle_project_worktree_create)
    project_worktree_cleanup_closed = project_worktree_subparsers.add_parser(
        "cleanup-closed",
        help="Close registered worktrees whose cached Jira status or PR state is terminal.",
    )
    project_worktree_cleanup_closed.add_argument("--domain", help="Limit cleanup to a domain.")
    project_worktree_cleanup_closed.add_argument("--project", help="Limit cleanup to a project.")
    cleanup_mode = project_worktree_cleanup_closed.add_mutually_exclusive_group()
    cleanup_mode.add_argument("--dry-run", action="store_true", default=True, help="Show cleanup candidates without writing.")
    cleanup_mode.add_argument("--apply", action="store_true", help="Move matching registry entries to worktrees/closed.yml.")
    project_worktree_cleanup_closed.add_argument(
        "--remove-files",
        action="store_true",
        help="Also remove in-project worktree directories after closing their registry entries; merged PR dirt is ignored unless REOPEN.md is present.",
    )
    project_worktree_cleanup_closed.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_worktree_cleanup_closed.set_defaults(handler=handle_project_worktree_cleanup_closed)
    project_work_item = project_subparsers.add_parser("work-item", help="Manage project lifecycle work items.")
    project_work_item_subparsers = project_work_item.add_subparsers(dest="project_work_item_command", required=True)
    project_work_item_create = project_work_item_subparsers.add_parser("create", help="Create a project lifecycle work item.")
    project_work_item_create.add_argument("domain")
    project_work_item_create.add_argument("project")
    project_work_item_create.add_argument("--title", required=True)
    project_work_item_create.add_argument("--summary", required=True)
    project_work_item_create.add_argument("--work-id", help="Optional work item slug. Defaults to a slug from the title.")
    project_work_item_create.add_argument("--status", default="captured", choices=WORK_LIFECYCLE_STATES)
    project_work_item_create.add_argument(
        "--format",
        choices=("markdown", "packet"),
        help="Override the default shape. Captured/triaged ideas default to markdown; active and complete states use packet folders.",
    )
    project_work_item_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_work_item_create.set_defaults(handler=handle_project_work_item_create)
    project_work_item_repair = project_work_item_subparsers.add_parser(
        "repair", help="Backfill missing lifecycle packet files and folders without overwriting local edits."
    )
    project_work_item_repair.add_argument("domain")
    project_work_item_repair.add_argument("project")
    project_work_item_repair.add_argument("--work-item", help="Specific work item id, slug, title, or ticket to repair.")
    project_work_item_repair.add_argument("--all", action="store_true", help="Repair every folder-format project work item.")
    project_work_item_repair.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_work_item_repair.set_defaults(handler=handle_project_work_item_repair)
    project_work_item_sync_active = project_work_item_subparsers.add_parser(
        "sync-active",
        help="Rebuild the root global active-work symlink container from work items, worktrees, and automations.",
    )
    project_work_item_sync_active.add_argument("--domain", help="Limit active work-item/worktree links to a domain.")
    project_work_item_sync_active.add_argument("--project", help="Limit active work-item/worktree links to a project.")
    project_work_item_sync_active.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_work_item_sync_active.set_defaults(handler=handle_project_work_item_sync_active)
    project_work_item_finalize_lingering = project_work_item_subparsers.add_parser(
        "finalize-lingering",
        help="Move terminal-status packets out of active lanes, update indexes, and refresh the global active container.",
    )
    project_work_item_finalize_lingering.add_argument("--domain", help="Limit cleanup to a domain.")
    project_work_item_finalize_lingering.add_argument("--project", help="Limit cleanup to a project.")
    lingering_mode = project_work_item_finalize_lingering.add_mutually_exclusive_group()
    lingering_mode.add_argument("--dry-run", action="store_true", default=True, help="Show stale terminal packets without writing.")
    lingering_mode.add_argument("--apply", action="store_true", help="Move stale terminal packets and refresh active links.")
    project_work_item_finalize_lingering.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_work_item_finalize_lingering.set_defaults(handler=handle_project_work_item_finalize_lingering)
    project_work_item_infer_complete = project_work_item_subparsers.add_parser(
        "infer-complete",
        help="Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity.",
    )
    project_work_item_infer_complete.add_argument("--domain", help="Limit inference to a domain.")
    project_work_item_infer_complete.add_argument("--project", help="Limit inference to a project.")
    infer_mode = project_work_item_infer_complete.add_mutually_exclusive_group()
    infer_mode.add_argument("--dry-run", action="store_true", default=True, help="Report completion decisions without writing.")
    infer_mode.add_argument("--apply", action="store_true", help="Finalize high-confidence completed packets and refresh active links.")
    project_work_item_infer_complete.add_argument(
        "--older-than-days",
        type=int,
        default=3,
        help="Conversation quiet-window threshold before automatic completion.",
    )
    project_work_item_infer_complete.add_argument(
        "--min-confidence",
        choices=("high", "medium", "low"),
        default="high",
        help="Minimum confidence accepted in apply mode.",
    )
    project_work_item_infer_complete.add_argument(
        "--include-blocked",
        action="store_true",
        help="Allow blocked items to be completed when all other high-confidence gates pass.",
    )
    project_work_item_infer_complete.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_work_item_infer_complete.set_defaults(handler=handle_project_work_item_infer_complete)

    project_sync_remote = project_subparsers.add_parser(
        "sync-remote",
        help="Refresh manifest.yml for declared remote SSH sources.",
    )
    project_sync_remote.add_argument("domain")
    project_sync_remote.add_argument("project")
    project_sync_remote.add_argument("--name", help="Sync only the remote with this name (default: all).")
    project_sync_remote.add_argument("--timeout", type=int, default=20, help="SSH command timeout in seconds (default: 20).")
    project_sync_remote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_sync_remote.set_defaults(handler=handle_project_sync_remote)

    project_mount_remote = project_subparsers.add_parser(
        "mount-remote",
        help="Plan or execute an SSHFS mount for a declared remote source (dry-run by default).",
    )
    project_mount_remote.add_argument("domain")
    project_mount_remote.add_argument("project")
    project_mount_remote.add_argument("--name", help="Name of the remote to mount (default: first with a mount block).")
    project_mount_remote.add_argument("--namespace", help="Override the local mount namespace path.")
    project_mount_remote.add_argument("--timeout", type=int, default=20, help="SSHFS command timeout in seconds (default: 20).")
    project_mount_remote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _mount_mode = project_mount_remote.add_mutually_exclusive_group()
    _mount_mode.add_argument("--dry-run", action="store_true", default=True, help="Print the planned SSHFS command without mounting (default).")
    _mount_mode.add_argument("--apply", action="store_true", help="Execute the SSHFS mount if sshfs is available and path is in an approved namespace.")
    project_mount_remote.set_defaults(handler=handle_project_mount_remote)

    project_unmount_remote = project_subparsers.add_parser(
        "unmount-remote",
        help="Plan or execute an SSHFS unmount for a declared remote source (dry-run by default).",
    )
    project_unmount_remote.add_argument("domain")
    project_unmount_remote.add_argument("project")
    project_unmount_remote.add_argument("--name", help="Name of the remote to unmount (default: all with a mount block).")
    project_unmount_remote.add_argument("--timeout", type=int, default=20, help="Unmount command timeout in seconds (default: 20).")
    project_unmount_remote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    _unmount_mode = project_unmount_remote.add_mutually_exclusive_group()
    _unmount_mode.add_argument("--dry-run", action="store_true", default=True, help="Print the planned unmount command without unmounting (default).")
    _unmount_mode.add_argument("--apply", action="store_true", help="Execute the platform-appropriate unmount command.")
    project_unmount_remote.set_defaults(handler=handle_project_unmount_remote)

    project_exec = project_subparsers.add_parser(
        "exec",
        help="Run a command on the remote host for a remote-authoritative project.",
    )
    project_exec.add_argument("domain")
    project_exec.add_argument("project")
    project_exec.add_argument("--name", help="Name of the remote to use (default: first remote-authoritative).")
    project_exec.add_argument("--timeout", type=int, default=60, help="SSH command timeout in seconds (default: 60).")
    project_exec.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    project_exec.add_argument("cmd", nargs="*", metavar="command", help="Command to run remotely. Use -- to separate from options: exec acme proj -- git status")
    project_exec.set_defaults(handler=handle_project_exec)

    workflow_parser = subparsers.add_parser("workflow", help="Manage workflows.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_create = workflow_subparsers.add_parser("create", help="Create a workflow scaffold.")
    workflow_create.add_argument("domain")
    workflow_create.add_argument("lane")
    workflow_create.add_argument("name")
    workflow_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    workflow_create.set_defaults(handler=handle_workflow_create)
    workflow_check = workflow_subparsers.add_parser("check", help="Check workflow readiness.")
    workflow_check.add_argument("domain")
    workflow_check.add_argument("lane")
    workflow_check.add_argument("workflow")
    workflow_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    workflow_check.set_defaults(handler=handle_workflow_check)

    program_parser = subparsers.add_parser("program", help="Manage shared OS programs.")
    program_subparsers = program_parser.add_subparsers(dest="program_command", required=True)
    program_create = program_subparsers.add_parser("create", help="Create a shared OSProgram scaffold.")
    program_create.add_argument("name")
    program_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    program_create.set_defaults(handler=handle_program_create)

    instance_program_parser = subparsers.add_parser("instance-program", help="Manage domain-local OS programs.")
    instance_program_subparsers = instance_program_parser.add_subparsers(dest="instance_program_command", required=True)
    instance_program_create = instance_program_subparsers.add_parser(
        "create",
        help="Create a domain-local InstanceOSProgram scaffold.",
    )
    instance_program_create.add_argument("domain")
    instance_program_create.add_argument("name")
    instance_program_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    instance_program_create.set_defaults(handler=handle_instance_program_create)

    host_parser = subparsers.add_parser("host", help="Manage the SSH host registry (config/hosts.yml).")
    host_subparsers = host_parser.add_subparsers(dest="host_command", required=True)
    host_add = host_subparsers.add_parser("add", help="Add or update a host alias in the registry.")
    host_add.add_argument("alias", help="Host alias (identifier used in project remotes).")
    host_add.add_argument("--ssh-alias", help="SSH alias that resolves via ~/.ssh/config.")
    host_add.add_argument("--user", help="Remote username (informational).")
    host_add.add_argument("--description", help="Human-readable description of this host.")
    host_add.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_add.set_defaults(handler=handle_host_add)
    host_list = host_subparsers.add_parser("list", help="List registered hosts.")
    host_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_list.set_defaults(handler=handle_host_list)

    automation_parser = subparsers.add_parser("automation", help="Manage automations.")
    automation_subparsers = automation_parser.add_subparsers(dest="automation_command", required=True)
    automation_create = automation_subparsers.add_parser("create", help="Create an automation scaffold.")
    automation_create.add_argument("domain")
    automation_create.add_argument("lane")
    automation_create.add_argument("name")
    automation_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_create.set_defaults(handler=handle_automation_create)
    automation_check = automation_subparsers.add_parser("check", help="Check automation maturity readiness.")
    automation_check.add_argument("domain")
    automation_check.add_argument("lane")
    automation_check.add_argument("automation")
    automation_check.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_check.set_defaults(handler=handle_automation_check)
    automation_attach = automation_subparsers.add_parser("attach", help="Attach an automation to a project.")
    automation_attach.add_argument("domain")
    automation_attach.add_argument("lane")
    automation_attach.add_argument("automation")
    automation_attach.add_argument("--project", required=True)
    automation_attach.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_attach.set_defaults(handler=handle_automation_attach)
    automation_maturity = automation_subparsers.add_parser(
        "set-maturity",
        help="Set the automation maturity level after evidence checks.",
    )
    automation_maturity.add_argument("domain")
    automation_maturity.add_argument("lane")
    automation_maturity.add_argument("automation")
    automation_maturity.add_argument("level", choices=AUTOMATION_MATURITY_LEVELS)
    automation_maturity.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_maturity.set_defaults(handler=handle_automation_set_maturity)

    automation_control_parser = subparsers.add_parser(
        "automation-control",
        help="Gate expensive automations behind cheap source-readiness probes.",
    )
    automation_control_subparsers = automation_control_parser.add_subparsers(
        dest="automation_control_command",
        required=True,
    )
    automation_control_list = automation_control_subparsers.add_parser("list", help="List managed automation gates.")
    automation_control_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_list.set_defaults(handler=handle_automation_control_list)
    automation_control_doctor_parser = automation_control_subparsers.add_parser(
        "doctor",
        help="Validate managed automation-control config.",
    )
    automation_control_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_doctor_parser.set_defaults(handler=handle_automation_control_doctor)
    automation_control_run = automation_control_subparsers.add_parser(
        "run",
        help="Evaluate configured automation gates and enqueue ready work.",
    )
    automation_control_run.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    automation_control_run_mode = automation_control_run.add_mutually_exclusive_group()
    automation_control_run_mode.add_argument("--dry-run", action="store_true", default=True)
    automation_control_run_mode.add_argument("--apply", action="store_true")
    automation_control_run.set_defaults(handler=handle_automation_control_run)

    ps_parser = subparsers.add_parser(
        "ps",
        help="Show Agentic OS work running right now; use --active for the broader dashboard.",
        description=(
            "Show the current Agentic OS work snapshot. "
            "Default (no flags): in-flight async runs and recently started items. "
            "--active: adds queued work, enabled automations/schedules/watchers, and stale thread candidates. "
            "--all: includes disabled and terminal registry/queue rows."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/run-queue.yml", "Run-queue state read for active items."),
                ("harness/registries/runtime-registry.yml", "Runtime registry (schedules, heartbeats, integrations)."),
                ("harness/registries/automation-run-tracking.yml", "Automation run tracking state."),
            ],
            examples=[
                ("agentic-os ps", "Show in-flight runs only."),
                ("agentic-os ps --active", "Show full active work dashboard."),
                ("agentic-os ps --all --json", "Emit all rows as JSON."),
                ("agentic-os ps --limit 0", "Show all rows with no row cap."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    ps_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    ps_parser.add_argument("--json", action="store_true", help="Emit the snapshot as JSON.")
    ps_mode = ps_parser.add_mutually_exclusive_group()
    ps_mode.add_argument(
        "--active",
        action="store_true",
        help="Show queued work, enabled automations/schedules/watchers, active workflows, and stale thread candidates.",
    )
    ps_mode.add_argument("--all", action="store_true", help="Include disabled and terminal registry/queue rows.")
    ps_parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize table output (default: auto).",
    )
    ps_parser.add_argument(
        "--limit",
        type=int,
        default=120,
        help="Maximum rows to print; use 0 for no limit.",
    )
    ps_parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Thread stale-candidate threshold in days (default: {DEFAULT_STALE_DAYS}).",
    )
    ps_parser.set_defaults(handler=handle_ps)

    run_log_parser = subparsers.add_parser("run-log", help="Manage run logs.")
    run_log_subparsers = run_log_parser.add_subparsers(dest="run_log_command", required=True)
    run_log_create = run_log_subparsers.add_parser("create", help="Create a timestamped run log.")
    run_log_create.add_argument("domain")
    run_log_create.add_argument("workflow_or_automation")
    run_log_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_create.set_defaults(handler=handle_run_log_create)
    run_log_close = run_log_subparsers.add_parser("close", help="Close a run log with audit evidence.")
    run_log_close.add_argument("domain")
    run_log_close.add_argument("run_id")
    run_log_close.add_argument("--status", required=True, choices=("done", "waiting", "failed", "needs_approval"))
    run_log_close.add_argument("--summary", default="")
    run_log_close.add_argument("--validation", action="append", default=[])
    run_log_close.add_argument("--artifact", action="append", default=[])
    run_log_close.add_argument("--approval", action="append", default=[])
    run_log_close.add_argument("--next-action", default="")
    run_log_close.add_argument("--owner", default="OS Owner")
    run_log_close.add_argument("--learning", default="")
    run_log_close.add_argument("--project")
    run_log_close.add_argument("--emit-events", action="store_true")
    run_log_close.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    run_log_close.set_defaults(handler=handle_run_log_close)

    thread_parser = subparsers.add_parser("thread", help="Manage thread lifecycle closeouts.")
    thread_subparsers = thread_parser.add_subparsers(dest="thread_command", required=True)
    thread_end = thread_subparsers.add_parser("end", help="Finalize the current thread without archiving.")
    add_thread_closeout_args(thread_end, "artifact-closeout")
    thread_finalize = thread_subparsers.add_parser("finalize", help="Alias for thread end.")
    add_thread_closeout_args(thread_finalize, "artifact-closeout")
    thread_cleanup = thread_subparsers.add_parser("cleanup", help="Finalize and classify generated dirt without deletion.")
    add_thread_closeout_args(thread_cleanup, "cleanup")
    thread_archive = thread_subparsers.add_parser("archive", help="Finalize and archive when no unresolved next action remains.")
    add_thread_closeout_args(thread_archive, "archive")
    thread_stale = thread_subparsers.add_parser("stale-finalize", help="Dry-run or apply stale thread finalization.")
    add_stale_finalize_args(thread_stale)

    end_chat_parser = subparsers.add_parser("end-chat", help="Alias for agentic-os thread end.")
    add_thread_closeout_args(end_chat_parser, "artifact-closeout")
    finalize_parser = subparsers.add_parser("finalize", help="Alias for agentic-os thread finalize.")
    add_thread_closeout_args(finalize_parser, "artifact-closeout")
    cleanup_thread_parser = subparsers.add_parser("cleanup-thread", help="Alias for agentic-os thread cleanup.")
    add_thread_closeout_args(cleanup_thread_parser, "cleanup")
    archive_thread_parser = subparsers.add_parser("archive", help="Alias for agentic-os thread archive.")
    add_thread_closeout_args(archive_thread_parser, "archive")

    route_parser = subparsers.add_parser("route", help="Route a request to a domain, project, or workflow.")
    route_parser.add_argument("request")
    route_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    route_parser.set_defaults(handler=handle_route)

    context_parser = subparsers.add_parser("context", help="Build deterministic context packets.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build = context_subparsers.add_parser("build", help="Build a context packet.")
    context_build.add_argument("--domain")
    context_build.add_argument("--project")
    context_build.add_argument("--work-item")
    context_build.add_argument("--workflow")
    context_build.add_argument("--lane")
    context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    context_build.set_defaults(handler=handle_context_build)

    here_parser = subparsers.add_parser("here", help="Route from the current working directory.")
    here_subparsers = here_parser.add_subparsers(dest="here_command", required=True)
    here_route = here_subparsers.add_parser("route", help="Route a request from the current directory.")
    here_route.add_argument("request")
    here_route.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_route.set_defaults(handler=handle_here_route)
    here_context = here_subparsers.add_parser("context", help="Build context from the current directory.")
    here_context_subparsers = here_context.add_subparsers(dest="here_context_command", required=True)
    here_context_build = here_context_subparsers.add_parser("build", help="Build context from the current directory.")
    here_context_build.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    here_context_build.set_defaults(handler=handle_here_context_build)

    customer_parser = subparsers.add_parser("customer", help="Manage customer Agentic OS installs.")
    customer_subparsers = customer_parser.add_subparsers(dest="customer_command", required=True)
    customer_init_parser = customer_subparsers.add_parser("init", help="Create a customer OS from a profile.")
    customer_init_parser.add_argument("customer_slug")
    customer_init_parser.add_argument("--profile", required=True)
    customer_init_parser.add_argument("--target", required=True)
    customer_init_parser.set_defaults(handler=handle_customer_init)
    customer_update_parser = customer_subparsers.add_parser("update", help="Add missing customer OS assets.")
    customer_update_parser.add_argument("customer_slug")
    customer_update_parser.add_argument("--root", required=True)
    customer_update_parser.set_defaults(handler=handle_customer_update)
    customer_validate_parser = customer_subparsers.add_parser("validate", help="Validate a customer OS root.")
    customer_validate_parser.add_argument("--root", required=True)
    customer_validate_parser.set_defaults(handler=handle_customer_validate)
    customer_brief_parser = customer_subparsers.add_parser(
        "brief",
        help="Scaffold a client-automation-brief instance into a customer install domain.",
    )
    customer_brief_parser.add_argument("--root", required=True, help="Customer OS root path.")
    customer_brief_parser.add_argument("--domain", required=True, help="Domain (room) to place the brief in.")
    customer_brief_parser.add_argument("--name", required=True, help="Brief slug (snake_case). Becomes <name>-brief.md in domain/01-intake/.")
    customer_brief_parser.set_defaults(handler=handle_customer_brief)

    update_parser = subparsers.add_parser("update", help="Check, plan, apply, and report installed OS updates.")
    update_subparsers = update_parser.add_subparsers(dest="update_command", required=True)
    update_check_parser = update_subparsers.add_parser("check", help="Check for available updates without mutating files.")
    update_check_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_check_parser.add_argument("--manifest", help="Update manifest YAML or JSON file.")
    update_check_parser.set_defaults(handler=handle_update_check)
    update_register_parser = update_subparsers.add_parser(
        "register",
        help="Generate local update/backup SSH keys and write an update grant.",
    )
    update_register_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_register_parser.set_defaults(handler=handle_update_register)
    update_pull_parser = update_subparsers.add_parser("pull", help="Plan or record an operator-pushed update pull.")
    update_pull_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_pull_mode = update_pull_parser.add_mutually_exclusive_group()
    update_pull_mode.add_argument("--dry-run", action="store_true", default=True)
    update_pull_mode.add_argument("--apply", action="store_true")
    update_pull_parser.set_defaults(handler=handle_update_pull)
    update_plan_parser = update_subparsers.add_parser("plan", help="Write an inspectable update plan.")
    update_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_plan_parser.add_argument("--manifest", help="Update manifest YAML or JSON file.")
    update_plan_parser.set_defaults(handler=handle_update_plan)
    update_apply_parser = update_subparsers.add_parser("apply", help="Apply safe additive update changes.")
    update_apply_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_apply_parser.add_argument("--plan", help="Previously reviewed update plan YAML file.")
    update_apply_parser.add_argument("--approve-risky", action="store_true", help="Allow approved risky changes in the plan.")
    update_apply_parser.set_defaults(handler=handle_update_apply)
    update_rollback_parser = update_subparsers.add_parser("rollback", help="Record rollback against the latest update snapshot.")
    update_rollback_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_rollback_parser.add_argument("--snapshot", help="Specific update snapshot to record.")
    update_rollback_parser.set_defaults(handler=handle_update_rollback)
    update_status_parser = update_subparsers.add_parser("status", help="Show local update status.")
    update_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_status_parser.set_defaults(handler=handle_update_status)
    update_phone_home_parser = update_subparsers.add_parser(
        "phone-home",
        help="Emit a heartbeat-safe operational metadata payload.",
    )
    update_phone_home_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    update_phone_home_parser.set_defaults(handler=handle_update_phone_home)

    license_parser = subparsers.add_parser("license", help="Manage customer OS license metadata.")
    license_subparsers = license_parser.add_subparsers(dest="license_command", required=True)
    license_activate_parser = license_subparsers.add_parser(
        "activate",
        help="Activate a customer license without printing or storing the raw key.",
    )
    license_activate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    license_activate_parser.add_argument("--key", required=True, help="Customer license key.")
    license_activate_parser.set_defaults(handler=handle_license_activate)

    backup_parser = subparsers.add_parser("backup", help="Plan or run GitHub-backed OS state backups.")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command", required=True)
    backup_run_parser = backup_subparsers.add_parser("run", help="Plan or record a backup run.")
    backup_run_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_run_mode = backup_run_parser.add_mutually_exclusive_group()
    backup_run_mode.add_argument("--dry-run", action="store_true", default=True)
    backup_run_mode.add_argument("--apply", action="store_true")
    backup_run_parser.set_defaults(handler=handle_backup_run)
    backup_push_parser = backup_subparsers.add_parser(
        "push",
        help=(
            "Record a local backup push run log. "
            "Skips remote push when update grant is absent (no creds); always logs locally."
        ),
    )
    backup_push_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_push_parser.set_defaults(handler=handle_backup_push)

    fleet_parser = subparsers.add_parser("fleet", help="Operator fleet management commands.")
    fleet_subparsers = fleet_parser.add_subparsers(dest="fleet_command", required=True)
    fleet_push_parser = fleet_subparsers.add_parser(
        "push",
        help=(
            "Record a simulated operator-push event for a customer installation. "
            "V1 local-only: no real SSH or network calls."
        ),
    )
    fleet_push_parser.add_argument("customer_slug", help="Customer slug (snake_case).")
    fleet_push_parser.add_argument(
        "--source",
        default="latest",
        help="Release ref or tag to push (default: latest).",
    )
    fleet_push_parser.set_defaults(handler=handle_fleet_push)

    metrics_parser = subparsers.add_parser("metrics", help="Compute and view OS metrics scorecards.")
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command", required=True)
    metrics_refresh_parser = metrics_subparsers.add_parser(
        "refresh",
        help=(
            "Compute a metrics scorecard from run logs, doctor findings, and automation maturity. "
            "Writes result to harness/shared_factory/07-metrics/scorecard.yml."
        ),
    )
    metrics_refresh_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    metrics_refresh_parser.set_defaults(handler=handle_metrics_refresh)

    config_parser = subparsers.add_parser(
        "config",
        help="Install or update Codex config.toml conventions.",
        description=(
            "Install, merge, or validate Codex config.toml files at each OS layer. "
            "Layers: root, domain, project, workflow, automation. "
            "All write operations default to --dry-run; pass --apply to write. "
            "Use 'install-tree' to apply all layers at once across the routed OS root."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("config.toml", "Codex config file at each OS layer directory."),
            ],
            examples=[
                ("agentic-os config install --layer root --apply", "Install root-layer config.toml."),
                ("agentic-os config install-tree --apply", "Install config.toml across the full OS tree."),
                ("agentic-os config install-tree --dry-run", "Preview install-tree changes without writing."),
                ("agentic-os config doctor --layer root", "Validate root-layer config.toml contracts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_install = config_subparsers.add_parser("install", help="Install or merge config.toml for an OS directory.")
    config_install.add_argument("--root", default=DEFAULT_ROOT, help="Directory that should receive config.toml.")
    config_install.add_argument("--layer", required=True, choices=sorted(CONFIG_LAYERS), help="Agentic OS config layer.")
    config_install_mode = config_install.add_mutually_exclusive_group()
    config_install_mode.add_argument("--dry-run", action="store_true", default=True)
    config_install_mode.add_argument("--apply", action="store_true")
    config_install.add_argument("--backup", action="store_true", help="Back up an existing config.toml before applying.")
    config_install.add_argument(
        "--confirm-conflicts",
        action="store_true",
        help="Apply non-conflicting additions while preserving existing conflicting keys.",
    )
    config_install.set_defaults(handler=handle_config_install)
    config_install_tree = config_subparsers.add_parser(
        "install-tree",
        help="Install or merge config.toml across the routed OS root, domains, projects, workflows, and automations.",
    )
    config_install_tree.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    config_install_tree_mode = config_install_tree.add_mutually_exclusive_group()
    config_install_tree_mode.add_argument("--dry-run", action="store_true", default=True)
    config_install_tree_mode.add_argument("--apply", action="store_true")
    config_install_tree.add_argument("--backup", action="store_true", help="Back up existing config.toml files before applying.")
    config_install_tree.add_argument(
        "--confirm-conflicts",
        action="store_true",
        help="Apply non-conflicting additions while preserving existing conflicting keys.",
    )
    config_install_tree.set_defaults(handler=handle_config_install_tree)
    config_doctor = config_subparsers.add_parser("doctor", help="Validate config.toml OTEL and MCP contracts.")
    config_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Directory containing config.toml.")
    config_doctor.add_argument("--layer", required=True, choices=sorted(CONFIG_LAYERS), help="Agentic OS config layer.")
    config_doctor.set_defaults(handler=handle_config_doctor)

    doc_config_parser = subparsers.add_parser(
        "doc-config",
        help="Plan and validate document-routing config.",
        description=(
            "Install, validate, and query doc-config.yml — the file that controls where documents, "
            "specs, and notes are written across the OS and Notion. "
            "Use 'plan' to get a deterministic routing decision for a given request before writing anything."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("<domain>/<project>/doc-config.yml", "Per-project document routing config."),
                ("harness/shared_factory/doc-config.yml", "Shared-factory fallback routing config."),
            ],
            examples=[
                ("agentic-os doc-config init --domain acme --project myproj", "Install doc-config.yml for a project."),
                ("agentic-os doc-config doctor", "Check doc-config.yml contracts."),
                ('agentic-os doc-config plan --request "write a spec for X"', "Get a routing plan for a document request."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    doc_config_subparsers = doc_config_parser.add_subparsers(dest="doc_config_command", required=True)
    doc_config_init = doc_config_subparsers.add_parser("init", help="Install doc-config.yml if missing.")
    doc_config_init.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    doc_config_init.add_argument("--domain", help="Routed domain, when known.")
    doc_config_init.add_argument("--project", help="Routed project, when known.")
    doc_config_init.set_defaults(handler=handle_doc_config_init)
    doc_config_doctor_parser = doc_config_subparsers.add_parser("doctor", help="Check doc-config.yml contracts.")
    doc_config_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    doc_config_doctor_parser.set_defaults(handler=handle_doc_config_doctor)
    doc_config_plan = doc_config_subparsers.add_parser("plan", help="Build a deterministic document-routing plan.")
    doc_config_plan.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    doc_config_plan.add_argument("--request", required=True, help="Request or document intent to route.")
    doc_config_plan.add_argument("--domain", help="Routed domain, when known.")
    doc_config_plan.add_argument("--project", help="Routed project, when known.")
    doc_config_plan.add_argument("--work-item", help="Active work item id/slug, when known.")
    doc_config_plan.add_argument("--questions-present", action="store_true", help="Include QUESTIONS bucket in the plan.")
    doc_config_plan.set_defaults(handler=handle_doc_config_plan)

    hook_parser = subparsers.add_parser(
        "hook",
        help="Sync active Claude/Codex hooks to installed OS hook sources.",
        description=(
            "Point active Claude and Codex hook settings at installed OS hook scripts. "
            "Use 'sync' to apply (default: dry-run). Use 'doctor' to validate the current hook wiring. "
            "Targets: 'all' (default), 'claude' only, or 'codex' only."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("~/.claude/settings.json", "Claude hook settings (read and written by 'sync --target claude')."),
                ("~/.codex/hooks.json", "Codex hook settings (read and written by 'sync --target codex')."),
                ("harness/hooks/", "Installed OS hook scripts (the sync target)."),
            ],
            examples=[
                ("agentic-os hook sync --apply", "Point both Claude and Codex hooks at OS hook scripts."),
                ("agentic-os hook sync --target claude --apply", "Sync Claude hooks only."),
                ("agentic-os hook sync --dry-run", "Preview hook sync without writing."),
                ("agentic-os hook doctor", "Validate current hook wiring."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    hook_subparsers = hook_parser.add_subparsers(dest="hook_command", required=True)
    hook_sync_parser = hook_subparsers.add_parser("sync", help="Point active harness hook settings at installed OS hooks.")
    hook_sync_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    hook_sync_parser.add_argument("--target", choices=("all", "codex", "claude"), default="all")
    hook_sync_mode = hook_sync_parser.add_mutually_exclusive_group()
    hook_sync_mode.add_argument("--dry-run", action="store_true", default=True)
    hook_sync_mode.add_argument("--apply", action="store_true")
    hook_sync_parser.add_argument("--backup", action="store_true", help="Back up active hook config before applying.")
    hook_sync_parser.add_argument("--codex-hooks-path", help="Override Codex hooks.json path.")
    hook_sync_parser.add_argument("--claude-settings-path", help="Override Claude settings.json path.")
    hook_sync_parser.set_defaults(handler=handle_hook_sync)
    hook_doctor_parser = hook_subparsers.add_parser("doctor", help="Validate active hook settings use installed OS hooks.")
    hook_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    hook_doctor_parser.add_argument("--target", choices=("all", "codex", "claude"), default="all")
    hook_doctor_parser.add_argument("--codex-hooks-path", help="Override Codex hooks.json path.")
    hook_doctor_parser.add_argument("--claude-settings-path", help="Override Claude settings.json path.")
    hook_doctor_parser.set_defaults(handler=handle_hook_doctor)

    notion_parser = subparsers.add_parser("notion", help="Plan and apply filesystem-to-Notion sync.")
    notion_subparsers = notion_parser.add_subparsers(dest="notion_command", required=True)
    notion_plan = notion_subparsers.add_parser("plan-sync", help="Build a reviewable Notion sync plan.")
    notion_plan.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_plan.set_defaults(handler=handle_notion_plan_sync)
    notion_sync = notion_subparsers.add_parser("sync", help="Run a guarded Notion sync.")
    notion_sync.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_sync_mode = notion_sync.add_mutually_exclusive_group(required=True)
    notion_sync_mode.add_argument("--dry-run", action="store_true")
    notion_sync_mode.add_argument("--apply", action="store_true")
    notion_sync.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_sync.set_defaults(handler=handle_notion_sync)
    notion_bootstrap = notion_subparsers.add_parser("bootstrap", help="Plan or apply the Notion control-plane bootstrap.")
    notion_bootstrap.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_bootstrap_mode = notion_bootstrap.add_mutually_exclusive_group(required=True)
    notion_bootstrap_mode.add_argument("--dry-run", action="store_true")
    notion_bootstrap_mode.add_argument("--apply", action="store_true")
    notion_bootstrap.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_bootstrap.add_argument("--parent-page-id", help="Approved parent page id in the verified workspace.")
    notion_bootstrap.set_defaults(handler=handle_notion_bootstrap)
    notion_track_runtime = notion_subparsers.add_parser(
        "track-runtime",
        help="Plan or apply guarded Notion tracking for runtime registries and runs.",
    )
    notion_track_runtime.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_track_runtime_mode = notion_track_runtime.add_mutually_exclusive_group(required=True)
    notion_track_runtime_mode.add_argument("--dry-run", action="store_true")
    notion_track_runtime_mode.add_argument("--apply", action="store_true")
    notion_track_runtime.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_track_runtime.set_defaults(handler=handle_notion_track_runtime)
    notion_active_work = notion_subparsers.add_parser(
        "active-work-sync",
        help="Plan or apply guarded Notion sync for the generated OS Active Work database.",
    )
    notion_active_work.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_active_work_mode = notion_active_work.add_mutually_exclusive_group(required=True)
    notion_active_work_mode.add_argument("--dry-run", action="store_true")
    notion_active_work_mode.add_argument("--apply", action="store_true")
    notion_active_work.add_argument("--database-id", help="Existing OS Active Work Notion database id.")
    notion_active_work.add_argument("--verified-workspace", help="Workspace name verified by the operator or connector.")
    notion_active_work.add_argument("--token-env", default="GENOMES_NOTION_PAT", help="Environment variable containing the Notion token.")
    notion_active_work.set_defaults(handler=handle_notion_active_work_sync)

    notion_org_parser = subparsers.add_parser(
        "notion-org",
        help="Check Notion IA organization before page moves.",
        description=(
            "Validate Notion information-architecture organization and backup readiness "
            "before performing page moves or structural changes. "
            "Currently supports 'doctor' to check config and verify a local backup exists."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
                ("GENOMES_NOTION_PAT", "Notion API token for read access."),
                ("GENOMES_NOTION_CONNECTOR", "Alternative Notion token (checked second)."),
            ],
            config_files=[
                ("harness/registries/notion-surfaces.yml", "Notion page/database ID registry."),
            ],
            examples=[
                ("agentic-os notion-org doctor", "Check Notion org config and backup readiness."),
                ("agentic-os notion-org doctor --backup-dir ~/notion-backup", "Also verify a local backup directory."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    notion_org_subparsers = notion_org_parser.add_subparsers(dest="notion_org_command", required=True)
    notion_org_doctor_parser = notion_org_subparsers.add_parser("doctor", help="Check Notion organization config and backup readiness.")
    notion_org_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    notion_org_doctor_parser.add_argument("--backup-dir", help="Local Notion backup directory to verify before moves.")
    notion_org_doctor_parser.set_defaults(handler=handle_notion_org_doctor)

    runtime_parser = subparsers.add_parser(
        "runtime",
        help="Manage file-backed runtime state.",
        description=(
            "Manage the file-backed runtime surface: registries, run queue, heartbeats, schedules, integrations, and sources. "
            "All mutating subcommands default to --dry-run; pass --apply to write changes. "
            "'runtime supervise' runs a full supervisor tick across all subsystems at once."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/runtime-registry.yml", "Runtime registry: schedules, heartbeats, integrations."),
                ("harness/registries/run-queue.yml", "Run queue: pending and in-progress items."),
                ("harness/registries/automation-run-tracking.yml", "Automation run tracking."),
            ],
            examples=[
                ("agentic-os runtime init", "Create runtime registries and log folders."),
                ("agentic-os runtime doctor", "Check runtime registry health."),
                ("agentic-os runtime supervise --apply", "Run a full supervisor tick across all subsystems."),
                ("agentic-os runtime run-next --apply", "Dispatch the next safe queued item."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_init_parser = runtime_subparsers.add_parser("init", help="Create runtime registries and log folders.")
    runtime_init_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_init_parser.set_defaults(handler=handle_runtime_init)
    runtime_doctor_parser = runtime_subparsers.add_parser("doctor", help="Check runtime registry health.")
    runtime_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_doctor_parser.set_defaults(handler=handle_runtime_doctor)
    runtime_run_next_parser = runtime_subparsers.add_parser("run-next", help="Dispatch the next safe queued runtime item.")
    runtime_run_next_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_run_next_parser.add_argument("--item-id", help="Specific queue item id to inspect or dispatch.")
    runtime_run_next_mode = runtime_run_next_parser.add_mutually_exclusive_group()
    runtime_run_next_mode.add_argument("--dry-run", action="store_true", default=True)
    runtime_run_next_mode.add_argument("--apply", action="store_true")
    runtime_run_next_parser.set_defaults(handler=handle_runtime_run_next)
    runtime_supervise_parser = runtime_subparsers.add_parser(
        "supervise",
        help="Run one supervisor tick across the runtime surface (heartbeats, schedules, sources, events, run queue) plus a health check.",
    )
    runtime_supervise_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    runtime_supervise_mode = runtime_supervise_parser.add_mutually_exclusive_group()
    runtime_supervise_mode.add_argument("--dry-run", action="store_true", default=True)
    runtime_supervise_mode.add_argument("--apply", action="store_true")
    runtime_supervise_parser.set_defaults(handler=handle_runtime_supervise)

    heartbeat_parser = subparsers.add_parser("heartbeat", help="Manage runtime heartbeats.")
    heartbeat_subparsers = heartbeat_parser.add_subparsers(dest="heartbeat_command", required=True)
    heartbeat_list_parser = heartbeat_subparsers.add_parser("list", help="List configured heartbeats.")
    heartbeat_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_list_parser.set_defaults(handler=handle_heartbeat_list)
    heartbeat_run_parser = heartbeat_subparsers.add_parser("run", help="Run or dry-run a heartbeat.")
    heartbeat_run_parser.add_argument("heartbeat_id")
    heartbeat_run_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_run_mode = heartbeat_run_parser.add_mutually_exclusive_group()
    heartbeat_run_mode.add_argument("--dry-run", action="store_true", default=True)
    heartbeat_run_mode.add_argument("--apply", action="store_true")
    heartbeat_run_parser.set_defaults(handler=handle_heartbeat_run)
    heartbeat_doctor_parser = heartbeat_subparsers.add_parser("doctor", help="Check runtime heartbeat health.")
    heartbeat_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    heartbeat_doctor_parser.set_defaults(handler=handle_runtime_doctor)

    schedule_parser = subparsers.add_parser("schedule", help="Manage runtime schedules.")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command", required=True)
    schedule_create_parser = schedule_subparsers.add_parser("create", help="Create a schedule in the runtime registry.")
    schedule_create_parser.add_argument("schedule_id")
    schedule_create_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    schedule_create_parser.add_argument("--cadence", default="manual")
    schedule_create_parser.add_argument("--timezone", default="America/Chicago")
    schedule_create_parser.add_argument("--command")
    schedule_create_parser.set_defaults(handler=handle_schedule_create)
    schedule_run_due_parser = schedule_subparsers.add_parser("run-due", help="Queue due schedules without executing external effects.")
    schedule_run_due_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    schedule_run_due_mode = schedule_run_due_parser.add_mutually_exclusive_group()
    schedule_run_due_mode.add_argument("--dry-run", action="store_true", default=True)
    schedule_run_due_mode.add_argument("--apply", action="store_true")
    schedule_run_due_parser.set_defaults(handler=handle_schedule_run_due)

    integration_parser = subparsers.add_parser("integration", help="Manage runtime integrations.")
    integration_subparsers = integration_parser.add_subparsers(dest="integration_command", required=True)
    integration_list_parser = integration_subparsers.add_parser("list", help="List configured integrations.")
    integration_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_list_parser.set_defaults(handler=handle_integration_list)
    integration_setup_parser = integration_subparsers.add_parser("setup", help="Dry-run or record integration setup.")
    integration_setup_parser.add_argument("integration_id")
    integration_setup_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_setup_mode = integration_setup_parser.add_mutually_exclusive_group()
    integration_setup_mode.add_argument("--dry-run", action="store_true", default=True)
    integration_setup_mode.add_argument("--apply", action="store_true")
    integration_setup_parser.set_defaults(handler=handle_integration_setup)
    integration_doctor_parser = integration_subparsers.add_parser("doctor", help="Check integration setup contracts.")
    integration_doctor_parser.add_argument("integration_id", nargs="?")
    integration_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    integration_doctor_parser.set_defaults(handler=handle_integration_doctor)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run installed OS health checks.",
        description=(
            "Run OS health checks against the installed root. Checks required files, registry contracts, "
            "config.toml conventions, and optional remote host reachability. "
            "Use --all to aggregate all subsystem doctors (runtime, event-graph, config) in one pass. "
            "Use --fix-missing to create only missing managed files without overwriting local edits."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/registries/", "Registry files checked for contract compliance."),
                ("config/hosts.yml", "SSH host registry probed when --check-remotes is set."),
            ],
            examples=[
                ("agentic-os doctor", "Run structural health checks on the default OS root."),
                ("agentic-os doctor --all", "Run all subsystem doctors in one report."),
                ("agentic-os doctor --fix-missing", "Create missing managed files only."),
                ("agentic-os doctor --check-remotes", "Also probe registered SSH hosts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    doctor_parser.add_argument("--fix-missing", action="store_true", help="Create missing managed files only.")
    doctor_parser.add_argument(
        "--all",
        action="store_true",
        dest="all_systems",
        help="Aggregate all subsystem doctors (runtime, event-graph, config) into one report.",
    )
    doctor_parser.add_argument(
        "--check-remotes",
        action="store_true",
        help="Probe each registered host with ssh -o BatchMode=yes <alias> true and report unreachable hosts as warnings.",
    )
    doctor_parser.set_defaults(handler=handle_doctor)

    migrate_parser = subparsers.add_parser("migrate", help="Plan and apply explicit migrations.")
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_plan_parser = migrate_subparsers.add_parser("plan", help="Create a reviewable migration plan.")
    migrate_plan_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    migrate_plan_parser.set_defaults(handler=handle_migrate_plan)
    migrate_apply_parser = migrate_subparsers.add_parser("apply", help="Apply an approved migration by ID.")
    migrate_apply_parser.add_argument("migration_id")
    migrate_apply_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    migrate_apply_parser.set_defaults(handler=handle_migrate_apply)

    losmon_parser = subparsers.add_parser("losmon", help="Validate Agentic OS against LOSMon replacement needs.")
    losmon_subparsers = losmon_parser.add_subparsers(dest="losmon_command", required=True)
    losmon_validate_parser = losmon_subparsers.add_parser("validate", help="Create LOSMon replacement validation objects.")
    losmon_validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    losmon_validate_parser.add_argument("--repo", help="LOS or losmon repository path.")
    losmon_validate_parser.set_defaults(handler=handle_losmon_validate)

    plan_parser = subparsers.add_parser("plan", help="Capture future OS ideas and plans.")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)
    plan_capture = plan_subparsers.add_parser("capture", help="Capture a future idea in the right OS location.")
    plan_capture.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    plan_capture.add_argument("--title", required=True)
    plan_capture.add_argument("--summary", required=True)
    plan_capture.add_argument("--kind", default="os", choices=("os", "domain", "customer"))
    plan_capture.add_argument("--domain")
    plan_capture.add_argument("--project")
    plan_capture.set_defaults(handler=handle_plan_capture)

    self_improvement_parser = subparsers.add_parser(
        "self-improvement",
        help="Review local evidence for proposal-only OS improvements.",
        description=(
            "Analyse run logs, doctor findings, and automation maturity to generate proposal-only OS improvement suggestions. "
            "Proposals are never auto-applied; they require explicit approve + promote steps. "
            "Use 'run --dry-run' (default) to preview without writing, or 'run --apply' to persist proposals and generate a daily report."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
                ("GENOMES_NOTION_PAT", "Notion API token for writing the daily report projection (--apply mode)."),
                ("GENOMES_NOTION_CONNECTOR", "Alternative Notion token (checked second after GENOMES_NOTION_PAT)."),
            ],
            config_files=[
                ("harness/shared_factory/06-self-improvement/", "Self-improvement proposals, run records, and reports."),
                ("harness/registries/self-improvement.yml", "Self-improvement config (review cadence, enabled checks)."),
            ],
            examples=[
                ("agentic-os self-improvement run", "Preview a review without writing anything (dry-run)."),
                ("agentic-os self-improvement run --apply", "Run review and persist proposals + report."),
                ("agentic-os self-improvement list", "List open proposals."),
                ("agentic-os self-improvement approve P042 --target harness/RULES.md", "Approve proposal P042 for a target file."),
                ("agentic-os self-improvement promote P042 --target harness/RULES.md", "Promote approved proposal into a draft."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    self_improvement_subparsers = self_improvement_parser.add_subparsers(
        dest="self_improvement_command",
        required=True,
    )
    self_improvement_run = self_improvement_subparsers.add_parser(
        "run",
        help="Run a self-improvement review (dry-run by default; use --apply to persist + document).",
    )
    self_improvement_run.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_run_mode = self_improvement_run.add_mutually_exclusive_group()
    self_improvement_run_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a review without writing run records, proposals, or a report (default behaviour).",
    )
    self_improvement_run_mode.add_argument(
        "--apply",
        action="store_true",
        help="Persist mode: write run records, proposals, daily report, and Notion projection.",
    )
    self_improvement_run.set_defaults(handler=handle_self_improvement_run)
    self_improvement_status_parser = self_improvement_subparsers.add_parser(
        "status",
        help="Summarize self-improvement run and proposal state.",
    )
    self_improvement_status_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_status_parser.set_defaults(handler=handle_self_improvement_status)
    self_improvement_list = self_improvement_subparsers.add_parser("list", help="List self-improvement proposals.")
    self_improvement_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_list.set_defaults(handler=handle_self_improvement_list)
    self_improvement_show = self_improvement_subparsers.add_parser("show", help="Show one self-improvement proposal.")
    self_improvement_show.add_argument("proposal_id")
    self_improvement_show.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_show.set_defaults(handler=handle_self_improvement_show)
    self_improvement_approve = self_improvement_subparsers.add_parser(
        "approve",
        help="Approve one proposal for a specific draft target.",
    )
    self_improvement_approve.add_argument("proposal_id")
    self_improvement_approve.add_argument("--target", required=True)
    self_improvement_approve.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_approve.set_defaults(handler=handle_self_improvement_approve)
    self_improvement_reject = self_improvement_subparsers.add_parser("reject", help="Reject one proposal and start cooldown.")
    self_improvement_reject.add_argument("proposal_id")
    self_improvement_reject.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_reject.set_defaults(handler=handle_self_improvement_reject)
    self_improvement_promote = self_improvement_subparsers.add_parser(
        "promote",
        help="Promote an approved proposal into a draft artifact.",
    )
    self_improvement_promote.add_argument("proposal_id")
    self_improvement_promote.add_argument("--target", required=True)
    self_improvement_promote.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_promote.set_defaults(handler=handle_self_improvement_promote)
    self_improvement_actions = self_improvement_subparsers.add_parser(
        "actions",
        help="Consume checked Notion action boxes on self-improvement suggestion pages.",
    )
    self_improvement_actions.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_actions_mode = self_improvement_actions.add_mutually_exclusive_group()
    self_improvement_actions_mode.add_argument("--dry-run", action="store_true", help="Preview checked action boxes without queuing workers.")
    self_improvement_actions_mode.add_argument("--apply", action="store_true", help="Queue checked actions and update their Notion pages.")
    self_improvement_actions.set_defaults(handler=handle_self_improvement_actions)
    self_improvement_reconcile = self_improvement_subparsers.add_parser(
        "reconcile-queue",
        help="Mark stale self-improvement review queue rows done when covered by a later successful run.",
    )
    self_improvement_reconcile.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    self_improvement_reconcile_mode = self_improvement_reconcile.add_mutually_exclusive_group()
    self_improvement_reconcile_mode.add_argument("--dry-run", action="store_true", help="Preview queue reconciliation without writing.")
    self_improvement_reconcile_mode.add_argument("--apply", action="store_true", help="Apply local run-queue reconciliation.")
    self_improvement_reconcile.set_defaults(handler=handle_self_improvement_reconcile_queue)

    connected_parser = subparsers.add_parser("connected-system", help="Manage connected source systems.")
    connected_subparsers = connected_parser.add_subparsers(dest="connected_system_command", required=True)
    connected_list = connected_subparsers.add_parser("list", help="List connected systems and selected providers.")
    connected_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_list.set_defaults(handler=handle_connected_system_list)
    connected_doctor = connected_subparsers.add_parser("doctor", help="Check a connected system.")
    connected_doctor.add_argument("system_id")
    connected_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_doctor.set_defaults(handler=handle_connected_system_doctor)

    watch_parser = subparsers.add_parser("watch-source", help="Manage connected source watchers.")
    watch_subparsers = watch_parser.add_subparsers(dest="watch_source_command", required=True)
    watch_list = watch_subparsers.add_parser("list", help="List watch sources.")
    watch_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_list.set_defaults(handler=handle_watch_source_list)
    watch_create = watch_subparsers.add_parser("create", help="Create a file-backed watch source.")
    watch_create.add_argument("source_id")
    watch_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_create.add_argument("--connected-system", default="notion_genome")
    watch_create.add_argument("--source-type", default="notion_database")
    watch_create.add_argument("--display-name")
    watch_create.add_argument("--cadence", default="manual")
    watch_create.add_argument("--external-ref", action="append", default=[])
    watch_create.add_argument("--route-to", default="shared_factory")
    watch_create.add_argument("--enabled", action="store_true")
    watch_create.set_defaults(handler=handle_watch_source_create)
    watch_doctor = watch_subparsers.add_parser("doctor", help="Check a watch source.")
    watch_doctor.add_argument("source_id")
    watch_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_doctor.set_defaults(handler=handle_watch_source_doctor)
    watch_poll = watch_subparsers.add_parser("poll", help="Poll one watch source.")
    watch_poll.add_argument("source_id")
    watch_poll.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_poll_mode = watch_poll.add_mutually_exclusive_group(required=True)
    watch_poll_mode.add_argument("--dry-run", action="store_true")
    watch_poll_mode.add_argument("--apply", action="store_true")
    watch_poll.set_defaults(handler=handle_watch_source_poll)
    watch_run_due = watch_subparsers.add_parser("run-due", help="Poll enabled watch sources.")
    watch_run_due.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_run_due_mode = watch_run_due.add_mutually_exclusive_group(required=True)
    watch_run_due_mode.add_argument("--dry-run", action="store_true")
    watch_run_due_mode.add_argument("--apply", action="store_true")
    watch_run_due.set_defaults(handler=handle_watch_source_run_due)

    event_parser = subparsers.add_parser("event", help="Manage the file-backed event ledger.")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)
    event_append = event_subparsers.add_parser("append", help="Append a normalized event.")
    event_append.add_argument("--type", required=True, dest="event_type")
    event_append.add_argument("--source", required=True, dest="source_ref")
    event_append.add_argument("--summary", default="")
    event_append.add_argument("--correlation-id")
    event_append.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_append.set_defaults(handler=handle_event_append)
    event_list = event_subparsers.add_parser("list", help="List recent events.")
    event_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_list.add_argument("--limit", type=int, default=20)
    event_list.set_defaults(handler=handle_event_list)
    event_summary = event_subparsers.add_parser("summary", help="Summarize recent events and pending follow-up.")
    event_summary.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_summary.add_argument("--limit", type=int, default=20)
    event_summary.set_defaults(handler=handle_event_summary)
    event_process = event_subparsers.add_parser("process-due", help="Process matching chain rules.")
    event_process.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_process_mode = event_process.add_mutually_exclusive_group(required=True)
    event_process_mode.add_argument("--dry-run", action="store_true")
    event_process_mode.add_argument("--apply", action="store_true")
    event_process.set_defaults(handler=handle_event_process_due)
    event_replay = event_subparsers.add_parser("replay", help="Replay one event against chain rules.")
    event_replay.add_argument("event_id")
    event_replay.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_replay_mode = event_replay.add_mutually_exclusive_group(required=True)
    event_replay_mode.add_argument("--dry-run", action="store_true")
    event_replay_mode.add_argument("--apply", action="store_true")
    event_replay.set_defaults(handler=handle_event_replay)

    chain_parser = subparsers.add_parser("chain", help="Manage event chain rules.")
    chain_subparsers = chain_parser.add_subparsers(dest="chain_command", required=True)
    chain_list_parser = chain_subparsers.add_parser("list", help="List chain rules.")
    chain_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_list_parser.set_defaults(handler=handle_chain_list)
    chain_test = chain_subparsers.add_parser("test", help="Test a chain rule against an event file.")
    chain_test.add_argument("chain_rule_id")
    chain_test.add_argument("--event", required=True)
    chain_test.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_test.set_defaults(handler=handle_chain_test)
    chain_doctor_parser = chain_subparsers.add_parser("doctor", help="Check chain rule safety.")
    chain_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_doctor_parser.set_defaults(handler=handle_chain_doctor)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an installed OS root.",
        description=(
            "Validate the installed OS root directory structure, required files, and YAML contracts. "
            "Exits 0 when valid; prints errors to stderr and exits 1 on failure. "
            "Use --strict to also check structured YAML/JSON files against JSON schemas."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("schemas/", "JSON schemas used by --strict validation (inside the repo package)."),
            ],
            examples=[
                ("agentic-os validate", "Validate the default OS root."),
                ("agentic-os validate --root ~/my-os", "Validate a non-default OS root."),
                ("agentic-os validate --strict", "Also validate YAML files against JSON schemas."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also validate structured files against JSON schemas in schemas/.",
    )
    validate_parser.set_defaults(handler=handle_validate)

    docs_parser = subparsers.add_parser(
        "docs",
        help="Install or update runtime OS documentation.",
        description=(
            "Install, update, or run upkeep on runtime OS documentation assets: "
            "templates, manuals, commands, skills, and plans. "
            "'install' is a one-shot full install; 'update' adds only missing assets without overwriting local edits; "
            "'upkeep' runs the observe-mode drift planner against the upkeep registry."
        ),
        epilog=env_epilog(
            env_vars=[
                ("AGENTIC_OS_ROOT", "Installed OS root (fallback for --root). Default: ~/agentic_os."),
            ],
            config_files=[
                ("harness/docs/", "Installed runtime documentation assets."),
                ("harness/registries/documentation-upkeep.yml", "Documentation upkeep registry (used by 'upkeep')."),
            ],
            examples=[
                ("agentic-os docs install", "Install all runtime documentation assets."),
                ("agentic-os docs update", "Add missing assets without overwriting existing ones."),
                ("agentic-os docs upkeep --write-receipt", "Run upkeep drift planner and write receipt artifacts."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_install = docs_subparsers.add_parser(
        "install",
        help="Install runtime templates, manual, commands, skills, and plans.",
    )
    docs_install.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_install.set_defaults(handler=handle_docs_install)
    docs_update = docs_subparsers.add_parser(
        "update",
        help="Add missing runtime template, manual, command, skill, and plan assets without overwriting local edits.",
    )
    docs_update.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_update.set_defaults(handler=handle_docs_update)
    docs_upkeep = docs_subparsers.add_parser(
        "upkeep",
        help="Run the observe-mode documentation upkeep registry and drift planner.",
    )
    docs_upkeep.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    docs_upkeep.add_argument("--write-receipt", action="store_true", help="Write local YAML/Markdown receipt artifacts.")
    docs_upkeep.add_argument("--output-dir", help="Optional receipt output directory.")
    docs_upkeep.set_defaults(handler=handle_docs_upkeep)

    capability_parser = subparsers.add_parser("capability", help="Inspect installed OS capabilities.")
    capability_subparsers = capability_parser.add_subparsers(dest="capability_command", required=True)
    capability_list_parser = capability_subparsers.add_parser("list", help="List capabilities from installed registry.")
    capability_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_list_parser.add_argument("--type", dest="type", help="Filter by capability type (e.g. commands, skills, mcp_servers).")
    capability_list_parser.set_defaults(handler=handle_capability_list)
    capability_inventory_parser = capability_subparsers.add_parser("inventory", help="Show or regenerate INVENTORY.md.")
    capability_inventory_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_inventory_parser.add_argument("--regenerate", action="store_true", help="Rewrite INVENTORY.md from current registry state.")
    capability_inventory_parser.set_defaults(handler=handle_capability_inventory)

    return parser


def print_result(result) -> None:
    messages = result.messages()
    if not messages:
        print("no changes")
        return
    for message in messages:
        print(message)


def handle_init(args: argparse.Namespace) -> int:
    if args.profile:
        print(
            format_profile_result(
                install_profile_os(
                    args.target,
                    args.profile,
                    projects_source=args.projects_source,
                    include_legacy_agent=args.include_legacy_agent,
                )
            )
        )
        return 0
    print_result(
        init_os(args.target, projects_source=args.projects_source, include_legacy_agent=args.include_legacy_agent)
    )
    return 0


def handle_domain_create(args: argparse.Namespace) -> int:
    print_result(create_domain(args.root, args.name, include_legacy_agent=args.include_legacy_agent))
    return 0


def handle_profile_create(args: argparse.Namespace) -> int:
    print(format_profile_result(write_profile_template(args.target)))
    return 0


def handle_profile_validate(args: argparse.Namespace) -> int:
    profile = load_os_profile(args.profile)
    print(format_profile_result({"profile": args.profile, "rooms": [room["slug"] for room in profile["rooms"]], "ok": True}))
    return 0


def handle_room_create(args: argparse.Namespace) -> int:
    print_result(create_domain(args.root, args.room_slug))
    return 0


def handle_room_update(args: argparse.Namespace) -> int:
    profile = load_os_profile(args.from_profile)
    room = next((room for room in profile["rooms"] if room["slug"] == args.room_slug), None)
    if room is None:
        raise ValueError(f"room not found in profile: {args.room_slug}")
    result = install_profile_os(args.root, args.from_profile)
    print(format_profile_result(result))
    return 0


def handle_project_create(args: argparse.Namespace) -> int:
    remotes = None
    if getattr(args, "remote_host", None) and getattr(args, "remote_path", None):
        remotes = [{
            "name": args.remote_name or args.project,
            "host": args.remote_host,
            "path": args.remote_path,
            "kind": args.remote_kind,
            "authority": args.authority,
        }]
    print_result(
        create_project(
            args.root,
            args.domain,
            args.project,
            repo=args.repo,
            notion=args.notion,
            jira=args.jira,
            status=args.status,
            lane=args.lane,
            remotes=remotes,
        )
    )
    return 0


def handle_project_link_source(args: argparse.Namespace) -> int:
    print_result(link_project_source(args.root, args.domain, args.project, repo=args.repo, force=args.force))
    return 0


def handle_project_link_remote(args: argparse.Namespace) -> int:
    print_result(
        link_project_remote(
            args.root,
            args.domain,
            args.project,
            host=args.host,
            path=args.path,
            name=getattr(args, "name", None),
            kind=args.kind,
            authority=args.authority,
            force=args.force,
        )
    )
    return 0


def handle_project_onboard(args: argparse.Namespace) -> int:
    print_result(onboard_project(args.root, args.domain, args.project))
    return 0


def handle_host_add(args: argparse.Namespace) -> int:
    result = upsert_host(
        args.root,
        args.alias,
        ssh_alias=getattr(args, "ssh_alias", None),
        user=getattr(args, "user", None),
        description=getattr(args, "description", None),
    )
    print(f"{result['action']}: {result['alias']} → {result['path']}")
    return 0


def handle_host_list(args: argparse.Namespace) -> int:
    hosts = list_hosts(args.root)
    if not hosts:
        print("No hosts registered. Use: agentic-os host add <alias>")
        return 0
    for entry in hosts:
        alias = entry.get("alias", "")
        ssh_alias = entry.get("ssh_alias", alias)
        desc = entry.get("description", "")
        print(f"  {alias}  (ssh_alias: {ssh_alias})  {desc}")
    return 0


def handle_project_sync_remote(args: argparse.Namespace) -> int:
    result = sync_project_remote(
        args.root,
        args.domain,
        args.project,
        name=getattr(args, "name", None),
        timeout=getattr(args, "timeout", 20),
    )
    for w in result.get("warnings", []):
        print(f"warning: {w}")
    for e in result.get("errors", []):
        print(f"error: {e}")
    synced = result.get("synced", [])
    if synced:
        print(f"synced: {', '.join(synced)}")
    else:
        print("no remotes synced")
    return 1 if result.get("errors") else 0


def handle_project_mount_remote(args: argparse.Namespace) -> int:
    apply = getattr(args, "apply", False)
    result = mount_remote(
        args.root,
        args.domain,
        args.project,
        name=getattr(args, "name", None),
        namespace=getattr(args, "namespace", None),
        apply=apply,
        timeout=getattr(args, "timeout", 20),
    )
    for line in result.get("plan", []):
        print(line)
    for w in result.get("warnings", []):
        print(f"warning: {w}")
    for e in result.get("errors", []):
        print(f"error: {e}")
    if not apply:
        print("(dry-run; use --apply to mount)")
    elif result.get("applied"):
        print("mount applied")
    return 1 if result.get("errors") else 0


def handle_project_unmount_remote(args: argparse.Namespace) -> int:
    apply = getattr(args, "apply", False)
    result = unmount_remote(
        args.root,
        args.domain,
        args.project,
        name=getattr(args, "name", None),
        apply=apply,
        timeout=getattr(args, "timeout", 20),
    )
    for line in result.get("plan", []):
        print(line)
    for w in result.get("warnings", []):
        print(f"warning: {w}")
    for e in result.get("errors", []):
        print(f"error: {e}")
    if not apply:
        print("(dry-run; use --apply to unmount)")
    elif result.get("applied"):
        print("unmount applied")
    return 1 if result.get("errors") else 0


def handle_project_exec(args: argparse.Namespace) -> int:
    cmd_parts: list[str] = [c for c in (args.cmd or []) if c != "--"]
    if not cmd_parts:
        print("error: no command specified; use: agentic-os project exec <domain> <project> -- <command...>")
        return 1
    result = exec_remote(
        args.root,
        args.domain,
        args.project,
        cmd_parts,
        name=getattr(args, "name", None),
        timeout=getattr(args, "timeout", 60),
    )
    if result.get("stdout"):
        print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="")
    for e in result.get("errors", []):
        print(f"error: {e}")
    return 0 if result.get("ok") else 1


def handle_project_worktree_add(args: argparse.Namespace) -> int:
    print_result(
        register_project_worktree(
            args.root,
            args.domain,
            args.project,
            args.name,
            path=args.path,
            force=args.force,
        )
    )
    return 0


def handle_project_worktree_create(args: argparse.Namespace) -> int:
    print_result(
        create_project_worktree(
            args.root,
            args.domain,
            args.project,
            args.name,
            repo=args.repo,
            branch=args.branch,
        )
    )
    return 0


def handle_project_worktree_cleanup_closed(args: argparse.Namespace) -> int:
    print(
        yaml_dump(
            cleanup_terminal_worktrees(
                args.root,
                domain=args.domain,
                project=args.project,
                apply=args.apply,
                remove_files=args.remove_files,
            )
        )
    )
    return 0


def handle_project_work_item_create(args: argparse.Namespace) -> int:
    print_result(
        create_project_work_item(
            args.root,
            args.domain,
            args.project,
            title=args.title,
            summary=args.summary,
            status=args.status,
            work_id=args.work_id,
            item_format=args.format,
        )
    )
    return 0


def handle_project_work_item_repair(args: argparse.Namespace) -> int:
    print_result(
        repair_project_work_item(
            args.root,
            args.domain,
            args.project,
            work_item=args.work_item,
            all_items=args.all,
        )
    )
    return 0


def handle_project_work_item_sync_active(args: argparse.Namespace) -> int:
    print(yaml_dump(sync_active_container(args.root, domain=args.domain, project=args.project)))
    return 0


def handle_project_work_item_finalize_lingering(args: argparse.Namespace) -> int:
    print(yaml_dump(finalize_lingering_work_items(args.root, domain=args.domain, project=args.project, apply=args.apply)))
    return 0


def handle_project_work_item_infer_complete(args: argparse.Namespace) -> int:
    print(
        yaml_dump(
            infer_complete_work_items(
                args.root,
                domain=args.domain,
                project=args.project,
                older_than_days=args.older_than_days,
                min_confidence=args.min_confidence,
                include_blocked=args.include_blocked,
                apply=args.apply,
            )
        )
    )
    return 0


def handle_workflow_create(args: argparse.Namespace) -> int:
    print_result(create_workflow(args.root, args.domain, args.lane, args.name))
    return 0


def handle_workflow_check(args: argparse.Namespace) -> int:
    print(format_findings(check_workflow(args.root, args.domain, args.lane, args.workflow)))
    return 0


def handle_program_create(args: argparse.Namespace) -> int:
    print_result(create_program(args.root, args.name))
    return 0


def handle_instance_program_create(args: argparse.Namespace) -> int:
    print_result(create_instance_program(args.root, args.domain, args.name))
    return 0


def handle_automation_create(args: argparse.Namespace) -> int:
    print_result(create_automation(args.root, args.domain, args.lane, args.name))
    return 0


def handle_automation_check(args: argparse.Namespace) -> int:
    print(format_automation_check(check_automation(args.root, args.domain, args.lane, args.automation)))
    return 0


def handle_automation_attach(args: argparse.Namespace) -> int:
    result = attach_automation(args.root, args.domain, args.lane, args.automation, args.project)
    print(yaml_dump(result))
    return 0


def handle_automation_set_maturity(args: argparse.Namespace) -> int:
    result = set_automation_maturity(args.root, args.domain, args.lane, args.automation, args.level)
    print(yaml_dump(result))
    return 0


def handle_automation_control_list(args: argparse.Namespace) -> int:
    print(format_automation_control_result(list_automation_control(args.root)))
    return 0


def handle_automation_control_doctor(args: argparse.Namespace) -> int:
    result = automation_control_doctor(args.root)
    print(format_automation_control_result(result))
    return 0 if result.get("ok") else 1


def handle_automation_control_run(args: argparse.Namespace) -> int:
    print(format_automation_control_result(run_automation_control(args.root, dry_run=not args.apply)))
    return 0


def handle_run_log_create(args: argparse.Namespace) -> int:
    print_result(create_run_log(args.root, args.domain, args.workflow_or_automation))
    return 0


def handle_run_log_close(args: argparse.Namespace) -> int:
    result = close_run_log(
        args.root,
        args.domain,
        args.run_id,
        status=args.status,
        summary=args.summary,
        validation=args.validation,
        artifacts=args.artifact,
        approvals=args.approval,
        next_action=args.next_action,
        owner=args.owner,
        learning=args.learning,
        project=args.project,
    )
    if args.emit_events:
        result["emitted_event"] = emit_run_close_event(args.root, result)
    print(yaml_dump(result))
    return 0


def handle_thread_closeout(args: argparse.Namespace) -> int:
    result = close_thread(
        args.root,
        mode=args.closeout_mode,
        thread_id=args.thread_id,
        domain=args.domain,
        project=args.project,
        work_item=args.work_item,
        work_level=args.work_level,
        summary=args.summary,
        next_action=args.next_action,
        validations=args.validation,
        artifacts=args.artifact,
        receipts=args.receipt,
        memory_receipts=args.memory_receipt,
        notion_url=args.notion_url,
        notion_warning=args.notion_warning,
        verified_notion_workspace=args.verified_notion_workspace,
        skip_notion=args.skip_notion,
        allow_blocked_archive=args.allow_blocked_archive,
        request=args.request,
        cwd=args.cwd,
    )
    print(format_thread_closeout_result(result))
    return 0


def handle_thread_stale_finalize(args: argparse.Namespace) -> int:
    result = stale_finalize_threads(
        args.root,
        older_than_days=args.older_than_days,
        domain=args.domain,
        project=args.project,
        apply=args.apply,
    )
    print(format_thread_closeout_result(result))
    return 0


def yaml_dump(value) -> str:
    import yaml

    return yaml.safe_dump(value, sort_keys=False).strip()


def handle_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request)))
    return 0


def handle_context_build(args: argparse.Namespace) -> int:
    domain = args.domain
    project = args.project
    workflow = args.workflow
    lane = args.lane
    cwd = Path.cwd()

    if not domain:
        inferred = detect_from_cwd(Path(args.root).expanduser().resolve(), cwd)
        domain = inferred.get("domain")
        if not project:
            project = inferred.get("project")
        if not workflow:
            workflow = inferred.get("workflow")
        if not lane:
            lane = inferred.get("lane")

    if not domain and project:
        matches = [record for record in project_records(Path(args.root).expanduser().resolve()) if record["project"] == project]
        if len(matches) == 1:
            domain = matches[0]["domain"]
            lane = lane or matches[0].get("lane") or None
        elif len(matches) > 1:
            raise ValueError(f"project is ambiguous; specify --domain: {project}")

    if not domain:
        raise ValueError("domain is required unless current directory or unique --project identifies a domain")

    print(
        format_packet(
            build_context(
                args.root,
                domain=domain,
                project=project,
                work_item=args.work_item,
                workflow=workflow,
                lane=lane,
                cwd=cwd,
            )
        )
    )
    return 0


def handle_here_route(args: argparse.Namespace) -> int:
    print(format_packet(route_request(args.root, args.request, cwd=Path.cwd())))
    return 0


def handle_here_context_build(args: argparse.Namespace) -> int:
    print(format_packet(context_from_here(args.root, cwd=Path.cwd())))
    return 0


def handle_customer_init(args: argparse.Namespace) -> int:
    print(format_customer_result(customer_init(args.customer_slug, args.profile, args.target)))
    return 0


def handle_customer_update(args: argparse.Namespace) -> int:
    print(format_customer_result(customer_update(args.customer_slug, args.root)))
    return 0


def handle_customer_validate(args: argparse.Namespace) -> int:
    result = customer_validate(args.root)
    print(format_customer_result(result))
    return 0 if result["ok"] else 1


def handle_customer_brief(args: argparse.Namespace) -> int:
    import json

    result = scaffold_customer_brief(args.root, args.domain, args.name)
    print(json.dumps(result, indent=2))
    return 0


def handle_update_check(args: argparse.Namespace) -> int:
    print(format_update_result(update_check(args.root, manifest=args.manifest)))
    return 0


def handle_update_register(args: argparse.Namespace) -> int:
    print(format_update_result(update_register(args.root)))
    return 0


def handle_update_pull(args: argparse.Namespace) -> int:
    print(format_update_result(update_pull(args.root, dry_run=not args.apply)))
    return 0


def handle_update_plan(args: argparse.Namespace) -> int:
    print(format_update_result(update_plan(args.root, manifest=args.manifest)))
    return 0


def handle_update_apply(args: argparse.Namespace) -> int:
    result = update_apply(args.root, plan=args.plan, approve_risky=args.approve_risky)
    print(format_update_result(result))
    return 2 if result.get("blocked") else 0


def handle_update_rollback(args: argparse.Namespace) -> int:
    print(format_update_result(update_rollback(args.root, snapshot=args.snapshot)))
    return 0


def handle_update_status(args: argparse.Namespace) -> int:
    print(format_update_result(update_status(args.root)))
    return 0


def handle_update_phone_home(args: argparse.Namespace) -> int:
    print(format_update_result(phone_home_payload(args.root)))
    return 0


def handle_license_activate(args: argparse.Namespace) -> int:
    print(format_update_result(activate_license(args.root, key=args.key)))
    return 0


def handle_backup_run(args: argparse.Namespace) -> int:
    print(format_update_result(backup_run(args.root, dry_run=not args.apply)))
    return 0


def handle_backup_push(args: argparse.Namespace) -> int:
    print(format_update_result(backup_push(args.root)))
    return 0


def handle_fleet_push(args: argparse.Namespace) -> int:
    print(format_update_result(fleet_push(args.customer_slug, source=args.source)))
    return 0


def handle_metrics_refresh(args: argparse.Namespace) -> int:
    print(format_metrics_result(metrics_refresh(args.root)))
    return 0


def handle_config_install(args: argparse.Namespace) -> int:
    result = install_config(
        args.root,
        layer=args.layer,
        dry_run=not args.apply,
        backup=args.backup,
        confirm_conflicts=args.confirm_conflicts,
    )
    print(yaml_dump(result.as_dict()))
    return 2 if result.blocked else 0


def handle_config_install_tree(args: argparse.Namespace) -> int:
    result = install_config_tree(
        args.root,
        dry_run=not args.apply,
        backup=args.backup,
        confirm_conflicts=args.confirm_conflicts,
    )
    print(yaml_dump(result.as_dict()))
    return 2 if result.blocked else 0


def handle_config_doctor(args: argparse.Namespace) -> int:
    result = doctor_config(args.root, layer=args.layer)
    print(yaml_dump(result))
    return 0 if (result["ok"] if isinstance(result, dict) else True) else 1


def handle_doc_config_init(args: argparse.Namespace) -> int:
    print(format_doc_config_result(init_doc_config(args.root, domain=args.domain, project=args.project)))
    return 0


def handle_doc_config_doctor(args: argparse.Namespace) -> int:
    result = doc_config_doctor(args.root)
    print(format_doc_config_result(result))
    return 0 if result["ok"] else 1


def handle_doc_config_plan(args: argparse.Namespace) -> int:
    print(
        format_doc_config_result(
            build_doc_config_plan(
                args.root,
                request=args.request,
                domain=args.domain,
                project=args.project,
                work_item=args.work_item,
                questions_present=args.questions_present,
            )
        )
    )
    return 0


def handle_hook_sync(args: argparse.Namespace) -> int:
    result = hook_sync(
        args.root,
        target=args.target,
        dry_run=not args.apply,
        backup=args.backup,
        codex_hooks_path=args.codex_hooks_path,
        claude_settings_path=args.claude_settings_path,
    )
    print(yaml_dump(result.as_dict()))
    return 1 if result.findings else 0


def handle_hook_doctor(args: argparse.Namespace) -> int:
    result = hook_doctor(
        args.root,
        target=args.target,
        codex_hooks_path=args.codex_hooks_path,
        claude_settings_path=args.claude_settings_path,
    )
    print(yaml_dump(result.as_dict()))
    return 0 if result.ok else 1


def handle_notion_plan_sync(args: argparse.Namespace) -> int:
    print(format_sync_result(build_sync_plan(args.root)))
    return 0


def handle_notion_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_sync_plan(args.root)))
    else:
        print(format_sync_result(apply_sync_plan(args.root, verified_workspace=args.verified_workspace)))
    return 0


def handle_notion_bootstrap(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_bootstrap_plan(args.root, parent_page_id=args.parent_page_id)))
    else:
        print(
            format_sync_result(
                apply_bootstrap_plan(
                    args.root,
                    verified_workspace=args.verified_workspace,
                    parent_page_id=args.parent_page_id,
                )
            )
        )
    return 0


def handle_notion_track_runtime(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_runtime_result(build_runtime_tracking_plan(args.root)))
    else:
        print(format_runtime_result(apply_runtime_tracking(args.root, verified_workspace=args.verified_workspace)))
    return 0


def handle_notion_active_work_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(format_sync_result(build_active_work_sync_plan(args.root, database_id=args.database_id)))
    else:
        print(
            format_sync_result(
                apply_active_work_sync(
                    args.root,
                    database_id=args.database_id,
                    verified_workspace=args.verified_workspace,
                    token_env=args.token_env,
                )
            )
        )
    return 0


def handle_notion_org_doctor(args: argparse.Namespace) -> int:
    result = doctor_notion_org(args.root, backup_dir=args.backup_dir)
    print(format_notion_org_result(result))
    return 0 if result["ok"] else 1


def handle_runtime_init(args: argparse.Namespace) -> int:
    print(format_runtime_result(runtime_init(args.root)))
    return 0


def handle_runtime_doctor(args: argparse.Namespace) -> int:
    result = runtime_doctor(args.root)
    print(format_runtime_result(result))
    return 0 if result["ok"] else 1


def handle_runtime_run_next(args: argparse.Namespace) -> int:
    result = runtime_run_next(args.root, dry_run=not args.apply, item_id=args.item_id)
    print(format_runtime_result(result))
    return 0 if not args.apply or result["status"] not in {"failed", "blocked"} else 1


def handle_runtime_supervise(args: argparse.Namespace) -> int:
    result = supervise_tick(args.root, dry_run=not args.apply)
    print(format_supervise_result(result))
    return 0 if result["ok"] else 1


def handle_heartbeat_list(args: argparse.Namespace) -> int:
    print(format_runtime_result(heartbeat_list(args.root)))
    return 0


def handle_heartbeat_run(args: argparse.Namespace) -> int:
    print(format_runtime_result(heartbeat_run(args.root, args.heartbeat_id, dry_run=not args.apply)))
    return 0


def handle_schedule_create(args: argparse.Namespace) -> int:
    print(
        format_runtime_result(
            schedule_create(
                args.root,
                args.schedule_id,
                cadence=args.cadence,
                timezone_name=args.timezone,
                command=args.command,
            )
        )
    )
    return 0


def handle_schedule_run_due(args: argparse.Namespace) -> int:
    print(format_runtime_result(schedule_run_due(args.root, dry_run=not args.apply)))
    return 0


def handle_integration_list(args: argparse.Namespace) -> int:
    print(format_runtime_result(integration_list(args.root)))
    return 0


def handle_integration_setup(args: argparse.Namespace) -> int:
    print(format_runtime_result(integration_setup(args.root, args.integration_id, dry_run=not args.apply)))
    return 0


def handle_integration_doctor(args: argparse.Namespace) -> int:
    result = integration_doctor(args.root, args.integration_id)
    print(format_runtime_result(result))
    return 0 if result["ok"] else 1


def handle_doctor(args: argparse.Namespace) -> int:
    if getattr(args, "all_systems", False):
        result = doctor_all(args.root)
    else:
        result = doctor(args.root, fix_missing=args.fix_missing)
    if getattr(args, "check_remotes", False):
        from .hosts import load_hosts  # noqa: PLC0415
        from .validate import validate_project_remotes_connectivity  # noqa: PLC0415

        root_path = Path(args.root).expanduser()
        try:
            hosts = load_hosts(root_path)
        except ValueError:
            hosts = {}
        # Unreachable hosts are a warning state by spec — never flip doctor ok.
        connectivity_warnings = validate_project_remotes_connectivity(root_path, hosts)
        if isinstance(result.get("warnings"), list):
            result["warnings"].extend(connectivity_warnings)
        else:
            result["warnings"] = connectivity_warnings
    print(format_doctor_result(result))
    return 0 if result["ok"] else 1


def handle_migrate_plan(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_plan(args.root)))
    return 0


def handle_migrate_apply(args: argparse.Namespace) -> int:
    print(format_migration_result(migrate_apply(args.root, args.migration_id)))
    return 0


def handle_losmon_validate(args: argparse.Namespace) -> int:
    print(format_losmon_result(losmon_validate(args.root, repo=args.repo)))
    return 0


def handle_plan_capture(args: argparse.Namespace) -> int:
    print(
        format_plan_result(
            capture_plan(
                args.root,
                title=args.title,
                summary=args.summary,
                kind=args.kind,
                domain=args.domain,
                project=args.project,
            )
        )
    )
    return 0


def handle_self_improvement_run(args: argparse.Namespace) -> int:
    # Bare invocation and --dry-run both produce dry_run=True (read-only, SPEC 15 first-run safety).
    # Only --apply flips to persist mode.
    print(format_self_improvement_result(run_self_improvement(args.root, dry_run=not args.apply)))
    return 0


def handle_self_improvement_status(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(self_improvement_status(args.root)))
    return 0


def handle_self_improvement_list(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(list_self_improvement_proposals(args.root)))
    return 0


def handle_self_improvement_show(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(show_self_improvement_proposal(args.root, args.proposal_id)))
    return 0


def handle_self_improvement_approve(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            approve_self_improvement_proposal(args.root, args.proposal_id, target=args.target)
        )
    )
    return 0


def handle_self_improvement_reject(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(reject_self_improvement_proposal(args.root, args.proposal_id)))
    return 0


def handle_self_improvement_promote(args: argparse.Namespace) -> int:
    print(
        format_self_improvement_result(
            promote_self_improvement_proposal(args.root, args.proposal_id, target=args.target)
        )
    )
    return 0


def handle_self_improvement_actions(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(process_self_improvement_actions(args.root, dry_run=not args.apply)))
    return 0


def handle_self_improvement_reconcile_queue(args: argparse.Namespace) -> int:
    print(format_self_improvement_result(reconcile_self_improvement_queue(args.root, dry_run=not args.apply)))
    return 0


def handle_connected_system_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_connected_systems(args.root)))
    return 0


def handle_connected_system_doctor(args: argparse.Namespace) -> int:
    result = doctor_connected_system(args.root, args.system_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_watch_sources(args.root)))
    return 0


def handle_watch_source_create(args: argparse.Namespace) -> int:
    result = create_watch_source(
        args.root,
        args.source_id,
        connected_system=args.connected_system,
        source_type=args.source_type,
        display_name=args.display_name,
        cadence=args.cadence,
        external_ref=parse_external_refs(args.external_ref),
        route_to=args.route_to,
        enabled=args.enabled,
    )
    print(format_source_watch_result(result))
    return 0


def handle_watch_source_doctor(args: argparse.Namespace) -> int:
    result = doctor_watch_source(args.root, args.source_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_poll(args: argparse.Namespace) -> int:
    result = poll_watch_source(args.root, args.source_id, dry_run=args.dry_run)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_run_due(args: argparse.Namespace) -> int:
    print(format_source_watch_result(run_due_watch_sources(args.root, dry_run=args.dry_run)))
    return 0


def handle_ps(args: argparse.Namespace) -> int:
    mode = "all" if args.all else "active" if args.active else "now"
    color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())
    result = ps_snapshot(
        args.root,
        mode=mode,
        limit=args.limit,
        stale_days=args.stale_days,
    )
    result["prog"] = Path(sys.argv[0]).name if Path(sys.argv[0]).name in {"agentic-os", "aos"} else "agentic-os"
    print(format_ps_result(result, as_json=args.json, color=color))
    return 0


def handle_event_append(args: argparse.Namespace) -> int:
    print(
        format_event_graph_result(
            append_event(
                args.root,
                event_type=args.event_type,
                source_ref=args.source_ref,
                summary=args.summary,
                correlation_id=args.correlation_id,
            )
        )
    )
    return 0


def handle_event_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(list_events(args.root, limit=args.limit)))
    return 0


def handle_event_summary(args: argparse.Namespace) -> int:
    print(format_event_graph_result(summarize_events(args.root, limit=args.limit)))
    return 0


def handle_event_process_due(args: argparse.Namespace) -> int:
    print(format_event_graph_result(process_due(args.root, dry_run=args.dry_run)))
    return 0


def handle_event_replay(args: argparse.Namespace) -> int:
    print(format_event_graph_result(replay_event(args.root, args.event_id, dry_run=args.dry_run)))
    return 0


def handle_chain_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(chain_list(args.root)))
    return 0


def handle_chain_test(args: argparse.Namespace) -> int:
    print(format_event_graph_result(test_chain_rule(args.root, args.chain_rule_id, args.event)))
    return 0


def handle_chain_doctor(args: argparse.Namespace) -> int:
    result = chain_doctor(args.root)
    print(format_event_graph_result(result))
    return 0 if result["ok"] else 1


def handle_validate(args: argparse.Namespace) -> int:
    result = validate_root(args.root)
    strict_findings: list[StrictFinding] = []
    if getattr(args, "strict", False):
        from pathlib import Path as _Path  # noqa: PLC0415
        strict_findings = validate_schemas_strict(_Path(args.root).expanduser())
    if result.ok and not strict_findings:
        print(f"valid: {Path(args.root).expanduser()}")
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for finding in strict_findings:
        print(f"strict: [{finding.schema}] {finding.path}: {finding.message}", file=sys.stderr)
    return 1 if (result.errors or strict_findings) else 0


def handle_docs_install(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_update(args: argparse.Namespace) -> int:
    print_result(install_docs(args.root))
    return 0


def handle_docs_upkeep(args: argparse.Namespace) -> int:
    result = build_documentation_upkeep_plan(
        args.root,
        write_receipt=bool(args.write_receipt),
        output_dir=args.output_dir,
    )
    print(format_documentation_upkeep_result(result))
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    prog = Path(sys.argv[0]).name if argv is None else "agentic-os"
    if prog not in {"agentic-os", "aos"}:
        prog = "agentic-os"
    parser = build_parser(prog=prog)
    parse_argv = list(sys.argv[1:] if argv is None else argv)
    project_exec_cmd: list[str] | None = None
    if parse_argv[:2] == ["project", "exec"] and "--" in parse_argv:
        separator = parse_argv.index("--")
        project_exec_cmd = parse_argv[separator + 1 :]
        parse_argv = parse_argv[:separator]
    args = parser.parse_args(parse_argv)
    if project_exec_cmd is not None and getattr(args, "handler", None) == handle_project_exec:
        args.cmd = project_exec_cmd
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
