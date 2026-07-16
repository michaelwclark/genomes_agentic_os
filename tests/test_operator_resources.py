from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import jsonschema
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.operator_resources import (
    API_VERSION,
    get_operator_resource,
    query_operator_resources,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _yaml(path: Path, value: object) -> Path:
    return _write(path, yaml.safe_dump(value, sort_keys=False))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    _write(root / ".agentic_root", "agentic-os\n")
    _write(root / "harness/rules/os-authoring-rules.md", "# OS Authoring Rules\n")
    for domain in ("work", "archive"):
        _write(root / domain / "CONTEXT.md", f"# {domain}\n")
        _yaml(root / domain / "domain.yml", {"id": domain, "name": domain})
    return root


def _program_definition(root: Path, name: str = "demo") -> Path:
    path = root / "harness/shared_factory/00-programs" / name
    _write(
        path / "program.md",
        f"# OSProgram: {name}\n\n## Status\n\n- Status: active\n\n## Purpose\n\nCanonical demo program.\n",
    )
    _yaml(
        path / ".agentic-resource.yml",
        {
            "kind": "program",
            "id": name,
            "display_name": "Demo Program",
            "icon": "🚀",
            "settings": {"timeout": 10, "mode": "safe"},
        },
    )
    _yaml(
        path / "components.yml",
        {
            "schema_version": 1,
            "components": {
                "skills": [{"id": "present", "path": "present.md"}],
                "workflows": ["release_review"],
            },
        },
    )
    _write(path / "present.md", "present\n")
    _write(path / "config.toml", 'model = "gpt-base"\n[settings]\ntimeout = 20\n')
    return path


def _program_instance(
    root: Path,
    name: str,
    *,
    definition_id: str,
    icon: str | None = None,
) -> Path:
    path = root / "work/00-programs" / name
    _write(
        path / "program.md",
        f"# InstanceOSProgram: {name}\n\n## Status\n\n- Status: active\n\n## Purpose\n\nInstalled demo.\n",
    )
    overlay: dict[str, object] = {
        "kind": "instance-program",
        "id": name,
        "definition_id": definition_id,
        "settings": {"mode": "fast"},
    }
    if icon:
        overlay["icon"] = icon
    _yaml(path / ".agentic-resource.yml", overlay)
    _yaml(path / "components.yml", {"components": {"skills": []}})
    _yaml(path / "config/instance.yml", {"settings": {"timeout": 30}})
    _write(path / "logs/run.json", '{"status":"done"}\n')
    return path


def _automation(
    root: Path, name: str = "daily_sync", *, harness: str = "agentic_os"
) -> Path:
    path = root / "work/04-automations/engineering" / name
    _write(
        path / "automation.md",
        f"""# Automation: {name}

## Metadata

| Field | Value |
| --- | --- |
| Domain | `work` |
| Lane | `engineering` |
| Status | `active` |
| Level | `observe` |

## Purpose

Synchronize deterministic data.

## Trigger

- Source: local schedule
- Frequency: hourly

## Idempotency

- Key: daily-sync
- Duplicate handling: skip

## Permissions

- Read: local files
- Write: local receipts
- Requires approval: external writes
- Default action before approval: observe

## Outputs

- local receipt
""",
    )
    for filename in (
        "inputs.md",
        "outputs.md",
        "permissions.md",
        "failure-modes.md",
        "runbook.md",
        "tests.md",
        "context-contract.yml",
    ):
        _write(path / filename, f"# {filename}\n")
    _write(path / "logs/20260715T120000Z.json", '{"status":"done"}\n')
    _yaml(
        path / ".agentic-resource.yml",
        {
            "kind": "automation",
            "id": name,
            "harness": harness,
            "model": "gpt-5",
            "complexity": "high",
            "settings": {"batch": 5},
        },
    )
    return path


def _runtime(
    root: Path,
    automation_path: Path,
    *,
    status: str,
    finished_at: str,
) -> None:
    relative = automation_path.relative_to(root)
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {
            "execution_targets": [{"id": "codex_harness", "type": "agent_harness"}],
            "schedules": [
                {
                    "id": "daily_sync_hourly",
                    "enabled": True,
                    "cadence": "hourly",
                    "timezone": "UTC",
                    "execution_target": "codex_harness",
                    "host": "bigmac",
                    "next_due_at": "2026-07-16T03:00:00Z",
                    "command": f"cd {relative} && ./run.sh",
                }
            ],
        },
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/run-queue.yml",
        {
            "items": [
                {
                    "id": "run-1",
                    "ref": "daily_sync_hourly",
                    "status": status,
                    "finished_at": finished_at,
                    "log": "work/04-automations/engineering/daily_sync/logs/run.json",
                }
            ]
        },
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/automation-run-tracking.yml",
        {
            "automations": {
                "daily-sync": {
                    "cwd": str(relative),
                    "name": "Daily Sync",
                    "icon": "🔁",
                }
            }
        },
    )


def test_program_exact_join_config_provenance_components_icons_and_receipts(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _program_definition(root)
    _program_instance(root, "demo_install", definition_id="demo", icon="🛰️")

    result = query_operator_resources(
        root, "program", now=datetime(2026, 7, 16, tzinfo=UTC)
    )

    assert result["api_version"] == API_VERSION
    assert result["summary"]["remote_probes"] == 0
    definition = next(
        row for row in result["resources"] if row["id"] == "program_definition:demo"
    )
    instance = next(
        row
        for row in result["resources"]
        if row["id"] == "program_instance:work:demo_install"
    )
    assert definition["instances"][0]["instance_id"] == instance["id"]
    assert instance["instance"]["definition_join"] == "exact_definition_id"
    assert instance["icon"] == {"value": "🛰️", "source": "metadata"}
    provenance = {
        row["field"]: row for row in instance["configuration"]["field_provenance"]
    }
    assert provenance["settings.mode"]["layer"] == "instance_overlay"
    assert provenance["settings.timeout"]["value"] == 30
    assert provenance["settings.timeout"]["layer"] == "config"
    assert instance["configuration"]["layers"][-1]["status"] == "unknown"
    assert {row["id"] for row in instance["components"]} == set()
    assert instance["recent_evidence"][0]["source"] == "filesystem_receipt"
    assert definition["components"][0]["exists"] is True


def test_program_never_uses_same_name_inference_and_reports_missing_dependencies(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    definition = _program_definition(root, "same_name")
    _yaml(
        definition / "components.yml",
        {"components": {"skills": [{"id": "missing", "path": "missing.md"}]}},
    )
    _program_instance(root, "same_name", definition_id="different_definition")

    result = query_operator_resources(root, "program")
    instance = next(
        row for row in result["resources"] if row["resource_type"] == "instance"
    )

    assert instance["definition"] is None
    assert instance["instance"]["definition_join"] == "unmatched_definition_id"
    assert any(
        row["code"] == "program_definition_unmatched" for row in result["diagnostics"]
    )
    assert any(row["code"] == "dependency_missing" for row in result["diagnostics"])


def test_program_malformed_component_source_is_partial_not_fatal(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    definition = _program_definition(root)
    _write(definition / "components.yml", "components: [unterminated\n")

    result = query_operator_resources(root, "program")

    assert result["resources"]
    assert result["summary"]["partial"] is True
    assert any(row["code"] == "source_malformed" for row in result["diagnostics"])


def test_automation_keeps_identities_distinct_and_projects_error_health(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    automation = _automation(root)
    _runtime(root, automation, status="failed", finished_at="2026-07-16T01:00:00Z")

    result = query_operator_resources(
        root, "automation", now=datetime(2026, 7, 16, 2, tzinfo=UTC)
    )
    resource = result["resources"][0]

    assert resource["definition"]["definition_id"].startswith("automation_definition:")
    assert resource["instances"][0]["instance_id"].startswith("automation_instance:")
    assert resource["schedules"][0]["schedule_id"] == "daily_sync_hourly"
    assert resource["runs"][0]["run_id"] == "run-1"
    assert resource["health"]["status"] == "error"
    assert resource["health"]["liveness_observed"] is False
    assert resource["next_run_at"] == "2026-07-16T03:00:00Z"
    assert resource["tracking"]["tracking_id"] == "daily-sync"
    effective = resource["configuration"]["effective"]
    assert effective["model"] == "gpt-5"
    assert effective["host"] == "bigmac"
    assert resource["routing"]["host"]["value"] == "bigmac"
    assert resource["routing"]["harness"]["value"] == "agentic_os"
    assert resource["routing"]["execution_target"]["value"] == "codex_harness"
    assert resource["routing"]["model"]["value"] == "gpt-5"
    assert resource["routing"]["complexity"]["value"] == "high"
    assert any(
        row["finding_type"] == "qualification"
        for row in resource["qualification_findings"]
    )


def test_automation_stale_health_and_placement_denial(tmp_path: Path) -> None:
    root = _root(tmp_path)
    automation = _automation(root, harness="claude")
    _runtime(root, automation, status="done", finished_at="2026-07-14T00:00:00Z")

    result = query_operator_resources(
        root, "automation", now=datetime(2026, 7, 16, 2, tzinfo=UTC)
    )
    resource = result["resources"][0]

    assert resource["health"]["status"] == "stale"
    placement = next(
        row
        for row in resource["qualification_findings"]
        if row["finding_type"] == "placement"
    )
    assert placement["decision"] == "denied"
    assert placement["severity"] == "blocker"
    assert "CLAUDE.md" in placement["message"]


def test_automation_partial_sources_and_unmatched_tracking_remain_visible(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _write(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        "schedules: [bad\n",
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/automation-run-tracking.yml",
        {"automations": {"tracking-only": {"cwd": "work/other", "status": "ACTIVE"}}},
    )

    result = query_operator_resources(root, "automation")

    assert result["summary"]["partial"] is True
    assert any(row["code"] == "source_malformed" for row in result["diagnostics"])
    tracked = next(
        row
        for row in result["resources"]
        if row["resource_type"] == "tracking_instance"
    )
    assert tracked["definition"] is None
    assert tracked["qualification_findings"][0]["decision"] == "denied"


def test_fixed_cli_query_and_get_emit_versioned_json(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    _program_definition(root)

    assert main(["operator-resource", "query", "program", "--root", str(root)]) == 0
    queried = json.loads(capsys.readouterr().out)
    assert queried["api_version"] == API_VERSION
    resource_id = queried["resources"][0]["id"]

    assert (
        main(["operator-resource", "get", "program", resource_id, "--root", str(root)])
        == 0
    )
    fetched = json.loads(capsys.readouterr().out)
    assert fetched["query"] == {"kind": "program", "id": resource_id}
    assert fetched["resources"][0]["id"] == resource_id

    schema = json.loads(
        (
            Path(__file__).parents[1] / "schemas/operator-resource-query-v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(fetched, schema)


def test_get_rejects_unknown_exact_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _program_definition(root)

    try:
        get_operator_resource(root, "program", "program_definition:missing")
    except ValueError as exc:
        assert str(exc) == "operator resource not found: program_definition:missing"
    else:
        raise AssertionError("expected exact get to fail")
