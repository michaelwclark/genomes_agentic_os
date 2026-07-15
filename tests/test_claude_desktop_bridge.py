from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "harness/bin/agentic-os-claude-desktop-bridge"


def run_bridge(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_builds_a_uploadable_skill_and_instruction_payloads(tmp_path: Path) -> None:
    output = tmp_path / "claude-desktop"

    result = run_bridge("--output-dir", str(output), "--build")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["skill_id"] == "agentic-os-operating-contract"
    assert "cloud-hosted" in manifest["verification_limit"]
    assert "agentic-os-operating-contract" in (output / "PROFILE_INSTRUCTIONS.md").read_text()
    assert "agentic-os-operating-contract" in (output / "PROJECT_INSTRUCTIONS.md").read_text()
    with zipfile.ZipFile(output / "agentic-os-operating-contract.zip") as package:
        assert package.namelist() == ["agentic-os-operating-contract/SKILL.md"]
        skill = package.read("agentic-os-operating-contract/SKILL.md").decode()
    assert skill.startswith("---\nname: agentic-os-operating-contract\n")


def test_audit_detects_stale_generated_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "claude-desktop"
    assert run_bridge("--output-dir", str(output), "--build").returncode == 0
    (output / "PROFILE_INSTRUCTIONS.md").write_text("stale\n")

    result = run_bridge("--output-dir", str(output), "--audit")

    assert result.returncode == 1
    assert "stale artifact: PROFILE_INSTRUCTIONS.md" in result.stdout

