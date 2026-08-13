"""CLI surface for the canonical Spec Engine."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..cli_help import AosHelpFormatter, env_epilog
from ..lifecycle import indexed_work_id
from ..scaffold import domain_path, expand_path, normalize_domain, validate_name
from ..spec_adapters import (
    FilesystemSpecAdapter,
    JiraSpecAdapter,
    LinearSpecAdapter,
    transport_from_environment,
)
from ..spec_engine import (
    SPEC_STATUSES,
    SPEC_TYPES,
    Spec,
    SpecEngine,
    normalize_status,
    normalize_type,
)
from ..spec_policy import load_spec_policy
from ._shared import DEFAULT_ROOT, yaml_dump


def _adapter_config(policy: Mapping[str, Any], name: str) -> dict[str, Any]:
    adapters = (
        policy.get("adapters") if isinstance(policy.get("adapters"), Mapping) else {}
    )
    value = adapters.get(name) if isinstance(adapters, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _build_engine(
    root: str, domain: str, project: str, *, invocation: Mapping[str, Any] | None = None
) -> tuple[SpecEngine, FilesystemSpecAdapter, dict[str, Any]]:
    policy = load_spec_policy(
        root, domain=domain, project=project, invocation=invocation
    )
    filesystem = FilesystemSpecAdapter(
        root, domain, project, _adapter_config(policy, "filesystem")
    )
    adapters = {
        "filesystem": filesystem,
        "linear": LinearSpecAdapter(_adapter_config(policy, "linear")),
        "jira": JiraSpecAdapter(
            _adapter_config(policy, "jira"), transport_from_environment()
        ),
    }
    return SpecEngine(policy, adapters), filesystem, policy


def _project_root(root: str, domain: str, project: str) -> Path:
    return (
        domain_path(expand_path(root), normalize_domain(domain))
        / "02-projects"
        / validate_name(project, "project")
    )


def handle_spec_add(args: argparse.Namespace) -> int:
    invocation: dict[str, Any] = {}
    if args.placement:
        invocation = {"adapters": {"jira": {"placement": {"default": args.placement}}}}
    engine, _, policy = _build_engine(
        args.root, args.domain, args.project, invocation=invocation
    )
    defaults = (
        policy.get("defaults") if isinstance(policy.get("defaults"), Mapping) else {}
    )
    spec_type, legacy_type = normalize_type(args.type or defaults.get("type"))
    status, legacy_status, inferred_disposition = normalize_status(
        args.status or defaults.get("status")
    )
    project_root = _project_root(args.root, args.domain, args.project)
    spec_id = args.spec_id or indexed_work_id(project_root, args.title)
    legacy = {}
    if legacy_type:
        legacy["type"] = legacy_type
    if legacy_status:
        legacy["status"] = legacy_status
    spec = Spec(
        id=spec_id,
        title=args.title,
        summary=args.summary,
        type=spec_type,
        status=status,
        disposition=inferred_disposition
        or str(defaults.get("disposition") or "active"),
        domain=normalize_domain(args.domain),
        project=validate_name(args.project, "project"),
        authority=dict(policy.get("authority") or {}),
        legacy=legacy,
        provenance={"capture": "agentic-os spec add"},
    )
    result = engine.add(
        spec, adapter=args.adapter, apply_external=args.apply, dry_run=args.dry_run
    )
    print(yaml_dump(result))
    return 0 if result["ok"] else 1


def handle_spec_show(args: argparse.Namespace) -> int:
    engine, filesystem, _ = _build_engine(args.root, args.domain, args.project)
    if args.adapter == "jira":
        raise ValueError(
            "spec show is unsupported for the Jira adapter; use the provider issue key"
        )
    adapter = engine.adapters[args.adapter] if args.adapter else filesystem
    item = adapter.get(args.spec_id)
    if item is None:
        raise ValueError(f"spec not found: {args.spec_id}")
    print(yaml_dump(item.to_mapping()))
    return 0


def _project_scopes(root: str, domain: str | None, project: str | None):
    os_root = expand_path(root)
    if domain:
        domains = [domain_path(os_root, normalize_domain(domain))]
    else:
        domains = (
            [
                path
                for path in {*os_root.glob("*/"), *os_root.glob("domains/*/")}
                if path.is_dir() and (path / "02-projects").is_dir()
            ]
            if os_root.is_dir()
            else []
        )
    for domain_root in sorted(domains):
        projects_root = domain_root / "02-projects"
        if not projects_root.is_dir():
            continue
        for project_root in sorted(projects_root.iterdir()):
            if not project_root.is_dir() or (project and project_root.name != project):
                continue
            yield domain_root.name, project_root.name


def handle_spec_list(args: argparse.Namespace) -> int:
    status = normalize_status(args.status)[0] if args.status else None
    spec_type = normalize_type(args.type)[0] if args.type else None
    items: list[dict[str, Any]] = []
    for domain, project in _project_scopes(args.root, args.domain, args.project):
        _, filesystem, _ = _build_engine(args.root, domain, project)
        items.extend(
            item.to_mapping() for item in filesystem.list(status=status, type=spec_type)
        )
    print(yaml_dump({"count": len(items), "items": items}))
    return 0


def handle_spec_transition(args: argparse.Namespace) -> int:
    engine, filesystem, _ = _build_engine(args.root, args.domain, args.project)
    item = filesystem.get(args.spec_id)
    if item is None:
        raise ValueError(f"spec not found: {args.spec_id}")
    result = engine.transition(
        item,
        args.status,
        adapter=args.adapter,
        apply_external=args.apply,
        dry_run=args.dry_run,
    )
    print(yaml_dump(result))
    return 0 if result["ok"] else 1


def handle_spec_sync(args: argparse.Namespace) -> int:
    engine, filesystem, _ = _build_engine(args.root, args.domain, args.project)
    if not args.spec_id and not args.all:
        raise ValueError("provide spec_id or --all")
    items = filesystem.list() if args.all else [filesystem.get(args.spec_id)]
    results = []
    for item in items:
        if item is None:
            raise ValueError(f"spec not found: {args.spec_id}")
        results.append(engine.sync(item, adapter=args.adapter, apply=args.apply))
    ok = all(result["ok"] for result in results)
    print(yaml_dump({"ok": ok, "count": len(results), "results": results}))
    return 0 if ok else 1


def handle_spec_doctor(args: argparse.Namespace) -> int:
    if bool(args.domain) != bool(args.project):
        raise ValueError("domain and project must be provided together")
    if not args.domain:
        policy = load_spec_policy(args.root)
        adapters = policy.get("adapters") or {}
        primary = adapters.get("primary")
        ok = primary in {"filesystem", "linear", "jira"}
        print(
            yaml_dump(
                {
                    "ok": ok,
                    "scope": "root",
                    "loaded_from": policy.get("loaded_from"),
                    "primary_adapter": primary,
                }
            )
        )
        return 0 if ok else 1
    engine, _, policy = _build_engine(args.root, args.domain, args.project)
    result = engine.doctor(args.adapter)
    result["loaded_from"] = policy.get("loaded_from")
    print(yaml_dump(result))
    return 0 if result["ok"] else 1


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "spec",
        help="Capture and operate canonical Specs.",
        description="Manage bug, feature, and config Specs through project-aware filesystem, Linear, or Jira adapters.",
        epilog=env_epilog(
            config_files=[
                ("templates/runtime/spec-engine.yml", "Shipped Spec Engine defaults."),
                (
                    "<domain>/00-control-plane/spec-engine.yml",
                    "Optional domain policy.",
                ),
                (
                    "<project>/config/spec-engine.yml",
                    "Optional project adapter and lifecycle policy.",
                ),
            ],
            examples=[
                (
                    "agentic-os spec add acme app --title 'Fix login' --summary 'Repair login' --type bug",
                    "Capture a filesystem Spec.",
                ),
                (
                    "agentic-os spec transition acme app 001_fix_login grooming",
                    "Move a Spec into grooming.",
                ),
                (
                    "agentic-os spec doctor --domain acme --project app",
                    "Validate effective policy and adapter targets.",
                ),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    sub = parser.add_subparsers(dest="spec_command", required=True)

    add = sub.add_parser("add", help="Capture a new Spec.")
    add.add_argument("domain")
    add.add_argument("project")
    add.add_argument("--title", required=True)
    add.add_argument("--summary", required=True)
    add.add_argument("--type", choices=SPEC_TYPES)
    add.add_argument("--status", choices=SPEC_STATUSES)
    add.add_argument("--id", dest="spec_id")
    add.add_argument("--adapter", choices=("filesystem", "linear", "jira"))
    add.add_argument(
        "--placement",
        choices=("backlog", "active_sprint"),
        help="Jira placement override; active sprint is explicit only.",
    )
    mode = add.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply external provider writes after verification; filesystem writes by default.",
    )
    add.add_argument("--root", default=DEFAULT_ROOT)
    add.set_defaults(handler=handle_spec_add)

    show = sub.add_parser("show", help="Show one Spec.")
    show.add_argument("domain")
    show.add_argument("project")
    show.add_argument("spec_id")
    show.add_argument("--adapter", choices=("filesystem", "linear", "jira"))
    show.add_argument("--root", default=DEFAULT_ROOT)
    show.set_defaults(handler=handle_spec_show)

    list_parser = sub.add_parser("list", help="List Specs across a scope.")
    list_parser.add_argument("--domain")
    list_parser.add_argument("--project")
    list_parser.add_argument("--status")
    list_parser.add_argument("--type")
    list_parser.add_argument("--root", default=DEFAULT_ROOT)
    list_parser.set_defaults(handler=handle_spec_list)

    transition = sub.add_parser("transition", help="Transition or resume a Spec.")
    transition.add_argument("domain")
    transition.add_argument("project")
    transition.add_argument("spec_id")
    transition.add_argument("status", choices=(*SPEC_STATUSES, "resume"))
    transition.add_argument("--adapter", choices=("filesystem", "linear", "jira"))
    transition.add_argument("--dry-run", action="store_true")
    transition.add_argument("--apply", action="store_true")
    transition.add_argument("--root", default=DEFAULT_ROOT)
    transition.set_defaults(handler=handle_spec_transition)

    sync = sub.add_parser("sync", help="Plan or apply tracker synchronization.")
    sync.add_argument("domain")
    sync.add_argument("project")
    sync.add_argument("spec_id", nargs="?")
    sync.add_argument("--all", action="store_true")
    sync.add_argument("--adapter", required=True, choices=("linear", "jira"))
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--root", default=DEFAULT_ROOT)
    sync.set_defaults(handler=handle_spec_sync)

    doctor = sub.add_parser(
        "doctor", help="Validate effective Spec Engine policy and targets."
    )
    doctor.add_argument("--domain")
    doctor.add_argument("--project")
    doctor.add_argument("--adapter", choices=("filesystem", "linear", "jira"))
    doctor.add_argument("--root", default=DEFAULT_ROOT)
    doctor.set_defaults(handler=handle_spec_doctor)
