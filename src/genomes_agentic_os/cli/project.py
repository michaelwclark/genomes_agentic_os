"""CLI commands for the project family: scaffolds, remotes, worktrees, work items."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..lifecycle import (
    WORK_LIFECYCLE_STATES,
    cleanup_terminal_worktrees,
    create_project_work_item,
    infer_complete_work_items,
    repair_project_work_item,
)
from ..lifecycle import finalize_lingering_work_items, sync_active_container
from ..spec_engine import SPEC_STATUSES, SPEC_TYPES
from ..scaffold import (
    create_project,
    create_project_worktree,
    link_project_remote,
    link_project_source,
    onboard_project,
    register_project_worktree,
)
from ..remote_ops import sync_project_remote
from ..remote_mounts import exec_remote, mount_remote, unmount_remote

from ._shared import DEFAULT_ROOT, print_result, yaml_dump
from .spec import handle_spec_add


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
    # Compatibility entrypoint: explicit canonical type/status requests use the
    # Spec Engine. Historical invocations retain their exact legacy layout.
    if getattr(args, "type", None) or args.status in SPEC_STATUSES:
        return handle_spec_add(
            argparse.Namespace(
                root=args.root,
                domain=args.domain,
                project=args.project,
                title=args.title,
                summary=args.summary,
                type=args.type,
                status=args.status,
                spec_id=args.work_id,
                adapter="filesystem",
                placement=None,
                dry_run=False,
                apply=False,
            )
        )
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


def register(subparsers) -> None:
    """Register the project command group."""
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
    project_work_item_create.add_argument("--status", default="captured", choices=tuple(dict.fromkeys((*WORK_LIFECYCLE_STATES, *SPEC_STATUSES))))
    project_work_item_create.add_argument("--type", choices=SPEC_TYPES, help="Canonical Spec type; routes creation through the Spec Engine.")
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
