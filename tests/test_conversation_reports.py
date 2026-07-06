"""Tests for conversation-report mining utilities."""

from __future__ import annotations

import json
from pathlib import Path

from genomes_agentic_os.conversation_reports import (
    find_conversation_report_files,
    scan_conversation_reports,
)
from genomes_agentic_os.cli import main


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_conversation_report_scan_clusters_and_writes_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    project = root / "clarks_consulting" / "02-projects" / "genomes_agentic_os"
    work_item = project / "work-items" / "02-active" / "030_linear_tracker_config_drift"
    logs = work_item / "logs" / "conversations"
    work_item.mkdir(parents=True)
    (work_item / "SPEC.md").write_text("# Fix Linear Tracker Config Drift\n", encoding="utf-8")
    _write_jsonl(
        logs / "2026_07_06_030_linear_tracker_config_drift.jsonl",
        [
            {
                "type": "message",
                "role": "assistant",
                "content": "Linear tracker drift hit USAGE_LIMIT_EXCEEDED while token sk-abcdefghijklmnop1234567890 was present.",
            },
            {
                "type": "tool_result",
                "content": "config.toml is missing and validation failed",
            },
        ],
    )
    _write_jsonl(
        logs / "2026_07_06_030_linear_tracker_config_drift_tool_calls.jsonl",
        [{"name": "Bash"}],
    )

    output_dir = tmp_path / "out"
    result = scan_conversation_reports(root, project="genomes_agentic_os", output_dir=output_dir)

    assert result["summary"]["files_scanned"] == 1
    assert result["summary"]["rows_scanned"] == 2
    assert result["summary"]["classes"]["tracker_drift"] == 1
    assert result["summary"]["classes"]["missing_config"] == 1
    assert result["findings"][0]["matches"][0]["work_item"] == "030_linear_tracker_config_drift"
    assert "sk-abcdefghijklmnop1234567890" not in (output_dir / "conversation-report-scan.md").read_text(encoding="utf-8")
    assert (output_dir / "conversation-report-scan.json").is_file()
    assert (output_dir / "conversation-report-scan.md").is_file()
    assert (output_dir / "conversation-report-backlog.md").is_file()


def test_conversation_report_file_discovery_skips_tool_call_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(logs / "2026_07_06_root.jsonl", [{"content": "timeout"}])
    _write_jsonl(logs / "2026_07_06_root_tool_calls.jsonl", [{"name": "Bash"}])

    files = find_conversation_report_files(root)

    assert files == [logs / "2026_07_06_root.jsonl"]


def test_conversation_report_scan_skips_metadata_and_encoded_images(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(
        logs / "2026_07_06_root.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"base_instructions": {"text": "timeout validation error workspace"}},
            },
            {
                "type": "turn_context",
                "payload": {"workspace_roots": ["/tmp/agentic_os"], "timezone": "America/Chicago"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "just showing a screenshot"},
                        {"type": "input_image", "image_url": "data:image/png;base64," + "A" * 600},
                    ],
                },
            },
        ],
    )

    result = scan_conversation_reports(root)

    assert result["summary"]["findings"] == 0


def test_conversation_report_scan_skips_injected_harness_context(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(
        logs / "2026_07_06_root.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions for /tmp/agentic_os\n\n"
                            "<INSTRUCTIONS>\n"
                            "If the active Notion MCP is Michael Clark's personal Notion, do not write there.\n"
                            "Also mention timeout and missing required config in the rules.\n"
                            "</INSTRUCTIONS>",
                        },
                        {
                            "type": "input_text",
                            "text": "<environment_context><cwd>/tmp/agentic_os</cwd></environment_context>",
                        },
                    ],
                },
            }
        ],
    )

    result = scan_conversation_reports(root)

    assert result["summary"]["findings"] == 0


def test_conversation_report_scan_skips_tool_discovery_output(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(
        logs / "2026_07_06_root.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_output",
                    "tools": [
                        {
                            "name": "shell",
                            "description": "Runs with command timeouts and reports missing required parameters.",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "I hit timeout waiting for the backup command.",
                },
            },
        ],
    )

    result = scan_conversation_reports(root)

    assert result["summary"]["findings"] == 1
    assert result["findings"][0]["class"] == "timeout"


def test_conversation_report_scan_skips_reference_doc_outputs(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(
        logs / "2026_07_06_root.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "Chunk ID: 1\nOutput:\n# Agent Router\n\n"
                    "Read `CONTEXT.md`, `RULES.md`, and `TOOLS.md`.\n"
                    "| Notion work | Verify Genome's Notion before any write. |",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": '{"count":1,"hits":[{"substrate":"cocoindex","preview":"runtime doctor exits 1 when missing config"}]}',
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "Process completed with exit code 1 while running validation.",
                },
            },
        ],
    )

    result = scan_conversation_reports(root)

    assert result["summary"]["findings"] == 1
    assert result["findings"][0]["class"] == "validation_failure"


def test_conversation_reports_scan_cli_prints_receipt_not_full_findings(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    logs = root / "harness" / "logs" / "conversations"
    _write_jsonl(
        logs / "2026_07_06_root.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "The command timed out again.",
                },
            }
        ],
    )

    ret = main(["conversation-reports", "scan", "--root", str(root)])
    out = capsys.readouterr().out

    assert ret == 0
    assert "Conversation Report Scan Receipt" in out
    assert "Files scanned: 1" in out
    assert "Evidence:" not in out
