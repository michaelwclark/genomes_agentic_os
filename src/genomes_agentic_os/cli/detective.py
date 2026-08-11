"""CLI for version-aware Auto-Dev Detective investigations."""

from __future__ import annotations

import argparse
import json

from ..investigation_contracts import (
    analyze_investigation,
    investigation_contract_doctor,
    investigation_status,
    pause_investigation,
    record_deployed_version,
    record_investigation_evidence,
    record_source_disposition,
    render_investigation_artifact,
    resolve_investigation_contract,
    resume_investigation,
    start_investigation,
)
from ._shared import DEFAULT_ROOT, yaml_dump


def _print(value: dict, *, json_output: bool) -> None:
    print(json.dumps(value, indent=2, sort_keys=True) if json_output else yaml_dump(value))


def _output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _scope(parser: argparse.ArgumentParser, *, include_context: bool = True) -> None:
    if include_context:
        parser.add_argument("--domain", help="Optional domain investigation pack.")
        parser.add_argument("--project", help="Optional project pack; requires --domain.")
        parser.add_argument("--environment", help="Runtime environment whose deployed version must be resolved.")
        parser.add_argument("--output-type", default="investigation-report")
        parser.add_argument("--overlay", action="append", help="Invocation policy overlay Markdown; repeatable.")
        parser.add_argument(
            "--touched-path",
            action="append",
            help="Normalized repository-relative path touched by the investigation; repeatable.",
        )
        parser.add_argument(
            "--subject",
            action="append",
            help="Declared semantic investigation subject, such as rulebook or caller; repeatable.",
        )
        parser.add_argument(
            "--rulebook-id",
            action="append",
            help=(
                "Exact Rules Engine rulebook identity used to resolve a concrete "
                "catalog kit; repeatable only when one unambiguous rulebook is in scope."
            ),
        )
    parser.add_argument("--root", default=DEFAULT_ROOT)


def handle_resolve(args: argparse.Namespace) -> int:
    result = resolve_investigation_contract(
        args.root,
        trigger=args.trigger,
        environment=args.environment,
        output_type=args.output_type,
        domain=args.domain,
        project=args.project,
        overlays=args.overlay or [],
        touched_paths=args.touched_path or [],
        subjects=args.subject or [],
        rulebook_ids=args.rulebook_id or [],
    )
    if not args.explain:
        result = {
            "schema": result["schema"],
            "trigger": result["trigger"],
            "environment": result["environment"],
            "output_type": result["output_type"],
            "domain": result["domain"],
            "project": result["project"],
            "version_gate": result["version_gate"],
            "selection": result["selection"],
            "fingerprint": result["fingerprint"],
            "source_ids": result["effective"]["source_ids"],
            "sources": [item["source_ref"] for item in result["sources"]],
        }
    _print(result, json_output=args.json)
    return 0


def handle_start(args: argparse.Namespace) -> int:
    result = start_investigation(
        args.root,
        args.input,
        trigger=args.trigger,
        environment=args.environment,
        tenant=args.tenant,
        output_type=args.output_type,
        domain=args.domain,
        project=args.project,
        overlays=args.overlay or [],
        touched_paths=args.touched_path or [],
        subjects=args.subject or [],
        rulebook_ids=args.rulebook_id or [],
        run_id=args.run_id,
        run_dir=args.run_dir,
    )
    _print(result, json_output=args.json)
    return 0


def handle_status(args: argparse.Namespace) -> int:
    _print(investigation_status(args.root, args.run_dir), json_output=args.json)
    return 0


def handle_record_version(args: argparse.Namespace) -> int:
    result = record_deployed_version(
        args.root,
        args.run_dir,
        authority_receipt=args.authority_receipt,
    )
    _print(result, json_output=args.json)
    return 0


def handle_record_evidence(args: argparse.Namespace) -> int:
    result = record_investigation_evidence(
        args.root,
        args.run_dir,
        source_id=args.source,
        summary=args.summary,
        facts=args.fact or [],
        limitations=args.limitation or [],
        authority=args.authority,
        evidence_ref=args.evidence_ref,
        evidence_file=args.file,
        captured_at=args.captured_at,
        fresh_until=args.fresh_until,
        prerequisites_satisfied=args.prerequisite or [],
    )
    _print(result, json_output=args.json)
    return 0


def handle_pause(args: argparse.Namespace) -> int:
    result = pause_investigation(
        args.root,
        args.run_dir,
        reason=args.reason,
        resume_when=args.resume_when,
        detail=args.detail,
    )
    _print(result, json_output=args.json)
    return 0


def handle_source_status(args: argparse.Namespace) -> int:
    result = record_source_disposition(
        args.root,
        args.run_dir,
        source_id=args.source,
        status=args.status,
        reason=args.reason,
        evidence_ref=args.evidence_ref,
    )
    _print(result, json_output=args.json)
    return 0


def handle_resume(args: argparse.Namespace) -> int:
    _print(
        resume_investigation(args.root, args.run_dir, availability_receipt=args.availability_receipt),
        json_output=args.json,
    )
    return 0


def handle_analyze(args: argparse.Namespace) -> int:
    result = analyze_investigation(args.root, args.run_dir, args.analysis, conclude=False)
    _print(result, json_output=args.json)
    return 0


def handle_conclude(args: argparse.Namespace) -> int:
    result = analyze_investigation(args.root, args.run_dir, args.analysis, conclude=True)
    _print(result, json_output=args.json)
    return 0


def handle_render(args: argparse.Namespace) -> int:
    result = render_investigation_artifact(
        args.root,
        args.run_dir,
        provider=args.provider,
        artifact_type=args.artifact_type,
        output_path=args.output,
        overlays=args.overlay or [],
    )
    _print(result, json_output=args.json)
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    result = investigation_contract_doctor(args.root)
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def _run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", required=True, help="Investigation run folder under the Agentic OS root.")
    parser.add_argument("--root", default=DEFAULT_ROOT)
    _output(parser)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "detective",
        help="Run version-first, evidence-receipted bug and RCA investigations.",
        description=(
            "Resolve root/domain/project investigation packs, pin the deployed environment version, gather bounded "
            "evidence, pause unavailable transports without retry storms, and render conclusions through artifact contracts."
        ),
    )
    sub = parser.add_subparsers(dest="detective_command", required=True)

    resolve = sub.add_parser("resolve", help="Explain the effective investigation plan and evidence sources.")
    resolve.add_argument("--trigger", required=True)
    resolve.add_argument("--explain", action="store_true")
    _scope(resolve)
    _output(resolve)
    resolve.set_defaults(handler=handle_resolve)

    start = sub.add_parser("start", help="Create an idempotent local investigation packet.")
    start.add_argument("--input", required=True, help="JSON/YAML signal mapping or Markdown report.")
    start.add_argument("--trigger", required=True)
    start.add_argument("--tenant")
    start.add_argument("--run-id")
    start.add_argument("--run-dir", help="Optional explicit run folder under the Agentic OS root.")
    _scope(start)
    _output(start)
    start.set_defaults(handler=handle_start)

    status = sub.add_parser("status", help="Read compact state, version gate, source coverage, and receipts.")
    _run(status)
    status.set_defaults(handler=handle_status)

    version = sub.add_parser("record-version", help="Resolve the deployed environment version before evidence gathering.")
    version.add_argument("--authority-receipt", required=True, help="Verified investigation-version-authority/v1 JSON readback.")
    _run(version)
    version.set_defaults(handler=handle_record_version)

    evidence = sub.add_parser("record-evidence", help="Append one bounded evidence record and update source coverage.")
    evidence.add_argument("--source", required=True, help="Source id declared by the pinned investigation policy.")
    evidence.add_argument("--summary", required=True)
    evidence.add_argument("--fact", action="append")
    evidence.add_argument("--limitation", action="append")
    evidence.add_argument("--authority")
    evidence.add_argument("--evidence-ref")
    evidence.add_argument("--file", help="Optional evidence file; only name, size, and SHA-256 are receipted.")
    evidence.add_argument("--captured-at")
    evidence.add_argument("--fresh-until")
    evidence.add_argument("--prerequisite", action="append", help="Exact non-automatic policy prerequisite satisfied; repeatable.")
    _run(evidence)
    evidence.set_defaults(handler=handle_record_evidence)

    source_status = sub.add_parser("source-status", help="Disposition a planned source as unavailable, deferred, or not applicable.")
    source_status.add_argument("--source", required=True)
    source_status.add_argument("--status", required=True, choices=("not-applicable", "unavailable", "deferred"))
    source_status.add_argument("--reason", required=True)
    source_status.add_argument("--evidence-ref", required=True)
    _run(source_status)
    source_status.set_defaults(handler=handle_source_status)

    pause = sub.add_parser("pause", help="Pause once on VPN/provider/environment availability.")
    pause.add_argument("--reason", required=True)
    pause.add_argument("--resume-when", required=True)
    pause.add_argument("--detail")
    _run(pause)
    pause.set_defaults(handler=handle_pause)

    resume = sub.add_parser("resume", help="Resume the same run after fresh availability evidence.")
    resume.add_argument("--availability-receipt", required=True, help="Verified investigation-availability/v1 probe receipt.")
    _run(resume)
    resume.set_defaults(handler=handle_resume)

    analyze = sub.add_parser("analyze", help="Record facts, hypotheses, contradictions, and evidence gaps.")
    analyze.add_argument("--analysis", required=True, help="JSON/YAML analysis mapping.")
    _run(analyze)
    analyze.set_defaults(handler=handle_analyze)

    conclude = sub.add_parser("conclude", help="Write the final evidence-backed local result.")
    conclude.add_argument("--analysis", required=True, help="JSON/YAML analysis with facts and conclusion.")
    _run(conclude)
    conclude.set_defaults(handler=handle_conclude)

    render = sub.add_parser("render", help="Render a concluded result through Auto-Dev Create Artifacts.")
    render.add_argument("--provider", required=True)
    render.add_argument("--type", dest="artifact_type", required=True)
    render.add_argument("--output", help="Optional rendered-artifact JSON path under the Agentic OS root.")
    render.add_argument("--overlay", action="append", help="Artifact contract overlay; repeatable.")
    _run(render)
    render.set_defaults(handler=handle_render)

    doctor = sub.add_parser("doctor", help="Validate all root/domain/project investigation policy packs.")
    doctor.add_argument("--root", default=DEFAULT_ROOT)
    _output(doctor)
    doctor.set_defaults(handler=handle_doctor)
