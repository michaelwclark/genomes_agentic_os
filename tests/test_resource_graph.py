from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sqlite3

import yaml

from genomes_agentic_os.cli.resource_graph import handle_resource_graph_query, register
from genomes_agentic_os.resource_graph import MAX_RESULT_LIMIT, ResourceGraphError, ResourceGraphService


NOW = "2026-07-14T12:00:00Z"


def _mark_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".agentic_root").write_text("agentic_os: true\n", encoding="utf-8")


def _write_spec(
    root: Path,
    domain: str,
    project: str,
    lane: str,
    packet: str,
    metadata: dict,
    body: str = "",
) -> Path:
    _mark_root(root)
    item = root / domain / "02-projects" / project / "work-items" / lane / packet
    item.mkdir(parents=True)
    (item / "work.yml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (item / "SPEC.md").write_text(body, encoding="utf-8")
    return item


def _service(root: Path) -> ResourceGraphService:
    return ResourceGraphService(root, clock=lambda: NOW)


def test_scope_filters_and_provider_neutral_identity(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _write_spec(
        root,
        "clarks_consulting",
        "agentic_harness",
        "02-active",
        "001_graph",
        {
            "id": "001_graph",
            "title": "Build resource graph",
            "status": "building",
            "summary": "Add a local query layer.",
            "updated_at": "2026-07-14T10:00:00Z",
        },
    )
    _write_spec(root, "los", "los_app", "01-intake", "002_other", {"id": "002_other", "title": "Other"})

    result = _service(root).execute(
        """
        { resources(kind: SPEC, domain: "clarks_consulting", project: "agentic_harness") {
            id kind title scope { domain project }
            provenance { sourceId sourceKind nativeId relativePath }
            freshness { observedAt sourceUpdatedAt state }
            externalRefs { provider nativeId url }
            links { kind label href }
            privacyFlags
        }}
        """
    )

    assert "errors" not in result
    resource = result["data"]["resources"][0]
    assert resource["id"] == "spec:clarks_consulting:agentic_harness:001_graph"
    assert resource["scope"] == {"domain": "clarks_consulting", "project": "agentic_harness"}
    assert resource["provenance"]["sourceId"] == "agentic-os-filesystem"
    assert resource["provenance"]["sourceKind"] == "AGENTIC_OS_FILESYSTEM"
    assert resource["freshness"] == {
        "observedAt": NOW,
        "sourceUpdatedAt": "2026-07-14T10:00:00Z",
        "state": "CURRENT",
    }


def test_legacy_and_canonical_specs_share_one_projection(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _write_spec(
        root,
        "legacy_domain",
        "legacy_project",
        "02-active",
        "010_legacy",
        {
            "id": "010_legacy",
            "title": "Legacy packet",
            "status": "building",
            "type": "configuration",
            "summary": "Legacy summary",
        },
        "# Legacy\n\nTrack FLYWL-900 and https://github.com/example/repo/pull/42.\n",
    )
    _write_spec(
        root,
        "actual_path_domain",
        "actual_path_project",
        "01-intake",
        "020_canonical",
        {
            "schema_version": "agentic-os-spec/v1",
            "scope": {"domain": "canonical_domain", "project": "canonical_project"},
            "spec": {
                "id": "020_canonical",
                "title": "Canonical packet",
                "status": "ready",
                "type": "bug",
                "summary": "Canonical summary",
                "external_refs": [{"provider": "linear", "native_id": "CC-300", "url": "https://linear.app/x/CC-300"}],
            },
        },
        "# Canonical\n",
    )

    result = _service(root).execute(
        "{ specs(limit: 10) { id nativeId title status disposition blockedFrom type body resource { scope { domain project } externalRefs { provider nativeId url } } } }"
    )

    assert "errors" not in result
    specs = {item["nativeId"]: item for item in result["data"]["specs"]}
    assert specs["010_legacy"]["status"] == "in_progress"
    assert specs["010_legacy"]["disposition"] == "active"
    assert specs["010_legacy"]["type"] == "CONFIG"
    assert {ref["provider"] for ref in specs["010_legacy"]["resource"]["externalRefs"]} == {"github", "jira"}
    assert specs["020_canonical"]["status"] == "ready"
    assert specs["020_canonical"]["type"] == "BUG"
    assert specs["020_canonical"]["resource"]["scope"] == {
        "domain": "canonical_domain",
        "project": "canonical_project",
    }
    assert specs["020_canonical"]["resource"]["externalRefs"][0]["nativeId"] == "CC-300"


def test_introspection_exposes_query_only_schema(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    result = _service(root).execute("{ __schema { queryType { name } mutationType { name } types { name } } }")

    assert "errors" not in result
    assert result["data"]["__schema"]["queryType"]["name"] == "Query"
    assert result["data"]["__schema"]["mutationType"] is None
    assert "Resource" in {item["name"] for item in result["data"]["__schema"]["types"]}


def test_existing_state_database_events_are_projected_read_only(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    db_path = root / "harness" / "shared_factory" / "00-control-plane" / "state.db"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE events (
          id TEXT, type TEXT, observed_at TEXT, source_ref TEXT, summary TEXT,
          payload_json TEXT, contains_secret INTEGER, contains_customer_data INTEGER,
          run_log_link TEXT, source_url TEXT, domain TEXT
        );
        INSERT INTO events VALUES (
          'evt_1', 'github.pull_request.updated', '2026-07-14T11:00:00Z',
          'github:example/repo', 'PR updated', '{"project":"agentic_harness"}',
          0, 1, 'logs/run.md', 'https://github.com/example/repo/pull/42',
          'clarks_consulting'
        );
        """
    )
    connection.commit()
    connection.close()

    result = _service(root).execute(
        """
        { resources(kind: EVENT) {
            id kind scope { domain project }
            provenance { sourceId sourceKind nativeId relativePath }
            freshness { observedAt sourceUpdatedAt state }
            externalRefs { provider nativeId url }
            privacyFlags
        }}
        """
    )

    assert "errors" not in result
    event = result["data"]["resources"][0]
    assert event["id"] == "event:evt_1"
    assert event["scope"] == {"domain": "clarks_consulting", "project": "agentic_harness"}
    assert event["provenance"]["sourceKind"] == "AGENTIC_OS_STATE"
    assert event["freshness"]["sourceUpdatedAt"] == "2026-07-14T11:00:00Z"
    assert event["privacyFlags"] == ["CONTAINS_CUSTOMER_DATA"]

    # A query must not write to the existing projection or create sidecars.
    assert connectionless_count(db_path) == 1


def connectionless_count(db_path: Path) -> int:
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    finally:
        connection.close()


def test_hostile_resource_id_cannot_become_a_path(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read", encoding="utf-8")

    result = _service(root).execute('{ resource(id: "../../secret.txt") { id title } }')

    assert result["data"]["resource"] is None
    assert result["errors"][0]["extensions"]["code"] == "INVALID_RESOURCE_ID"
    assert "do not read" not in json.dumps(result)


def test_unmarked_directory_is_not_an_allowlisted_os_root(tmp_path: Path) -> None:
    root = tmp_path / "ordinary_directory"
    root.mkdir()

    try:
        ResourceGraphService(root)
    except ResourceGraphError as error:
        assert error.code == "INVALID_ROOT"
        assert str(error) == "allowlisted Agentic OS root marker is missing"
    else:
        raise AssertionError("unmarked directory was accepted as an Agentic OS root")


def test_symlinked_spec_outside_allowlisted_root_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    external = tmp_path / "outside"
    outside_item = _write_spec(external, "domain", "project", "01-intake", "001_escape", {"id": "001_escape"})
    project_items = root / "domain" / "02-projects" / "project" / "work-items" / "01-intake"
    project_items.mkdir(parents=True)
    (project_items / "001_escape").symlink_to(outside_item)

    result = _service(root).execute("{ specs { id } }")

    assert result == {"data": {"specs": []}}


def test_mutations_and_excessive_limits_have_deterministic_errors(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    service = _service(root)

    mutation = service.execute("mutation { archiveConversation(id: \"x\") }")
    assert mutation == {
        "data": None,
        "errors": [{"message": "mutations are disabled", "extensions": {"code": "MUTATIONS_DISABLED"}}],
    }

    excessive = service.execute(f"{{ resources(limit: {MAX_RESULT_LIMIT + 1}) {{ id }} }}")
    assert excessive["data"] is None or excessive["data"]["resources"] is None
    assert excessive["errors"][0]["extensions"]["code"] == "LIMIT_EXCEEDED"


def test_resolvers_do_not_use_network(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agentic_os"
    _write_spec(root, "domain", "project", "01-intake", "001_offline", {"id": "001_offline", "title": "Offline"})

    def fail_network(*_args, **_kwargs):
        raise AssertionError("resolver attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = _service(root).execute("{ resources { id title } specs { id title } }")

    assert "errors" not in result
    assert result["data"]["resources"][0]["title"] == "Offline"


def test_cli_handler_prints_machine_readable_result(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    args = argparse.Namespace(root=str(root), query="{ specs { id } }", variables=None, operation_name=None)

    assert handle_resource_graph_query(args) == 0
    assert json.loads(capsys.readouterr().out) == {"data": {"specs": []}}


def test_cli_module_registers_without_top_level_cli_edits(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _mark_root(root)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    register(subparsers)

    args = parser.parse_args(
        ["resource-graph", "query", "--root", str(root), "--query", "{ __typename }"]
    )
    assert args.handler(args) == 0
    assert json.loads(capsys.readouterr().out) == {"data": {"__typename": "Query"}}
