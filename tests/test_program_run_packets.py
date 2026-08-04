from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from genomes_agentic_os.program_run_packets import (
    PROGRAM_RUN_PACKET_ROOT,
    ProgramRunPacketError,
    begin_program_workflow,
    read_program_run_packet,
    record_program_workflow,
    start_program_run_packet,
)


def _transport() -> dict[str, str | None]:
    return {
        "driver": "development_delivery",
        "mode": "execution_fabric",
        "queue_ref": "queue:agentic-release",
        "worker_ref": "worker:qa-1",
        "attempt_ref": "attempt:1",
        "run_ref": "run:cc-412",
    }


def _packet(root: Path, packet_id: str = "20260803-CC-412-release") -> str:
    start_program_run_packet(
        root,
        packet_id=packet_id,
        program_id="genomes_agentic_release",
        run_id="20260803-cc-412",
        title="Genomes Agentic Release",
        subject={"tracker_ref": "linear:CC-412", "family": "genomes_agentic"},
        execution=_transport(),
        config_refs=[
            {
                "kind": "domain_auto_dev",
                "ref": "domains/clarks_consulting/config/auto_dev/family.yml",
                "sha256": "a" * 64,
            }
        ],
        started_at="2026-08-03T06:00:00Z",
    )
    return packet_id


def test_packet_keeps_quality_failures_distinct_from_execution_failures(
    tmp_path: Path,
) -> None:
    packet_id = _packet(tmp_path)
    begin_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="source_qa",
        transport=_transport(),
        idempotency_key="cc-412:source-qa:started",
        started_at="2026-08-03T06:00:10Z",
    )
    result = record_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="source_qa",
        execution={"status": "completed", "transport": _transport()},
        quality={
            "status": "failed",
            "failures": [
                {
                    "tracker_ref": "linear:CC-415",
                    "summary": "Cross-repository install contract failed.",
                    "receipt_ref": "artifacts/qa/source-qa.json",
                }
            ],
        },
        idempotency_key="cc-412:source-qa:completed",
        finished_at="2026-08-03T06:01:10Z",
        next_workflow_id="remediate_quality_failure",
        receipt_refs=["artifacts/qa/source-qa.json"],
    )

    summary = read_program_run_packet(tmp_path, packet_id)
    packet_dir = tmp_path / PROGRAM_RUN_PACKET_ROOT / packet_id
    assert (packet_dir / "00-program.json").is_file()
    assert (packet_dir / "01-source-qa.json").is_file()
    assert result["record"]["execution"]["status"] == "completed"
    assert result["record"]["quality"]["status"] == "failed"
    assert result["record"]["duration_seconds"] == 60
    assert summary["state"] == "quality_failed"
    assert summary["metrics"]["execution_failure_count"] == 0
    assert summary["metrics"]["quality_failure_count"] == 1
    assert summary["last_workflow"] == "source_qa"
    assert summary["next_workflow"] == "remediate_quality_failure"


def test_packet_classifies_unexpected_execution_failure_separately(tmp_path: Path) -> None:
    packet_id = _packet(tmp_path)
    begin_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="release",
        transport=_transport(),
        idempotency_key="cc-412:release:started",
        started_at="2026-08-03T06:02:00Z",
    )
    record_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="release",
        execution={
            "status": "failed",
            "transport": _transport(),
            "failure": {
                "kind": "unexpected_exit",
                "reason": "Release adapter exited before provider readback.",
                "receipt_ref": "artifacts/release/exit.json",
            },
        },
        quality={"status": "unknown", "failures": []},
        idempotency_key="cc-412:release:completed",
        finished_at="2026-08-03T06:02:05Z",
    )

    summary = read_program_run_packet(tmp_path, packet_id)
    assert summary["state"] == "execution_failed"
    assert summary["metrics"]["execution_failure_count"] == 1
    assert summary["metrics"]["quality_failure_count"] == 0


def test_packet_replays_exact_evidence_but_rejects_mutation(tmp_path: Path) -> None:
    packet_id = _packet(tmp_path)
    begin_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="groom",
        transport=_transport(),
        idempotency_key="cc-412:groom:started",
        started_at="2026-08-03T06:03:00Z",
    )
    first = record_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="groom",
        execution={"status": "completed", "transport": _transport()},
        quality={"status": "not_applicable", "failures": []},
        idempotency_key="cc-412:groom:completed",
        finished_at="2026-08-03T06:03:01Z",
    )
    replay = record_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="groom",
        execution={"status": "completed", "transport": _transport()},
        quality={"status": "not_applicable", "failures": []},
        idempotency_key="cc-412:groom:completed",
        finished_at="2026-08-03T06:03:01Z",
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["record"] == first["record"]
    with pytest.raises(ProgramRunPacketError, match="different immutable evidence"):
        record_program_workflow(
            tmp_path,
            packet_id=packet_id,
            workflow_id="groom",
            execution={"status": "completed", "transport": _transport()},
            quality={"status": "not_applicable", "failures": []},
            idempotency_key="cc-412:groom:completed",
            finished_at="2026-08-03T06:03:02Z",
        )
    with pytest.raises(ProgramRunPacketError, match="sealed only once"):
        record_program_workflow(
            tmp_path,
            packet_id=packet_id,
            workflow_id="groom",
            execution={"status": "completed", "transport": _transport()},
            quality={"status": "not_applicable", "failures": []},
            idempotency_key="cc-412:groom:changed",
            finished_at="2026-08-03T06:03:03Z",
        )


def test_quality_failure_requires_a_tracker_backed_remediation_record(tmp_path: Path) -> None:
    packet_id = _packet(tmp_path)
    with pytest.raises(ProgramRunPacketError, match="tracker-backed"):
        record_program_workflow(
            tmp_path,
            packet_id=packet_id,
            workflow_id="platform_qa",
            execution={"status": "completed", "transport": _transport()},
            quality={"status": "failed", "failures": []},
            idempotency_key="cc-412:platform-qa:completed",
            finished_at="2026-08-03T06:04:00Z",
        )


def test_packet_records_match_the_registered_schema(tmp_path: Path) -> None:
    packet_id = _packet(tmp_path)
    record_program_workflow(
        tmp_path,
        packet_id=packet_id,
        workflow_id="groom",
        execution={"status": "completed", "transport": _transport()},
        quality={"status": "not_applicable", "failures": []},
        idempotency_key="cc-412:groom:completed",
        finished_at="2026-08-03T06:05:00Z",
    )

    repository = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository / "schemas/program-run-packet.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    packet_dir = tmp_path / PROGRAM_RUN_PACKET_ROOT / packet_id
    for path in (packet_dir / "00-program.json", packet_dir / "01-groom.json"):
        assert list(validator.iter_errors(json.loads(path.read_text(encoding="utf-8")))) == []
