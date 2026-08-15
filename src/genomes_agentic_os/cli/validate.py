"""CLI commands that validate the installed OS root."""

from __future__ import annotations

import argparse
import math
import multiprocessing
from queue import Empty
import sys
from pathlib import Path
import time
from typing import Any, Callable

from ..cli_help import AosHelpFormatter, env_epilog
from ..validate import VALIDATION_SCOPES, StrictFinding, validate_scope, validate_schemas_strict

from ._shared import DEFAULT_ROOT


DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_NO_PROGRESS_SECONDS = 60.0
DEFAULT_PROGRESS_INTERVAL_SECONDS = 5.0


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return seconds


def _validation_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    try:
        def report_progress(stage: str) -> None:
            queue.put(("progress", {"scope": scope, "stage": stage, "status": "running"}))

        queue.put(("progress", {"scope": scope, "stage": scope, "status": "started"}))
        result = validate_scope(root, scope, progress=report_progress)
        queue.put(("progress", {"scope": scope, "stage": scope, "status": "completed"}))
        strict_findings: list[StrictFinding] = []
        if strict:
            queue.put(("progress", {"scope": scope, "stage": "schemas", "status": "started"}))
            strict_findings = validate_schemas_strict(
                Path(root).expanduser(),
                progress=report_progress,
            )
            queue.put(("progress", {"scope": scope, "stage": "schemas", "status": "completed"}))
        queue.put(
            (
                "result",
                {
                    "root": str(result.root),
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "strict_findings": [finding.as_dict() for finding in strict_findings],
                },
            )
        )
    except BaseException as exc:  # Child failures must become deterministic CLI diagnostics.
        queue.put(("error", {"type": type(exc).__name__, "message": str(exc)}))


def _terminate_process(process: Any) -> None:
    if not process.is_alive():
        process.join(timeout=0.1)
        return
    process.terminate()
    process.join(timeout=1.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=1.0)


def _run_bounded_validation(
    *,
    root: str,
    scope: str,
    strict: bool,
    timeout_seconds: float,
    no_progress_seconds: float,
    progress_interval_seconds: float,
    progress: Callable[[str], None],
) -> tuple[int, dict[str, Any] | None, str | None]:
    try:
        context = multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover - non-POSIX fallback
        context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_validation_worker, args=(queue, root, scope, strict))
    process.start()
    started = last_worker_progress = time.monotonic()
    next_observation = started + progress_interval_seconds
    last_stage = scope
    try:
        while True:
            now = time.monotonic()
            elapsed = now - started
            silent_for = now - last_worker_progress
            if elapsed >= timeout_seconds:
                _terminate_process(process)
                return 124, None, f"timeout after {timeout_seconds:g}s (last_stage={last_stage})"
            if silent_for >= no_progress_seconds:
                _terminate_process(process)
                return 124, None, f"no progress for {no_progress_seconds:g}s (last_stage={last_stage})"
            if now >= next_observation:
                progress(
                    f"progress: scope={scope} stage={last_stage} status=running "
                    f"elapsed={elapsed:.1f}s"
                )
                next_observation = now + progress_interval_seconds
            try:
                queue_wait = min(
                    0.1,
                    timeout_seconds - elapsed,
                    no_progress_seconds - silent_for,
                    max(0.001, next_observation - now),
                )
                kind, payload = queue.get(timeout=queue_wait)
            except Empty:
                if not process.is_alive():
                    try:
                        kind, payload = queue.get_nowait()
                    except Empty:
                        return 2, None, f"worker exited without a receipt (exit_code={process.exitcode})"
                else:
                    continue
            if kind == "progress":
                last_worker_progress = time.monotonic()
                last_stage = str(payload.get("stage") or scope)
                progress(
                    f"progress: scope={scope} stage={last_stage} "
                    f"status={payload.get('status', 'unknown')}"
                )
                continue
            process.join(timeout=1.0)
            if kind == "result":
                return 0, payload, None
            return 2, None, f"worker failed: {payload.get('type')}: {payload.get('message')}"
    except KeyboardInterrupt:
        _terminate_process(process)
        return 130, None, f"cancelled safely (last_stage={last_stage})"
    finally:
        if process.is_alive():
            _terminate_process(process)
        queue.close()


def handle_validate(args: argparse.Namespace) -> int:
    scope = getattr(args, "scope", "root")
    exit_code, payload, diagnostic = _run_bounded_validation(
        root=args.root,
        scope=scope,
        strict=getattr(args, "strict", False),
        timeout_seconds=args.timeout_seconds,
        no_progress_seconds=args.no_progress_seconds,
        progress_interval_seconds=args.progress_interval_seconds,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    if diagnostic:
        print(f"error: validation scope={scope} terminated: {diagnostic}", file=sys.stderr)
        return exit_code
    assert payload is not None
    errors = payload["errors"]
    warnings = payload["warnings"]
    strict_findings = payload["strict_findings"]
    if not errors and not strict_findings:
        print(f"valid: {Path(args.root).expanduser()} (scope={scope})")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for finding in strict_findings:
        print(
            f"strict: [{finding['schema']}] {finding['path']}: {finding['message']}",
            file=sys.stderr,
        )
    return 1


def register(subparsers) -> None:
    """Register the validate command group."""
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
                ("agentic-os validate --scope registries", "Validate one root surface."),
                ("agentic-os validate --strict", "Also validate YAML files against JSON schemas."),
            ],
        ),
        formatter_class=AosHelpFormatter,
    )
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path (default: %(default)s).")
    validate_parser.add_argument(
        "--scope",
        choices=VALIDATION_SCOPES,
        default="root",
        help="Validation surface to run (default: %(default)s).",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also validate structured files against JSON schemas in schemas/.",
    )
    validate_parser.add_argument(
        "--timeout-seconds",
        type=_positive_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Hard wall-clock bound before safe termination (default: %(default)ss).",
    )
    validate_parser.add_argument(
        "--no-progress-seconds",
        type=_positive_seconds,
        default=DEFAULT_NO_PROGRESS_SECONDS,
        help="Terminate when the validation worker emits no progress for this long (default: %(default)ss).",
    )
    validate_parser.add_argument(
        "--progress-interval-seconds",
        type=_positive_seconds,
        default=DEFAULT_PROGRESS_INTERVAL_SECONDS,
        help="Emit an observation while validation is still running (default: %(default)ss).",
    )
    validate_parser.set_defaults(handler=handle_validate)
