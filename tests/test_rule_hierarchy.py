from __future__ import annotations

import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.context_contracts import resolve_context_contract
from genomes_agentic_os.rule_hierarchy import effective_rules


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registry(path: Path, rules: list[dict]) -> None:
    _write(path, yaml.safe_dump({"rules": rules}, sort_keys=False))


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "agentic_os"
    target = root / "acme" / "03-workflows" / "engineering" / "release_review"
    _write(root / "RULES.md", "# System rules\n\nProtect operator data.\n")
    _write(root / "acme" / "RULES.md", "# Acme rules\n\nUse company review policy.\n")
    _write(target / "RULES.md", "# Release review rules\n\nVerify every release receipt.\n")
    _write(
        target / "context-contract.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "workflow",
                "inherits": ["parent"],
                "read": {"first": ["RULES.md"], "deferred": [], "exclude": []},
                "capabilities": [],
                "providers": {},
                "overrides": {"rules": []},
            },
            sort_keys=False,
        ),
    )
    _registry(
        root / "harness" / "registries" / "rules.yml",
        [
            {
                "id": "system_guard",
                "key": "merge_policy",
                "name": "System merge guard",
                "description": "Never merge without validated checks.",
                "source": "../../outside.md",
                "effect": "deny",
                "strictness": 50,
            },
            {
                "id": "system_note",
                "name": "System note",
                "description": "Record exact terminal receipts.",
                "source": "harness/rules/system-note.md",
                "effect": "inform",
            },
        ],
    )
    _registry(
        root / "acme" / "00-control-plane" / "resource-registries" / "rules.yml",
        [
            {
                "id": "domain_guard",
                "key": "merge_policy",
                "name": "Domain merge preference",
                "description": "Allow a merge when a reviewer approves.",
                "source": "/tmp/secret-rule.md",
                "effect": "allow",
                "strictness": 10,
            }
        ],
    )
    return root, target


def test_effective_projection_matches_context_sources_and_never_opens_registry_source(tmp_path: Path) -> None:
    root, target = _tree(tmp_path)
    secret = tmp_path / "secret-rule.md"
    secret.write_text("THIS MUST NOT BE RENDERED", encoding="utf-8")

    result = effective_rules(root, target)
    resolved = resolve_context_contract(target, root=root)
    expected = [
        item.path.relative_to(root).as_posix()
        for item in (*resolved.read_first, *resolved.deferred)
        if item.exists and item.path.name == "RULES.md"
    ]

    assert result["api_version"] == "rules/v1"
    assert result["context_parity"]["rule_source_refs"] == expected
    assert {row["source_ref"] for row in result["rules"] if row["source_kind"] == "context_ruleset"} == set(expected)
    assert not any("THIS MUST NOT BE RENDERED" in row["body_markdown"] for row in result["rules"])
    local = next(row for row in result["rules"] if row["source_ref"].endswith("release_review/RULES.md"))
    assert local["local"] is True
    assert local["inherited"] is False
    assert all(not row["source_ref"].startswith("/") for row in result["rules"])


def test_strictest_wins_then_narrower_scope_and_reports_exact_conflicts(tmp_path: Path) -> None:
    root, target = _tree(tmp_path)
    project = root / "acme" / "02-projects" / "console"
    workflow = project / "03-workflows" / "engineering" / "release_review"
    _write(project / "RULES.md", "# Project rules\n\nApply the project release gate.\n")
    _write(
        workflow / "context-contract.yml",
        "schema_version: 1\nkind: workflow\ninherits: [parent]\nread:\n  first: []\n  deferred: []\n  exclude: []\ncapabilities: []\nproviders: {}\noverrides:\n  rules: []\n",
    )
    _registry(
        project / "config" / "resource-registries" / "rules.yml",
        [
            {
                "id": "project_guard",
                "key": "merge_policy",
                "name": "Project merge guard",
                "description": "Never merge until project checks pass.",
                "source": "ignored.md",
                "effect": "deny",
                "strictness": 50,
            }
        ],
    )

    result = effective_rules(root, workflow)
    candidates = [row for row in result["rules"] if row["key"] == "merge_policy"]
    winner = next(row for row in candidates if row["effective"])

    assert winner["rule_id"] == "project_guard"
    assert winner["scope"] == "project"
    assert all(row["shadowed_by"] == winner["id"] for row in candidates if row is not winner)
    conflict = next(item for item in result["diagnostics"] if item["code"] == "rule_conflict")
    assert conflict["winner_id"] == winner["id"]
    assert {item["id"] for item in conflict["definitions"]} == {row["id"] for row in candidates}
    assert all(item["source_ref"] for item in conflict["definitions"])


def test_numbering_is_stable_and_scope_specific(tmp_path: Path) -> None:
    root, target = _tree(tmp_path)
    first = effective_rules(root, target)
    second = effective_rules(root, target)
    numbers = [(row["id"], row["display_number"]) for row in first["rules"]]

    assert numbers == [(row["id"], row["display_number"]) for row in second["rules"]]
    assert len({number for _, number in numbers}) == len(numbers)
    assert any(number.startswith("SYS-") for _, number in numbers)
    assert any(number.startswith("DOM-") for _, number in numbers)
    assert any(number.startswith("WFL-") for _, number in numbers)


def test_duplicate_and_partial_registry_diagnostics_do_not_collapse_projection(tmp_path: Path) -> None:
    root, target = _tree(tmp_path)
    system_registry = root / "harness" / "registries" / "rules.yml"
    data = yaml.safe_load(system_registry.read_text(encoding="utf-8"))
    duplicate = dict(data["rules"][1])
    duplicate["id"] = "system_note_copy"
    duplicate["key"] = "system_note"
    data["rules"][1]["key"] = "system_note"
    data["rules"].append(duplicate)
    system_registry.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    domain_registry = root / "acme" / "00-control-plane" / "resource-registries" / "rules.yml"
    domain_registry.write_text("rules: [unterminated", encoding="utf-8")

    result = effective_rules(root, target)

    assert result["rules"]
    assert any(item["code"] == "duplicate_rule" for item in result["diagnostics"])
    assert any(item["code"] == "partial_rule_registry" for item in result["diagnostics"])
    assert result["counts"]["warnings"] >= 1


def test_cli_filters_search_scope_effect_local_and_conflicts(tmp_path: Path, capsys) -> None:
    root, target = _tree(tmp_path)
    args = [
        "rules",
        "effective",
        "--path",
        str(target),
        "--query",
        "release receipt",
        "--scope",
        "workflow",
        "--effect",
        "require",
        "--local-only",
        "--root",
        str(root),
        "--json",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["returned"] == 1
    assert result["rules"][0]["scope"] == "workflow"
    assert result["rules"][0]["local"] is True

    assert main(["rules", "effective", "--path", str(target), "--conflicts-only", "--root", str(root), "--json"]) == 0
    conflicts = json.loads(capsys.readouterr().out)
    assert {row["key"] for row in conflicts["rules"]} == {"merge_policy"}


def test_rule_target_rejects_paths_outside_root(tmp_path: Path, capsys) -> None:
    root, _ = _tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert main(["rules", "effective", "--path", str(outside), "--root", str(root), "--json"]) == 2
    assert "outside root" in capsys.readouterr().err
