from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

from genomes_agentic_os.host_doctor import (
    apply_safe_repairs,
    build_host_report,
    load_host_policies,
    host_projection,
    next_run_at,
    render_host_report,
    project_losmon_report,
    project_losmon_drop,
    write_host_report,
)


class _Response:
    status = 202


def test_losmon_projection_uses_env_token_without_returning_it(monkeypatch) -> None:
    seen = {}
    def fetcher(request, timeout):
        seen['authorization'] = request.headers['Authorization']
        seen['timeout'] = timeout
        return _Response()
    monkeypatch.setenv('TEST_HOST_TOKEN', 'secret-value')
    result = project_losmon_report(
        {'api_version': 'auto-doctor-report/v1', 'host': 'bigmac'},
        'http://example.test/api/host-health/bigmac',
        token_env='TEST_HOST_TOKEN',
        fetcher=fetcher,
    )
    assert result == {'applied': True, 'url': 'http://example.test/api/host-health/bigmac', 'status': 202}
    assert seen == {'authorization': 'Bearer secret-value', 'timeout': 20}
    assert 'secret-value' not in str(result)


def test_losmon_drop_uses_fixed_scp_command(tmp_path: Path) -> None:
    latest = tmp_path / 'latest.json'
    latest.write_text('{}', encoding='utf-8')
    seen = []
    def runner(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')
    result = project_losmon_drop(
        latest,
        'genomesbox:/home/genome/agentic_os/auto-doctor/bigmac/latest.json',
        runner=runner,
    )
    assert result['applied'] is True
    assert seen[0][:5] == ['scp', '-q', '-o', 'ConnectTimeout=8', str(latest.resolve())]


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
---
# Testbox
""",
    )
    assert host_projection(load_host_policies(config, "testbox")) == {
        "workspace": "Genome's Notion",
        "page_id": "abc123",
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
