from __future__ import annotations

import json
import subprocess
from argparse import Namespace

import pytest

from genomes_agentic_os.compose_pressure import (
    ComposeContainer,
    ComposePressureThresholds,
    WorktreeLifecycleEvidence,
    build_compose_pressure_report,
    execute_compose_teardown,
)
from genomes_agentic_os.cli import build_parser
from genomes_agentic_os.cli import hosts as cli_hosts
from genomes_agentic_os.cli.hosts import handle_compose_teardown


THRESHOLDS = {
    "orbstack_vmgr_rss_bytes": 1,
    "orbstack_vmgr_cpu_percent": 1,
    "load1_per_cpu": 1,
    "container_memory_bytes": 1,
    "container_cpu_percent": 1,
}
METRICS = {
    "orbstack_vmgr_rss_bytes": 2,
    "orbstack_vmgr_cpu_percent": 2,
    "load1_per_cpu": 2,
    "fseventsd_rss_bytes": 3,
    "fseventsd_cpu_percent": 4,
    "load1": 5,
    "load5": 6,
    "load15": 7,
}


def _container(path: str = "/tmp/worktrees/age-167") -> ComposeContainer:
    return ComposeContainer(
        name="age-167-api",
        project="age-167",
        state="running",
        cpu_percent=2,
        memory_bytes=2,
        bind_mounts=(path,),
        named_volumes=("age-167-db",),
        working_directory=path,
        config_files=(f"{path}/compose.yml", f"{path}/compose.override.yml"),
    )


def _owner(**changes) -> WorktreeLifecycleEvidence:
    values = {
        "worktree_id": "age-167",
        "path": "/tmp/worktrees/age-167",
        "lifecycle": "closed",
        "lifecycle_source": "/state.db",
        "provider_pull_request": "https://github.test/pull/1",
        "provider_merged": True,
        "dirty": False,
        "runtime_owner": "development-delivery",
        "runtime_identity": "runtime-123",
        "lifecycle_verified_at": "2026-08-14T10:00:00Z",
        "provider_fresh": True,
        "provider_state": "MERGED",
    }
    values.update(changes)
    return WorktreeLifecycleEvidence(**values)


def _proposal(owners=(_owner(),), thresholds=THRESHOLDS):
    return build_compose_pressure_report((_container(),), owners, METRICS, thresholds).proposals[0]


def test_thresholds_are_strict_all_or_nothing() -> None:
    missing = ComposePressureThresholds.from_config({"load1_per_cpu": 1})
    invalid = ComposePressureThresholds.from_config({**THRESHOLDS, "load1_per_cpu": 0})
    assert missing.configured is False
    assert "missing threshold: container_cpu_percent" in missing.errors
    assert invalid.configured is False
    assert "threshold must be positive: load1_per_cpu" in invalid.errors
    assert ComposePressureThresholds.from_config(THRESHOLDS).configured is True


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_thresholds_reject_non_finite_values(value: float) -> None:
    parsed = ComposePressureThresholds.from_config(
        {**THRESHOLDS, "load1_per_cpu": value}
    )
    assert parsed.configured is False
    assert "threshold must be finite: load1_per_cpu" in parsed.errors


def test_only_terminal_merged_clean_exact_owner_is_eligible() -> None:
    proposal = _proposal()
    assert proposal.recommendation == "eligible_for_explicit_teardown"
    assert proposal.as_dict()["automatic_action"] is False
    assert proposal.as_dict()["named_volume_disposition"] == {
        "decision": "retain",
        "volumes": ["age-167-db"],
    }


@pytest.mark.parametrize(
    ("owners", "reason"),
    [
        ((_owner(lifecycle="active"),), "lifecycle_not_terminal"),
        ((_owner(dirty=True),), "worktree_dirty"),
        ((_owner(provider_merged=False),), "provider_merge_unverified"),
        ((_owner(lifecycle_stale=True),), "lifecycle_evidence_stale"),
        ((_owner(provider_fresh=False),), "provider_evidence_stale"),
        ((_owner(provider_state="OPEN"),), "provider_pr_reopened"),
        ((_owner(reopen_marker=True),), "reopen_marker_present"),
        ((_owner(runtime_identity=None),), "runtime_identity_missing"),
        ((), "registered_worktree_missing"),
        ((_owner(), _owner(worktree_id="other")), "registered_worktree_ambiguous"),
    ],
)
def test_unsafe_or_ambiguous_ownership_is_retained(owners, reason) -> None:
    proposal = _proposal(owners=owners)
    assert proposal.recommendation == "retain"
    assert reason in proposal.reasons


def test_unconfigured_thresholds_are_report_only() -> None:
    report = build_compose_pressure_report((_container(),), (_owner(),), METRICS, None)
    assert report.proposals[0].recommendation == "unconfigured"
    assert report.as_dict()["mode"] == "report_only"


def test_single_fuzzy_owner_without_bind_mount_is_never_eligible() -> None:
    proposal = build_compose_pressure_report(
        (_container(path="/unrelated"),), (_owner(),), METRICS, THRESHOLDS
    ).proposals[0]
    assert proposal.recommendation == "retain"
    assert "ownership_fuzzy_without_bind_mount" in proposal.reasons


def test_compose_working_directory_and_config_files_must_be_consistent() -> None:
    other = ComposeContainer(
        **{
            **_container().__dict__,
            "name": "age-167-worker",
            "config_files": ("/tmp/worktrees/age-167/other.yml",),
        }
    )
    proposal = build_compose_pressure_report(
        (_container(), other), (_owner(),), METRICS, THRESHOLDS
    ).proposals[0]
    assert proposal.recommendation == "retain"
    assert "compose_config_files_inconsistent" in proposal.reasons


def test_executor_revalidates_exact_fingerprint_and_retains_named_volumes() -> None:
    proposal = _proposal()
    seen = []

    def runner(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "stopped", "")

    receipt = execute_compose_teardown(
        proposal,
        proposal,
        runner=runner,
        metric_reader=lambda: {"load1": 1},
        volume_reader=lambda names: names,
    )
    assert seen == [[
        "docker", "compose", "--project-name", "age-167",
        "--project-directory", "/tmp/worktrees/age-167",
        "-f", "/tmp/worktrees/age-167/compose.yml",
        "-f", "/tmp/worktrees/age-167/compose.override.yml", "down",
    ]]
    assert "-v" not in seen[0]
    assert receipt["applied"] is True
    assert receipt["named_volume_disposition"]["verified"] is True


def test_executor_refuses_changed_evidence() -> None:
    proposal = _proposal()
    changed = _proposal(owners=(_owner(dirty=True),))
    with pytest.raises(ValueError, match="fingerprint"):
        execute_compose_teardown(
            proposal,
            changed,
            runner=lambda *_args, **_kwargs: None,
            metric_reader=dict,
            volume_reader=lambda names: names,
        )


def test_executor_allows_metric_drift_but_rechecks_current_pressure() -> None:
    proposal = _proposal()
    changed_metrics = {**METRICS, "load1": 99, "load5": 88}
    current = build_compose_pressure_report(
        (_container(),), (_owner(),), changed_metrics, THRESHOLDS
    ).proposals[0]
    assert proposal.before_metrics != current.before_metrics
    assert proposal.evidence_fingerprint == current.evidence_fingerprint
    receipt = execute_compose_teardown(
        proposal,
        current,
        runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
        metric_reader=dict,
        volume_reader=lambda names: names,
    )
    assert receipt["applied"] is True

    quiet_container = ComposeContainer(
        **{**_container().__dict__, "cpu_percent": 0, "memory_bytes": 0}
    )
    below = build_compose_pressure_report(
        (quiet_container,), (_owner(),), {key: 0 for key in METRICS}, THRESHOLDS
    ).proposals[0]
    with pytest.raises(ValueError, match="not eligible"):
        execute_compose_teardown(
            proposal,
            below,
            runner=lambda *_args, **_kwargs: None,
            metric_reader=dict,
            volume_reader=lambda names: names,
        )


def test_host_cli_routes_explicit_compose_teardown_and_refuses_dry_invocation() -> None:
    args = build_parser().parse_args(
        ["host", "compose-teardown", "--proposal", "proposal.json", "--apply"]
    )
    assert args.handler is handle_compose_teardown
    assert args.apply is True
    with pytest.raises(ValueError, match="--apply"):
        handle_compose_teardown(
            Namespace(apply=False, proposal="unused", root="/tmp", host=None, config_root=None, json=True)
        )


def test_host_cli_allows_pressure_metric_drift_after_evidence_revalidation(
    tmp_path, monkeypatch, capsys
) -> None:
    proposal = _proposal()
    current = build_compose_pressure_report(
        (_container(),), (_owner(),), {**METRICS, "load1": 101}, THRESHOLDS
    ).proposals[0]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal.as_dict()), encoding="utf-8")
    monkeypatch.setattr(
        cli_hosts,
        "build_host_report",
        lambda *args, **kwargs: {
            "inventory": {"compose_pressure": {"proposals": [current.as_dict()]}}
        },
    )
    monkeypatch.setattr(cli_hosts, "collect_metrics", lambda: ({"load1": 1}, []))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(cli_hosts.subprocess, "run", run)
    exit_code = handle_compose_teardown(
        Namespace(
            apply=True,
            proposal=str(proposal_path),
            root=str(tmp_path),
            host=None,
            config_root=None,
            json=True,
        )
    )
    assert exit_code == 0
    assert any(command[:2] == ["docker", "compose"] for command in calls)
    assert json.loads(capsys.readouterr().out)["applied"] is True
