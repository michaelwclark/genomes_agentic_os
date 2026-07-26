"""Coverage for CC-383 per-tool-call byte accounting."""

from __future__ import annotations

import json
from pathlib import Path

from genomes_agentic_os.tool_byte_accounting import (
    NO_INTERCEPTOR,
    SCHEMA,
    append_records,
    histogram,
    iter_tool_calls,
    records_for,
)


def _transcript(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
    return path


def _use(call_id: str, name: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": call_id, "name": name}]}}


def _result(call_id: str, content) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": content}]}}


def test_every_tool_call_yields_a_row_with_name_and_bytes(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, [
        _use("a", "Bash"), _result("a", "hello"),
        _use("b", "Read"), _result("b", "worldly"),
    ])

    calls = list(iter_tool_calls(transcript))

    assert [(c.seq, c.tool, c.bytes_admitted) for c in calls] == [
        (1, "Bash", 5),
        (2, "Read", 7),
    ]


def test_counts_utf8_bytes_not_characters(tmp_path: Path) -> None:
    # "é" is two UTF-8 bytes; counting characters would understate context cost.
    transcript = _transcript(tmp_path, [_use("a", "Bash"), _result("a", "é")])

    assert next(iter_tool_calls(transcript)).bytes_admitted == 2


def test_handles_block_list_content(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, [
        _use("a", "Grep"),
        _result("a", [{"type": "text", "text": "abc"}, {"type": "text", "text": "de"}]),
    ])

    assert next(iter_tool_calls(transcript)).bytes_admitted == 5


def test_result_without_matching_call_is_reported_as_unknown(tmp_path: Path) -> None:
    # A rotated or truncated transcript must not silently understate totals.
    transcript = _transcript(tmp_path, [_result("orphan", "12345")])

    call = next(iter_tool_calls(transcript))
    assert call.tool == "unknown"
    assert call.bytes_admitted == 5


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "not json\n" + json.dumps(_use("a", "Bash")) + "\n" + json.dumps(_result("a", "xy")) + "\n",
        encoding="utf-8",
    )

    assert [c.tool for c in iter_tool_calls(path)] == ["Bash"]


def test_missing_transcript_yields_nothing(tmp_path: Path) -> None:
    assert list(iter_tool_calls(tmp_path / "absent.jsonl")) == []


def test_records_carry_null_bytes_avoided_with_a_reason(tmp_path: Path) -> None:
    # Nothing redirects yet; a 0 would falsely read as "measured, nothing avoided".
    transcript = _transcript(tmp_path, [_use("a", "Bash"), _result("a", "hi")])

    rows = records_for(transcript, session_id="s-1", verified_at="2026-07-26T00:00:00Z")

    assert len(rows) == 1
    assert rows[0]["schema"] == SCHEMA
    assert rows[0]["session_id"] == "s-1"
    assert rows[0]["tool"] == "Bash"
    assert rows[0]["bytes_admitted"] == 2
    assert rows[0]["bytes_avoided"] is None
    assert rows[0]["bytes_avoided_reason"] == NO_INTERCEPTOR


def test_append_is_additive_across_sessions(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, [_use("a", "Bash"), _result("a", "hi")])
    destination = tmp_path / "nested" / "accounting.jsonl"

    first = append_records(destination, records_for(transcript, "s-1", "2026-07-26T00:00:00Z"))
    second = append_records(destination, records_for(transcript, "s-2", "2026-07-26T01:00:00Z"))

    assert (first, second) == (1, 1)
    assert len(destination.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_write_failure_returns_zero_and_never_raises(tmp_path: Path) -> None:
    # A hook must survive telemetry failure; a directory is an unwritable target.
    blocked = tmp_path / "blocked"
    blocked.mkdir()

    assert append_records(blocked, [{"schema": SCHEMA, "tool": "Bash"}]) == 0


def test_empty_records_write_nothing(tmp_path: Path) -> None:
    destination = tmp_path / "accounting.jsonl"

    assert append_records(destination, []) == 0
    assert not destination.exists()


def test_histogram_aggregates_per_tool_across_files(tmp_path: Path) -> None:
    one, two = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    append_records(one, [
        {"schema": SCHEMA, "tool": "Bash", "bytes_admitted": 10},
        {"schema": SCHEMA, "tool": "Read", "bytes_admitted": 3},
    ])
    append_records(two, [{"schema": SCHEMA, "tool": "Bash", "bytes_admitted": 5}])

    assert histogram([one, two]) == {
        "Bash": {"calls": 2, "bytes_admitted": 15},
        "Read": {"calls": 1, "bytes_admitted": 3},
    }


def test_histogram_ignores_foreign_rows_and_missing_files(tmp_path: Path) -> None:
    source = tmp_path / "mixed.jsonl"
    source.write_text(
        json.dumps({"schema": "something-else/v1", "tool": "Bash", "bytes_admitted": 99}) + "\n"
        + json.dumps({"schema": SCHEMA, "tool": "Read", "bytes_admitted": 4}) + "\n"
        + "not json\n",
        encoding="utf-8",
    )

    assert histogram([source, tmp_path / "absent.jsonl"]) == {"Read": {"calls": 1, "bytes_admitted": 4}}
