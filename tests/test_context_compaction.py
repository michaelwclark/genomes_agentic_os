import base64
import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.config_ops import BASE_PROMPT_FILES, policy_for_layer, prompt_file_template
from genomes_agentic_os.context_compaction import build_compaction_plan, check_context_contracts


def make_target(root: Path, name: str) -> Path:
    target = root / "acme" / "03-workflows" / "engineering" / name
    target.mkdir(parents=True)
    (target / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (target / "context-contract.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "workflow",
                "inherits": ["parent"],
                "read": {"first": ["workflow.md"], "deferred": [], "exclude": []},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target


def test_compaction_plan_is_deterministic_and_contains_exact_rollback(tmp_path: Path) -> None:
    root = tmp_path / "os"
    first = make_target(root, "first")
    second = make_target(root, "second")
    duplicate = "# Generic router\n\nRoute to the parent.\n"
    (first / "ROUTER.md").write_text(duplicate, encoding="utf-8")
    (second / "ROUTER.md").write_text(duplicate, encoding="utf-8")

    check = check_context_contracts(root)
    plan = build_compaction_plan(root)

    assert check.ok
    assert check.duplicate_groups == 1
    assert plan == build_compaction_plan(root)
    assert plan["summary"]["files_preserved_in_rollback"] == 2
    restored = base64.b64decode(plan["rollback_manifest"]["files"][0]["content_base64"]).decode()
    assert restored == duplicate
    assert all(action["status"] == "proposed" for action in plan["actions"])


def test_context_cli_explain_check_and_plan_receipts(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    assert main(["workflow", "create", "acme", "engineering", "ship", "--root", str(root)]) == 0
    assert main(["automation", "create", "acme", "engineering", "watch_ship", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(
        [
            "context",
            "explain",
            "--domain",
            "acme",
            "--lane",
            "engineering",
            "--workflow",
            "ship",
            "--root",
            str(root),
        ]
    ) == 0
    explained = yaml.safe_load(capsys.readouterr().out)
    assert explained["ok"] is True
    assert explained["legacy_fallback"] is False
    assert explained["read_first"]
    workflow_root = root / "acme/03-workflows/engineering/ship"
    assert (workflow_root / "context-contract.yml").is_file()
    for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (workflow_root / copied_contract).exists()
    assert any(item["path"].endswith("acme/RULES.md") for item in explained["read_first"])

    legacy_words = sum(
        len(prompt_file_template(policy_for_layer("workflow_or_task"), filename).split())
        for filename in BASE_PROMPT_FILES
    )
    compact_words = sum(
        len((workflow_root / filename).read_text(encoding="utf-8").split())
        for filename in ("AGENTS.md", "PROFILE.md", "CLAUDE.md", "context-contract.yml")
    )
    assert compact_words <= legacy_words * 0.6

    assert main(["context", "check", "--root", str(root)]) == 0
    checked = yaml.safe_load(capsys.readouterr().out)
    assert checked["manifests"] == 2
    automation_root = root / "acme/04-automations/engineering/watch_ship"
    assert (automation_root / "context-contract.yml").is_file()
    for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (automation_root / copied_contract).exists()

    assert main(["config", "install-tree", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    for object_root in (workflow_root, automation_root):
        for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
            assert not (object_root / copied_contract).exists()

    receipts = tmp_path / "receipts"
    assert main(
        ["context", "compact", "--dry-run", "--root", str(root), "--output-dir", str(receipts)]
    ) == 0
    capsys.readouterr()
    plan = json.loads((receipts / "context-compaction-plan.json").read_text())
    rollback = json.loads((receipts / "context-compaction-rollback.json").read_text())
    assert plan["mode"] == "dry_run"
    assert rollback["operation"] == "context_compact"


def test_context_compact_refuses_implicit_mutation(tmp_path: Path, capsys) -> None:
    assert main(["context", "compact", "--root", str(tmp_path)]) == 2
    assert "plan-only" in capsys.readouterr().err
