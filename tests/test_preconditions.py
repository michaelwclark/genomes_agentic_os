from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.preconditions import PRECONDITION_CONFIG, evaluate_preconditions
from genomes_agentic_os.scaffold import init_os


def _registry(root: Path, value: dict) -> None:
    path = root / PRECONDITION_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"preconditions": value}, sort_keys=False), encoding="utf-8")


def test_named_preconditions_compose_without_running_commands(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root)
    assert (root / PRECONDITION_CONFIG).is_file()
    (root / "feature-card.md").write_text("present\n", encoding="utf-8")
    _registry(
        root,
        {
            "feature-card-exists": {"type": "path_exists", "path": "feature-card.md"},
            "build-succeeds": {"type": "context_equals", "key": "build.ok", "equals": True},
            "ready-for-dispatch": {"type": "all", "checks": ["feature-card-exists", "build-succeeds"]},
        },
    )

    passed = evaluate_preconditions(root, ["ready-for-dispatch"], context={"build": {"ok": True}})
    failed = evaluate_preconditions(root, ["ready-for-dispatch"], context={"build": {"ok": False}})

    assert passed["mode"] == "evaluate_only"
    assert passed["ok"] is True
    assert passed["checks"][0]["checks"][0]["name"] == "feature-card-exists"
    assert failed["ok"] is False
    assert failed["checks"][0]["checks"][1]["name"] == "build-succeeds"


def test_precondition_paths_cannot_escape_the_installed_root(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root)
    _registry(root, {"unsafe-path": {"type": "path_exists", "path": "../outside"}})

    result = evaluate_preconditions(root, ["unsafe-path"])

    assert result["ok"] is False
    assert result["checks"] == [
        {
            "name": "unsafe-path",
            "ok": False,
            "kind": "path_exists",
            "reason": "precondition path must remain within the installed OS root",
        }
    ]
