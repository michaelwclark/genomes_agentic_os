import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def configured_bridge_command(monkeypatch):
    monkeypatch.setenv("GENOMES_LINEAR_BRIDGE_COMMAND", "node /tmp/linear.js")


def load_intake_sync_module():
    script = Path(__file__).resolve().parents[1] / "harness" / "bin" / "agentic-os-intake-sync"
    loader = SourceFileLoader("agentic_os_intake_sync_under_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def base_config() -> dict:
    return {
        "team_id": "team-1",
        "team_key": "CC",
        "team_name": "Clarks Consulting",
        "status_map": {
            "triaged": "Backlog",
            "queued": {"state": "Todo"},
        },
        "project_map": {
            "Agentic OS": "project-1",
        },
        "synced_statuses": ["triaged", "queued"],
    }


def test_intake_sync_bootstraps_source_runtime_under_isolated_python() -> None:
    script = Path(__file__).resolve().parents[1] / "harness" / "bin" / "agentic-os-intake-sync"
    completed = subprocess.run(
        [sys.executable, "-I", str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Sync the OS Work Intake" in completed.stdout


def fake_visibility_with_configured_team(token):
    return {
        "viewer": {"id": "user-1", "name": "Genome", "email": "genome@example.com"},
        "workspace": {"id": "workspace-1", "name": "Genome", "urlKey": "genomes"},
        "teams": [{"id": "team-1", "key": "CC", "name": "Clarks Consulting"}],
    }


def _check_named(result: dict, name: str) -> dict:
    return next(check for check in result["checks"] if check["name"] == name)


def test_intake_sync_doctor_reports_linear_usage_limit(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def raise_usage_limit(team_id, token):
        raise module.LinearBridgeError("USAGE_LIMITED", "Linear bridge operation failed")

    monkeypatch.setattr(module, "linear_get_token_visibility", fake_visibility_with_configured_team)
    monkeypatch.setattr(module, "linear_get_team_sync_profile", raise_usage_limit)

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    assert result["blocker_count"] == 1
    assert result["findings"][0]["code"] == "linear_usage_limit_exceeded"
    assert "USAGE_LIMIT_EXCEEDED" in result["findings"][0]["message"]
    assert _check_named(result, "linear_team")["error_codes"] == ["USAGE_LIMITED"]


def test_intake_sync_doctor_validates_state_and_project_mapping(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def fake_profile(team_id, token):
        return {
            "team": {"id": team_id, "name": "Clarks Consulting", "key": "CC"},
            "states": [{"id": "state-1", "name": "Backlog", "type": "backlog"}],
            "projects": [{"id": "project-visible", "name": "Genomes Agentic OS"}],
        }

    monkeypatch.setattr(module, "linear_get_token_visibility", fake_visibility_with_configured_team)
    monkeypatch.setattr(module, "linear_get_team_sync_profile", fake_profile)

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    codes = {finding["code"] for finding in result["findings"]}
    assert result["ok"] is False
    assert codes == {"missing_linear_state", "missing_linear_project"}


def test_intake_sync_doctor_passes_for_valid_mapping(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def fake_profile(team_id, token):
        return {
            "team": {"id": team_id, "name": "Clarks Consulting", "key": "CC"},
            "states": [
                {"id": "state-1", "name": "Backlog", "type": "backlog"},
                {"id": "state-2", "name": "Todo", "type": "unstarted"},
            ],
            "projects": [{"id": "project-1", "name": "Genomes Agentic OS"}],
        }

    monkeypatch.setattr(module, "linear_get_token_visibility", fake_visibility_with_configured_team)
    monkeypatch.setattr(module, "linear_get_team_sync_profile", fake_profile)

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is True
    assert result["blocker_count"] == 0
    assert result["findings"] == []
    token_check = _check_named(result, "linear_token")
    assert token_check["ok"] is True
    assert token_check["configured_team_visible"] is True


def test_intake_sync_doctor_flags_configured_team_not_visible(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def fake_visibility_other_workspace(token):
        return {
            "viewer": {"id": "user-1", "name": "Genome", "email": "genome@example.com"},
            "workspace": {"id": "workspace-2", "name": "Ledgerline", "urlKey": "ledgerline"},
            "teams": [{"id": "team-other", "key": "LED", "name": "Ledgerline"}],
        }

    def fail_profile(team_id, token):
        raise AssertionError("team profile must not be queried when the configured team is not visible")

    monkeypatch.setattr(module, "linear_get_token_visibility", fake_visibility_other_workspace)
    monkeypatch.setattr(module, "linear_get_team_sync_profile", fail_profile)

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    finding = next(f for f in result["findings"] if f["code"] == "linear_team_not_visible")
    assert "Clarks Consulting / CC" in finding["message"]
    assert "Ledgerline (LED)" in finding["message"]
    assert "personal API key" in finding["remediation"]
    assert "connector-backed" in finding["remediation"]
    token_check = _check_named(result, "linear_token")
    assert token_check["ok"] is False
    assert token_check["configured_team_visible"] is False
    assert all(check["name"] != "linear_team" for check in result["checks"])


def test_intake_sync_doctor_flags_invalid_linear_token(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def raise_auth_error(token):
        raise module.LinearBridgeError("AUTH_ERROR", "Linear bridge operation failed")

    monkeypatch.setattr(module, "linear_get_token_visibility", raise_auth_error)

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    finding = next(f for f in result["findings"] if f["code"] == "linear_token_invalid")
    assert "token visibility check" in finding["message"]
    assert "connector-backed" in finding["remediation"]
    token_check = _check_named(result, "linear_token")
    assert token_check["ok"] is False
    assert token_check["error_codes"] == ["AUTH_ERROR"]
    assert all(check["name"] != "linear_team" for check in result["checks"])


def test_linear_description_uses_marker_without_private_notion_url():
    module = load_intake_sync_module()

    description = module.build_linear_description("abc-def", "Plain summary")

    assert "Plain summary" in description
    assert "notion:abc-def" in description
    assert "`notion:abc-def`" not in description
    assert description.splitlines()[-1] == "notion:abc-def"
    assert "notion.so" not in description
    assert "app.notion.com" not in description


def test_external_write_scrubber_blocks_private_paths_and_urls():
    module = load_intake_sync_module()

    findings = module.external_write_findings(
        "See /Users/genome/agentic_os/private.md and https://app.notion.com/p/private"
    )

    assert {finding["code"] for finding in findings} == {"local_path", "notion_url"}


def test_external_write_scrubber_blocks_token_shaped_values():
    module = load_intake_sync_module()

    findings = module.external_write_findings("token lin_api_abcdefghijklmnop1234567890 should not leave")

    assert [finding["code"] for finding in findings] == ["token_value"]


def test_linear_token_env_default_and_override():
    module = load_intake_sync_module()
    assert module._linear_token_env({}) == "LINEAR_TOKEN"
    assert module._linear_token_env({"token_env": "  "}) == "LINEAR_TOKEN"
    assert module._linear_token_env({"token_env": "LINEAR_CC_TOKEN"}) == "LINEAR_CC_TOKEN"


def test_intake_sync_doctor_missing_token_names_configured_env(monkeypatch, tmp_path):
    module = load_intake_sync_module()
    cfg = base_config()
    cfg["token_env"] = "LINEAR_CC_TOKEN"

    result = module.run_doctor(
        cfg,
        config_path=tmp_path / "intake-sync.yml",
        token_linear="",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    finding = next(f for f in result["findings"] if f["code"] == "missing_linear_token")
    assert "LINEAR_CC_TOKEN env var is not set." in finding["message"]
    assert "LINEAR_CC_TOKEN" in finding["remediation"]


def test_intake_sync_doctor_blocks_missing_bridge_command(monkeypatch, tmp_path):
    module = load_intake_sync_module()
    monkeypatch.delenv("GENOMES_LINEAR_BRIDGE_COMMAND")

    result = module.run_doctor(
        base_config(),
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    finding = next(
        f for f in result["findings"] if f["code"] == "linear_bridge_unconfigured"
    )
    assert "GENOMES_LINEAR_BRIDGE_COMMAND" in finding["message"]
    assert _check_named(result, "linear_bridge_command")["ok"] is False


def test_intake_sync_doctor_team_not_visible_names_configured_env(monkeypatch, tmp_path):
    module = load_intake_sync_module()
    cfg = base_config()
    cfg["token_env"] = "LINEAR_CC_TOKEN"

    def fake_visibility_other_workspace(token):
        return {
            "viewer": {"id": "user-1", "name": "Genome", "email": "genome@example.com"},
            "teams": [{"id": "team-other", "key": "LED", "name": "Ledgerline"}],
        }

    monkeypatch.setattr(module, "linear_get_token_visibility", fake_visibility_other_workspace)

    result = module.run_doctor(
        cfg,
        config_path=tmp_path / "intake-sync.yml",
        token_linear="linear-token",
        token_notion="",
        check_notion=False,
    )

    assert result["ok"] is False
    finding = next(f for f in result["findings"] if f["code"] == "linear_team_not_visible")
    assert finding["message"].startswith("LINEAR_CC_TOKEN authenticates as")
    assert "export it as LINEAR_CC_TOKEN" in finding["remediation"]


def test_linear_url_workspace_parses_slug():
    module = load_intake_sync_module()
    assert module._linear_url_workspace("https://linear.app/ledgerline/issue/LED-207/x") == "ledgerline"
    assert module._linear_url_workspace("https://linear.app/agenticoslinear/issue/CC-182") == "agenticoslinear"
    assert module._linear_url_workspace("https://example.com/no-linear") is None
    assert module._linear_url_workspace(None) is None


def test_linear_workspace_url_key_fails_closed(monkeypatch):
    module = load_intake_sync_module()

    class BrokenClient:
        def request(self, operation, args):
            raise module.LinearBridgeError("AUTH_ERROR", "Linear bridge operation failed")

    monkeypatch.setattr(module, "_linear_client", lambda token: BrokenClient())
    with pytest.raises(module.LinearBridgeError) as error:
        module._linear_workspace_url_key("token")
    assert error.value.code == "AUTH_ERROR"


def test_linear_workspace_url_key_pins_reviewed_bridge_shape(monkeypatch):
    module = load_intake_sync_module()
    calls = []

    class FakeClient:
        def request(self, operation, args):
            calls.append((operation, args))
            if operation == "listTeams":
                return [{"id": "team-1", "key": "AGE", "name": "Agentic OS"}]
            return {
                "team": {"id": "team-1", "key": "AGE", "name": "Agentic OS"},
                "viewer": {"id": "viewer-1"},
                "workspace": {"id": "workspace-1", "urlKey": "genomes"},
            }

    monkeypatch.setattr(module, "_linear_client", lambda token: FakeClient())
    assert module._linear_workspace_url_key("token") == "genomes"
    assert calls == [
        ("listTeams", {}),
        ("preflightIdentity", {"teamId": "team-1"}),
    ]


def test_linear_token_visibility_handles_zero_visible_teams(monkeypatch):
    module = load_intake_sync_module()

    class FakeClient:
        def request(self, operation, args):
            assert operation == "listTeams"
            return []

    monkeypatch.setattr(module, "_linear_client", lambda token: FakeClient())
    assert module.linear_get_token_visibility("token") == {
        "viewer": {"id": None, "name": None, "email": None},
        "teams": [],
        "workspace": {"id": None, "name": None, "urlKey": None},
    }


def test_linear_get_labels_filters_foreign_team_labels(monkeypatch):
    module = load_intake_sync_module()
    observed = []

    class FakeClient:
        def request(self, operation, args):
            observed.append((operation, args))
            return [
                {"id": "l-ws", "name": "Improvement"},
                {"id": "l-cc", "name": "aos-intake", "teamId": "team-1"},
            ]

    monkeypatch.setattr(module, "_linear_client", lambda token: FakeClient())
    usable = module.linear_get_labels("token", "team-1")
    assert {l["id"] for l in usable} == {"l-ws", "l-cc"}
    assert observed == [("listLabels", {"teamId": "team-1"})]


def test_linear_marker_scan_is_exhaustive_and_blocks_duplicates(monkeypatch):
    module = load_intake_sync_module()

    class FakeClient:
        def __init__(self, issues_by_team):
            self.issues_by_team = issues_by_team
            self.calls = []

        def request(self, operation, args):
            self.calls.append((operation, args))
            if operation == "listTeams":
                return [
                    {"id": team_id, "key": team_id.upper(), "name": team_id}
                    for team_id in self.issues_by_team
                ]
            return self.issues_by_team[args["teamId"]]

    one = FakeClient(
        {
            "team": [
                {"id": "other", "description": "notion:page-10"},
            ],
            "moved": [
                {"id": "match", "description": "body\n`notion:page-1`"},
            ],
        }
    )
    monkeypatch.setattr(module, "_linear_client", lambda token: one)
    assert module.linear_search_by_marker("page-1", "team", "token")["id"] == "match"
    assert one.calls == [
        ("listTeams", {}),
        ("listIssuesByTeam", {"teamId": "team", "includeArchived": True}),
        ("listIssuesByTeam", {"teamId": "moved", "includeArchived": True}),
    ]

    duplicate = FakeClient(
        {
            "team": [{"id": "one", "description": "notion:page-1"}],
            "other": [{"id": "two", "description": "notion:page-1"}],
        }
    )
    monkeypatch.setattr(module, "_linear_client", lambda token: duplicate)
    with pytest.raises(module.LinearBridgeError) as error:
        module.linear_search_by_marker("page-1", "team", "token")
    assert error.value.code == "CONFLICT"


def test_linear_create_and_update_preserve_legacy_issue_fields(monkeypatch):
    module = load_intake_sync_module()
    calls = []

    class FakeClient:
        def request(self, operation, args):
            calls.append((operation, args))
            return {
                "id": "issue-1",
                "identifier": "AGE-1",
                "url": "https://linear.app/genomes/issue/AGE-1/example",
                "state": {"id": "todo", "name": "Todo", "type": "unstarted"},
                "priority": 2,
            }

    monkeypatch.setattr(module, "_linear_client", lambda token: FakeClient())
    issue = module.linear_create_issue(
        "Title", "Description", "todo", 2, ["label"], "team", "project", "token"
    )
    module.linear_update_issue("issue-1", "started", 1, "token")
    assert issue["identifier"] == "AGE-1"
    assert calls == [
        (
            "createIssue",
            {
                "input": {
                    "title": "Title",
                    "description": "Description",
                    "stateId": "todo",
                    "priority": 2,
                    "labelIds": ["label"],
                    "teamId": "team",
                    "projectId": "project",
                }
            },
        ),
        (
            "updateIssue",
            {"issue": "issue-1", "input": {"stateId": "started", "priority": 1}},
        ),
    ]


def test_linear_find_or_create_uses_atomic_bridge_reconciliation(monkeypatch):
    module = load_intake_sync_module()
    calls = []

    class FakeClient:
        def request(self, operation, args):
            calls.append((operation, args))
            return {
                "issue": {"id": "issue-1", "identifier": "AGE-1", "url": "url"},
                "created": False,
            }

    monkeypatch.setattr(module, "_linear_client", lambda token: FakeClient())
    issue, created = module.linear_find_or_create_issue(
        "notion:page-1",
        title="Title",
        description="Description",
        state_id="todo",
        priority=2,
        label_ids=["label"],
        team_id="team",
        project_id="project",
        token="token",
    )
    assert issue["identifier"] == "AGE-1"
    assert created is False
    assert calls[0][0] == "findOrCreateIssueByMarker"
    assert calls[0][1]["marker"] == "notion:page-1"
