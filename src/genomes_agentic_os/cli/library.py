"""CLI for the installed versioned Agentic OS object library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from ..library import (
    LIBRARY_REPOSITORY_ENV,
    OBJECT_KINDS,
    apply_legacy_migration,
    create_object,
    get_object,
    init_library,
    install_library,
    library_doctor,
    query_objects,
    refresh_registry,
    rollback_library_install,
    verify_library_install,
)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_init(args: argparse.Namespace) -> int:
    _print(init_library(args.root, dry_run=not args.apply, initialize_git=args.git))
    return 0


def handle_refresh(args: argparse.Namespace) -> int:
    _print(refresh_registry(args.root, dry_run=not args.apply))
    return 0


def handle_create(args: argparse.Namespace) -> int:
    _print(
        create_object(
            args.root,
            args.kind,
            args.object_id,
            level=args.level,
            domain=args.domain,
            project=args.project,
            title=args.title,
            description=args.description,
            entrypoint=args.entrypoint,
            dry_run=not args.apply,
        )
    )
    return 0


def handle_list(args: argparse.Namespace) -> int:
    objects = query_objects(
        args.root,
        kind=args.kind,
        level=args.level,
        domain=args.domain,
        project=args.project,
        status=args.status,
    )
    _print({"api_version": "agentic-os-library/v1", "count": len(objects), "objects": objects})
    return 0


def handle_show(args: argparse.Namespace) -> int:
    _print(get_object(args.root, args.object_id))
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    result = library_doctor(args.root)
    _print(result)
    return 0 if result["status"] in {"healthy", "warning"} else 1


def handle_install(args: argparse.Namespace) -> int:
    result = install_library(
        args.root,
        repository=args.repository,
        ref=args.ref,
        replace_dirty=args.replace_dirty,
        dry_run=not args.apply,
    )
    _print(result)
    return 1 if result.get("status") == "blocked" else 0


def handle_verify_install(args: argparse.Namespace) -> int:
    result = verify_library_install(args.root)
    _print(result)
    return 0 if result["status"] == "verified" else 1


def handle_rollback_install(args: argparse.Namespace) -> int:
    result = rollback_library_install(args.root, dry_run=not args.apply)
    _print(result)
    return 1 if result.get("status") == "blocked" else 0


def _run_source_helper(
    args: argparse.Namespace,
    *,
    script_name: str,
    action: str,
    auto_dev_stage: str,
    extra_args: list[str],
) -> int:
    """Run one source-owned helper without taking ownership of its lifecycle stage."""

    source_root = Path(args.source_root).expanduser().resolve()
    script = source_root / "scripts" / script_name
    if not script.is_file():
        _print(
            {
                "api_version": "agentic-os-library/v1",
                "action": action,
                "status": "blocked",
                "auto_dev_stage": auto_dev_stage,
                "source_root": str(source_root),
                "blocker": f"source helper not found: scripts/{script_name}",
            }
        )
        return 1
    completed = subprocess.run(
        [sys.executable, str(script), "--repo", str(source_root), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        _print(
            {
                "api_version": "agentic-os-library/v1",
                "action": action,
                "status": "failed",
                "auto_dev_stage": auto_dev_stage,
                "source_root": str(source_root),
                "error": "source helper did not emit one JSON object",
            }
        )
        return completed.returncode or 1
    _print(payload)
    return completed.returncode


def handle_build(args: argparse.Namespace) -> int:
    extra_args: list[str] = []
    if args.output_dir:
        extra_args.extend(["--output-dir", args.output_dir])
    if args.require_clean:
        extra_args.append("--require-clean")
    if args.require_revision:
        extra_args.append("--require-revision")
    return _run_source_helper(
        args,
        script_name="build_library.py",
        action="library.build",
        auto_dev_stage="develop",
        extra_args=extra_args,
    )


def handle_validate(args: argparse.Namespace) -> int:
    extra_args: list[str] = []
    for flag, value in (
        ("--receipt", args.receipt),
        ("--archive", args.archive),
        ("--write-receipt", args.write_receipt),
    ):
        if value:
            extra_args.extend([flag, value])
    return _run_source_helper(
        args,
        script_name="validate_library.py",
        action="library.validate",
        auto_dev_stage="qa",
        extra_args=extra_args,
    )


def handle_release(args: argparse.Namespace) -> int:
    extra_args = ["--output", args.output] if args.output else []
    return _run_source_helper(
        args,
        script_name="render_release_notes.py",
        action="library.release-notes",
        auto_dev_stage="release",
        extra_args=extra_args,
    )


def handle_document(args: argparse.Namespace) -> int:
    extra_args = ["--input", args.input]
    for asset in args.required_asset:
        extra_args.extend(["--required-asset", asset])
    for flag, value in (
        ("--notes", args.notes),
        ("--write-receipt", args.write_receipt),
    ):
        if value:
            extra_args.extend([flag, value])
    return _run_source_helper(
        args,
        script_name="verify_release_readback.py",
        action="library.release-readback",
        auto_dev_stage="document_rerun",
        extra_args=extra_args,
    )


def handle_migrate(args: argparse.Namespace) -> int:
    result = apply_legacy_migration(args.root, dry_run=not args.apply)
    _print(result)
    return 1 if result.get("status") == "blocked" else 0


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default="~/agentic_os", help="Installed Agentic OS root.")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "library",
        help="Install and inspect the disposable object-library projection.",
        description=(
            "Install and inspect <os-root>/lib as a disposable, receipt-backed "
            "projection of the canonical external object-library source."
        ),
    )
    commands = parser.add_subparsers(dest="library_command", required=True)

    init_parser = commands.add_parser(
        "init",
        help=(
            "Compatibility/bootstrap only: plan or create an empty lib/ layout; "
            "normal installed projections use 'library install'."
        ),
    )
    _root_argument(init_parser)
    init_parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the empty compatibility layout.",
    )
    init_parser.add_argument(
        "--git",
        action="store_true",
        help=(
            "Legacy source-fixture compatibility only; normal installed "
            "projections never contain lib/.git."
        ),
    )
    init_parser.set_defaults(handler=handle_init)

    refresh_parser = commands.add_parser("refresh", help="Plan or rebuild generated library registries.")
    _root_argument(refresh_parser)
    refresh_parser.add_argument("--apply", action="store_true", help="Write generated registries.")
    refresh_parser.set_defaults(handler=handle_refresh)

    create_parser = commands.add_parser(
        "create",
        help=(
            "Compatibility/migration only: plan or create one manifest-backed "
            "object before moving it to the canonical source library."
        ),
    )
    _root_argument(create_parser)
    create_parser.add_argument("kind", choices=OBJECT_KINDS)
    create_parser.add_argument("object_id")
    create_parser.add_argument("--level", choices=("root", "domain", "project"), default="root")
    create_parser.add_argument("--domain")
    create_parser.add_argument("--project")
    create_parser.add_argument("--title")
    create_parser.add_argument("--description", default="")
    create_parser.add_argument("--entrypoint")
    create_parser.add_argument("--apply", action="store_true", help="Create the object and refresh registries.")
    create_parser.set_defaults(handler=handle_create)

    list_parser = commands.add_parser("list", help="List objects from the compact canonical registry.")
    _root_argument(list_parser)
    list_parser.add_argument("--kind", choices=OBJECT_KINDS)
    list_parser.add_argument("--level", choices=("root", "domain", "project"))
    list_parser.add_argument("--domain")
    list_parser.add_argument("--project")
    list_parser.add_argument("--status")
    list_parser.set_defaults(handler=handle_list)

    show_parser = commands.add_parser("show", help="Show one canonical object.")
    _root_argument(show_parser)
    show_parser.add_argument("object_id")
    show_parser.set_defaults(handler=handle_show)

    doctor_parser = commands.add_parser(
        "doctor",
        help="Validate manifests, registries, and source/install provenance.",
    )
    _root_argument(doctor_parser)
    doctor_parser.set_defaults(handler=handle_doctor)

    install_parser = commands.add_parser(
        "install",
        help="Plan or atomically install a validated library revision from Git.",
    )
    _root_argument(install_parser)
    install_parser.add_argument(
        "--repository",
        help=(
            "Git repository used as the canonical library source. Required unless "
            f"${LIBRARY_REPOSITORY_ENV} is set."
        ),
    )
    install_parser.add_argument("--ref", default="main", help="Branch, tag, or commit to install.")
    install_parser.add_argument(
        "--replace-dirty",
        action="store_true",
        help="Migration-only override after uncommitted installed definitions are captured.",
    )
    install_parser.add_argument(
        "--apply",
        action="store_true",
        help="Clone, validate, atomically replace lib/, and write a receipt.",
    )
    install_parser.set_defaults(handler=handle_install)

    verify_parser = commands.add_parser(
        "verify-install",
        help="Verify installed lib/ against its external source receipt.",
    )
    _root_argument(verify_parser)
    verify_parser.set_defaults(handler=handle_verify_install)

    rollback_parser = commands.add_parser(
        "rollback-install",
        help="Plan or restore the latest receipt-backed installed-library generation.",
    )
    _root_argument(rollback_parser)
    rollback_parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Atomically restore the retained prior projection and its exact "
            "verification receipt."
        ),
    )
    rollback_parser.set_defaults(handler=handle_rollback_install)

    build_parser = commands.add_parser(
        "build",
        help="Run the source-owned deterministic builder for Auto-Dev Develop.",
    )
    build_parser.add_argument("--source-root", required=True, help="Object Library source checkout.")
    build_parser.add_argument("--output-dir")
    build_parser.add_argument("--require-clean", action="store_true")
    build_parser.add_argument("--require-revision", action="store_true")
    build_parser.set_defaults(handler=handle_build)

    validate_parser = commands.add_parser(
        "validate",
        help="Run source or exact-artifact validation for Auto-Dev QA.",
    )
    validate_parser.add_argument("--source-root", required=True, help="Object Library source checkout.")
    validate_parser.add_argument("--receipt")
    validate_parser.add_argument("--archive")
    validate_parser.add_argument("--write-receipt")
    validate_parser.set_defaults(handler=handle_validate)

    release_boundary = (
        "Prepare release-notes evidence only; protected CI/operator owns publication."
    )
    release_parser = commands.add_parser(
        "release",
        help=release_boundary,
        description=release_boundary,
    )
    release_parser.add_argument("--source-root", required=True, help="Object Library source checkout.")
    release_parser.add_argument("--output")
    release_parser.set_defaults(handler=handle_release)

    document_boundary = (
        "Verify provider release readback for the Auto-Dev Document rerun; "
        "does not publish."
    )
    document_parser = commands.add_parser(
        "document",
        help=document_boundary,
        description=document_boundary,
    )
    document_parser.add_argument("--source-root", required=True, help="Object Library source checkout.")
    document_parser.add_argument("--input", required=True, help="Provider release-readback JSON.")
    document_parser.add_argument(
        "--required-asset",
        action="append",
        required=True,
        help="Required published asset name; repeat for each asset.",
    )
    document_parser.add_argument("--notes")
    document_parser.add_argument("--write-receipt")
    document_parser.set_defaults(handler=handle_document)

    migrate_parser = commands.add_parser(
        "migrate-legacy",
        help="Plan or copy legacy definitions into lib/ using the first-class registry.",
    )
    _root_argument(migrate_parser)
    migrate_parser.add_argument("--apply", action="store_true", help="Copy definitions and write manifests.")
    migrate_parser.set_defaults(handler=handle_migrate)
