"""CLI for polymorphic Auto-Dev artifact contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..artifact_contracts import (
    ArtifactContractError,
    artifact_contract_doctor,
    prepare_artifact_apply,
    record_artifact_readback,
    render_artifact,
    resolve_artifact_contract,
    validate_rendered_artifact,
)
from ._shared import DEFAULT_ROOT, yaml_dump


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, indent=2, sort_keys=True) if json_output else yaml_dump(value))


def _scope(args: argparse.Namespace) -> dict:
    return {
        "domain": getattr(args, "domain", None),
        "project": getattr(args, "project", None),
        "overlays": getattr(args, "overlay", None) or [],
    }


def handle_resolve(args: argparse.Namespace) -> int:
    result = resolve_artifact_contract(args.root, args.provider, args.artifact_type, **_scope(args))
    if not args.explain:
        result = {
            "schema": result["schema"],
            "provider": result["provider"],
            "artifact_type": result["artifact_type"],
            "domain": result["domain"],
            "project": result["project"],
            "fingerprint": result["fingerprint"],
            "effective": result["effective"],
            "sources": [item["source_ref"] for item in result["sources"]],
        }
    _print(result, json_output=args.json)
    return 0


def handle_render(args: argparse.Namespace) -> int:
    result = render_artifact(
        args.root,
        args.provider,
        args.artifact_type,
        args.input,
        **_scope(args),
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = Path(args.receipt).expanduser().resolve() if args.receipt else output.with_suffix(output.suffix + ".receipt.json")
    render_receipt = {
        "schema": "artifact-render-receipt/v1",
        "provider": result["provider"],
        "artifact_type": result["artifact_type"],
        "output": str(output),
        "contract_fingerprint": result["contract_fingerprint"],
        "evidence_sha256": result["evidence_sha256"],
        "rendered_at": result["rendered_at"],
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(render_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print({**render_receipt, "receipt": str(receipt)}, json_output=args.json)
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    result = validate_rendered_artifact(args.artifact)
    receipt = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt
        else Path(args.artifact).expanduser().resolve().with_suffix(".validation.json")
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print({**result, "receipt": str(receipt)}, json_output=args.json)
    return 0 if result["valid"] else 1


def handle_apply(args: argparse.Namespace) -> int:
    result = prepare_artifact_apply(
        args.root,
        args.artifact,
        target=args.target,
        execute=args.execute,
        receipt_path=args.receipt,
        approval_receipt=args.approval_receipt,
        target_receipt=args.target_receipt,
    )
    _print(result, json_output=args.json)
    return 0


def handle_readback(args: argparse.Namespace) -> int:
    result = record_artifact_readback(
        args.root,
        args.apply_receipt,
        readback_receipt=args.readback_receipt,
    )
    _print(result, json_output=args.json)
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    result = artifact_contract_doctor(args.root, domain=args.domain, project=args.project)
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def _output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _scope_arguments(parser: argparse.ArgumentParser, *, overlays: bool = True) -> None:
    parser.add_argument("--domain", help="Optional domain policy scope.")
    parser.add_argument("--project", help="Optional project policy scope; requires --domain.")
    if overlays:
        parser.add_argument("--overlay", action="append", help="Invocation policy overlay Markdown; repeatable.")
    parser.add_argument("--root", default=DEFAULT_ROOT)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "artifacts",
        help="Resolve, render, validate, and govern polymorphic SDLC artifacts.",
        description=(
            "Compose root, domain, project, and invocation Markdown contracts. Rendering is local and read-only; "
            "external apply emits a provider-adapter handoff that must be completed and read back by the registered tool."
        ),
    )
    sub = parser.add_subparsers(dest="artifacts_command", required=True)

    resolve = sub.add_parser("resolve", help="Show the effective provider/type contract.")
    resolve.add_argument("--provider", required=True)
    resolve.add_argument("--type", dest="artifact_type", required=True)
    resolve.add_argument("--explain", action="store_true", help="Include ordered candidates, conflicts, and provenance.")
    _scope_arguments(resolve)
    _output(resolve)
    resolve.set_defaults(handler=handle_resolve)

    render = sub.add_parser("render", help="Render a provider-native local draft and receipt.")
    render.add_argument("--provider", required=True)
    render.add_argument("--type", dest="artifact_type", required=True)
    render.add_argument("--input", required=True, help="Evidence mapping in JSON/YAML, or a Markdown summary.")
    render.add_argument("--output", required=True, help="Destination for the rendered-artifact/v1 JSON envelope.")
    render.add_argument("--receipt", help="Optional render receipt path; defaults beside --output.")
    _scope_arguments(render)
    _output(render)
    render.set_defaults(handler=handle_render)

    validate = sub.add_parser("validate", help="Validate a rendered draft against safety and content rules.")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--receipt", help="Optional validation receipt path.")
    _output(validate)
    validate.set_defaults(handler=handle_validate)

    apply = sub.add_parser("apply", help="Apply filesystem output or prepare an external provider handoff.")
    apply.add_argument("--artifact", required=True)
    apply.add_argument("--target", help="Verified filesystem path or provider destination identifier.")
    apply.add_argument("--receipt", required=True, help="Durable local apply/handoff receipt under the OS root.")
    apply.add_argument("--approval-receipt", help="artifact-approval/v1 JSON receipt; required for external providers.")
    apply.add_argument("--target-receipt", help="artifact-target-verification/v1 JSON receipt; required for external providers.")
    apply.add_argument("--execute", action="store_true", help="Required explicit mutation/handoff approval gate.")
    apply.add_argument("--root", default=DEFAULT_ROOT)
    _output(apply)
    apply.set_defaults(handler=handle_apply)

    readback = sub.add_parser("record-readback", help="Close a provider handoff after live target readback.")
    readback.add_argument("--apply-receipt", required=True)
    readback.add_argument("--readback-receipt", required=True, help="artifact-provider-readback/v1 receipt containing normalized live content.")
    readback.add_argument("--root", default=DEFAULT_ROOT)
    _output(readback)
    readback.set_defaults(handler=handle_readback)

    doctor = sub.add_parser("doctor", help="Validate contracts, fallback coverage, and representative resolutions.")
    _scope_arguments(doctor, overlays=False)
    _output(doctor)
    doctor.set_defaults(handler=handle_doctor)
