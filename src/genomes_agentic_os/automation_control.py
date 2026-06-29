"""Automation-control gates for scheduled Agentic OS work.

This module intentionally starts conservative: it exposes a stable CLI surface
that can be expanded by the automation-control feature without blocking other
commands when no gate config exists yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path


CONFIG_PATH = Path("harness/shared_factory/00-control-plane/automation-control.yml")


def _load_config(root: str | Path) -> tuple[Path, dict[str, Any]]:
    os_root = expand_path(root)
    path = os_root / CONFIG_PATH
    if not path.is_file():
        return path, {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return path, data if isinstance(data, dict) else {}


def list_automation_control(root: str | Path) -> dict[str, Any]:
    path, config = _load_config(root)
    gates = config.get("gates", []) if isinstance(config.get("gates"), list) else []
    return {
        "ok": True,
        "config_path": str(path),
        "configured": path.is_file(),
        "gates": gates,
    }


def automation_control_doctor(root: str | Path) -> dict[str, Any]:
    path, config = _load_config(root)
    findings: list[dict[str, str]] = []
    if not path.is_file():
        findings.append(
            {
                "severity": "observation",
                "path": str(path),
                "message": "automation-control config is not installed; all gates are inert",
            }
        )
    elif not isinstance(config.get("gates", []), list):
        findings.append(
            {
                "severity": "blocker",
                "path": str(path),
                "message": "gates must be a list",
            }
        )
    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "config_path": str(path),
        "configured": path.is_file(),
        "findings": findings,
    }


def run_automation_control(root: str | Path, *, automation_id: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    state = list_automation_control(root)
    gates = state["gates"]
    if automation_id:
        gates = [gate for gate in gates if isinstance(gate, dict) and gate.get("id") == automation_id]
    return {
        "ok": True,
        "dry_run": dry_run,
        "config_path": state["config_path"],
        "configured": state["configured"],
        "automation_id": automation_id,
        "evaluated": gates,
        "actions": [],
    }


def format_automation_control_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
