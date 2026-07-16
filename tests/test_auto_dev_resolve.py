import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


def load_resolver_module():
    script = Path(__file__).resolve().parents[1] / "harness" / "bin" / "agentic-os-auto-dev-resolve"
    loader = SourceFileLoader("agentic_os_auto_dev_resolve_under_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def project_yml(repo_root: Path) -> dict:
    return {
        "dev_factory": {
            "enabled": True,
            "tracker": {
                "primary": "linear",
                "linear": {
                    "team_id": "team-led",
                    "project_id": "project-led",
                    "workflow": {
                        "claimed": "In Progress",
                        "pr_open": "In Review",
                        "ready_for_merge": "In Review",
                        "merged": "Done",
                        "blocked": "Blocked",
                    },
                },
            },
            "repo": {"root": str(repo_root)},
        }
    }


def linear_response(*, issue_team_id: str = "team-led", issue_project_id: str = "project-led", states: list[str] | None = None) -> dict:
    state_names = states or ["In Progress", "In Review", "Done", "Blocked"]
    return {
        "team": {
            "id": "team-led",
            "name": "LedgerLine",
            "key": "LED",
            "states": {"nodes": [{"name": name, "type": "custom"} for name in state_names]},
            "projects": {"nodes": [{"id": "project-led", "name": "Genome's Agentic OS"}]},
        },
        "searchIssues": {
            "nodes": [
                {
                    "identifier": "CC-182",
                    "title": "Conversation report hardening",
                    "url": "https://linear.app/example/issue/CC-182/example",
                    "team": {"id": issue_team_id, "name": "Clarks Consulting", "key": "CC"},
                    "project": {"id": issue_project_id, "name": "Genomes Agentic OS"},
                    "state": {"name": "Todo", "type": "unstarted"},
                }
            ]
        },
    }


def linear_check(results: list[dict]) -> dict:
    return next(result for result in results if result["name"] == "linear_tracker")


def test_auto_dev_resolver_blocks_linear_tracker_team_drift(monkeypatch, tmp_path):
    module = load_resolver_module()
    monkeypatch.setenv("LINEAR_TOKEN", "token")
    monkeypatch.setattr(module, "_linear_graphql", lambda query, variables, token: linear_response(issue_team_id="team-cc"))

    results = module._preflight(tmp_path, project_yml(tmp_path), tmp_path / "packet", {"tracker": "CC-182"})

    check = linear_check(results)
    assert check["ok"] is False
    assert "belongs to Linear team CC / Clarks Consulting" in check["detail"]
    assert "project.yml points at LED / LedgerLine" in check["detail"]


def test_auto_dev_resolver_blocks_missing_linear_workflow_state(monkeypatch, tmp_path):
    module = load_resolver_module()
    monkeypatch.setenv("LINEAR_TOKEN", "token")
    monkeypatch.setattr(
        module,
        "_linear_graphql",
        lambda query, variables, token: linear_response(states=["In Progress", "In Review", "Done"]),
    )

    results = module._preflight(tmp_path, project_yml(tmp_path), tmp_path / "packet", {"tracker": "CC-182"})

    check = linear_check(results)
    assert check["ok"] is False
    assert "missing Linear state(s): Blocked" in check["detail"]


def test_auto_dev_resolver_passes_matching_linear_tracker(monkeypatch, tmp_path):
    module = load_resolver_module()
    monkeypatch.setenv("LINEAR_TOKEN", "token")
    monkeypatch.setattr(module, "_linear_graphql", lambda query, variables, token: linear_response())

    results = module._preflight(tmp_path, project_yml(tmp_path), tmp_path / "packet", {"tracker": "CC-182"})

    check = linear_check(results)
    assert check["ok"] is True
    assert "Linear tracker verified: CC-182" in check["detail"]


def test_auto_dev_resolver_uses_configured_linear_token_env(monkeypatch, tmp_path):
    module = load_resolver_module()
    config = project_yml(tmp_path)
    config["dev_factory"]["tracker"]["linear"]["token_env"] = "LINEAR_CC_TOKEN"
    monkeypatch.delenv("LINEAR_TOKEN", raising=False)
    monkeypatch.setenv("LINEAR_CC_TOKEN", "cc-token")
    observed = {}

    def fake_graphql(query, variables, token):
        observed["token"] = token
        return linear_response()

    monkeypatch.setattr(module, "_linear_graphql", fake_graphql)

    results = module._preflight(tmp_path, config, tmp_path / "packet", {"tracker": "CC-182"})

    assert linear_check(results)["ok"] is True
    assert observed["token"] == "cc-token"
