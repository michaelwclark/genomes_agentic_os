from __future__ import annotations

import fcntl
from datetime import datetime, timedelta, timezone
import json
import os
from hashlib import sha256
from pathlib import Path
import shlex
import sys
from typing import Any
from urllib.error import HTTPError

import pytest
import yaml

from genomes_agentic_os import execution_fabric_remote
from genomes_agentic_os.cli import main
from genomes_agentic_os.execution_fabric_config import ExecutionFabricConfigError
from genomes_agentic_os.execution_fabric_remote import (
    activate_personal_fallback,
    clear_personal_fallback,
    ExecutionFabricApiError,
    ExecutionFabricClient,
    ExecutionFabricRemoteError,
    RemoteFabricSettings,
    RemoteFabricWorker,
    TaskExecutionError,
    build_remote_runtime_snapshot,
    execute_assignment,
    materialize_approval_state,
    resolve_remote_settings,
    validate_task_route,
    validate_worker_routes,
    drain_artifact_spool,
    personal_fallback_status,
    probe_personal_fallback,
    _spool_artifact,
)
from genomes_agentic_os.runtime_ops import runtime_init


SOURCE_ROOT = Path(__file__).parents[1]


def _root(tmp_path: Path, *, remote: bool = True) -> Path:
    root = tmp_path / "agentic_os"
    runtime_init(root)
    config_path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["transport"].update(
        {
            "mode": "remote" if remote else "local",
            "control_plane_url": "http://127.0.0.1:3180" if remote else None,
            "request_timeout_seconds": 3,
            "long_poll_seconds": 0,
            "submit_token_env": "TEST_SUBMIT_TOKEN",
            "worker_token_env": "TEST_WORKER_TOKEN",
            "observer_token_env": "TEST_FABRIC_TOKEN",
            "admin_token_env": "TEST_ADMIN_TOKEN",
        }
    )
    config_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return root


def _fallback_root(tmp_path: Path) -> Path:
    root = _root(tmp_path)
    config_path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["transport"].update(
        {
            "mode": "remote_with_local_fallback",
            "fallback": {
                "failure_threshold": 3,
                "state_path": "harness/shared_factory/00-control-plane/fallback.json",
            },
        }
    )
    config_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return root


class Response:
    def __init__(self, payload: dict[str, Any] | None = None, *, status: int = 200):
        self.status = status
        self.payload = payload

    def read(self) -> bytes:
        if self.payload is None:
            return b""
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def test_remote_settings_fail_closed_without_token_or_safe_transport(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(ExecutionFabricConfigError, match="TEST_FABRIC_TOKEN"):
        resolve_remote_settings(root, environ={})

    config_path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["transport"]["control_plane_url"] = "http://192.168.1.20:3180"
    config_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    with pytest.raises(ExecutionFabricConfigError, match="literal Tailscale"):
        resolve_remote_settings(root, environ={"TEST_FABRIC_TOKEN": "secret"})

    loaded["execution_fabric"]["transport"]["control_plane_url"] = "http://100.64.0.2:3180"
    config_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    settings = resolve_remote_settings(
        root, environ={"TEST_FABRIC_TOKEN": "secret"}
    )
    assert settings.control_plane_url == "http://100.64.0.2:3180"


def test_remote_settings_accepts_operator_mounted_token_file(tmp_path: Path) -> None:
    root = _root(tmp_path)
    token_file = tmp_path / "worker-token"
    token_file.write_text("mounted-secret\n", encoding="utf-8")

    settings = resolve_remote_settings(
        root,
        role="worker",
        environ={"TEST_WORKER_TOKEN_FILE": str(token_file)},
    )

    assert settings.auth_token == "mounted-secret"
    with pytest.raises(ExecutionFabricConfigError, match="only one"):
        resolve_remote_settings(
            root,
            role="worker",
            environ={
                "TEST_WORKER_TOKEN": "direct",
                "TEST_WORKER_TOKEN_FILE": str(token_file),
            },
        )


def test_remote_settings_can_route_worker_through_governed_gateway(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)

    settings = resolve_remote_settings(
        root,
        role="worker",
        environ={"TEST_WORKER_TOKEN": "worker-secret"},
        endpoint_override="http://100.64.0.2:3181/",
    )

    assert settings.control_plane_url == "http://100.64.0.2:3181"
    with pytest.raises(ExecutionFabricConfigError, match="literal Tailscale"):
        resolve_remote_settings(
            root,
            role="worker",
            environ={"TEST_WORKER_TOKEN": "worker-secret"},
            endpoint_override="http://192.168.1.20:3181",
        )


def test_personal_fallback_latches_after_sustained_failure_and_requires_manual_failback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fallback_root(tmp_path)
    monkeypatch.setattr(
        "genomes_agentic_os.execution_fabric_remote._primary_ready",
        lambda _url, _timeout: (False, "connection_refused"),
    )

    for expected in (1, 2, 3):
        result = probe_personal_fallback(root, dry_run=False)
        assert result["consecutive_failures"] == expected
    assert result["status"] == "active"
    assert personal_fallback_status(root)["manual_failback"] is True

    settings = resolve_remote_settings(root, environ={})
    assert settings.mode == "remote_with_local_fallback"
    assert settings.remote is False
    assert settings.fallback_active is True
    assert settings.public()["effective_mode"] == "local"

    monkeypatch.setattr(
        "genomes_agentic_os.execution_fabric_remote._primary_ready",
        lambda _url, _timeout: (True, None),
    )
    recovered = probe_personal_fallback(root, dry_run=False)
    assert recovered["status"] == "active"
    assert recovered["primary_ready"] is True

    cleared = clear_personal_fallback(root, dry_run=False)
    assert cleared["status"] == "standby"
    remote = resolve_remote_settings(root, environ={"TEST_FABRIC_TOKEN": "secret"})
    assert remote.remote is True


def test_personal_fallback_manual_activation_and_failback_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fallback_root(tmp_path)
    activated = activate_personal_fallback(root, dry_run=False, reason="maintenance")
    assert activated["status"] == "active"
    assert activated["activation_reason"] == "maintenance"

    monkeypatch.setattr(
        "genomes_agentic_os.execution_fabric_remote._primary_ready",
        lambda _url, _timeout: (False, "timeout"),
    )
    with pytest.raises(ExecutionFabricRemoteError, match="readiness is not proven"):
        clear_personal_fallback(root, dry_run=False)
    assert personal_fallback_status(root)["status"] == "active"


def test_client_sends_bearer_auth_and_exact_v1_contract(tmp_path: Path) -> None:
    root = _root(tmp_path)
    requests = []

    def transport(request, timeout):
        requests.append((request, timeout))
        return Response(
            {
                "admitted": True,
                "task": {"id": "11111111-1111-4111-8111-111111111111"},
            },
            status=201,
        )

    client = ExecutionFabricClient.from_root(
        root,
        environ={"TEST_FABRIC_TOKEN": "secret"},
        transport=transport,
    )
    receipt = client.admit_task(
        {
            "namespace": "agentic_os",
            "queue": "non_llm",
            "taskType": "script",
            "idempotencyKey": "task-one",
            "payload": {"command": "harness/bin/example"},
        }
    )

    request, timeout = requests[0]
    assert request.full_url.endswith("/api/v1/tasks")
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.data)["idempotencyKey"] == "task-one"
    assert timeout == 3
    assert receipt["admitted"] is True


def test_client_sends_both_config_reload_fences(tmp_path: Path) -> None:
    root = _root(tmp_path)
    requests = []

    def transport(request, timeout):
        requests.append(request)
        return Response({"appliedFingerprint": "b" * 64})

    client = ExecutionFabricClient.from_root(
        root,
        role="admin",
        environ={"TEST_ADMIN_TOKEN": "admin-secret"},
        transport=transport,
    )
    result = client.reload_config(
        rotation_id="00000000-0000-4000-8000-000000000001",
        preparation_token="cpr1.payload.signature",
        expected_current_fingerprint="a" * 64,
        expected_candidate_fingerprint="b" * 64,
    )

    request = requests[0]
    assert request.full_url.endswith("/api/v1/admin/config/reload")
    assert request.headers["Authorization"] == "Bearer admin-secret"
    assert json.loads(request.data) == {
        "rotationId": "00000000-0000-4000-8000-000000000001",
        "preparationToken": "cpr1.payload.signature",
        "expectedCurrentFingerprint": "a" * 64,
        "expectedCandidateFingerprint": "b" * 64,
    }
    assert result["appliedFingerprint"] == "b" * 64


def test_client_publishes_reliability_observation_with_source_token(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    requests = []

    def transport(request, timeout):
        requests.append((request, timeout))
        return Response(
            {
                "admitted": True,
                "idempotent": False,
                "findingId": "finding-one",
                "alarmId": "alarm-one",
            },
            status=201,
        )

    client = ExecutionFabricClient.from_root(
        root,
        environ={"TEST_FABRIC_TOKEN": "global-observer-token"},
        transport=transport,
    )
    observation = {
        "source": "team-pr-runner",
        "incidentKey": "malformed-row:" + "a" * 32,
        "revision": 1,
        "active": True,
        "severity": "warning",
        "code": "malformed_request_row",
        "summary": "Team PR request row is malformed",
        "evidence": {"field": "pull_request_url", "reason": "missing"},
        "affected": {"kind": "notion_page", "id": "a" * 32},
        "runbook": {"ref": "execution-fabric/team-pr-malformed-row"},
        "observedAt": "2026-07-24T20:00:00.000Z",
    }

    receipt = client.publish_reliability_observation(
        observation,
        source_token="source-specific-token",
    )

    request, timeout = requests[0]
    assert request.full_url.endswith("/api/v1/reliability/observations")
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer source-specific-token"
    assert json.loads(request.data) == observation
    assert timeout == 3
    assert receipt["admitted"] is True

    with pytest.raises(ValueError, match="source_token"):
        client.publish_reliability_observation(observation, source_token=" ")


def test_task_route_rejects_unknown_or_mismatched_queue_work(tmp_path: Path) -> None:
    root = _root(tmp_path, remote=False)
    assert validate_task_route(root, "non_llm", "script")["worker_pool"] == "non_llm_workers"
    with pytest.raises(ValueError, match="unknown execution queue"):
        validate_task_route(root, "made_up", "script")
    with pytest.raises(ValueError, match="not accepted"):
        validate_task_route(root, "non_llm", "llm.codex")


def test_route_approval_class_materializes_to_run_queue_state() -> None:
    assert materialize_approval_state("not_required") == "not_required"
    assert materialize_approval_state("policy_gated") == "approved"
    assert materialize_approval_state("explicit") == "required"
    assert (
        materialize_approval_state("explicit", explicit_operator_apply=True)
        == "approved"
    )
    with pytest.raises(ValueError, match="unknown execution-fabric approval class"):
        materialize_approval_state("surprise")


def test_client_surfaces_safe_api_error_without_token(tmp_path: Path) -> None:
    root = _root(tmp_path)

    def transport(request, timeout):
        raise HTTPError(
            request.full_url,
            409,
            "Conflict",
            {},
            Response({"error": "fenced", "message": "lease expired"}),
        )

    client = ExecutionFabricClient.from_root(
        root,
        environ={"TEST_FABRIC_TOKEN": "do-not-print"},
        transport=transport,
    )
    with pytest.raises(ExecutionFabricApiError, match="lease expired") as raised:
        client.get_task("11111111-1111-4111-8111-111111111111")
    assert "do-not-print" not in str(raised.value)


def test_client_exposes_fenced_effect_delivery_contract(tmp_path: Path) -> None:
    root = _root(tmp_path)
    requests = []

    def transport(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/v1/effects/claim"):
            return Response({"effects": [{"effectId": "effect-one"}]})
        return Response(None, status=204)

    client = ExecutionFabricClient.from_root(
        root,
        environ={"TEST_FABRIC_TOKEN": "secret"},
        transport=transport,
    )
    assert client.claim_effects(
        "jira-effects",
        source="jira-projector",
        effect_types=["jira.labels.apply"],
        consumer_token="effect-consumer-secret",
    ) == [{"effectId": "effect-one"}]
    claimed = json.loads(requests[0].data)
    assert claimed["source"] == "jira-projector"
    assert claimed["effectTypes"] == ["jira.labels.apply"]
    assert requests[0].headers["Authorization"] == "Bearer effect-consumer-secret"
    client.deliver_effect(
        "11111111-1111-4111-8111-111111111111",
        consumer_id="jira-effects",
        claim_token="22222222-2222-4222-8222-222222222222",
        fabric_epoch=7,
        provider_receipt={"issue": "CC-357"},
    )
    delivered = json.loads(requests[-1].data)
    assert delivered["fabricEpoch"] == 7
    assert delivered["providerReceipt"] == {"issue": "CC-357"}


def test_client_publishes_artifact_through_scoped_service_contract(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    artifact_path = tmp_path / "run-report.json"
    artifact_path.write_text('{"ok":true}\n', encoding="utf-8")
    requests = []
    artifact_id = "30000000-0000-4000-8000-000000000001"

    def transport(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/v1/artifacts/uploads"):
            return Response(
                {
                    "artifact": {"artifactId": artifact_id, "status": "pending"},
                    "alreadyAvailable": False,
                    "upload": {
                        "method": "PUT",
                        "url": "https://objects.example.test/scoped-upload",
                        "headers": {
                            "content-type": "application/json",
                            "content-length": str(artifact_path.stat().st_size),
                            "x-amz-meta-sha256": (
                                "e5f1eb4d806641698a35efe20e098efd20d7d57a9b90ee69079d5bb650920726"
                            ),
                        },
                    },
                },
                status=201,
            )
        if request.full_url == "https://objects.example.test/scoped-upload":
            return Response(None, status=200)
        return Response(
            {
                "artifactId": artifact_id,
                "status": "available",
                "uri": "s3://execution-fabric-artifacts/report",
            }
        )

    client = ExecutionFabricClient.from_root(
        root,
        environ={"TEST_FABRIC_TOKEN": "secret"},
        transport=transport,
    )
    receipt = client.publish_artifact(
        task_id="20000000-0000-4000-8000-000000000001",
        attempt_id="00000000-0000-4000-8000-000000000001",
        path=artifact_path,
        name="run-report.json",
        worker_id="worker-one",
        lease_token="00000000-0000-4000-8000-000000000099",
        fabric_epoch=7,
    )

    assert receipt["status"] == "available"
    initiated = json.loads(requests[0].data)
    assert initiated["sizeBytes"] == artifact_path.stat().st_size
    assert len(initiated["sha256"]) == 64
    assert initiated["workerId"] == "worker-one"
    assert requests[0].headers["Authorization"].endswith("000000000099")
    assert requests[1].headers["Content-type"] == "application/json"
    assert requests[2].full_url.endswith(f"/artifacts/{artifact_id}/finalize")


def test_artifact_spool_retries_with_fresh_worker_session_grant(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "run-report.json"
    artifact_path.write_text("{}\n", encoding="utf-8")

    class PublishingClient:
        calls = []

        def publish_recovered_artifact(self, **kwargs):
            self.calls.append(
                {
                    **kwargs,
                    "payload": Path(kwargs["path"]).read_bytes(),
                }
            )
            return {"status": "available"}

    _spool_artifact(
        tmp_path,
        task_id="task-one",
        attempt_id="attempt-one",
        path=artifact_path,
        name="run-report.json",
        content_type="application/json",
        worker_id="worker-one",
        workload_id="worker-bootstrap-one",
        attempt_recovery_token="40000000-0000-4000-8000-000000000001",
        error="store unavailable",
    )
    spool = next(
        (
            tmp_path
            / "harness/shared_factory/06-runs-and-logs/execution-fabric/artifact-spool"
        ).glob("pending/task-one/attempt-one/*.upload.json")
    )
    receipt = json.loads(spool.read_text(encoding="utf-8"))
    receipt["next_attempt_at"] = "2020-01-01T00:00:00Z"
    spool.write_text(json.dumps(receipt), encoding="utf-8")
    artifact_path.unlink()

    client = PublishingClient()
    result = drain_artifact_spool(
        client,  # type: ignore[arg-type]
        tmp_path,
        worker_id="worker-one",
        workload_id="worker-bootstrap-one",
        registration_token="30000000-0000-4000-8000-000000000001",
        fabric_epoch=7,
    )
    assert result["attempted"] == result["published"] == 1
    assert result["quarantined"] == result["foreign"] == 0
    assert result["health"]["status"] == "healthy"
    assert client.calls[0]["payload"] == b"{}\n"
    assert (
        client.calls[0]["attempt_recovery_token"]
        == "40000000-0000-4000-8000-000000000001"
    )
    assert not spool.exists()


def test_generic_worker_image_advertises_only_shipped_remote_handlers(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, remote=False)
    assert validate_worker_routes(root, ["codex"], ["codex.task"]) == [
        {
            "queue": "codex",
            "task_type": "llm.codex",
            "domain_worker": "codex_task",
        }
    ]
    with pytest.raises(ValueError, match="no shipped remote handler"):
        validate_worker_routes(
            root,
            ["los_environment"],
            ["los.environment.reconcile"],
        )


class FakeClient:
    def __init__(self, assignments: list[dict[str, Any]]) -> None:
        self.settings = RemoteFabricSettings(
            mode="remote",
            control_plane_url="https://fabric.example.ts.net",
            request_timeout_seconds=5,
            long_poll_seconds=0,
            auth_token_env="TOKEN",
            auth_token="secret",
        )
        self.assignments = list(assignments)
        self.registrations = []
        self.heartbeats = []
        self.completed = []
        self.failed = []

    def register_worker(self, payload):
        self.registrations.append(payload)
        return {"registrationToken": "registration-token", "fabricEpoch": 4}

    def publish_recovered_artifact(self, **kwargs):
        return {"status": "available"}

    def heartbeat(
        self,
        worker_id,
        registration_token,
        active_attempt_ids,
        artifact_spool_health=None,
    ):
        self.heartbeats.append(
            {
                "active_attempt_ids": active_attempt_ids,
                "artifact_spool_health": artifact_spool_health,
            }
        )
        return {}

    def claim(self, **kwargs):
        return self.assignments.pop(0) if self.assignments else None

    def complete_attempt(self, attempt_id, **kwargs):
        self.completed.append((attempt_id, kwargs))
        return {}

    def fail_attempt(self, attempt_id, **kwargs):
        self.failed.append((attempt_id, kwargs))
        return {}


def _assignment(number: int) -> dict[str, Any]:
    return {
        "attemptId": f"00000000-0000-4000-8000-{number:012d}",
        "attemptRecoveryToken": f"30000000-0000-4000-8000-{number:012d}",
        "leaseToken": f"10000000-0000-4000-8000-{number:012d}",
        "fabricEpoch": 4,
        "task": {
            "id": f"20000000-0000-4000-8000-{number:012d}",
            "queue": "non_llm",
            "taskType": "script",
            "payload": {},
        },
    }


def test_worker_registers_heartbeats_and_completes_multiple_assignments(tmp_path: Path) -> None:
    client = FakeClient([_assignment(1), _assignment(2)])

    def executor(root, assignment):
        return {"result": {"task": assignment["task"]["id"]}, "effects": []}

    result = RemoteFabricWorker(
        client,  # type: ignore[arg-type]
        root=tmp_path,
        worker_id="worker-one",
        bootstrap_id="worker-bootstrap-one",
        host_id="bigmac",
        queues=["non_llm"],
        max_concurrency=2,
        heartbeat_seconds=1,
        executor=executor,
    ).work(max_tasks=2)

    assert client.registrations[0]["maxConcurrency"] == 2
    assert client.heartbeats
    assert {attempt_id for attempt_id, _ in client.completed} == {
        _assignment(1)["attemptId"],
        _assignment(2)["attemptId"],
    }
    assert result["completed"] == 2
    assert result["failed"] == 0


def test_worker_classifies_and_reports_failure(tmp_path: Path) -> None:
    client = FakeClient([_assignment(1)])

    def executor(root, assignment):
        raise TaskExecutionError("configuration", "bad command", retryable=False)

    result = RemoteFabricWorker(
        client,  # type: ignore[arg-type]
        root=tmp_path,
        worker_id="worker-one",
        bootstrap_id="worker-bootstrap-one",
        host_id="bigmac",
        queues=["non_llm"],
        executor=executor,
    ).work(max_tasks=1)

    assert not client.completed
    assert client.failed[0][1]["error_code"] == "configuration"
    assert client.failed[0][1]["retryable"] is False
    assert result["failed"] == 1


def test_remote_worker_rejects_legacy_arbitrary_script_assignments(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, remote=False)
    assignment = _assignment(1)
    assignment["task"]["payload"] = {
        "execution_target": "script",
        "command": shlex.join([sys.executable, "-c", "print('worker-ok')"]),
    }

    with pytest.raises(ValueError, match="local-only"):
        execute_assignment(root, assignment)


def test_remote_snapshot_normalizes_queue_worker_and_run_contract(tmp_path: Path) -> None:
    root = _root(tmp_path)

    class SnapshotClient:
        settings = RemoteFabricSettings(
            mode="remote",
            control_plane_url="https://fabric.example.ts.net",
            request_timeout_seconds=5,
            long_poll_seconds=1,
            auth_token_env="TOKEN",
            auth_token="secret",
        )

        def queue_snapshot(self):
            return {
                "queues": [
                    {
                        "queue": "non_llm",
                        "queued": 3,
                        "running": 1,
                        "succeeded": 4,
                        "failed": 0,
                        "deadLettered": 1,
                        "retrying": 2,
                        "delayed": 1,
                        "oldestReadyAgeSeconds": 45,
                        "throughputPerHour": 8,
                        "failureRateLastHour": 0.125,
                        "maxRunning": 4,
                        "capacityRemaining": 3,
                    }
                ]
            }

        def worker_snapshot(self):
            return {
                "workers": [
                    {
                        "workerId": "bigmac-one",
                        "hostId": "bigmac",
                        "queues": ["non_llm"],
                        "capabilities": [],
                        "maxConcurrency": 2,
                        "running": 1,
                        "state": "online",
                        "currentSessionId": "session-one",
                        "sessionHistory": [
                            {"sessionId": "session-one", "status": "active"}
                        ],
                    }
                ]
            }

        def run_snapshot(self, *, limit):
            return {
                "runs": [
                    {
                        "taskId": "task-one",
                        "queue": "non_llm",
                        "taskType": "script",
                        "status": "running",
                        "attemptCount": 1,
                        "workerId": "bigmac-one",
                        "createdAt": "2026-07-24T17:59:00Z",
                        "completedAt": None,
                        "lastErrorSummary": None,
                        "attempts": [
                            {
                                "attemptId": "attempt-one",
                                "startedAt": "2026-07-24T18:00:00Z",
                                "finishedAt": None,
                            }
                        ],
                        "effects": [
                            {"effectId": "effect-one", "status": "pending"}
                        ],
                        "artifacts": [
                            {
                                "artifactId": "artifact-one",
                                "name": "run-report.json",
                                "sha256": "a" * 64,
                                "sizeBytes": 42,
                                "status": "available",
                                "uri": "s3://fabric/run-report.json",
                            }
                        ],
                    }
                ]
            }

        def status(self, *, limit):
            assert limit == 200
            return {
                "schemaVersion": "agentic-os-execution-fabric-status/v1",
                "sampledAt": "2026-07-24T18:00:00Z",
                **self.queue_snapshot(),
                **self.worker_snapshot(),
                **self.run_snapshot(limit=limit),
                "config": {
                    "state": "applied",
                    "appliedFingerprint": "a" * 64,
                },
                "controlPlane": {
                    "activeHost": "genomesbox",
                    "leaderHostId": "genomesbox",
                    "fabricEpoch": 7,
                    "databasePolicyFingerprint": "a" * 64,
                    "eventSequence": 19,
                    "leadershipReceiptId": "receipt-seven",
                    "leadership": {
                        "state": "active",
                        "lastVerifiedAt": "2026-07-24T17:59:59Z",
                        "proofExpiresAt": "2026-07-24T18:05:00Z",
                    },
                },
                "healing": {"status": "healthy", "lastReceipt": None},
                "roleHealth": [
                    {
                        "hostId": "genomesbox",
                        "role": "healer",
                        "instanceId": "role-instance-one",
                        "approvedPolicyFingerprint": "a" * 64,
                        "appliedPolicyFingerprint": "a" * 64,
                        "lastSuccessfulTickAt": "2026-07-24T17:59:58Z",
                        "lastError": None,
                        "consecutiveFailures": 0,
                        "status": "healthy",
                    }
                ],
                "alarms": [],
                "effects": {"pending": 2},
            }

        def get_task(self, task_id):
            return {"id": task_id, "status": "running"}

    snapshot = build_remote_runtime_snapshot(
        root,
        task_id="task-one",
        client=SnapshotClient(),  # type: ignore[arg-type]
    )

    assert snapshot["queue_mode"] == "execution_fabric"
    assert snapshot["summary"]["queue_depth"] == 3
    assert snapshot["summary"]["active_workers"] == 1
    assert snapshot["requested_task"]["id"] == "task-one"
    assert snapshot["control_plane"]["active_host"] == "genomesbox"
    assert snapshot["control_plane"]["transport"] == "remote"
    assert snapshot["control_plane"]["witness_status"] == "healthy"
    assert snapshot["queues"][0]["queue_name"] == "non_llm"
    assert snapshot["queues"][0]["statuses"]["done"] == 4
    assert snapshot["queues"][0]["retrying"] == 2
    assert snapshot["queues"][0]["oldest_wait_seconds"] == 45
    assert snapshot["workers"][0]["pool_name"] == "non_llm_workers"
    assert snapshot["workers"][0]["session_id"] == "session-one"
    assert snapshot["tasks"][0]["worker_pool"] == "non_llm_workers"
    assert snapshot["recent_run_reports"][0]["task_id"] == "task-one"
    assert snapshot["recent_run_reports"][0]["run_id"] == "task-one"
    assert snapshot["recent_run_reports"][0]["effects_pending"] == 1
    assert snapshot["recent_run_reports"][0]["artifacts"][0] == {
        "artifact_id": "artifact-one",
        "name": "run-report.json",
        "content_type": None,
        "sha256": "a" * 64,
        "size_bytes": 42,
        "status": "available",
        "uri": "s3://fabric/run-report.json",
        "available_at": None,
        "last_error": None,
    }
    assert snapshot["config"]["state"] == "applied"
    assert snapshot["effects"] == {"pending": 2}
    assert snapshot["healing"]["status"] == "healthy"
    assert snapshot["role_health"][0]["role"] == "healer"
    assert snapshot["role_health"][0]["status"] == "healthy"
    assert snapshot["control_plane"]["epoch"] == 7
    assert snapshot["control_plane"]["role"] == "leader"
    assert snapshot["control_plane"]["leadership_receipt_id"] == "receipt-seven"


def test_cli_submit_preserves_explicit_local_degraded_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, remote=False)
    assert (
        main(
            [
                "runtime",
                "queue-mode",
                "apply",
                "execution_fabric",
                "--root",
                str(root),
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "runtime",
                "submit",
                "--root",
                str(root),
                "--queue",
                "non_llm",
                "--task-type",
                "script",
                "--idempotency-key",
                "local-one",
                "--command",
                "harness/bin/example",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "submitted-local-degraded"
    assert result["transport"]["mode"] == "local"
    assert result["queue_item"]["id"] == "local-one"
    assert result["queue_item"]["approval_state"] == "approved"


def test_cli_submit_allows_commandless_domain_task_for_harness_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, remote=False)
    assert (
        main(
            [
                "runtime",
                "submit",
                "--root",
                str(root),
                "--queue",
                "pr_reviews",
                "--task-type",
                "los.team_pr.ai_review.v1",
                "--idempotency-key",
                "team-pr-review-one",
                "--payload-json",
                json.dumps(
                    {
                        "repository": "example/repo",
                        "pull_request": 42,
                        "pull_request_url": "https://github.com/example/repo/pull/42",
                        "expected_head_sha": "a" * 40,
                        "base_branch": "develop",
                        "source_key": "github-pr-42",
                        "title": "Review example",
                        "notion_page_id": "a" * 32,
                        "author_identity": "github:example",
                    }
                ),
                "--execution-target",
                "codex_harness",
                "--capability",
                "pr_review",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "would-submit"
    assert result["task"]["taskType"] == "los.team_pr.ai_review.v1"
    assert "command" not in result["task"]["payload"]
    assert "execution_target" not in result["task"]["payload"]


def test_team_pr_route_rejects_non_review_mode(tmp_path: Path) -> None:
    root = _root(tmp_path, remote=False)
    with pytest.raises(ValueError, match="review_mode"):
        validate_task_route(
            root,
            "pr_reviews",
            "los.team_pr.ai_review.v1",
            payload={
                "repository": "example/repo",
                "pull_request": 42,
                "pull_request_url": "https://github.com/example/repo/pull/42",
                "expected_head_sha": "a" * 40,
                "base_branch": "develop",
                "source_key": "FLYWL-409",
                "review_mode": "review_and_merge",
                "title": "Review example",
                "notion_page_id": "a" * 32,
                "author_identity": "github:external-author",
            },
            remote=True,
        )


@pytest.mark.parametrize(
    ("author_identity", "expected_kind"),
    [
        ("github:michaelwclark", "ours"),
        ("github:external-author", "others"),
    ],
)
def test_registered_team_pr_domain_worker_invokes_installed_safe_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    author_identity: str,
    expected_kind: str,
) -> None:
    from genomes_agentic_os import runtime_ops

    monkeypatch.setattr(
        execution_fabric_remote,
        "resolve_execution_fabric_host_id",
        lambda *_args, **_kwargs: "bigmac",
    )
    root = _root(tmp_path, remote=False)
    assignment = _assignment(3)
    assignment["task"].update(
        {
            "queue": "pr_reviews",
            "taskType": "los.team_pr.ai_review.v1",
            "payload": {
                "repository": "example/repo",
                "pull_request": 42,
                "pull_request_url": "https://github.com/example/repo/pull/42",
                "expected_head_sha": "a" * 40,
                "base_branch": "develop",
                "source_key": "github-pr-42",
                "title": "Review example",
                "notion_page_id": "a" * 32,
                "author_identity": author_identity,
            },
        }
    )
    if expected_kind == "ours":
        assignment["task"]["payload"]["review_mode"] = "review_no_merge"
    development = (
        root
        / "domains/los/02-projects/los_app_los_django/config/development.yml"
    )
    development.parent.mkdir(parents=True, exist_ok=True)
    development.write_text(
        yaml.safe_dump(
            {"review": {"authorship": {"ours": ["github:michaelwclark"]}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    helper = (
        root
        / "lib/programs/domains/los/team_pr_sync/scripts/team_pr_review_fabric.py"
    )
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("# installed portable helper fixture\n", encoding="utf-8")
    canonical = {
        "schema_version": "team-pr-review-result/v1",
        "provider": "github",
        "repository": "example/repo",
        "pull_request": 42,
        "configured_base": "develop",
        "reviewed_head_sha": "a" * 40,
        "final_head_sha": "a" * 40,
        "review_mode": "review_no_merge",
        "author_identity": author_identity,
        "author_kind": expected_kind,
        "readback_verified": True,
        "outcome": "findings",
        "findings": [{"severity": "medium", "summary": "fixture finding"}],
        "summary": "Review finished with one fixture finding.",
        "provider_readback": {
            "repository": "example/repo",
            "pull_request": 42,
            "head_sha": "a" * 40,
            "base_branch": "develop",
            "author_identity": author_identity,
        },
    }
    canonical_hash = sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    captured: dict[str, Any] = {"calls": 0}

    def run(_root: Path, command: str, **_kwargs: Any) -> dict[str, Any]:
        captured["command"] = command
        captured["calls"] += 1
        helper_command = shlex.split(command)
        return {
            "supported": True,
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "status": "findings",
                    "run_id": helper_command[helper_command.index("--run-id") + 1],
                    "source_key": "github-pr-42",
                    "canonical_review_receipt": canonical,
                    "receipt_sha256": canonical_hash,
                }
            ),
            "stderr": "",
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(runtime_ops, "_run_local_script", run)
    result = execute_assignment(root, assignment)

    command = shlex.split(captured["command"])
    assert command[:3] == ["python3", str(helper), "execute"]
    assert command[-1] == "--apply"
    assert command[command.index("--review-mode") + 1] == "review_no_merge"
    assert "auto-dev-review-others" not in captured["command"]
    assert "auto-dev-review-self" not in captured["command"]
    assert "command" not in assignment["task"]["payload"]
    assert json.loads(result["result"]["stdout"])["canonical_review_receipt"] == canonical
    identity = execution_fabric_remote._team_pr_review_identity(
        assignment["task"]["payload"]
    )
    intent_key = execution_fabric_remote._team_pr_review_intent_key(identity)
    expected_effect_key = (
        f"notion.pr_review.update:{intent_key}"
        if "review_mode" in assignment["task"]["payload"]
        else f"notion.pr_review.update:github-pr-42:{'a' * 40}"
    )
    expected_effects = [
        {
            "effectKey": expected_effect_key,
            "effectType": "notion.pr_review.update",
            "payload": {
                "page_id": "a" * 32,
                "repository": "example/repo",
                "pull_request": 42,
                "expected_head_sha": "a" * 40,
                "base_branch": "develop",
                "source_key": "github-pr-42",
                "review_mode": "review_no_merge",
                "review_intent_key": intent_key,
                "task_identity": assignment["task"]["id"],
                "operation": "project_completed_review",
                "author_identity": author_identity,
                "author_kind": expected_kind,
            },
            "maxAttempts": 8,
            "baseBackoffSeconds": 60,
        }
    ]
    assert result["effects"] == expected_effects
    intent_path = (
        root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs"
        / assignment["task"]["id"]
        / "review-intent.json"
    )
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["status"] == "completed"
    assert intent["identity"] == identity
    assert intent["effects"] == expected_effects

    monkeypatch.setattr(
        execution_fabric_remote,
        "resolve_execution_fabric_host_id",
        lambda *_args, **_kwargs: "genomesbox",
    )
    with pytest.raises(TaskExecutionError) as wrong_host:
        execute_assignment(root, assignment)
    assert wrong_host.value.code == "task_host_affinity_violation"
    assert wrong_host.value.retryable is True
    monkeypatch.setattr(
        execution_fabric_remote,
        "resolve_execution_fabric_host_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ExecutionFabricConfigError("transient host identity fixture")
        ),
    )
    with pytest.raises(TaskExecutionError) as host_unavailable:
        execute_assignment(root, assignment)
    assert host_unavailable.value.code == "task_host_affinity_unavailable"
    assert host_unavailable.value.retryable is True
    assert captured["calls"] == 1
    monkeypatch.setattr(
        execution_fabric_remote,
        "resolve_execution_fabric_host_id",
        lambda *_args, **_kwargs: "bigmac",
    )
    assignment["attemptId"] = "00000000-0000-4000-8000-999999999999"
    retried = execute_assignment(root, assignment)

    assert captured["calls"] == 1
    assert retried["effects"] == expected_effects
    assert retried["result"]["helperStatus"] == "findings"
    assert json.loads(intent_path.read_text(encoding="utf-8")) == intent

    helper_result = {
        "status": "findings",
        "run_id": command[command.index("--run-id") + 1],
        "source_key": "github-pr-42",
        "canonical_review_receipt": canonical,
        "receipt_sha256": canonical_hash,
    }
    pending_intent = {
        key: value
        for key, value in intent.items()
        if key not in {"completed_at", "helper_status", "helper_result", "effects"}
    }
    pending_intent["status"] = "pending"
    intent_path.write_text(
        json.dumps(pending_intent, sort_keys=True), encoding="utf-8"
    )
    summary_path = execution_fabric_remote._team_pr_review_summary_path(root, identity)
    launch_path = summary_path.with_name("helper-launch.json")
    terminal_launch_marker = json.loads(launch_path.read_text(encoding="utf-8"))
    assert terminal_launch_marker["status"] == "succeeded"
    terminal_launch_marker["status"] = "running"
    terminal_launch_marker.pop("finished_at", None)
    launch_path.write_text(json.dumps(terminal_launch_marker), encoding="utf-8")
    assert summary_path.parent.name.endswith(intent_key.split(":", 1)[1])
    assert command[command.index("--run-id") + 1] == summary_path.parent.name
    assert command[command.index("--summary-path") + 1] == str(summary_path)
    assert command[command.index("--launch-marker-path") + 1] == str(
        summary_path.with_name("helper-launch.json")
    )
    with pytest.raises(TaskExecutionError) as possibly_running:
        execute_assignment(root, assignment)
    assert possibly_running.value.code == "team_pr_review_in_progress"
    assert possibly_running.value.retryable is True
    assert captured["calls"] == 1
    launch_marker = json.loads(launch_path.read_text(encoding="utf-8"))
    launch_marker["helper_pid"] = os.getpid()
    launch_marker["launched_at"] = (
        datetime.now(timezone.utc)
        - timedelta(seconds=execution_fabric_remote.TEAM_PR_HELPER_TIMEOUT_SECONDS + 1)
    ).isoformat().replace("+00:00", "Z")
    launch_path.write_text(json.dumps(launch_marker), encoding="utf-8")
    with pytest.raises(TaskExecutionError) as orphan_still_bounded:
        execute_assignment(root, assignment)
    assert orphan_still_bounded.value.code == "team_pr_review_in_progress"
    assert captured["calls"] == 1
    launch_marker["launched_at"] = (
        datetime.now(timezone.utc)
        - timedelta(seconds=execution_fabric_remote.TEAM_PR_HELPER_STALE_SECONDS + 1)
    ).isoformat().replace("+00:00", "Z")
    launch_marker["status"] = "failed"
    launch_path.write_text(json.dumps(launch_marker), encoding="utf-8")
    real_helper_match = execution_fabric_remote._process_is_team_pr_helper
    monkeypatch.setattr(
        execution_fabric_remote,
        "_process_is_team_pr_helper",
        lambda *_args, **_kwargs: True,
    )
    with pytest.raises(TaskExecutionError) as verified_live_orphan:
        execute_assignment(root, assignment)
    assert verified_live_orphan.value.code == "team_pr_review_in_progress"
    monkeypatch.setattr(
        execution_fabric_remote, "_process_is_team_pr_helper", real_helper_match
    )
    launch_marker["status"] = "running"
    launch_marker.pop("helper_pid")
    launch_marker["launched_at"] = "2026-07-29T10:00:00"
    launch_path.write_text(json.dumps(launch_marker), encoding="utf-8")
    with pytest.raises(TaskExecutionError) as naive_launch_time:
        execute_assignment(root, assignment)
    assert naive_launch_time.value.code == "invalid_team_pr_durable_receipt"
    assert naive_launch_time.value.receipt_path == str(launch_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps({**helper_result, "source_key": "other-ticket"}),
        encoding="utf-8",
    )
    with pytest.raises(TaskExecutionError) as wrong_summary_identity:
        execute_assignment(root, assignment)
    assert wrong_summary_identity.value.code == "invalid_team_pr_durable_receipt"
    summary_path.write_text(json.dumps(helper_result), encoding="utf-8")
    assignment["attemptId"] = "00000000-0000-4000-8000-888888888888"

    recovered = execute_assignment(root, assignment)

    assert captured["calls"] == 1
    assert recovered["effects"] == expected_effects
    assert recovered["result"]["helperStatus"] == "findings"

    intent_path.write_text(
        json.dumps(pending_intent, sort_keys=True), encoding="utf-8"
    )
    summary_path.unlink()
    launch_marker = json.loads(launch_path.read_text(encoding="utf-8"))
    launch_path.write_text(
        json.dumps({**launch_marker, "status": "failed"}), encoding="utf-8"
    )

    def launch_error(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise PermissionError("fixture spawn failure")

    monkeypatch.setattr(runtime_ops, "_run_local_script", launch_error)
    with pytest.raises(TaskExecutionError) as failed_launch:
        execute_assignment(root, assignment)
    assert failed_launch.value.code == "team_pr_helper_launch_failed"
    assert failed_launch.value.retryable is True
    assert json.loads(launch_path.read_text(encoding="utf-8"))["status"] == "failed"

    def poll_error_after_spawn(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        marker = json.loads(launch_path.read_text(encoding="utf-8"))
        launch_path.write_text(
            json.dumps({**marker, "helper_pid": os.getpid()}), encoding="utf-8"
        )
        raise RuntimeError("fixture governor poll failure")

    monkeypatch.setattr(runtime_ops, "_run_local_script", poll_error_after_spawn)
    monkeypatch.setattr(
        execution_fabric_remote,
        "_process_is_team_pr_helper",
        lambda *_args, **_kwargs: True,
    )
    with pytest.raises(TaskExecutionError) as live_poll_error:
        execute_assignment(root, assignment)
    assert live_poll_error.value.code == "team_pr_review_in_progress"
    assert json.loads(launch_path.read_text(encoding="utf-8"))["status"] == "running"
    monkeypatch.setattr(
        execution_fabric_remote, "_process_is_team_pr_helper", real_helper_match
    )
    launch_marker = json.loads(launch_path.read_text(encoding="utf-8"))
    launch_marker["status"] = "failed"
    launch_marker.pop("helper_pid", None)
    launch_path.write_text(json.dumps(launch_marker), encoding="utf-8")

    def stale_execution(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        marker = json.loads(launch_path.read_text(encoding="utf-8"))
        launch_path.write_text(
            json.dumps({**marker, "helper_pid": os.getpid()}), encoding="utf-8"
        )
        return {
            "supported": True,
            "ok": False,
            "returncode": None,
            "governed_run": str(tmp_path / "run"),
            "governed_status": "stale",
            "errors": ["fixture governed run is stale"],
            "warnings": [],
        }

    monkeypatch.setattr(runtime_ops, "_run_local_script", stale_execution)
    with pytest.raises(TaskExecutionError) as stale_child:
        execute_assignment(root, assignment)
    assert stale_child.value.code == "team_pr_review_in_progress"
    assert json.loads(launch_path.read_text(encoding="utf-8"))["status"] == "running"
    monkeypatch.setattr(runtime_ops, "_run_local_script", run)
    summary_path.write_text(json.dumps(helper_result), encoding="utf-8")
    recovered = execute_assignment(root, assignment)
    assert recovered["result"]["helperStatus"] == "findings"

    lock_path = summary_path.with_name("review-intent.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        competing_assignment = json.loads(json.dumps(assignment))
        competing_assignment["task"]["id"] = "different-task-same-review-identity"
        with pytest.raises(TaskExecutionError) as locked:
            execute_assignment(root, competing_assignment)
        assert locked.value.code == "team_pr_review_in_progress"
        assert locked.value.retryable is True
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    completed = json.loads(intent_path.read_text(encoding="utf-8"))
    intent_path.write_text(
        json.dumps({**completed, "author_kind": "conflicting"}), encoding="utf-8"
    )
    with pytest.raises(TaskExecutionError) as conflict:
        execute_assignment(root, assignment)
    assert conflict.value.code == "team_pr_review_intent_conflict"
    assert conflict.value.retryable is False

    intent_path.write_text("{", encoding="utf-8")
    with pytest.raises(TaskExecutionError) as corrupt:
        execute_assignment(root, assignment)
    assert corrupt.value.code == "invalid_team_pr_durable_receipt"
    assert corrupt.value.retryable is False


def test_team_pr_changed_head_helper_receipt_produces_no_projection_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genomes_agentic_os import runtime_ops

    monkeypatch.setattr(
        execution_fabric_remote,
        "resolve_execution_fabric_host_id",
        lambda *_args, **_kwargs: "bigmac",
    )
    root = _root(tmp_path, remote=False)
    assignment = _assignment(3)
    assignment["task"].update(
        {
            "queue": "pr_reviews",
            "taskType": "los.team_pr.ai_review.v1",
            "payload": {
                "repository": "example/repo",
                "pull_request": 42,
                "pull_request_url": "https://github.com/example/repo/pull/42",
                "expected_head_sha": "a" * 40,
                "base_branch": "develop",
                "source_key": "github-pr-42",
                "title": "Review example",
                "notion_page_id": "a" * 32,
                "author_identity": "github:external-author",
            },
        }
    )
    development = (
        root
        / "domains/los/02-projects/los_app_los_django/config/development.yml"
    )
    development.parent.mkdir(parents=True, exist_ok=True)
    development.write_text(
        yaml.safe_dump(
            {"review": {"authorship": {"ours": ["github:michaelwclark"]}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    helper = (
        root
        / "lib/programs/domains/los/team_pr_sync/scripts/team_pr_review_fabric.py"
    )
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("# installed portable helper fixture\n", encoding="utf-8")
    calls = 0

    def run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        helper_command = shlex.split(str(_args[1]))
        helper_result = {
            "status": "superseded",
            "run_id": helper_command[helper_command.index("--run-id") + 1],
            "source_key": "github-pr-42",
            "reason": "head_changed",
            "observed_head_sha": "b" * 40,
        }
        helper_summary = Path(
            helper_command[helper_command.index("--summary-path") + 1]
        )
        helper_summary.parent.mkdir(parents=True, exist_ok=True)
        helper_summary.write_text(json.dumps(helper_result), encoding="utf-8")
        return {
            "supported": True,
            "ok": True,
            "exit_code": 0,
            "stdout": "truncated governed output before terminal JSON",
            "stderr": "",
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(runtime_ops, "_run_local_script", run)

    result = execute_assignment(root, assignment)
    assignment["attemptId"] = "00000000-0000-4000-8000-777777777777"
    retried = execute_assignment(root, assignment)

    assert result["result"]["helperStatus"] == "superseded"
    assert result["effects"] == []
    assert retried["effects"] == []
    assert calls == 1
    intent_path = (
        root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs"
        / assignment["task"]["id"]
        / "review-intent.json"
    )
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["status"] == "completed"
    assert intent["helper_status"] == "superseded"
    assert intent["effects"] == []


def test_team_pr_durable_receipt_os_error_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "review-intent.json"
    real_read_text = Path.read_text

    def unreadable(_self: Path, **_kwargs: Any) -> str:
        raise PermissionError("transient fixture")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(TaskExecutionError) as failure:
        execution_fabric_remote._read_json_object(path, label="fixture")

    assert failure.value.code == "team_pr_durable_receipt_unavailable"
    assert failure.value.retryable is True

    monkeypatch.setattr(Path, "read_text", real_read_text)

    def lock_unavailable(_self: Path, *_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("transient lock fixture")

    monkeypatch.setattr(Path, "open", lock_unavailable)
    with pytest.raises(TaskExecutionError) as lock_failure:
        with execution_fabric_remote._TeamPRLaunchMarkerLock(
            tmp_path / "helper-launch.json"
        ):
            raise AssertionError("unreachable")

    assert lock_failure.value.code == "team_pr_durable_receipt_unavailable"
    assert lock_failure.value.retryable is True

    monkeypatch.setattr(
        execution_fabric_remote,
        "_write_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("transient write fixture")
        ),
    )
    with pytest.raises(TaskExecutionError) as write_failure:
        execution_fabric_remote._write_team_pr_receipt(
            tmp_path / "summary.json", {"status": "fixture"}, durable=True
        )

    assert write_failure.value.code == "team_pr_durable_receipt_unavailable"
    assert write_failure.value.retryable is True


def test_durable_receipt_writes_fsync_file_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def tracked_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    execution_fabric_remote._write_receipt(
        tmp_path / "replace.json", {"ok": True}, durable=True
    )
    assert execution_fabric_remote._write_receipt_once(
        tmp_path / "create.json", {"ok": True}
    )

    assert len(calls) == 4


def test_unregistered_los_domain_worker_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path, remote=False)
    assignment = _assignment(3)
    assignment["task"].update(
        {
            "queue": "los_environment",
            "taskType": "los.jira.action.execute",
            "payload": {
                "action_id": "action-1",
                "action_key": "jira:action-1",
            },
        }
    )
    with pytest.raises(TaskExecutionError, match="domain worker los_jira_action"):
        execute_assignment(root, assignment)
