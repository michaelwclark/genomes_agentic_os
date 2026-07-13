"""CLI commands for config.toml, doc-config, and harness hook surfaces."""

from __future__ import annotations

import argparse

from ..cli_help import AosHelpFormatter, env_epilog
from ..config_ops import LAYERS as CONFIG_LAYERS
from ..config_ops import doctor_config, install_config, install_config_tree
from ..doc_config import build_doc_config_plan, doc_config_doctor, format_doc_config_result, init_doc_config
from ..hook_ops import hook_doctor, hook_sync

from ._shared import DEFAULT_ROOT, yaml_dump


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


def register(subparsers) -> None:
    """Register the config / doc-config / hook command group."""
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
