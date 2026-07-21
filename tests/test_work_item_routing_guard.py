"""Tests for the non-blocking work-item routing guard hook."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from genomes_agentic_os.hook_ops import sync_codex_hooks


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "harness" / "hooks" / "work-item-routing-guard.py"


def run_hook(*, home: Path, path: Path, tool_name: str = "apply_patch") -> dict:
    """Execute the hook through its real stdin/stdout contract."""
    payload = {"tool_name": tool_name, "tool_input": {"path": str(path)}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env={"HOME": str(home)},
    )
    assert result.returncode == 0
    return json.loads(result.stdout)


def test_packet_write_in_linked_repo_points_to_canonical_work_item(tmp_path: Path) -> None:
    """Arrange a linked repo; act with a packet write; assert exact OS routing."""
    home = tmp_path / "home"
    os_root = home / "agentic_os"
    repo = tmp_path / "source" / "lending-app"
    project = os_root / "lending" / "02-projects" / "lending-app"
    project.mkdir(parents=True)
    repo.mkdir(parents=True)
    (project / "project.yml").write_text(f"repo: {repo}\n", encoding="utf-8")

    output = run_hook(home=home, path=repo / ".features" / "LEND-1" / "WORKLOG.md")

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "work-item-routing-guard" in context
    assert str(project / "work-items") in context
    assert "disposable mirror" in context


def test_raw_evidence_in_features_remains_allowed(tmp_path: Path) -> None:
    """Arrange raw evidence; act with a write; assert the guard stays silent."""
    home = tmp_path / "home"
    repo = tmp_path / "source" / "lending-app"

    output = run_hook(home=home, path=repo / ".features" / "LEND-1" / "watch-state.json")

    assert output["hookSpecificOutput"]["additionalContext"] == ""


def test_packet_inside_agentic_os_root_is_not_rewritten(tmp_path: Path) -> None:
    """Arrange a canonical OS work item; act with a write; assert no false warning."""
    home = tmp_path / "home"
    path = home / "agentic_os" / "lending" / ".features" / "LEND-1" / "PLAN.md"

    output = run_hook(home=home, path=path)

    assert output["hookSpecificOutput"]["additionalContext"] == ""


def test_codex_hook_configuration_registers_routing_guard(tmp_path: Path) -> None:
    """Arrange empty hooks; act with sync; assert PostToolUse registration."""
    data: dict = {}

    changed = sync_codex_hooks(data, tmp_path / "agentic_os")

    assert changed is True
    commands = [
        hook["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hook in entry.get("hooks", [])
    ]
    assert any(command.endswith("work-item-routing-guard.py") for command in commands)
