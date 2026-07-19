from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.spec_adapters import FilesystemSpecAdapter, JiraSpecAdapter, LinearSpecAdapter
from genomes_agentic_os.spec_engine import (
    SPEC_DISPOSITIONS,
    SPEC_STATUSES,
    SPEC_TYPES,
    Spec,
    SpecEngine,
    normalize_status,
    normalize_type,
    sanitize_external_text,
)
from genomes_agentic_os.spec_policy import load_spec_policy


class FakeTransport:
    def __init__(self, *, fail: str | None = None):
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self.records: dict[str, dict] = {}

    def request(self, action, payload):
        payload = dict(payload)
        self.calls.append((action, payload))
        if self.fail == action:
            raise RuntimeError(f"{action} unavailable")
        if action == "verify_target":
            return {"ok": True}
        if action == "resolve_active_sprint":
            return {"ok": True, "sprint_id": "resolved-sprint"}
        if action == "find_by_idempotency":
            record = self.records.get(payload["idempotency_key"])
            return {"provider_id": record["provider_id"]} if record else {}
        if action in {"create_spec", "update_spec"}:
            key = payload["idempotency_key"]
            provider_id = payload.get("provider_id") or f"remote-{len(self.records) + 1}"
            record = {"provider_id": provider_id, "url": f"https://provider.invalid/{provider_id}", "payload": payload}
            self.records[key] = record
            return record
        if action == "get_spec":
            return {"ok": True, "provider_id": payload["provider_id"], "url": f"https://provider.invalid/{payload['provider_id']}"}
        if action == "get_by_spec_id":
            return {}
        if action == "list_specs":
            return {"items": []}
        raise AssertionError(action)


def create_project(tmp_path: Path, domain: str = "acme", project: str = "app") -> Path:
    root = tmp_path / "agentic_os"
    assert main(["project", "create", domain, project, "--root", str(root)]) == 0
    return root


def policy_for(primary="filesystem"):
    return {
        "adapters": {"primary": primary, "mirrors": [], "filesystem": {"enabled": True}},
        "authority": {"content": "filesystem", "lifecycle": primary},
    }


def test_canonical_model_and_schema_are_small_and_explicit():
    assert SPEC_TYPES == ("bug", "feature", "config")
    assert SPEC_STATUSES == ("idea", "grooming", "blocked", "ready", "in_progress", "built")
    assert SPEC_DISPOSITIONS == ("active", "cancelled", "duplicate", "wont_do", "archived")
    spec = Spec(id="001_login", title="Login", type="bug", status="idea", domain="acme", project="app")
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "spec.schema.json").read_text())
    jsonschema.validate(spec.to_mapping(), schema)
    policy_schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "spec-engine.schema.json").read_text()
    )
    shipped_policy = yaml.safe_load(
        (Path(__file__).parents[1] / "templates" / "runtime" / "spec-engine.yml").read_text()
    )
    jsonschema.validate(shipped_policy, policy_schema)


def test_legacy_status_and_type_normalization_retains_original_values():
    cases = {
        "captured": "idea",
        "triaged": "grooming",
        "specified": "grooming",
        "building": "in_progress",
        "validating": "in_progress",
        "finished": "built",
        "documented": "built",
    }
    for old, new in cases.items():
        assert normalize_status(old)[:2] == (new, old)
    assert normalize_type("investigation") == ("feature", "investigation")
    migrated = Spec.from_mapping({"id": "legacy", "title": "Legacy", "status": "specified", "type": "plan"})
    assert migrated.status == "grooming"
    assert migrated.type == "feature"
    assert migrated.legacy == {"status": "specified", "type": "plan"}
    archived = Spec.from_mapping({"id": "old", "title": "Old", "status": "archived"})
    assert archived.status == "idea"
    assert archived.disposition == "archived"
    assert archived.legacy["status"] == "archived"


def test_block_and_resume_preserve_blocked_from():
    spec = Spec(id="one", title="One", status="ready")
    spec.transition("blocked")
    assert (spec.status, spec.blocked_from) == ("blocked", "ready")
    spec.transition("resume")
    assert (spec.status, spec.blocked_from) == ("ready", None)


def test_layered_policy_precedence(tmp_path: Path):
    root = create_project(tmp_path)
    root_cfg = root / "harness" / "shared_factory" / "00-control-plane" / "spec-engine.yml"
    root_cfg.parent.mkdir(parents=True, exist_ok=True)
    root_cfg.write_text("spec_engine:\n  defaults:\n    type: config\n  adapters:\n    primary: filesystem\n", encoding="utf-8")
    domain_cfg = root / "domains" / "acme" / "00-control-plane" / "spec-engine.yml"
    domain_cfg.write_text("spec_engine:\n  defaults:\n    status: grooming\n", encoding="utf-8")
    project_cfg = root / "domains" / "acme" / "02-projects" / "app" / "config" / "spec-engine.yml"
    project_cfg.write_text("spec_engine:\n  defaults:\n    type: bug\n", encoding="utf-8")
    policy = load_spec_policy(root, domain="acme", project="app", invocation={"defaults": {"status": "ready"}})
    assert policy["defaults"]["type"] == "bug"
    assert policy["defaults"]["status"] == "ready"
    assert policy["adapters"]["primary"] == "filesystem"
    assert policy["loaded_from"][-1] == "invocation"


def test_filesystem_adapter_create_duplicate_transition_and_readback(tmp_path: Path):
    root = create_project(tmp_path)
    adapter = FilesystemSpecAdapter(root, "acme", "app")
    spec = Spec(id="001_login", title="Fix Login", type="bug", status="idea", domain="acme", project="app", summary="Repair login")
    receipt = adapter.create(spec, apply=True)
    assert receipt.ok and receipt.readback_verified
    path = root / "domains" / "acme" / "02-projects" / "app" / "work-items" / "01-intake" / "001_login"
    assert (path / "work.yml").is_file()
    assert adapter.create(spec, apply=True).status == "exists"
    duplicate = Spec(id="002_login", title="Fix Login", domain="acme", project="app")
    duplicate_receipt = adapter.create(duplicate, apply=True)
    assert duplicate_receipt.status == "duplicate"
    spec.transition("ready")
    moved = adapter.transition(spec, previous_status="idea", apply=True)
    assert moved.ok
    assert not path.exists()
    assert (root / "domains" / "acme" / "02-projects" / "app" / "work-items" / "02-active" / "001_login" / "work.yml").is_file()


def test_engine_filesystem_default_writes_while_dry_run_does_not(tmp_path: Path):
    root = create_project(tmp_path)
    fs = FilesystemSpecAdapter(root, "acme", "app")
    engine = SpecEngine(policy_for(), {"filesystem": fs})
    spec = Spec(id="001_one", title="One", domain="acme", project="app")
    planned = engine.add(spec, dry_run=True)
    assert planned["receipts"][0]["status"] == "planned"
    assert fs.get(spec.id) is None
    applied = engine.add(spec)
    assert applied["ok"] and fs.get(spec.id) is not None


def test_external_override_still_creates_required_local_identity(tmp_path: Path):
    root = create_project(tmp_path)
    fs = FilesystemSpecAdapter(root, "acme", "app")
    linear = LinearSpecAdapter(
        {"enabled": True, "target": {"team_id": "team", "project_id": "project"}},
        FakeTransport(),
    )
    engine = SpecEngine(policy_for(), {"filesystem": fs, "linear": linear})
    spec = Spec(id="001_external", title="External", domain="acme", project="app")

    result = engine.add(spec, adapter="linear", apply_external=True)

    assert [receipt["adapter"] for receipt in result["receipts"]] == ["filesystem", "linear"]
    persisted = fs.get(spec.id)
    assert persisted is not None
    assert persisted.external_refs == [
        {
            "adapter": "linear",
            "provider_id": "remote-1",
            "url": "https://provider.invalid/remote-1",
        }
    ]
    receipt_files = list(
        (
            root
            / "domains"
            / "acme"
            / "02-projects"
            / "app"
            / "work-items"
            / "01-intake"
            / spec.id
            / "artifacts"
            / "spec-receipts"
        ).glob("*-add.yml")
    )
    assert len(receipt_files) == 1
    assert all(receipt["readback_verified"] for receipt in result["receipts"])


def test_linear_adapter_dry_run_apply_readback_and_idempotency():
    transport = FakeTransport()
    adapter = LinearSpecAdapter({"enabled": True, "mode": "backlog", "target": {"team_id": "team", "project_id": "project"}}, transport)
    spec = Spec(id="one", title="One", status="grooming", domain="acme", project="app")
    plan = adapter.create(spec)
    assert plan.status == "planned" and plan.plan["native_status"] == "Backlog"
    first = adapter.create(spec, apply=True)
    second = adapter.create(spec, apply=True)
    assert first.ok and first.readback_verified
    assert second.provider_id == first.provider_id
    assert [action for action, _ in transport.calls].count("create_spec") == 1
    assert [action for action, _ in transport.calls].count("update_spec") == 1


def test_jira_adapter_resolves_active_sprint_and_maps_issue_type():
    transport = FakeTransport()
    adapter = JiraSpecAdapter(
        {
            "enabled": True,
            "mode": "sprint",
            "target": {"project_key": "APP", "site": "example"},
            "placement": {"default": "active_sprint", "allow_active_sprint_override": True},
            "issue_type_map": {"bug": "Bug", "feature": "Story", "config": "Task"},
        },
        transport,
    )
    spec = Spec(id="cfg", title="Config", type="config", domain="acme", project="app")
    planned = adapter.create(spec)
    assert planned.plan["issue_type"] == "Task"
    assert planned.plan["resolve_active_sprint"] is True
    applied = adapter.create(spec, apply=True)
    assert applied.ok
    create_payload = next(payload for action, payload in transport.calls if action == "create_spec")
    assert create_payload["resolved_sprint_id"] == "resolved-sprint"


def test_jira_active_sprint_override_rejection_is_a_receipt():
    adapter = JiraSpecAdapter(
        {
            "enabled": True,
            "target": {"project_key": "APP"},
            "placement": {"default": "backlog", "allow_active_sprint_override": False},
        },
        FakeTransport(),
    )
    receipt = adapter.create(Spec(id="one", title="One"), placement="active_sprint")
    assert receipt.ok is False
    assert receipt.status == "blocked"
    assert "disabled" in str(receipt.error)


def test_provider_outage_becomes_receipt_not_exception():
    adapter = LinearSpecAdapter({"enabled": True, "target": {"team_id": "team"}}, FakeTransport(fail="verify_target"))
    receipt = adapter.create(Spec(id="one", title="One"), apply=True)
    assert receipt.ok is False
    assert receipt.status == "blocked"
    assert "unavailable" in receipt.error


def test_provider_outage_receipt_is_persisted_with_local_identity(tmp_path: Path):
    root = create_project(tmp_path)
    fs = FilesystemSpecAdapter(root, "acme", "app")
    linear = LinearSpecAdapter(
        {"enabled": True, "target": {"team_id": "team"}},
        FakeTransport(fail="verify_target"),
    )
    engine = SpecEngine(policy_for(), {"filesystem": fs, "linear": linear})
    spec = Spec(id="001_retry", title="Retry", domain="acme", project="app")

    result = engine.add(spec, adapter="linear", apply_external=True)

    assert result["ok"] is False
    receipt_dir = (
        root
        / "domains"
        / "acme"
        / "02-projects"
        / "app"
        / "work-items"
        / "01-intake"
        / spec.id
        / "artifacts"
        / "spec-receipts"
    )
    payload = yaml.safe_load(next(receipt_dir.glob("*-add.yml")).read_text())
    assert payload["receipts"][1]["status"] == "blocked"
    assert "unavailable" in payload["receipts"][1]["error"]


def test_external_payload_is_sanitized():
    summary = "Use /Users/genome/agentic_os/private.md and https://notion.so/private-page with token=abcdefghijklmnopq"
    clean = sanitize_external_text(summary)
    assert "/Users/" not in clean
    assert "notion.so" not in clean
    assert "abcdefghijklmnopq" not in clean
    spec = Spec(id="one", title="One", summary=summary)
    assert "/Users/" not in spec.external_payload()["summary"]


def test_cli_add_show_list_transition_resume_and_doctor(tmp_path: Path, capsys):
    root = create_project(tmp_path)
    capsys.readouterr()
    assert main(["spec", "add", "acme", "app", "--title", "CLI Spec", "--summary", "Exercise CLI", "--type", "config", "--root", str(root)]) == 0
    created = yaml.safe_load(capsys.readouterr().out)
    spec_id = created["spec"]["id"]
    assert created["spec"]["type"] == "config"
    assert main(["spec", "show", "acme", "app", spec_id, "--root", str(root)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["id"] == spec_id
    assert main(["spec", "transition", "acme", "app", spec_id, "blocked", "--root", str(root)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["spec"]["blocked_from"] == "idea"
    assert main(["spec", "transition", "acme", "app", spec_id, "resume", "--root", str(root)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["spec"]["status"] == "idea"
    assert main(["spec", "list", "--domain", "acme", "--project", "app", "--root", str(root)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["count"] == 1
    assert main(["spec", "doctor", "--domain", "acme", "--project", "app", "--root", str(root)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["ok"] is True


def test_project_work_item_compatibility_routes_explicit_type_to_spec_engine(tmp_path: Path, capsys):
    root = create_project(tmp_path)
    capsys.readouterr()
    assert main(["project", "work-item", "create", "acme", "app", "--title", "Typed Bug", "--summary", "Bug", "--type", "bug", "--root", str(root)]) == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["spec"]["type"] == "bug"
    work_item = root / "domains" / "acme" / "02-projects" / "app" / "work-items" / "01-intake" / result["spec"]["id"]
    assert (work_item / "work.yml").is_file()
