"""Regression coverage for the source-owned policy-context harness executable."""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import uuid

import pytest


SOURCE_ROOT = Path(__file__).parents[1]
SCRIPT = SOURCE_ROOT / "harness/bin/agentic-os-policy-context"


def load_policy_context():
    """Load the extension-less harness executable without invoking main()."""
    name = f"policy_context_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_profile(
    root: Path,
    relative_profile: str,
    repository: dict[str, object],
) -> Path:
    profile = root / relative_profile
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps({"repository": repository}, indent=2) + "\n",
        encoding="utf-8",
    )
    return profile


def resolved_plane(plane: str) -> dict[str, object]:
    return {
        "plane": plane,
        "fingerprint": f"{plane}-fingerprint",
        "layers": [
            {"rank": 0, "scope": "root", "root": "harness/root", "exists": True},
            {
                "rank": 1,
                "scope": "project",
                "root": "project/policy",
                "exists": True,
            },
        ],
        "sources": [{"rank": 1, "scope": "project", "source_ref": "project/policy/rule.md"}],
    }


def patch_plane_resolution(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(module, "agentic_os_binary", lambda: "agentic-os")
    monkeypatch.setattr(
        module,
        "resolve_plane",
        lambda _binary, _root, _domain, _project, plane, _overlays: resolved_plane(plane),
    )


def test_profile_paths_and_path_routing_support_domain_and_shared_factory_layouts(
    tmp_path: Path,
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    domain_checkout = tmp_path / "domain-checkout"
    shared_checkout = tmp_path / "shared-checkout"
    domain_checkout.mkdir()
    shared_checkout.mkdir()

    domain_profile = write_profile(
        root,
        "domains/acme/02-projects/payments/config/development.yml",
        {"root": str(domain_checkout)},
    )
    shared_profile = write_profile(
        root,
        "harness/shared_factory/02-projects/genomes_agentic_lib/config/development.yml",
        {"root": str(shared_checkout)},
    )

    assert module.profile_paths(root) == [domain_profile, shared_profile]
    assert module.route_from_path(root, domain_profile.parent.parent / "worktrees/current") == (
        "acme",
        "payments",
    )
    assert module.route_from_path(root, shared_profile.parent.parent / "worktrees/current") == (
        "shared_factory",
        "genomes_agentic_lib",
    )
    assert module.route_from_path(root, domain_checkout / "src") == ("acme", "payments")
    assert module.route_from_path(root, shared_checkout / "objects") == (
        "shared_factory",
        "genomes_agentic_lib",
    )


def test_shared_factory_resolution_selects_repository_and_hashes_source_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    source_checkout = tmp_path / "library-source"
    docs_checkout = tmp_path / "library-docs"
    source_checkout.mkdir()
    docs_checkout.mkdir()
    rules = source_checkout / "AGENTS.md"
    rules.write_text("# canonical source rules\n", encoding="utf-8")

    profile = write_profile(
        root,
        "harness/shared_factory/02-projects/genomes_agentic_lib/config/development.yml",
        {
            "catalog": [
                {"id": "source", "root": str(source_checkout)},
                {"id": "docs", "root": str(docs_checkout)},
            ],
            "rule_surfaces": {"globs": ["AGENTS.md"], "required": True},
        },
    )
    patch_plane_resolution(monkeypatch, module)
    args = argparse.Namespace(
        root=str(root),
        path=None,
        domain="shared_factory",
        project="genomes_agentic_lib",
        repository="source",
        overlay=[],
        strict_source_rules=True,
        detail="compact",
    )

    resolution = module.resolve(args)

    assert resolution["profile_source"] == str(profile)
    assert resolution["repository_id"] == "source"
    assert resolution["source_rules"]["checkout"] == str(source_checkout)
    assert resolution["source_rules"]["files"] == [
        {
            "source_ref": "AGENTS.md",
            "absolute_path": str(rules),
            "sha256": hashlib.sha256(rules.read_bytes()).hexdigest(),
        }
    ]
    assert len(resolution["effective_policy_fingerprint"]) == 64


def test_shared_factory_duplicate_domain_alias_is_a_handled_blocker(tmp_path: Path) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    write_profile(
        root,
        "domains/shared_factory/02-projects/genomes_agentic_lib/config/development.yml",
        {},
    )
    write_profile(
        root,
        "harness/shared_factory/02-projects/genomes_agentic_lib/config/development.yml",
        {},
    )

    assert module.profile_paths(root) == [
        root
        / "harness/shared_factory/02-projects/genomes_agentic_lib/config/development.yml"
    ]
    with pytest.raises(module.Blocker, match="domain alias profile is not supported"):
        module.profile_path_for(root, "shared_factory", "genomes_agentic_lib")


def test_strict_source_rules_returns_a_handled_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    empty_checkout = tmp_path / "empty-checkout"
    empty_checkout.mkdir()
    write_profile(
        root,
        "domains/acme/02-projects/payments/config/development.yml",
        {"root": str(empty_checkout), "rule_surfaces": {"globs": ["AGENTS.md"]}},
    )
    patch_plane_resolution(monkeypatch, module)

    result = module.main(
        [
            "--root",
            str(root),
            "--domain",
            "acme",
            "--project",
            "payments",
            "--strict-source-rules",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "BLOCKER: no source-checkout rule files matched" in captured.err
    assert "Do not proceed on inferred policy." in captured.err


def test_path_resolution_hashes_a_registered_worktree_not_the_primary_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    primary_checkout = tmp_path / "primary-checkout"
    primary_checkout.mkdir()
    (primary_checkout / "AGENTS.md").write_text("# primary rules\n", encoding="utf-8")
    profile = write_profile(
        root,
        "domains/acme/02-projects/payments/config/development.yml",
        {"root": str(primary_checkout), "rule_surfaces": {"globs": ["AGENTS.md"]}},
    )
    worktree = profile.parent.parent / "worktrees" / "feature-123"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /tmp/feature-123\n", encoding="utf-8")
    worktree_rules = worktree / "AGENTS.md"
    worktree_rules.write_text("# worktree rules\n", encoding="utf-8")
    patch_plane_resolution(monkeypatch, module)
    common_dir = primary_checkout / ".git"
    monkeypatch.setattr(module, "git_worktree_common_dir", lambda _checkout: common_dir)

    resolution = module.resolve(
        argparse.Namespace(
            root=str(root),
            path=str(worktree / "src"),
            domain=None,
            project=None,
            repository=None,
            overlay=[],
            strict_source_rules=True,
            detail="compact",
        )
    )

    assert resolution["source_rules"]["checkout"] == str(worktree)
    assert resolution["source_rules"]["files"] == [
        {
            "source_ref": "AGENTS.md",
            "absolute_path": str(worktree_rules),
            "sha256": hashlib.sha256(worktree_rules.read_bytes()).hexdigest(),
        }
    ]


def test_path_resolution_preserves_a_project_visible_external_worktree_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    primary_checkout = tmp_path / "primary-checkout"
    external_worktree = tmp_path / "external-worktrees" / "feature-123"
    primary_checkout.mkdir()
    (external_worktree / "src").mkdir(parents=True)
    external_rules = external_worktree / "AGENTS.md"
    external_rules.write_text("# external worktree rules\n", encoding="utf-8")
    profile = write_profile(
        root,
        "domains/acme/02-projects/payments/config/development.yml",
        {"root": str(primary_checkout), "rule_surfaces": {"globs": ["AGENTS.md"]}},
    )
    visible_worktree = profile.parent.parent / "worktrees" / "feature-123"
    visible_worktree.parent.mkdir()
    visible_worktree.symlink_to(external_worktree, target_is_directory=True)
    patch_plane_resolution(monkeypatch, module)
    common_dir = primary_checkout / ".git"
    monkeypatch.setattr(module, "git_worktree_common_dir", lambda _checkout: common_dir)

    resolution = module.resolve(
        argparse.Namespace(
            root=str(root),
            path=str(visible_worktree / "src"),
            domain=None,
            project=None,
            repository=None,
            overlay=[],
            strict_source_rules=True,
            detail="compact",
        )
    )

    assert resolution["source_rules"]["checkout"] == str(external_worktree)
    assert resolution["source_rules"]["files"][0]["absolute_path"] == str(external_rules)


def test_registered_worktree_must_belong_to_the_selected_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_policy_context()
    primary_checkout = tmp_path / "primary-checkout"
    worktree = tmp_path / "project" / "worktrees" / "feature-123"
    primary_checkout.mkdir()
    worktree.mkdir(parents=True)
    expected_common_dir = primary_checkout / ".git"
    other_common_dir = tmp_path / "other-checkout" / ".git"

    def common_dir_for(checkout: Path) -> Path:
        return expected_common_dir if checkout == primary_checkout else other_common_dir

    monkeypatch.setattr(module, "git_worktree_common_dir", common_dir_for)

    with pytest.raises(module.Blocker, match="does not belong to selected repository"):
        module.verify_selected_worktree(worktree, {"id": "source", "root": str(primary_checkout)})


def test_repository_selection_cannot_disagree_with_path_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_policy_context()
    root = tmp_path / "os"
    source_checkout = tmp_path / "source-checkout"
    docs_checkout = tmp_path / "docs-checkout"
    (source_checkout / "src").mkdir(parents=True)
    (docs_checkout / "src").mkdir(parents=True)
    (source_checkout / "AGENTS.md").write_text("# source\n", encoding="utf-8")
    (docs_checkout / "AGENTS.md").write_text("# docs\n", encoding="utf-8")
    write_profile(
        root,
        "domains/acme/02-projects/payments/config/development.yml",
        {
            "catalog": [
                {"id": "source", "root": str(source_checkout)},
                {"id": "docs", "root": str(docs_checkout)},
            ],
            "rule_surfaces": {"globs": ["AGENTS.md"], "required": True},
        },
    )
    patch_plane_resolution(monkeypatch, module)

    with pytest.raises(module.Blocker, match="selected repository source does not own --path"):
        module.resolve(
            argparse.Namespace(
                root=str(root),
                path=str(docs_checkout / "src"),
                domain=None,
                project=None,
                repository="source",
                overlay=[],
                strict_source_rules=True,
                detail="compact",
            )
        )


def test_recursive_rule_surfaces_are_complete_and_overflow_is_a_blocker(tmp_path: Path) -> None:
    module = load_policy_context()
    checkout = tmp_path / "checkout"
    (checkout / "nested").mkdir(parents=True)
    (checkout / ".claude" / "rules" / "nested").mkdir(parents=True)
    (checkout / "AGENTS.md").write_text("# root\n", encoding="utf-8")
    (checkout / "nested" / "AGENTS.md").write_text("# nested\n", encoding="utf-8")
    (checkout / ".claude" / "rules" / "nested" / "guard.md").write_text(
        "# guard\n", encoding="utf-8"
    )

    rules = module.resolve_source_rules(
        {"root": str(checkout)}, module.rule_surface_config({}), strict=True
    )
    assert {entry["source_ref"] for entry in rules["files"]} == {
        "AGENTS.md",
        "nested/AGENTS.md",
        ".claude/rules/nested/guard.md",
    }

    overflow = tmp_path / "overflow"
    for index in range(module.MAX_RULE_FILES + 1):
        rule = overflow / "rules" / str(index) / "AGENTS.md"
        rule.parent.mkdir(parents=True, exist_ok=True)
        rule.write_text("# rule\n", encoding="utf-8")
    with pytest.raises(module.Blocker, match="exceeds the safe limit"):
        module.resolve_source_rules(
            {"root": str(overflow)}, module.rule_surface_config({}), strict=True
        )


def test_effective_fingerprint_includes_checkout_and_priority_contract() -> None:
    module = load_policy_context()
    planes = [module.summarize_plane(resolved_plane("auto_dev"))]
    base_rules = {
        "status": "resolved",
        "checkout": "/tmp/checkout-a",
        "globs": ["*.md"],
        "priority_source": "one.md",
        "mode": "declared",
        "files": [
            {"source_ref": "one.md", "sha256": "same"},
            {"source_ref": "two.md", "sha256": "same"},
        ],
    }
    changed_priority = {**base_rules, "priority_source": "two.md"}
    changed_checkout = {**base_rules, "checkout": "/tmp/checkout-b"}

    baseline = module.composite_fingerprint(planes, base_rules)
    assert baseline != module.composite_fingerprint(planes, changed_priority)
    assert baseline != module.composite_fingerprint(planes, changed_checkout)
