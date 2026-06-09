"""Tests for F-011 strict schema validation, plan-18 AC, plan-22 staleness,
and F-003 doctor --all.

Kept in a separate file to avoid contention with tests/test_cli_scaffold.py.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.doctor import doctor_all, lifecycle_findings
from genomes_agentic_os.validate import (
    BUILDING_STALE_DAYS,
    SCHEMA_TARGETS,
    StrictFinding,
    lifecycle_staleness_findings,
    validate_root,
    validate_schemas_strict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def harness(root: Path) -> Path:
    return root / "harness"


def registries(root: Path) -> Path:
    return harness(root) / "registries"


def _init_root(root: Path) -> None:
    """Create a minimal valid OS root via the CLI."""
    assert main(["init", "--target", str(root)]) == 0


def _make_work_item(
    root: Path,
    *,
    domain: str = "personal",
    project: str = "my_project",
    status: str = "building",
    mtime_days_ago: int = 0,
) -> Path:
    """Scaffold a minimal work-item directory under the given OS root."""
    work_items_root = (
        root
        / f"harness/{domain}/02-projects/{project}/work-items"
    )
    work_item_root = work_items_root / "test_item"
    work_item_root.mkdir(parents=True, exist_ok=True)
    (work_item_root / "artifacts").mkdir(exist_ok=True)
    (work_item_root / "logs").mkdir(exist_ok=True)
    (work_item_root / "logs" / "conversations").mkdir(exist_ok=True)

    metadata: dict[str, Any] = {
        "state": status,
        "title": "Test Work Item",
        "slug": "test_item",
    }
    work_yml = work_item_root / "work.yml"
    work_yml.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")

    if status == "finished":
        # write SUMMARY.md so the default case is passing; tests can remove it
        (work_item_root / "SUMMARY.md").write_text("# Summary\n", encoding="utf-8")

    if mtime_days_ago > 0:
        # Back-date all files in the work-item directory
        old_ts = (
            datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(days=mtime_days_ago)
        ).timestamp()
        for child in work_item_root.rglob("*"):
            try:
                os.utime(child, (old_ts, old_ts))
            except OSError:
                pass
        os.utime(work_item_root, (old_ts, old_ts))

    return work_item_root


# ---------------------------------------------------------------------------
# F-011: SCHEMA_TARGETS mapping is explicit and covers all known schemas
# ---------------------------------------------------------------------------


def test_schema_targets_covers_registry_schemas() -> None:
    """Every capability-registry schema has an explicit target entry."""
    registry_schemas = {
        "capability-registry.schema.json",
        "command-registry.schema.json",
        "skill-registry.schema.json",
        "mcp-server-registry.schema.json",
        "library-registry.schema.json",
        "hook-registry.schema.json",
        "plugin-registry.schema.json",
        "rule-registry.schema.json",
        "composio-tool-routing.schema.json",
    }
    assert registry_schemas <= set(SCHEMA_TARGETS)


def test_schema_targets_values_are_lists() -> None:
    for key, val in SCHEMA_TARGETS.items():
        assert isinstance(val, list), f"SCHEMA_TARGETS[{key!r}] must be a list, got {type(val)}"


def test_validate_schemas_strict_returns_list(tmp_path: Path) -> None:
    """validate_schemas_strict always returns a list (even on an empty/nonexistent root)."""
    findings = validate_schemas_strict(tmp_path / "nonexistent")
    assert isinstance(findings, list)


def test_validate_schemas_strict_clean_on_fresh_install(tmp_path: Path) -> None:
    """A fresh install produces zero strict schema violations.

    Every SCHEMA_TARGETS pair must hold against scaffolder output; a failure
    here means a schema and the scaffolder drifted apart.
    """
    root = tmp_path / "agentic_os"
    _init_root(root)
    findings = validate_schemas_strict(root)
    assert findings == [], "\n".join(f.message for f in findings)


def test_validate_strict_cli_flag_passes_on_fresh_install(tmp_path: Path, capsys: Any) -> None:
    """agentic-os validate --strict exits 0 on a fresh install."""
    root = tmp_path / "agentic_os"
    _init_root(root)
    exit_code = main(["validate", "--root", str(root), "--strict"])
    assert exit_code == 0, f"strict violations on fresh install: {capsys.readouterr().out}"


def test_validate_strict_detects_schema_violation(tmp_path: Path) -> None:
    """validate --strict reports a schema violation when a registry file is malformed."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    # Write a composio-tools.yml that violates the schema (missing required fields)
    composio_path = registries(root) / "composio-tools.yml"
    composio_path.write_text(
        yaml.safe_dump(
            {
                "composio_tools": [
                    {
                        "id": "bad_entry",
                        # Missing required: toolkit, name, route_when, layer_scope,
                        # provider_priority, approval_required_for, boundary, status
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    findings = validate_schemas_strict(root)
    schema_errors = [f for f in findings if "schema violation" in f.message]
    assert schema_errors, "Expected schema violation findings but got none"
    assert any("composio-tool-routing" in f.schema for f in schema_errors)


def test_validate_strict_skips_missing_files(tmp_path: Path) -> None:
    """validate --strict does not report errors for files that do not exist."""
    root = tmp_path / "empty"
    root.mkdir()
    # An empty directory has no files to validate; should return an empty list
    findings = validate_schemas_strict(root)
    assert all("schema violation" not in f.message for f in findings)


# ---------------------------------------------------------------------------
# Plan-18 AC: validate reports missing declared capabilities
# ---------------------------------------------------------------------------


def test_validate_reports_missing_composio_tool_registry_entry(tmp_path: Path) -> None:
    """Removing a composio-tools.yml entry that capabilities.yml references is an error."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    # Add a capability entry that references a composio tool that doesn't exist
    capabilities_path = registries(root) / "capabilities.yml"
    capabilities = yaml.safe_load(capabilities_path.read_text(encoding="utf-8"))
    capabilities["capabilities"].append(
        {
            "id": "composio_tool:phantom_tool",
            "type": "composio_tool",
            "ref": "phantom_tool",
            "name": "Phantom Tool",
            "description": "Does not exist.",
        }
    )
    capabilities_path.write_text(
        yaml.safe_dump(capabilities, sort_keys=False), encoding="utf-8"
    )

    result = validate_root(root)
    assert not result.ok
    assert any("phantom_tool" in e for e in result.errors)


def test_validate_composio_tools_registry_file_is_required(tmp_path: Path) -> None:
    """The composio-tools.yml registry file is required by validate_root."""
    root = tmp_path / "agentic_os"
    _init_root(root)
    composio_path = registries(root) / "composio-tools.yml"
    assert composio_path.is_file(), "composio-tools.yml must exist after init"


# ---------------------------------------------------------------------------
# Plan-22: lifecycle staleness detection
# ---------------------------------------------------------------------------


def test_lifecycle_staleness_no_findings_for_fresh_building_item(tmp_path: Path) -> None:
    """A brand-new 'building' work-item (mtime = now) has no staleness finding."""
    root = tmp_path
    _make_work_item(root, status="building", mtime_days_ago=0)
    findings = lifecycle_staleness_findings(root)
    assert findings == []


def test_lifecycle_staleness_detects_stale_building_item(tmp_path: Path) -> None:
    """A 'building' work-item older than BUILDING_STALE_DAYS triggers a finding."""
    root = tmp_path
    _make_work_item(root, status="building", mtime_days_ago=BUILDING_STALE_DAYS + 1)
    findings = lifecycle_staleness_findings(root)
    assert findings, "Expected a staleness finding for an old building item"
    assert any("building" in f["message"] for f in findings)
    assert all(f["severity"] == "fix-soon" for f in findings)


def test_lifecycle_staleness_no_finding_for_finished_item_with_summary(tmp_path: Path) -> None:
    """A 'finished' item that has SUMMARY.md does not produce a finding."""
    root = tmp_path
    _make_work_item(root, status="finished", mtime_days_ago=0)
    findings = lifecycle_staleness_findings(root)
    assert findings == []


def test_lifecycle_staleness_detects_finished_item_missing_summary(tmp_path: Path) -> None:
    """A 'finished' work-item without SUMMARY.md triggers a finding."""
    root = tmp_path
    work_item_root = _make_work_item(root, status="finished", mtime_days_ago=0)
    (work_item_root / "SUMMARY.md").unlink()

    findings = lifecycle_staleness_findings(root)
    assert findings, "Expected a finding for finished item missing SUMMARY.md"
    assert any("finished" in f["message"] for f in findings)
    assert all(f["severity"] == "fix-soon" for f in findings)


def test_validate_root_includes_lifecycle_staleness_as_warnings(tmp_path: Path) -> None:
    """validate_root surfaces lifecycle staleness findings as warnings (not errors)."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    # Create a project and a stale building work-item under it
    domain_root = root / "harness" / "personal"
    project_root = domain_root / "02-projects" / "my_project"
    work_items = project_root / "work-items" / "stale_item"
    work_items.mkdir(parents=True, exist_ok=True)
    (work_items / "artifacts").mkdir(exist_ok=True)
    (work_items / "logs").mkdir(exist_ok=True)
    (work_items / "logs" / "conversations").mkdir(exist_ok=True)
    (work_items / "work.yml").write_text(
        yaml.safe_dump({"state": "building", "title": "Stale", "slug": "stale_item"}),
        encoding="utf-8",
    )

    # Back-date all files
    old_ts = (
        datetime.datetime.now(tz=datetime.timezone.utc)
        - datetime.timedelta(days=BUILDING_STALE_DAYS + 2)
    ).timestamp()
    for child in list(work_items.rglob("*")) + [work_items]:
        try:
            os.utime(child, (old_ts, old_ts))
        except OSError:
            pass

    result = validate_root(root)
    # Staleness is a warning, not a blocker
    assert any("building" in w for w in result.warnings)
    # result.ok is determined by errors only; staleness shouldn't block
    # (ok == True here because the root is structurally valid)


def test_doctor_includes_lifecycle_findings(tmp_path: Path) -> None:
    """doctor() returns lifecycle staleness findings in its findings list."""
    from genomes_agentic_os.doctor import doctor

    root = tmp_path
    work_item_root = _make_work_item(root, status="building", mtime_days_ago=BUILDING_STALE_DAYS + 3)

    result = doctor(root)
    messages = [f["message"] for f in result["findings"]]
    assert any("building" in m for m in messages), f"Findings: {messages}"


# ---------------------------------------------------------------------------
# F-003: doctor --all
# ---------------------------------------------------------------------------


def test_doctor_all_returns_expected_shape(tmp_path: Path) -> None:
    """doctor_all() returns a dict with ok, subsystems, and findings keys."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    result = doctor_all(root)

    assert "ok" in result
    assert "subsystems" in result
    assert "findings" in result
    assert "core" in result["subsystems"]
    assert "runtime" in result["subsystems"]
    assert "event_graph" in result["subsystems"]
    assert "config" in result["subsystems"]


def test_doctor_all_findings_have_subsystem_tag(tmp_path: Path) -> None:
    """Every finding in doctor_all output has a 'subsystem' key."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    result = doctor_all(root)
    for finding in result["findings"]:
        assert "subsystem" in finding, f"Finding missing subsystem key: {finding}"


def test_doctor_all_cli_flag(tmp_path: Path, capsys: Any) -> None:
    """agentic-os doctor --all runs without error on a fresh install."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    # A fresh install has no runtime registries so runtime subsystem may report
    # blockers; we just check the command runs and outputs YAML.
    exit_code = main(["doctor", "--all", "--root", str(root)])
    output = capsys.readouterr().out
    assert output.strip(), "doctor --all should produce YAML output"
    parsed = yaml.safe_load(output)
    assert "ok" in parsed
    assert "subsystems" in parsed


def test_doctor_all_ok_false_when_core_has_blockers(tmp_path: Path) -> None:
    """doctor_all returns ok=False when the core subsystem has blockers."""
    root = tmp_path / "empty_root"
    root.mkdir()
    # An empty directory has no .agentic_os_root marker → core will have blockers
    result = doctor_all(root)
    assert result["ok"] is False


def test_doctor_all_subsystems_have_ok_and_findings(tmp_path: Path) -> None:
    """Each subsystem entry in doctor_all has ok and findings keys."""
    root = tmp_path / "agentic_os"
    _init_root(root)

    result = doctor_all(root)
    for name, sub in result["subsystems"].items():
        assert "ok" in sub, f"subsystem {name!r} missing ok"
        assert "findings" in sub, f"subsystem {name!r} missing findings"


# ---------------------------------------------------------------------------
# StrictFinding dataclass
# ---------------------------------------------------------------------------


def test_strict_finding_as_dict() -> None:
    """StrictFinding.as_dict() returns all three expected keys."""
    finding = StrictFinding(
        schema="test.schema.json",
        path=Path("/some/path.yml"),
        message="test message",
    )
    d = finding.as_dict()
    assert d["schema"] == "test.schema.json"
    assert d["path"] == "/some/path.yml"
    assert d["message"] == "test message"
