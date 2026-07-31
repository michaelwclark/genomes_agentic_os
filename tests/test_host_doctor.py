from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

import pytest

from genomes_agentic_os.host_doctor import (
    apply_safe_repairs,
    build_host_report,
    load_host_policies,
    host_projection,
    next_run_at,
    render_host_report,
    project_host_report,
    project_http_report,
    project_report_drop,
    write_host_report,
    _docker_inventory,
    _worktree_inventory,
    notion_blocks,
)


class _Response:
    status = 202


def test_http_projection_uses_env_token_without_returning_it(monkeypatch) -> None:
    seen = {}
    def fetcher(request, timeout):
        seen['authorization'] = request.headers['Authorization']
        seen['timeout'] = timeout
        return _Response()
    monkeypatch.setenv('TEST_HOST_TOKEN', 'secret-value')
    result = project_http_report(
        {'api_version': 'auto-doctor-report/v1', 'host': 'bigmac'},
        'http://example.test/api/host-health/bigmac',
        token_env='TEST_HOST_TOKEN',
        fetcher=fetcher,
    )
    assert result == {'applied': True, 'url': 'http://example.test/api/host-health/bigmac', 'status': 202}
    assert seen == {'authorization': 'Bearer secret-value', 'timeout': 20}
    assert 'secret-value' not in str(result)


def test_report_drop_uses_fixed_scp_command(tmp_path: Path) -> None:
    latest = tmp_path / 'latest.json'
    latest.write_text('{}', encoding='utf-8')
    seen = []
    def runner(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')
    result = project_report_drop(
        latest,
        'genomesbox:/home/genome/agentic_os/auto-doctor/bigmac/latest.json',
        runner=runner,
    )
    assert result['applied'] is True
    assert seen[0][:5] == ['scp', '-q', '-o', 'ConnectTimeout=8', str(latest.resolve())]


def test_notion_projection_requires_and_verifies_workspace(monkeypatch) -> None:
    report = {"api_version": "auto-doctor-report/v1", "host": "testbox"}
    with pytest.raises(ValueError, match="verified_workspace is required"):
        project_host_report(
            report,
            "page-id",
            verified_workspace="",
            approved_parent_page_id="approved-root",
        )
    with pytest.raises(ValueError, match="approved_parent_page_id is required"):
        project_host_report(
            report,
            "page-id",
            verified_workspace="Expected Workspace",
            approved_parent_page_id="",
        )
    monkeypatch.setattr(
        "genomes_agentic_os.host_doctor.notion_api.get_bot_workspace",
        lambda token_env, **_: "Different Workspace",
    )
    with pytest.raises(RuntimeError, match="workspace mismatch"):
        project_host_report(
            report,
            "page-id",
            verified_workspace="Expected Workspace",
            approved_parent_page_id="approved-root",
        )


def test_notion_projection_binds_workspace_and_mutation_to_approved_parent(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    def workspace(token_env, **kwargs):
        seen["workspace"] = (token_env, kwargs)
        return "Genome's Notion"

    def replace(page_id, blocks, token_env, **kwargs):
        seen["replace"] = (page_id, token_env, kwargs, len(blocks))

    monkeypatch.setattr(
        "genomes_agentic_os.host_doctor.notion_api.get_bot_workspace", workspace
    )
    monkeypatch.setattr(
        "genomes_agentic_os.host_doctor.notion_api.replace_block_children", replace
    )
    monkeypatch.setattr(
        "genomes_agentic_os.host_doctor.notion_blocks", lambda report: [{"type": "paragraph"}]
    )
    result = project_host_report(
        {"api_version": "auto-doctor-report/v1", "host": "testbox"},
        "host-page",
        verified_workspace="Genome's Notion",
        approved_parent_page_id="approved-root",
    )

    assert seen["workspace"] == (
        "NOTION_TOKEN",
        {"parent_page_id": "approved-root"},
    )
    assert seen["replace"][2] == {"approved_parent_page_id": "approved-root"}
    assert result["approved_parent_page_id"] == "approved-root"


def _policy(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _runner(args, **kwargs):
    command = " ".join(args)
    if args[:2] == ["ps", "-axo"]:
        return subprocess.CompletedProcess(
            args,
            0,
            "1 0 root S 0.0 100 01:00 /sbin/init\n2 1 genome S 0.0 100 00:30 /usr/bin/node server.js\n",
            "",
        )
    if args[:3] == ["systemctl", "--user", "is-active"]:
        return subprocess.CompletedProcess(args, 3, "inactive\n", "")
    if args[:3] == ["systemctl", "--user", "restart"]:
        return subprocess.CompletedProcess(args, 0, "restarted\n", "")
    return subprocess.CompletedProcess(args, 0, "", "")


def test_policy_composition_report_repairs_and_receipts(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    _policy(
        config / "workflows" / "services.md",
        """---
api_version: auto-doctor-policy/v1
workflow: services
thresholds:
  process_count:
    critical_above: 1
services:
  - id: api
    kind: systemd_user
    name: api.service
    finding_code: service.api.unhealthy
repairs:
  - id: restart-api
    action: restart_user_service
    target: api.service
    when: service.api.unhealthy
    automatic: true
    safety: reconstructable
---
# Services
""",
    )
    _policy(
        config / "hosts" / "testbox" / "identity.md",
        """---
api_version: auto-doctor-policy/v1
workflow: identity
schedule:
  timezone: America/Chicago
  local_times: ['06:00', '14:00', '22:00']
notion_workspace: Genome's Notion
notion_page_id: abc-123
notion_parent_page_id: parent-456
notion_token_env: TEST_NOTION_TOKEN
---
# Testbox
""",
    )
    assert host_projection(load_host_policies(config, "testbox")) == {
        "workspace": "Genome's Notion",
        "page_id": "abc123",
        "parent_page_id": "parent456",
        "token_env": "TEST_NOTION_TOKEN",
    }
    monkeypatch.setattr("genomes_agentic_os.host_doctor.collect_metrics", lambda runner: ({
        "platform": "linux", "cpu_count": 4, "load1": 1.0, "load5": 1.0,
        "load15": 1.0, "load1_per_cpu": 0.25, "disk_used_percent": 10.0,
        "disk_free_bytes": 10, "memory_available_percent": 50.0,
        "memory_available_bytes": 10, "memory_total_bytes": 20,
        "swap_used_percent": 0.0, "swap_used_bytes": 0, "process_count": 2,
        "node_process_count": 1, "curl_process_count": 0, "orphan_process_count": 0,
        "fseventsd_cpu_percent": 0.0, "fseventsd_rss_bytes": 0,
    }, []))
    now = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)
    report = build_host_report(tmp_path, host_alias="testbox", config_root=config, now=now, runner=_runner)
    assert report["status"] == "critical"
    assert {item["code"] for item in report["findings"]} == {
        "threshold.process_count", "service.api.unhealthy"
    }
    repairs = apply_safe_repairs(report, load_host_policies(config, "testbox"), apply=True, runner=_runner)
    assert repairs[0]["status"] == "repaired"
    report["repairs"] = repairs
    paths = write_host_report(tmp_path, report)
    assert json.loads(Path(paths["latest_json"]).read_text())["host"] == "testbox"
    rendered = render_host_report(report)
    assert "Last ran:" in rendered and "Next run:" in rendered


def test_next_run_rolls_to_next_day() -> None:
    now = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)  # 23:00 prior day in Chicago
    assert next_run_at(now).isoformat() == "2026-07-22T11:00:00+00:00"


def test_docker_inventory_finds_old_unused_images_and_hogs() -> None:
    now = datetime(2026, 7, 21, 16, 0, tzinfo=UTC)
    def runner(args, **kwargs):
        command = " ".join(args)
        if args[:3] == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(args, 0, "c1\n", "")
        if args[:3] == ["docker", "inspect", "--format"]:
            return subprocess.CompletedProcess(args, 0, "api\trunning\t2026-07-10T00:00:00Z\thealthy\tsha256:used\n", "")
        if args[:3] == ["docker", "stats", "--no-stream"]:
            return subprocess.CompletedProcess(args, 0, '{"Name":"api","CPUPerc":"175%","MemUsage":"3GiB / 8GiB"}\n', "")
        if args[:4] == ["docker", "image", "ls", "-q"]:
            return subprocess.CompletedProcess(args, 0, "sha256:used\nsha256:old\n", "")
        if args[:4] == ["docker", "image", "inspect", "--format"]:
            return subprocess.CompletedProcess(args, 0,
                'sha256:used\t2026-07-20T00:00:00Z\t["used:latest"]\n'
                'sha256:old\t2026-07-01T00:00:00Z\t["old:latest"]\n', "")
        raise AssertionError(command)
    policy = {"docker": {"enabled": True, "image_prune_after_hours": 120,
                         "long_running_hours": 120, "container_memory_warn_bytes": 2 * 1024**3,
                         "container_cpu_warn_percent": 150,
                         "restart_watches": [{"name": "api", "memory_bytes_above": 3 * 1024**3,
                                              "finding_code": "docker.container_memory.api"}]}}
    inventory = _docker_inventory(policy, now=now, runner=runner)
    assert [item["id"] for item in inventory["old_unused_images"]] == ["sha256:old"]
    assert inventory["long_running"][0]["name"] == "api"
    assert inventory["memory_hogs"][0]["memory_bytes"] == 3 * 1024**3
    assert inventory["cpu_hogs"][0]["cpu_percent"] == 175
    assert inventory["restart_watch_hits"][0]["finding_code"] == "docker.container_memory.api"


def test_worktree_inventory_only_selects_old_clean_ephemeral_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    candidate = tmp_path / ".claude" / "worktrees" / "agent-old"
    repo.mkdir()
    candidate.mkdir(parents=True)
    def runner(args, **kwargs):
        if args[-3:] == ["worktree", "list", "--porcelain"]:
            return subprocess.CompletedProcess(args, 0,
                f"worktree {repo}\nbranch refs/heads/main\n\nworktree {candidate}\nbranch refs/heads/agent-old\n\n", "")
        if "--format=%ct" in args:
            return subprocess.CompletedProcess(args, 0, "1750000000\n", "")
        if "--porcelain" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)
    policy = {"worktrees": {"repositories": [str(repo)], "cleanup_after_days": 5,
                             "auto_cleanup_path_regex": r"/\.claude/worktrees/agent-"}}
    inventory = _worktree_inventory(policy, now=datetime(2026, 7, 21, tzinfo=UTC), runner=runner)
    assert len(inventory["worktrees"]) == 1
    assert inventory["cleanup_candidates"][0]["path"] == str(candidate)


def test_worktree_inventory_can_select_locked_ephemeral_paths_only_when_enabled(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    candidate = tmp_path / ".claude" / "worktrees" / "agent-old"
    repo.mkdir()
    candidate.mkdir(parents=True)
    def runner(args, **kwargs):
        if args[-3:] == ["worktree", "list", "--porcelain"]:
            return subprocess.CompletedProcess(args, 0,
                f"worktree {repo}\nbranch refs/heads/main\n\nworktree {candidate}\nbranch refs/heads/agent-old\nlocked stale agent\n\n", "")
        if "--format=%ct" in args:
            return subprocess.CompletedProcess(args, 0, "1750000000\n", "")
        if "--porcelain" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)
    base = {"repositories": [str(repo)], "cleanup_after_days": 5,
            "auto_cleanup_path_regex": r"/\.claude/worktrees/agent-"}
    assert not _worktree_inventory({"worktrees": base}, now=datetime(2026, 7, 21, tzinfo=UTC), runner=runner)["cleanup_candidates"]
    enabled = {**base, "auto_unlock_ephemeral": True}
    assert len(_worktree_inventory({"worktrees": enabled}, now=datetime(2026, 7, 21, tzinfo=UTC), runner=runner)["cleanup_candidates"]) == 1


def test_cleanup_commands_are_bounded_and_reconstructable() -> None:
    policy = {"workflow": "cleanup", "repairs": [
        {"id": "images", "action": "prune_docker_images", "target": "120h",
         "when": "docker.old_unused_images", "automatic": True, "safety": "reconstructable"},
        {"id": "cache", "action": "prune_docker_build_cache", "target": "120h",
         "when": "docker.old_unused_images", "automatic": True, "safety": "reconstructable"},
    ]}
    commands = []
    def runner(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "reclaimed", "")
    report = {"findings": [{"code": "docker.old_unused_images"}], "inventory": {"docker": {
        "old_unused_images": [{"id": "sha256:old1"}, {"id": "sha256:old2"}],
    }}}
    receipts = apply_safe_repairs(report, [policy], apply=True, runner=runner)
    assert all(item["status"] == "repaired" for item in receipts)
    assert commands == [
        ["docker", "image", "rm", "sha256:old1", "sha256:old2"],
        ["docker", "builder", "prune", "--all", "--force", "--filter", "until=120h"],
    ]


def test_manual_only_receipts_do_not_consume_automatic_repair_limit() -> None:
    report = {"findings": [{"code": "service.worker.unhealthy"}]}
    manual = [
        {
            "id": f"manual-{index}",
            "when": "service.worker.unhealthy",
            "action": "operator_only_action",
            "target": f"manual-{index}",
        }
        for index in range(5)
    ]
    automatic = {
        "id": "restart-worker",
        "when": "service.worker.unhealthy",
        "action": "restart_user_service",
        "target": "worker.service",
        "automatic": True,
        "safety": "reconstructable",
    }
    commands = []

    def runner(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "restarted", "")

    receipts = apply_safe_repairs(
        report,
        [{"workflow": "services", "repairs": [*manual, automatic]}],
        apply=True,
        runner=runner,
    )
    assert [item["status"] for item in receipts[:5]] == ["manual_only"] * 5
    assert receipts[-1]["status"] == "repaired"
    assert commands == [["systemctl", "--user", "restart", "worker.service"]]


def test_stopped_containers_are_degraded_but_unhealthy_running_containers_are_critical() -> None:
    from genomes_agentic_os.host_doctor import _probe_docker

    inventory = {"available": True, "containers": [
        {"name": "old-dev", "state": "exited", "health": "none"},
        {"name": "database", "state": "running", "health": "unhealthy"},
    ], "images": [], "old_unused_images": [], "long_running": [], "memory_hogs": [], "cpu_hogs": []}
    findings = _probe_docker({"workflow": "docker"}, inventory)
    assert {(item["code"], item["severity"]) for item in findings} == {
        ("docker.stopped_containers", "degraded"),
        ("docker.unhealthy_containers", "critical"),
    }


def test_notion_blocks_use_operator_friendly_native_layout() -> None:
    report = {
        "api_version": "auto-doctor-report/v1", "host": "bigmac", "status": "healthy",
        "checked_at": "2026-07-21T18:00:00Z", "next_run_at": "2026-07-21T19:00:00Z",
        "metrics": {"load1": 1, "load5": 1, "load15": 1, "memory_available_percent": 80,
                    "swap_used_percent": 0, "disk_used_percent": 20, "process_count": 100,
                    "node_process_count": 2, "curl_process_count": 0, "docker_container_count": 4,
                    "docker_long_running_count": 0, "worktree_count": 10,
                    "worktree_cleanup_candidate_count": 0},
        "findings": [], "repairs": [],
        "watch": {"phase": "monitoring", "samples_completed": 1, "samples_total": 3,
                  "planned_finish_at": "2026-07-21T19:00:00Z"},
        "watch_timeline": [{"checked_at": "18:00", "status": "healthy",
                            "memory_available_percent": 80, "swap_used_percent": 0,
                            "fseventsd_cpu_percent": 1, "curl_process_count": 0}],
    }
    blocks = notion_blocks(report)
    types = [block["type"] for block in blocks]
    assert {"callout", "column_list", "divider", "table", "heading_2", "toggle"}.issubset(types)
    assert sum(1 for block in blocks if block["type"] == "table") == 2
    report["host"] = "testbox"
    callout = notion_blocks(report)[0]["callout"]["rich_text"][0]["text"]["content"]
    assert callout == "HEALTHY · Testbox host health"
