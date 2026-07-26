"""Per-tool-call byte accounting derived from a harness session transcript.

Why this exists: the OS measures no per-tool context cost, so work that claims to
reduce it (CC-384, CC-386, CC-388) has no baseline to prove against. Deriving the
numbers from the Stop transcript keeps this out of the tool-call hot path — a
PreToolUse hook cannot load a native module without corrupting hook stdout, and
accounting does not need to intercept anything.

`bytes_avoided` is deliberately ``None`` rather than ``0``: nothing in the OS
redirects tool output yet, so a zero would read as "measured, nothing avoided"
when the truth is "not measurable here". CC-386 is what makes it real.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SCHEMA = "tool-byte-accounting/v1"
NO_INTERCEPTOR = "no_interceptor_installed"

_TOOL_USE_TYPES = frozenset({"tool_use", "server_tool_use"})
_TOOL_RESULT_TYPES = frozenset({"tool_result", "advisor_tool_result"})


@dataclass(frozen=True)
class ToolCall:
    """One completed tool call and the bytes its result admitted into context."""

    seq: int
    tool: str
    tool_use_id: str
    bytes_admitted: int


def _content_bytes(content: Any) -> int:
    """UTF-8 byte length of a tool_result payload across its known shapes.

    Transcripts carry `content` as a plain string, as a list of typed blocks
    (usually ``{"type": "text", "text": ...}``), or occasionally as a bare
    object. Unknown shapes fall back to their JSON encoding so the number is
    never silently zero.
    """
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                total += (
                    len(text.encode("utf-8"))
                    if isinstance(text, str)
                    else len(json.dumps(block, sort_keys=True).encode("utf-8"))
                )
            elif isinstance(block, str):
                total += len(block.encode("utf-8"))
        return total
    try:
        return len(json.dumps(content, sort_keys=True).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(content).encode("utf-8"))


def _content_blocks(entry: Any) -> list[dict[str, Any]]:
    if not isinstance(entry, dict):
        return []
    message = entry.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def iter_tool_calls(transcript: Path) -> Iterator[ToolCall]:
    """Yield one ToolCall per tool_result, in transcript order.

    Tool names live on the `tool_use` block and byte counts on the matching
    `tool_result`, so the two are joined by `tool_use_id`. A result whose call is
    missing (truncated or rotated transcript) is still reported, as ``unknown``,
    because dropping it would understate the total.
    """
    names: dict[str, str] = {}
    seq = 0
    try:
        handle = transcript.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            for block in _content_blocks(entry):
                block_type = block.get("type")
                if block_type in _TOOL_USE_TYPES:
                    call_id = block.get("id")
                    if isinstance(call_id, str):
                        names[call_id] = str(block.get("name") or "unknown")
                elif block_type in _TOOL_RESULT_TYPES:
                    call_id = block.get("tool_use_id")
                    seq += 1
                    yield ToolCall(
                        seq=seq,
                        tool=names.get(call_id, "unknown") if isinstance(call_id, str) else "unknown",
                        tool_use_id=call_id if isinstance(call_id, str) else "",
                        bytes_admitted=_content_bytes(block.get("content")),
                    )


def records_for(transcript: Path, session_id: str, verified_at: str) -> list[dict[str, Any]]:
    """Build the durable JSONL records for one session's transcript."""
    return [
        {
            "schema": SCHEMA,
            "session_id": session_id,
            "ts": verified_at,
            **asdict(call),
            "bytes_avoided": None,
            "bytes_avoided_reason": NO_INTERCEPTOR,
        }
        for call in iter_tool_calls(transcript)
    ]


def append_records(destination: Path, records: Iterable[dict[str, Any]]) -> int:
    """Append records as JSONL. Never raises — telemetry must not break a hook.

    Returns the number of records written, or 0 if the write failed for any
    reason. Callers log the count; they do not branch on failure.
    """
    rows = list(records)
    if not rows:
        return 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        return 0
    return len(rows)


def histogram(sources: Iterable[Path]) -> dict[str, dict[str, int]]:
    """Aggregate emitted JSONL into per-tool totals across sessions."""
    calls: Counter[str] = Counter()
    admitted: Counter[str] = Counter()
    for source in sources:
        try:
            handle = source.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or row.get("schema") != SCHEMA:
                    continue
                tool = str(row.get("tool") or "unknown")
                calls[tool] += 1
                value = row.get("bytes_admitted")
                admitted[tool] += value if isinstance(value, int) else 0
    return {
        tool: {"calls": calls[tool], "bytes_admitted": admitted[tool]}
        for tool in sorted(calls, key=lambda name: (-admitted[name], name))
    }


def default_destination(session_id: str) -> Path:
    """Where a Stop hook writes this session's accounting rows."""
    return Path.home() / ".local" / "state" / "harness" / "tool-byte-accounting" / f"{session_id}.jsonl"


def main(argv: list[str] | None = None) -> int:
    """CLI used by the Stop hook and for reading the histogram back.

    Always exits 0 on the emit path: this is telemetry invoked from a hook, and
    a non-zero exit there is worse than a missing row.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Per-tool-call byte accounting.")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--session-id", default="unknown")
    parser.add_argument("--verified-at", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--histogram", nargs="*", type=Path, metavar="JSONL")
    args = parser.parse_args(argv)

    if args.histogram is not None:
        sources = args.histogram or sorted(default_destination("x").parent.glob("*.jsonl"))
        # Not sort_keys: histogram() orders by bytes descending, which is the
        # whole point — the biggest context cost should be the first thing read.
        print(json.dumps(histogram(sources), indent=2))
        return 0

    if not args.transcript:
        parser.error("--transcript is required unless --histogram is used")

    destination = args.out or default_destination(args.session_id)
    written = append_records(
        destination,
        records_for(args.transcript, args.session_id, args.verified_at),
    )
    print(f"tool_byte_accounting rows={written} out={destination}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
