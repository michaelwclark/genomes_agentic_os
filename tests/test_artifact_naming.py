from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import runpy

import yaml

from genomes_agentic_os.artifact_naming import (
    ArtifactNamingPolicy,
    dated_name,
    load_artifact_naming_policy,
    split_date_prefix,
)
from genomes_agentic_os.lifecycle import create_project_work_item
from genomes_agentic_os.scaffold import create_project, create_run_log, init_os
from genomes_agentic_os.validate import validate_root


def test_default_policy_is_enabled_with_mmddyy_hyphen(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root, domains=("acme",))
    policy = load_artifact_naming_policy(root)
    assert policy.enabled is True
    assert policy.date_format == "%m%d%y"
    assert policy.separator == "-"
    assert dated_name(
        "example",
        when=datetime(2026, 7, 18, tzinfo=timezone.utc),
        policy=policy,
        scope="work_items",
    ) == "071826-example"
    assert split_date_prefix("071826-example", policy) == ("071826", "example")


def test_policy_can_be_disabled_per_root(tmp_path: Path) -> None:
    root = tmp_path / "os"
    config = root / "harness/config/artifact-naming.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yaml.safe_dump({"artifact_naming": {"date_prefix": {"enabled": False}}}),
        encoding="utf-8",
    )
    policy = load_artifact_naming_policy(root)
    assert dated_name("example", when=None, policy=policy, scope="work_items") == "example"


def test_new_work_items_and_run_logs_receive_date_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root, domains=("acme",))
    create_project(root, "acme", "app")
    result = create_project_work_item(
        root,
        "acme",
        "app",
        title="Example Work",
        summary="Exercise naming policy.",
        status="building",
        item_format="packet",
    )
    packet = next(path for path in result.created if path.is_dir() and (path / "work.yml").is_file())
    assert re.match(r"^\d{6}-001_example_work$", packet.name)
    assert yaml.safe_load((packet / "work.yml").read_text())["id"] == packet.name

    run_result = create_run_log(root, "acme", "example")
    run_root = next(path for path in run_result.created if path.is_dir() and (path / "run-log.md").is_file())
    assert re.match(r"^\d{6}-\d{6}Z-acme-example$", run_root.name)


def test_custom_separator_and_format_are_respected() -> None:
    policy = ArtifactNamingPolicy(date_format="%Y%m%d", separator="_")
    assert dated_name(
        "work",
        when=datetime(2026, 7, 18, tzinfo=timezone.utc),
        policy=policy,
        scope="work_items",
    ) == "20260718_work"


def test_root_validation_rejects_invalid_naming_config(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root, domains=("acme",))
    (root / "harness/config/artifact-naming.yml").write_text(
        "artifact_naming:\n  date_prefix:\n    separator: '/'\n",
        encoding="utf-8",
    )

    result = validate_root(root)

    assert any("invalid artifact naming config" in error for error in result.errors)


def test_quiet_runner_uses_configured_async_run_prefix(tmp_path: Path) -> None:
    root = tmp_path / "os"
    init_os(root, domains=("acme",))
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-quiet-run"
    namespace = runpy.run_path(str(script))

    run_id = namespace["generated_run_id"](root / "artifacts/async-runs", "Focused Tests")

    assert re.match(r"^\d{6}-\d{6}-focused-tests$", run_id)
