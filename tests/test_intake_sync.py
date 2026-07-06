import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


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


def fake_visibility_with_configured_team(token):
    return {
        "viewer": {"id": "user-1", "name": "Genome", "email": "genome@example.com"},
        "teams": [{"id": "team-1", "key": "CC", "name": "Clarks Consulting"}],
    }


def _check_named(result: dict, name: str) -> dict:
    return next(check for check in result["checks"] if check["name"] == name)


def test_intake_sync_doctor_reports_linear_usage_limit(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def raise_usage_limit(team_id, token):
        raise module.LinearGraphQLError(
            [
                {
                    "message": "Workspace issue limit exceeded",
                    "extensions": {"code": "USAGE_LIMIT_EXCEEDED"},
                }
            ]
        )

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
    assert _check_named(result, "linear_team")["error_codes"] == ["USAGE_LIMIT_EXCEEDED"]


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
        raise module.LinearGraphQLError(
            [
                {
                    "message": "Authentication required",
                    "extensions": {"code": "AUTHENTICATION_ERROR"},
                }
            ]
        )

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
    assert token_check["error_codes"] == ["AUTHENTICATION_ERROR"]
    assert all(check["name"] != "linear_team" for check in result["checks"])


def test_linear_description_uses_marker_without_private_notion_url():
    module = load_intake_sync_module()

    description = module.build_linear_description("abc-def", "Plain summary")

    assert "Plain summary" in description
    assert "notion:abc-def" in description
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


def test_linear_workspace_url_key_swallows_errors(monkeypatch):
    module = load_intake_sync_module()

    def boom(query, variables, token):
        raise module.LinearGraphQLError([{"message": "Authentication required"}])

    monkeypatch.setattr(module, "linear_query", boom)
    assert module._linear_workspace_url_key("token") is None
