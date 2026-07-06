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
        "status_map": {
            "triaged": "Backlog",
            "queued": {"state": "Todo"},
        },
        "project_map": {
            "Agentic OS": "project-1",
        },
        "synced_statuses": ["triaged", "queued"],
    }


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
    assert result["checks"][1]["error_codes"] == ["USAGE_LIMIT_EXCEEDED"]


def test_intake_sync_doctor_validates_state_and_project_mapping(monkeypatch, tmp_path):
    module = load_intake_sync_module()

    def fake_profile(team_id, token):
        return {
            "team": {"id": team_id, "name": "Clarks Consulting", "key": "CC"},
            "states": [{"id": "state-1", "name": "Backlog", "type": "backlog"}],
            "projects": [{"id": "project-visible", "name": "Genomes Agentic OS"}],
        }

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
