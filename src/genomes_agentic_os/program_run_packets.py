"""Immutable, cross-program workflow run packets.

The packet is an observability contract, not a scheduler or a second workflow
state machine.  Existing program, workflow, automation, and Execution Fabric
records remain authoritative; adapters append their receipt-backed observations
here so one program run can be inspected as a coherent, ordered packet.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import uuid


PROGRAM_RUN_PACKET_SCHEMA = "program-run-packet/v1"
PROGRAM_RUN_PACKET_SUMMARY_SCHEMA = "program-run-packet-summary/v1"
PROGRAM_RUN_EVENT_SCHEMA = "program-run-event/v1"
PROGRAM_RUN_PACKET_ROOT = Path("harness/shared_factory/06-runs-and-logs/program-runs")

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,180}$")
_WORKFLOW_FILENAME = re.compile(r"^(?P<sequence>\d+)-.+\.json$")
_TRANSPORT_MODES = {"execution_fabric", "queue", "direct", "manual"}
_EXECUTION_STATUSES = {"completed", "failed", "timed_out", "cancelled"}
_QUALITY_STATUSES = {"passed", "failed", "not_applicable", "unknown"}


class ProgramRunPacketError(ValueError):
    """Raised when a packet would be ambiguous, mutable, or semantically invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ProgramRunPacketError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProgramRunPacketError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ProgramRunPacketError(f"{label} must be a JSON object: {path}")
    return value


def _identifier(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ProgramRunPacketError(
            f"{label} must contain only letters, numbers, dot, underscore, colon, or hyphen"
        )
    return text


def _timestamp(value: str | None, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProgramRunPacketError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProgramRunPacketError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ProgramRunPacketError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _time_delta_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    seconds = (finish - start).total_seconds()
    if seconds < 0:
        raise ProgramRunPacketError("workflow finished_at cannot precede started_at")
    return seconds


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ProgramRunPacketError("workflow id cannot produce an empty packet filename")
    return slug


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _normalize_transport(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProgramRunPacketError("execution transport must be an object")
    driver = str(raw.get("driver") or "").strip()
    mode = str(raw.get("mode") or "").strip()
    if not driver:
        raise ProgramRunPacketError("execution transport requires driver")
    if mode not in _TRANSPORT_MODES:
        raise ProgramRunPacketError(
            "execution transport mode must be execution_fabric, queue, direct, or manual"
        )
    return {
        "driver": driver,
        "mode": mode,
        "queue_ref": str(raw.get("queue_ref") or "").strip() or None,
        "worker_ref": str(raw.get("worker_ref") or "").strip() or None,
        "attempt_ref": str(raw.get("attempt_ref") or "").strip() or None,
        "run_ref": str(raw.get("run_ref") or "").strip() or None,
    }


def _normalize_config_refs(raw: Sequence[Mapping[str, Any] | str]) -> list[dict[str, Any]]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ProgramRunPacketError("config_refs must be a list")
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            row: dict[str, Any] = {"kind": "configuration", "ref": item.strip(), "sha256": None}
        elif isinstance(item, Mapping):
            row = {
                "kind": str(item.get("kind") or "configuration").strip(),
                "ref": str(item.get("ref") or "").strip(),
                "sha256": str(item.get("sha256") or "").strip() or None,
            }
        else:
            raise ProgramRunPacketError("each config_refs entry must be a string or object")
        if not row["kind"] or not row["ref"]:
            raise ProgramRunPacketError("each config_refs entry requires kind and ref")
        if row["sha256"] and not re.fullmatch(r"[a-f0-9]{64}", str(row["sha256"]).lower()):
            raise ProgramRunPacketError("config_refs sha256 must be a SHA-256 digest when supplied")
        if row not in normalized:
            normalized.append(row)
    return normalized


def _normalize_execution(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProgramRunPacketError("workflow execution must be an object")
    status = str(raw.get("status") or "").strip()
    if status not in _EXECUTION_STATUSES:
        raise ProgramRunPacketError(
            "workflow execution status must be completed, failed, timed_out, or cancelled"
        )
    failure = raw.get("failure")
    if status == "completed":
        if failure not in (None, {}):
            raise ProgramRunPacketError("completed workflow execution cannot carry an execution failure")
        normalized_failure = None
    else:
        if not isinstance(failure, Mapping):
            raise ProgramRunPacketError("failed workflow execution requires a failure object")
        kind = str(failure.get("kind") or "").strip()
        reason = str(failure.get("reason") or "").strip()
        if not kind or not reason:
            raise ProgramRunPacketError("execution failure requires kind and reason")
        normalized_failure = {
            "kind": kind,
            "reason": reason,
            "receipt_ref": str(failure.get("receipt_ref") or "").strip() or None,
        }
    return {
        "status": status,
        "transport": _normalize_transport(
            raw.get("transport") if isinstance(raw.get("transport"), Mapping) else {}
        ),
        "failure": normalized_failure,
    }


def _normalize_quality(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProgramRunPacketError("workflow quality outcome must be an object")
    status = str(raw.get("status") or "").strip()
    if status not in _QUALITY_STATUSES:
        raise ProgramRunPacketError(
            "workflow quality status must be passed, failed, not_applicable, or unknown"
        )
    source_failures = raw.get("failures") or []
    if not isinstance(source_failures, list):
        raise ProgramRunPacketError("workflow quality failures must be a list")
    failures: list[dict[str, str | None]] = []
    for item in source_failures:
        if not isinstance(item, Mapping):
            raise ProgramRunPacketError("each quality failure must be an object")
        tracker_ref = str(item.get("tracker_ref") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not tracker_ref or not summary:
            raise ProgramRunPacketError("each quality failure requires tracker_ref and summary")
        failures.append(
            {
                "tracker_ref": tracker_ref,
                "summary": summary,
                "receipt_ref": str(item.get("receipt_ref") or "").strip() or None,
            }
        )
    if status == "failed" and not failures:
        raise ProgramRunPacketError(
            "a quality failure requires one or more tracker-backed failure records"
        )
    if status != "failed" and failures:
        raise ProgramRunPacketError("quality failures require quality status=failed")
    return {"status": status, "failures": failures}


def program_run_packet_path(root: str | Path, packet_id: str) -> Path:
    """Return one safe canonical packet folder beneath the OS runtime root."""

    os_root = Path(root).expanduser().resolve()
    packet = os_root / PROGRAM_RUN_PACKET_ROOT / _identifier(packet_id, "packet_id")
    if not packet.resolve().is_relative_to((os_root / PROGRAM_RUN_PACKET_ROOT).resolve()):
        raise ProgramRunPacketError("program run packet must remain beneath its canonical runtime root")
    return packet


def _packet_descriptor(root: Path, packet_dir: Path, program: Mapping[str, Any]) -> dict[str, str]:
    return {
        "schema": "program-run-packet-link/v1",
        "packet_id": str(program["packet_id"]),
        "packet_ref": packet_dir.relative_to(root).as_posix(),
        "program_ref": "00-program.json",
    }


def _events(packet_dir: Path) -> list[dict[str, Any]]:
    path = packet_dir / "events.jsonl"
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProgramRunPacketError(f"program run event is invalid JSON at line {index}") from exc
        if not isinstance(value, dict) or value.get("schema") != PROGRAM_RUN_EVENT_SCHEMA:
            raise ProgramRunPacketError(f"program run event is invalid at line {index}")
        result.append(value)
    return result


def _append_event_locked(
    packet_dir: Path,
    *,
    event_type: str,
    idempotency_key: str,
    occurred_at: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    for prior in _events(packet_dir):
        if prior.get("idempotency_key") != idempotency_key:
            continue
        if prior.get("type") != event_type or prior.get("payload") != dict(payload):
            raise ProgramRunPacketError(
                "program run event idempotency key already exists with different evidence"
            )
        return prior
    event = {
        "schema": PROGRAM_RUN_EVENT_SCHEMA,
        "type": event_type,
        "idempotency_key": idempotency_key,
        "occurred_at": occurred_at,
        "payload": dict(payload),
    }
    with (packet_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def _workflow_records(packet_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[int, Path, dict[str, Any]]] = []
    for path in packet_dir.glob("*.json"):
        if path.name == "00-program.json":
            continue
        match = _WORKFLOW_FILENAME.fullmatch(path.name)
        if not match:
            continue
        record = _read_json(path, "workflow packet record")
        if record.get("schema") != PROGRAM_RUN_PACKET_SCHEMA or record.get("record_type") != "workflow":
            raise ProgramRunPacketError(f"workflow packet record has the wrong schema: {path}")
        rows.append((int(match.group("sequence")), path, record))
    rows.sort(key=lambda item: item[0])
    expected = list(range(1, len(rows) + 1))
    if [sequence for sequence, _, _ in rows] != expected:
        raise ProgramRunPacketError("workflow packet records must use contiguous ordered sequences")
    return [(path, record) for _, path, record in rows]


def start_program_run_packet(
    root: str | Path,
    *,
    packet_id: str,
    program_id: str,
    run_id: str,
    subject: Mapping[str, Any],
    execution: Mapping[str, Any],
    config_refs: Sequence[Mapping[str, Any] | str],
    started_at: str | None = None,
    title: str | None = None,
) -> dict[str, str]:
    """Create one immutable program declaration or read back an exact replay."""

    os_root = Path(root).expanduser().resolve()
    packet_dir = program_run_packet_path(os_root, packet_id)
    declaration = {
        "schema": PROGRAM_RUN_PACKET_SCHEMA,
        "record_type": "program",
        "packet_id": _identifier(packet_id, "packet_id"),
        "program_id": _identifier(program_id, "program_id"),
        "run_id": _identifier(run_id, "run_id"),
        "title": str(title or "").strip() or None,
        "subject": dict(subject),
        "execution": _normalize_transport(execution),
        "config_refs": _normalize_config_refs(config_refs),
        "started_at": _timestamp(started_at or _utc_now(), "started_at"),
    }
    if not declaration["subject"]:
        raise ProgramRunPacketError("program run packet subject must be a non-empty object")
    with _file_lock(packet_dir / ".lock"):
        declaration_path = packet_dir / "00-program.json"
        if declaration_path.is_file():
            existing = _read_json(declaration_path, "program run packet declaration")
            immutable = {
                key: existing.get(key)
                for key in ("schema", "record_type", "packet_id", "program_id", "run_id", "subject", "execution", "config_refs")
            }
            expected = {
                key: declaration.get(key)
                for key in ("schema", "record_type", "packet_id", "program_id", "run_id", "subject", "execution", "config_refs")
            }
            if _canonical(immutable) != _canonical(expected):
                raise ProgramRunPacketError("program run packet already exists with different immutable inputs")
            declaration = existing
        else:
            _atomic_json(declaration_path, declaration)
            _append_event_locked(
                packet_dir,
                event_type="program.started",
                idempotency_key=f"{declaration['run_id']}:program:started",
                occurred_at=declaration["started_at"],
                payload={"program_id": declaration["program_id"]},
            )
    return _packet_descriptor(os_root, packet_dir, declaration)


def begin_program_workflow(
    root: str | Path,
    *,
    packet_id: str,
    workflow_id: str,
    transport: Mapping[str, Any],
    config_refs: Sequence[Mapping[str, Any] | str] = (),
    idempotency_key: str,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Append a durable start observation for one workflow in the packet."""

    os_root = Path(root).expanduser().resolve()
    packet_dir = program_run_packet_path(os_root, packet_id)
    workflow = _identifier(workflow_id, "workflow_id")
    event_at = _timestamp(started_at or _utc_now(), "started_at")
    with _file_lock(packet_dir / ".lock"):
        _read_json(packet_dir / "00-program.json", "program run packet declaration")
        if any(record.get("workflow_id") == workflow for _, record in _workflow_records(packet_dir)):
            raise ProgramRunPacketError("cannot start a workflow already sealed in the immutable packet")
        event = _append_event_locked(
            packet_dir,
            event_type="workflow.started",
            idempotency_key=_identifier(idempotency_key, "idempotency_key"),
            occurred_at=event_at,
            payload={
                "workflow_id": workflow,
                "transport": _normalize_transport(transport),
                "config_refs": _normalize_config_refs(config_refs),
            },
        )
    return event


def record_program_workflow(
    root: str | Path,
    *,
    packet_id: str,
    workflow_id: str,
    execution: Mapping[str, Any],
    quality: Mapping[str, Any],
    idempotency_key: str,
    finished_at: str | None = None,
    next_workflow_id: str | None = None,
    receipt_refs: Sequence[str] = (),
) -> dict[str, Any]:
    """Seal one workflow outcome, keeping execution and quality outcomes distinct."""

    os_root = Path(root).expanduser().resolve()
    packet_dir = program_run_packet_path(os_root, packet_id)
    workflow = _identifier(workflow_id, "workflow_id")
    finish = _timestamp(finished_at or _utc_now(), "finished_at")
    key = _identifier(idempotency_key, "idempotency_key")
    normalized_execution = _normalize_execution(execution)
    normalized_quality = _normalize_quality(quality)
    next_workflow = (
        _identifier(next_workflow_id, "next_workflow_id") if next_workflow_id else None
    )
    normalized_receipts = [str(ref).strip() for ref in receipt_refs if str(ref).strip()]
    input_sha256 = hashlib.sha256(
        _canonical(
            {
                "workflow_id": workflow,
                "execution": normalized_execution,
                "quality": normalized_quality,
                "finished_at": finish,
                "next_workflow_id": next_workflow,
                "receipt_refs": normalized_receipts,
            }
        ).encode("utf-8")
    ).hexdigest()
    with _file_lock(packet_dir / ".lock"):
        declaration = _read_json(packet_dir / "00-program.json", "program run packet declaration")
        records = _workflow_records(packet_dir)
        for path, prior in records:
            if prior.get("idempotency_key") != key:
                continue
            if prior.get("workflow_id") != workflow:
                raise ProgramRunPacketError("workflow idempotency key is already bound to another workflow")
            if prior.get("input_sha256") != input_sha256:
                raise ProgramRunPacketError(
                    "workflow idempotency key already exists with different immutable evidence"
                )
            return {"record": prior, "record_ref": path.relative_to(packet_dir).as_posix(), "created": False}
        if any(prior.get("workflow_id") == workflow for _, prior in records):
            raise ProgramRunPacketError("a workflow may be sealed only once per program run packet")
        starts = [
            event
            for event in _events(packet_dir)
            if event.get("type") == "workflow.started"
            and isinstance(event.get("payload"), Mapping)
            and event["payload"].get("workflow_id") == workflow
        ]
        if starts:
            started_at = _timestamp(str(starts[-1].get("occurred_at") or ""), "workflow started_at")
            timing_status = "observed"
        else:
            started_at = finish
            timing_status = "unobserved"
        previous_workflow = str(records[-1][1].get("workflow_id") or "") if records else None
        outcome = (
            "execution_failed"
            if normalized_execution["status"] != "completed"
            else "quality_failed"
            if normalized_quality["status"] == "failed"
            else "completed"
        )
        sequence = len(records) + 1
        record = {
            "schema": PROGRAM_RUN_PACKET_SCHEMA,
            "record_type": "workflow",
            "packet_id": declaration["packet_id"],
            "program_id": declaration["program_id"],
            "run_id": declaration["run_id"],
            "sequence": sequence,
            "workflow_id": workflow,
            "previous_workflow_id": previous_workflow,
            "next_workflow_id": next_workflow,
            "started_at": started_at,
            "finished_at": finish,
            "duration_seconds": _time_delta_seconds(started_at, finish),
            "timing_status": timing_status,
            "execution": normalized_execution,
            "quality": normalized_quality,
            "outcome": outcome,
            "receipt_refs": normalized_receipts,
            "idempotency_key": key,
            "input_sha256": input_sha256,
        }
        path = packet_dir / f"{sequence:02d}-{_slug(workflow)}.json"
        _atomic_json(path, record)
        _append_event_locked(
            packet_dir,
            event_type="workflow.completed",
            idempotency_key=f"{key}:completed",
            occurred_at=finish,
            payload={"workflow_id": workflow, "record_ref": path.name, "outcome": outcome},
        )
    return {"record": record, "record_ref": path.relative_to(packet_dir).as_posix(), "created": True}


def read_program_run_packet(root: str | Path, packet_id: str) -> dict[str, Any]:
    """Return a derived packet summary; metrics never mutate immutable evidence."""

    os_root = Path(root).expanduser().resolve()
    packet_dir = program_run_packet_path(os_root, packet_id)
    declaration = _read_json(packet_dir / "00-program.json", "program run packet declaration")
    records = [record for _, record in _workflow_records(packet_dir)]
    events = _events(packet_dir)
    completed = {str(record.get("workflow_id") or "") for record in records}
    running = [
        str(event.get("payload", {}).get("workflow_id") or "")
        for event in events
        if event.get("type") == "workflow.started"
        and isinstance(event.get("payload"), Mapping)
        and str(event["payload"].get("workflow_id") or "") not in completed
    ]
    execution_failures = [
        record for record in records if record.get("execution", {}).get("status") != "completed"
    ]
    quality_failures = [
        record for record in records if record.get("quality", {}).get("status") == "failed"
    ]
    observed_durations = [
        float(record["duration_seconds"])
        for record in records
        if record.get("timing_status") == "observed" and record.get("duration_seconds") is not None
    ]
    last = records[-1] if records else None
    state = (
        "execution_failed"
        if execution_failures
        else "quality_failed"
        if quality_failures
        else "running"
        if running
        else "completed"
        if records
        else "started"
    )
    return {
        "schema": PROGRAM_RUN_PACKET_SUMMARY_SCHEMA,
        "packet": declaration,
        "packet_ref": packet_dir.relative_to(os_root).as_posix(),
        "workflows": records,
        "metrics": {
            "workflow_count": len(records),
            "execution_failure_count": len(execution_failures),
            "quality_failure_count": len(quality_failures),
            "observed_duration_seconds": sum(observed_durations),
            "timed_workflow_count": len(observed_durations),
        },
        "state": state,
        "last_workflow": last.get("workflow_id") if last else None,
        "next_workflow": last.get("next_workflow_id") if last else (running[-1] if running else None),
        "running_workflows": running,
    }
