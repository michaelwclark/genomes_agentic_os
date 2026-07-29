"""Authenticated cross-host Execution Fabric client and host-native worker.

The remote control plane owns durable admission, leases, retries, and run
history.  This module deliberately keeps execution host-native: a worker reads
the installed OS policy on its own host, runs only an already-supported runtime
target, and reports a bounded receipt back to the control plane.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import ipaddress
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import yaml

from .execution_fabric_config import (
    ExecutionFabricConfigError,
    load_execution_fabric_config,
    resolve_execution_fabric_host_id,
)
from .scaffold import expand_path


REMOTE_SNAPSHOT_SCHEMA = "agentic-os-runtime-snapshot/v1"
DEFAULT_TRANSPORT = {
    "mode": "local",
    "control_plane_url": None,
    "request_timeout_seconds": 20,
    "long_poll_seconds": 20,
    "submit_token_env": "AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN",
    "worker_token_env": "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN",
    "observer_token_env": "AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN",
    "admin_token_env": "AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN",
    "fallback": {
        "failure_threshold": 3,
        "state_path": "harness/shared_factory/00-control-plane/execution-fabric-fallback.json",
    },
}
FALLBACK_STATE_SCHEMA = "agentic-os-execution-fabric-fallback/v1"


class ExecutionFabricRemoteError(RuntimeError):
    """A safe, token-free remote protocol or worker error."""


class ExecutionFabricApiError(ExecutionFabricRemoteError):
    """A non-success response from the remote control plane."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Execution Fabric API {status} {code}: {message}")


class TaskExecutionError(ExecutionFabricRemoteError):
    """A classified assignment failure suitable for the durable run ledger."""

    def __init__(
        self,
        code: str,
        summary: str,
        *,
        retryable: bool,
        receipt_path: str | None = None,
    ) -> None:
        self.code = code
        self.receipt_path = receipt_path
        suffix = f"; receipt={receipt_path}" if receipt_path else ""
        self.summary = f"{summary}{suffix}"[:2048]
        self.retryable = retryable
        super().__init__(self.summary)


@dataclass(frozen=True)
class RemoteFabricSettings:
    mode: str
    control_plane_url: str | None
    request_timeout_seconds: int
    long_poll_seconds: int
    auth_token_env: str
    auth_token: str | None = field(default=None, repr=False)
    fallback_active: bool = False
    fallback_state_path: str | None = None
    fallback_failure_threshold: int = 3

    @property
    def remote(self) -> bool:
        return self.mode == "remote" or (
            self.mode == "remote_with_local_fallback" and not self.fallback_active
        )

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "control_plane_url": self.control_plane_url,
            "request_timeout_seconds": self.request_timeout_seconds,
            "long_poll_seconds": self.long_poll_seconds,
            "auth_token_env": self.auth_token_env,
            "authenticated": bool(self.auth_token),
            "effective_mode": "remote" if self.remote else "local",
            "fallback_active": self.fallback_active,
            "fallback_state_path": self.fallback_state_path,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_remote_url(value: str) -> str:
    url = value.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExecutionFabricConfigError(
            "execution_fabric.transport.control_plane_url must be an absolute HTTP(S) URL"
        )
    if parsed.username or parsed.password:
        raise ExecutionFabricConfigError(
            "execution_fabric.transport.control_plane_url must not contain credentials"
        )
    if parsed.query or parsed.fragment:
        raise ExecutionFabricConfigError(
            "execution_fabric.transport.control_plane_url must not contain a query or fragment"
        )
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    tailscale_cgnat = bool(
        isinstance(address, ipaddress.IPv4Address)
        and address in ipaddress.ip_network("100.64.0.0/10")
    )
    if parsed.scheme != "https" and not (loopback or tailscale_cgnat):
        raise ExecutionFabricConfigError(
            "remote Execution Fabric requires HTTPS or a literal Tailscale 100.64.0.0/10 address"
        )
    return url


def resolve_remote_settings(
    root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    role: str = "observer",
    host_alias: str | None = None,
    endpoint_override: str | None = None,
) -> RemoteFabricSettings:
    """Resolve canonical transport/auth policy and an optional governed endpoint."""
    environment = os.environ if environ is None else environ
    effective = load_execution_fabric_config(
        root,
        host_alias=host_alias,
        environ=environment,
    )
    configured = effective.value["execution_fabric"].get("transport") or {}
    transport = {**DEFAULT_TRANSPORT, **configured}
    fallback = {
        **DEFAULT_TRANSPORT["fallback"],
        **dict(configured.get("fallback") or {}),
    }
    mode = str(transport["mode"])
    if mode not in {"local", "remote", "remote_with_local_fallback"}:
        raise ExecutionFabricConfigError(
            "execution_fabric.transport.mode must be local, remote, or "
            "remote_with_local_fallback"
        )
    if role not in {"submit", "worker", "observer", "admin"}:
        raise ExecutionFabricConfigError(f"unknown Execution Fabric credential role: {role}")
    token_env = str(transport[f"{role}_token_env"])
    url = None
    token = None
    fallback_state_path = None
    fallback_active = False
    fallback_failure_threshold = int(fallback["failure_threshold"])
    if mode == "remote_with_local_fallback":
        fallback_state_path = str(
            (expand_path(root) / str(fallback["state_path"])).resolve()
        )
        state_file = Path(fallback_state_path)
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ExecutionFabricConfigError(
                    "execution_fabric fallback state is unreadable or invalid"
                ) from exc
            if state.get("schema_version") != FALLBACK_STATE_SCHEMA:
                raise ExecutionFabricConfigError(
                    "execution_fabric fallback state has an unsupported schema"
                )
            fallback_active = state.get("status") == "active"
    if mode in {"remote", "remote_with_local_fallback"}:
        configured_url = str(transport.get("control_plane_url") or "")
        url = _validate_remote_url(endpoint_override or configured_url)
    if mode == "remote" or (
        mode == "remote_with_local_fallback" and not fallback_active
    ):
        token = str(environment.get(token_env) or "").strip()
        token_file = str(environment.get(f"{token_env}_FILE") or "").strip()
        if token and token_file:
            raise ExecutionFabricConfigError(
                f"remote Execution Fabric accepts only one of {token_env} or {token_env}_FILE"
            )
        if not token and token_file:
            try:
                token = Path(token_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ExecutionFabricConfigError(
                    f"remote Execution Fabric credential file for {token_env} is unreadable: "
                    f"{type(exc).__name__}"
                ) from None
        if not token:
            raise ExecutionFabricConfigError(
                f"remote Execution Fabric requires a non-empty {token_env} or "
                f"{token_env}_FILE credential"
            )
    return RemoteFabricSettings(
        mode=mode,
        control_plane_url=url,
        request_timeout_seconds=int(transport["request_timeout_seconds"]),
        long_poll_seconds=int(transport["long_poll_seconds"]),
        auth_token_env=token_env,
        auth_token=token,
        fallback_active=fallback_active,
        fallback_state_path=fallback_state_path,
        fallback_failure_threshold=fallback_failure_threshold,
    )


def _fallback_policy(root: str | Path) -> tuple[str, Path, int, int]:
    effective = load_execution_fabric_config(root).value["execution_fabric"]
    configured = dict(effective.get("transport") or {})
    transport = {**DEFAULT_TRANSPORT, **configured}
    if str(transport["mode"]) != "remote_with_local_fallback":
        raise ExecutionFabricConfigError(
            "personal fallback commands require transport.mode="
            "remote_with_local_fallback"
        )
    fallback = {
        **DEFAULT_TRANSPORT["fallback"],
        **dict(configured.get("fallback") or {}),
    }
    url = _validate_remote_url(str(transport.get("control_plane_url") or ""))
    state_path = (expand_path(root) / str(fallback["state_path"])).resolve()
    return (
        url,
        state_path,
        int(fallback["failure_threshold"]),
        int(transport["request_timeout_seconds"]),
    )


def _read_fallback_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": FALLBACK_STATE_SCHEMA,
            "status": "standby",
            "consecutive_failures": 0,
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionFabricConfigError(
            "execution_fabric fallback state is unreadable or invalid"
        ) from exc
    if state.get("schema_version") != FALLBACK_STATE_SCHEMA:
        raise ExecutionFabricConfigError(
            "execution_fabric fallback state has an unsupported schema"
        )
    return state


def _write_fallback_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(state), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _primary_ready(url: str, timeout: int) -> tuple[bool, str | None]:
    request = urllib.request.Request(f"{url}/readyz", method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=float(timeout))  # noqa: S310
        try:
            status = int(getattr(response, "status", getattr(response, "code", 200)))
        finally:
            response.close()
        ready = 200 <= status < 300
        return ready, None if ready else f"http_{status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, type(getattr(exc, "reason", exc)).__name__


def personal_fallback_status(root: str | Path) -> dict[str, Any]:
    url, state_path, threshold, _ = _fallback_policy(root)
    return {
        **_read_fallback_state(state_path),
        "primary_url": url,
        "failure_threshold": threshold,
        "state_path": str(state_path),
        "manual_failback": True,
    }


def probe_personal_fallback(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    url, state_path, threshold, timeout = _fallback_policy(root)
    before = _read_fallback_state(state_path)
    ready, error = _primary_ready(url, timeout)
    now = _utc_now()
    after = {
        **before,
        "schema_version": FALLBACK_STATE_SCHEMA,
        "checked_at": now,
        "primary_ready": ready,
    }
    if ready:
        after["consecutive_failures"] = 0
        after.pop("last_error", None)
        if before.get("status") == "active":
            after["status"] = "active"
            after.setdefault("primary_recovered_at", now)
        else:
            after["status"] = "standby"
    else:
        failures = int(before.get("consecutive_failures") or 0) + 1
        after["consecutive_failures"] = failures
        after["last_error"] = error or "unready"
        if before.get("status") == "active" or failures >= threshold:
            after["status"] = "active"
            after.setdefault("activated_at", now)
            after["activation_reason"] = "sustained_primary_unavailable"
        else:
            after["status"] = "standby"
    if not dry_run:
        _write_fallback_state(state_path, after)
    return {
        **after,
        "primary_url": url,
        "failure_threshold": threshold,
        "state_path": str(state_path),
        "manual_failback": True,
        "dry_run": dry_run,
        "applied": not dry_run,
    }


def activate_personal_fallback(
    root: str | Path, *, dry_run: bool = True, reason: str = "operator_requested"
) -> dict[str, Any]:
    url, state_path, threshold, _ = _fallback_policy(root)
    state = _read_fallback_state(state_path)
    state.update(
        {
            "schema_version": FALLBACK_STATE_SCHEMA,
            "status": "active",
            "activated_at": state.get("activated_at") or _utc_now(),
            "activation_reason": reason,
            "primary_ready": False,
            "consecutive_failures": max(
                threshold, int(state.get("consecutive_failures") or 0)
            ),
        }
    )
    if not dry_run:
        _write_fallback_state(state_path, state)
    return {
        **state,
        "primary_url": url,
        "failure_threshold": threshold,
        "state_path": str(state_path),
        "manual_failback": True,
        "dry_run": dry_run,
        "applied": not dry_run,
    }


def clear_personal_fallback(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    url, state_path, threshold, timeout = _fallback_policy(root)
    ready, error = _primary_ready(url, timeout)
    if not ready:
        raise ExecutionFabricRemoteError(
            f"refusing failback because primary readiness is not proven: {error or 'unready'}"
        )
    before = _read_fallback_state(state_path)
    now = _utc_now()
    after = {
        "schema_version": FALLBACK_STATE_SCHEMA,
        "status": "standby",
        "consecutive_failures": 0,
        "primary_ready": True,
        "checked_at": now,
        "cleared_at": now,
        "previous_activation": before.get("activated_at"),
    }
    if not dry_run:
        _write_fallback_state(state_path, after)
    return {
        **after,
        "primary_url": url,
        "failure_threshold": threshold,
        "state_path": str(state_path),
        "manual_failback": True,
        "dry_run": dry_run,
        "applied": not dry_run,
    }


def validate_task_route(
    root: str | Path,
    queue_name: str,
    task_type: str,
    *,
    payload: Mapping[str, Any] | None = None,
    remote: bool = False,
) -> dict[str, Any]:
    """Resolve one exact task definition and validate its closed payload shape."""
    fabric = load_execution_fabric_config(root).value["execution_fabric"]
    queue = next(
        (row for row in fabric["queues"] if str(row.get("id")) == queue_name),
        None,
    )
    if queue is None:
        raise ValueError(f"unknown execution queue: {queue_name}")
    if not queue.get("enabled"):
        raise ValueError(f"execution queue is disabled: {queue_name}")
    accepted = [str(value) for value in queue.get("accepted_task_types") or []]
    if task_type not in accepted:
        raise ValueError(
            f"task type {task_type!r} is not accepted by execution queue {queue_name!r}"
        )
    pool_id = str(queue["worker_pool"])
    pool = next(
        (row for row in fabric["worker_pools"] if str(row.get("id")) == pool_id),
        None,
    )
    if pool is None or not pool.get("enabled"):
        raise ValueError(
            f"execution queue {queue_name!r} has no enabled worker pool"
        )
    route = next(
        (
            row
            for row in fabric.get("task_routes") or []
            if str(row.get("task_type") or "") == task_type
        ),
        None,
    )
    if route is None or str(route.get("queue") or "") != queue_name:
        raise ValueError(f"no canonical task route for {task_type!r} on {queue_name!r}")
    execution = dict(route.get("execution") or {})
    if remote and not execution.get("remote_allowed"):
        raise ValueError(f"task type {task_type!r} is local-only and cannot be remote")
    if payload is None:
        return {
            "queue": queue_name,
            "task_type": task_type,
            "worker_pool": pool_id,
            "scheduling_class": route["scheduling_class"],
            "execution_target": execution["target"],
            "required_capability": execution.get("required_capability"),
            "command_template": execution.get("command_template"),
            "domain_worker": execution.get("domain_worker"),
            "allowed_host_ids": list(execution.get("allowed_host_ids") or []),
            "mutation_class": route["mutation_class"],
            "approval_class": route["approval_class"],
            "allowed_effect_types": list(route.get("allowed_effect_types") or []),
        }
    payload_value = dict(payload)
    payload_policy = dict(route.get("payload") or {})
    properties = dict(payload_policy.get("properties") or {})
    required = [str(value) for value in payload_policy.get("required") or []]
    missing = [name for name in required if name not in payload_value]
    if missing:
        raise ValueError(
            f"task type {task_type!r} requires payload fields: {', '.join(missing)}"
        )
    unexpected = sorted(set(payload_value) - set(properties))
    if unexpected:
        raise ValueError(
            f"task type {task_type!r} rejects payload fields: {', '.join(unexpected)}"
        )
    for name, value in payload_value.items():
        rule = dict(properties[name])
        expected = str(rule.get("type") or "")
        valid = (
            (expected == "string" and isinstance(value, str))
            or (
                expected == "integer"
                and isinstance(value, int)
                and not isinstance(value, bool)
            )
            or (expected == "boolean" and isinstance(value, bool))
        )
        if not valid:
            raise ValueError(
                f"task type {task_type!r} payload field {name!r} must be {expected}"
            )
        if "enum" in rule and value not in list(rule["enum"]):
            raise ValueError(
                f"task type {task_type!r} payload field {name!r} is not allowed"
            )
        pattern = rule.get("pattern")
        if pattern and (
            not isinstance(value, str) or re.fullmatch(str(pattern), value) is None
        ):
            raise ValueError(
                f"task type {task_type!r} payload field {name!r} does not match policy"
            )
    required_capability = execution.get("required_capability")
    return {
        "queue": queue_name,
        "task_type": task_type,
        "worker_pool": pool_id,
        "scheduling_class": route["scheduling_class"],
        "execution_target": execution["target"],
        "required_capability": required_capability,
        "command_template": execution.get("command_template"),
        "domain_worker": execution.get("domain_worker"),
        "allowed_host_ids": list(execution.get("allowed_host_ids") or []),
        "mutation_class": route["mutation_class"],
        "approval_class": route["approval_class"],
        "allowed_effect_types": list(route.get("allowed_effect_types") or []),
    }


def materialize_approval_state(
    approval_class: str,
    *,
    explicit_operator_apply: bool = False,
) -> str:
    """Translate route policy into the run-queue approval vocabulary.

    ``approval_class`` describes how a canonical route is authorized, while
    ``approval_state`` records the authorization state of one materialized run.
    Policy-gated work has already passed the closed route validator. Explicit
    local work is approved only when the operator invoked the mutating
    ``--apply`` path; callers that merely materialize such a route must leave it
    awaiting approval.
    """
    if approval_class == "not_required":
        return "not_required"
    if approval_class == "policy_gated":
        return "approved"
    if approval_class == "explicit":
        return "approved" if explicit_operator_apply else "required"
    raise ValueError(f"unknown execution-fabric approval class: {approval_class!r}")


Transport = Callable[[urllib.request.Request, float], Any]
DomainWorkerHandler = Callable[
    [Path, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    dict[str, Any],
]
_DOMAIN_WORKERS: dict[str, DomainWorkerHandler] = {}


def register_domain_worker(name: str, handler: DomainWorkerHandler) -> None:
    """Register one trusted, commandless domain adapter.

    Registration is process-local and may not replace an existing adapter.
    Task payloads still pass the canonical closed route schema before dispatch,
    and returned effects are filtered against that route.
    """
    if re.fullmatch(r"[a-z][a-z0-9_]{1,127}", name) is None:
        raise ValueError("domain worker name must be a stable snake_case identifier")
    if name in _DOMAIN_WORKERS:
        raise ValueError(f"domain worker is already registered: {name}")
    _DOMAIN_WORKERS[name] = handler


def validate_worker_routes(
    root: str | Path,
    queues: list[str],
    capabilities: list[str],
) -> list[dict[str, str]]:
    """Fail closed unless every subscribed remote route has a shipped handler."""
    fabric = load_execution_fabric_config(root).value["execution_fabric"]
    queue_by_id = {
        str(queue["id"]): queue for queue in fabric.get("queues") or []
    }
    available_capabilities = set(capabilities)
    routes: list[dict[str, str]] = []
    for queue_name in dict.fromkeys(queues):
        queue = queue_by_id.get(queue_name)
        if queue is None or not queue.get("enabled"):
            raise ValueError(f"worker subscribes to unknown or disabled queue: {queue_name}")
        for task_type in queue.get("accepted_task_types") or []:
            route = validate_task_route(
                root,
                queue_name,
                str(task_type),
                remote=True,
            )
            worker_name = str(route.get("domain_worker") or "")
            if not worker_name or worker_name not in _DOMAIN_WORKERS:
                raise ValueError(
                    f"worker image has no shipped remote handler for "
                    f"{queue_name}:{task_type}"
                )
            required_capability = str(route.get("required_capability") or "")
            if required_capability and required_capability not in available_capabilities:
                raise ValueError(
                    f"worker route {queue_name}:{task_type} requires capability "
                    f"{required_capability}"
                )
            routes.append(
                {
                    "queue": queue_name,
                    "task_type": str(task_type),
                    "domain_worker": worker_name,
                }
            )
    return routes


def _default_transport(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


class ExecutionFabricClient:
    """Minimal versioned HTTP client with a mockable stdlib transport."""

    def __init__(
        self,
        settings: RemoteFabricSettings,
        *,
        transport: Transport | None = None,
    ) -> None:
        if not settings.remote or not settings.control_plane_url or not settings.auth_token:
            raise ExecutionFabricConfigError(
                "ExecutionFabricClient requires fail-closed remote transport settings"
            )
        self.settings = settings
        self._transport = transport or _default_transport

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        role: str = "observer",
    ) -> "ExecutionFabricClient":
        return cls(
            resolve_remote_settings(root, environ=environ, role=role),
            transport=transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        bearer_token: str | None = None,
    ) -> Any:
        body = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            f"{self.settings.control_plane_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token or self.settings.auth_token}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            response = self._transport(
                request,
                timeout or float(self.settings.request_timeout_seconds),
            )
            try:
                status = int(getattr(response, "status", getattr(response, "code", 200)))
                raw = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            finally:
                exc.close()
            detail = _json_object(raw)
            raise ExecutionFabricApiError(
                exc.code,
                str(detail.get("error") or "http_error"),
                str(detail.get("message") or exc.reason or "request failed"),
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ExecutionFabricRemoteError(
                f"Execution Fabric request failed for {method} {path}: {reason}"
            ) from None
        if status == 204:
            return None
        if status < 200 or status >= 300:
            detail = _json_object(raw)
            raise ExecutionFabricApiError(
                status,
                str(detail.get("error") or "http_error"),
                str(detail.get("message") or "request failed"),
            )
        if not raw:
            return {}
        parsed = _json_object(raw)
        return parsed

    def admit_task(self, task: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/tasks", task)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/tasks/{task_id}")

    def register_worker(self, registration: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/workers/register", registration)

    def heartbeat(
        self,
        worker_id: str,
        registration_token: str,
        active_attempt_ids: list[str],
        artifact_spool_health: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "registrationToken": registration_token,
            "activeAttemptIds": active_attempt_ids,
        }
        if artifact_spool_health is not None:
            payload["artifactSpoolHealth"] = dict(artifact_spool_health)
        return self._request(
            "POST",
            f"/api/v1/workers/{worker_id}/heartbeat",
            payload,
            bearer_token=registration_token,
        )

    def claim(
        self,
        *,
        worker_id: str,
        registration_token: str,
        queues: list[str],
        capabilities: list[str],
        wait_ms: int | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "workerId": worker_id,
            "registrationToken": registration_token,
            "queues": queues,
            "capabilities": capabilities,
        }
        if wait_ms is not None:
            payload["waitMs"] = wait_ms
        return self._request(
            "POST",
            "/api/v1/assignments/claim",
            payload,
            timeout=max(
                self.settings.request_timeout_seconds,
                (wait_ms or 0) / 1000 + 5,
            ),
            bearer_token=registration_token,
        )

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        worker_id: str,
        lease_token: str,
        fabric_epoch: int,
        result: Mapping[str, Any],
        effects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/attempts/{attempt_id}/complete",
            {
                "workerId": worker_id,
                "leaseToken": lease_token,
                "fabricEpoch": fabric_epoch,
                "result": dict(result),
                "effects": effects or [],
            },
            bearer_token=lease_token,
        )

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        worker_id: str,
        lease_token: str,
        fabric_epoch: int,
        error_code: str,
        error_summary: str,
        retryable: bool,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/attempts/{attempt_id}/fail",
            {
                "workerId": worker_id,
                "leaseToken": lease_token,
                "fabricEpoch": fabric_epoch,
                "errorCode": error_code,
                "errorSummary": error_summary[:2048],
                "retryable": retryable,
            },
            bearer_token=lease_token,
        )

    def claim_effects(
        self,
        consumer_id: str,
        *,
        source: str,
        effect_types: list[str],
        consumer_token: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not effect_types:
            raise ValueError("effect_types must contain at least one owned effect type")
        result = self._request(
            "POST",
            "/api/v1/effects/claim",
            {
                "consumerId": consumer_id,
                "source": source,
                "effectTypes": effect_types,
                "limit": limit,
            },
            bearer_token=consumer_token,
        )
        return list(result.get("effects") or [])

    def deliver_effect(
        self,
        effect_id: str,
        *,
        consumer_id: str,
        claim_token: str,
        fabric_epoch: int,
        provider_receipt: Mapping[str, Any],
    ) -> None:
        self._request(
            "POST",
            f"/api/v1/effects/{effect_id}/deliver",
            {
                "consumerId": consumer_id,
                "claimToken": claim_token,
                "fabricEpoch": fabric_epoch,
                "providerReceipt": dict(provider_receipt),
            },
            bearer_token=claim_token,
        )

    def fail_effect(
        self,
        effect_id: str,
        *,
        consumer_id: str,
        claim_token: str,
        fabric_epoch: int,
        error_summary: str,
        retry_after_seconds: int = 60,
    ) -> None:
        self._request(
            "POST",
            f"/api/v1/effects/{effect_id}/fail",
            {
                "consumerId": consumer_id,
                "claimToken": claim_token,
                "fabricEpoch": fabric_epoch,
                "errorSummary": error_summary[:2048],
                "retryAfterSeconds": retry_after_seconds,
            },
            bearer_token=claim_token,
        )

    def queue_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/snapshots/queues")

    def worker_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/snapshots/workers")

    def run_snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/snapshots/runs?limit={limit}")

    def status(self, *, limit: int = 200) -> dict[str, Any]:
        """Read the versioned canonical operator status in one API snapshot."""
        return self._request("GET", f"/api/v1/status?limit={limit}")

    def reload_config(
        self,
        *,
        rotation_id: str,
        preparation_token: str,
        expected_current_fingerprint: str,
        expected_candidate_fingerprint: str,
    ) -> dict[str, Any]:
        """Validate and atomically activate a fingerprint-fenced policy."""
        return self._request(
            "POST",
            "/api/v1/admin/config/reload",
            {
                "rotationId": rotation_id,
                "preparationToken": preparation_token,
                "expectedCurrentFingerprint": expected_current_fingerprint,
                "expectedCandidateFingerprint": expected_candidate_fingerprint,
            },
        )

    def publish_reliability_observation(
        self,
        observation: Mapping[str, Any],
        *,
        source_token: str,
    ) -> dict[str, Any]:
        """Publish one typed observation with a credential scoped to its source."""
        if not source_token.strip():
            raise ValueError("source_token must be non-empty")
        return self._request(
            "POST",
            "/api/v1/reliability/observations",
            observation,
            bearer_token=source_token,
        )

    def publish_artifact(
        self,
        *,
        task_id: str,
        attempt_id: str,
        path: str | Path,
        name: str | None = None,
        content_type: str = "application/json",
        worker_id: str,
        lease_token: str,
        fabric_epoch: int,
    ) -> dict[str, Any]:
        """Upload one bounded artifact without exposing object-store credentials."""
        artifact_path = Path(path).expanduser().resolve()
        size_bytes = artifact_path.stat().st_size
        digest = sha256(artifact_path.read_bytes()).hexdigest()
        initiated = self._request(
            "POST",
            "/api/v1/artifacts/uploads",
            {
                "taskId": task_id,
                "attemptId": attempt_id,
                "workerId": worker_id,
                "leaseToken": lease_token,
                "fabricEpoch": fabric_epoch,
                "name": name or artifact_path.name,
                "contentType": content_type,
                "sha256": digest,
                "sizeBytes": size_bytes,
            },
            bearer_token=lease_token,
        )
        artifact = dict(initiated.get("artifact") or {})
        if not initiated.get("alreadyAvailable"):
            upload = dict(initiated.get("upload") or {})
            upload_headers = {
                str(key).lower(): str(value)
                for key, value in dict(upload.get("headers") or {}).items()
            }
            required_headers = {
                "content-type": content_type,
                "content-length": str(size_bytes),
                "x-amz-meta-sha256": digest,
            }
            if any(upload_headers.get(key) != value for key, value in required_headers.items()):
                raise ExecutionFabricRemoteError(
                    "Execution Fabric artifact upload grant omitted a required signed header"
                )
            request = urllib.request.Request(
                str(upload.get("url") or ""),
                data=artifact_path.read_bytes(),
                method="PUT",
                headers=upload_headers,
            )
            try:
                response = self._transport(
                    request,
                    float(self.settings.request_timeout_seconds),
                )
                try:
                    status = int(
                        getattr(response, "status", getattr(response, "code", 200))
                    )
                    response.read()
                finally:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ExecutionFabricRemoteError(
                    f"Execution Fabric artifact upload failed: {type(exc).__name__}"
                ) from None
            if status < 200 or status >= 300:
                raise ExecutionFabricRemoteError(
                    f"Execution Fabric artifact upload failed with HTTP {status}"
                )
            artifact = self._request(
                "POST",
                f"/api/v1/artifacts/{artifact['artifactId']}/finalize",
                {
                    "taskId": task_id,
                    "attemptId": attempt_id,
                    "workerId": worker_id,
                    "leaseToken": lease_token,
                    "fabricEpoch": fabric_epoch,
                },
                bearer_token=lease_token,
            )
        return artifact

    def publish_recovered_artifact(
        self,
        *,
        task_id: str,
        attempt_id: str,
        path: str | Path,
        name: str | None = None,
        content_type: str = "application/json",
        worker_id: str,
        registration_token: str,
        attempt_recovery_token: str,
        fabric_epoch: int,
    ) -> dict[str, Any]:
        """Request a fresh upload grant for a durable artifact spool record."""
        artifact_path = Path(path).expanduser().resolve()
        size_bytes = artifact_path.stat().st_size
        digest = sha256(artifact_path.read_bytes()).hexdigest()
        initiated = self._request(
            "POST",
            "/api/v1/artifacts/recovery-uploads",
            {
                "taskId": task_id,
                "attemptId": attempt_id,
                "workerId": worker_id,
                "registrationToken": registration_token,
                "attemptRecoveryToken": attempt_recovery_token,
                "fabricEpoch": fabric_epoch,
                "name": name or artifact_path.name,
                "contentType": content_type,
                "sha256": digest,
                "sizeBytes": size_bytes,
            },
            bearer_token=registration_token,
        )
        artifact = dict(initiated.get("artifact") or {})
        if initiated.get("alreadyAvailable"):
            return artifact
        upload = dict(initiated.get("upload") or {})
        upload_headers = {
            str(key).lower(): str(value)
            for key, value in dict(upload.get("headers") or {}).items()
        }
        required_headers = {
            "content-type": content_type,
            "content-length": str(size_bytes),
            "x-amz-meta-sha256": digest,
        }
        if any(upload_headers.get(key) != value for key, value in required_headers.items()):
            raise ExecutionFabricRemoteError(
                "Execution Fabric artifact recovery grant omitted a required signed header"
            )
        request = urllib.request.Request(
            str(upload.get("url") or ""),
            data=artifact_path.read_bytes(),
            method="PUT",
            headers=upload_headers,
        )
        try:
            response = self._transport(
                request,
                float(self.settings.request_timeout_seconds),
            )
            try:
                status = int(
                    getattr(response, "status", getattr(response, "code", 200))
                )
                response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ExecutionFabricRemoteError(
                f"Execution Fabric artifact recovery upload failed: {type(exc).__name__}"
            ) from None
        if status < 200 or status >= 300:
            raise ExecutionFabricRemoteError(
                f"Execution Fabric artifact recovery upload failed with HTTP {status}"
            )
        return self._request(
            "POST",
            f"/api/v1/artifacts/{artifact['artifactId']}/recovery-finalize",
            {
                "taskId": task_id,
                "attemptId": attempt_id,
                "workerId": worker_id,
                "registrationToken": registration_token,
                "attemptRecoveryToken": attempt_recovery_token,
                "fabricEpoch": fabric_epoch,
            },
            bearer_token=registration_token,
        )


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionFabricRemoteError("Execution Fabric returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ExecutionFabricRemoteError("Execution Fabric returned a non-object JSON response")
    return parsed


def _write_receipt(
    path: Path, receipt: Mapping[str, Any], *, durable: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        if durable:
            handle.flush()
            os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
    if durable:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _write_receipt_once(path: Path, receipt: Mapping[str, Any]) -> bool:
    """Atomically create a receipt without replacing an existing value."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        try:
            os.link(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        except FileExistsError:
            return False
    finally:
        temporary.unlink(missing_ok=True)


def _write_team_pr_receipt(
    path: Path, receipt: Mapping[str, Any], *, durable: bool = False
) -> None:
    try:
        _write_receipt(path, receipt, durable=durable)
    except OSError as exc:
        raise TaskExecutionError(
            "team_pr_durable_receipt_unavailable",
            f"Team PR durable receipt is temporarily unwritable: {type(exc).__name__}",
            retryable=True,
            receipt_path=str(path),
        ) from None


def _write_team_pr_receipt_once(path: Path, receipt: Mapping[str, Any]) -> bool:
    try:
        return _write_receipt_once(path, receipt)
    except OSError as exc:
        raise TaskExecutionError(
            "team_pr_durable_receipt_unavailable",
            f"Team PR durable receipt is temporarily unwritable: {type(exc).__name__}",
            retryable=True,
            receipt_path=str(path),
        ) from None


def _artifact_spool_root(root: str | Path) -> Path:
    return (
        expand_path(root)
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/artifact-spool"
    )


ARTIFACT_SPOOL_SCHEMA = "agentic-os-execution-fabric-artifact-spool/v2"
ARTIFACT_SPOOL_MAX_ATTEMPTS = 12


def _artifact_file_identity(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_artifact_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:128]
    return safe or "artifact"


def _artifact_spool_payload_path(
    root: str | Path,
    *,
    task_id: str,
    attempt_id: str,
    name: str,
    digest: str,
) -> Path:
    return (
        _artifact_spool_root(root)
        / "pending"
        / task_id
        / attempt_id
        / f"{digest[:16]}-{_safe_artifact_name(name)}.payload"
    )


def _copy_artifact_to_spool(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        return
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        delete=False,
    ) as handle:
        with source.open("rb") as source_handle:
            while chunk := source_handle.read(1024 * 1024):
                handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, destination)


def _spool_artifact(
    root: str | Path,
    *,
    task_id: str,
    attempt_id: str,
    path: str | Path,
    name: str,
    content_type: str,
    worker_id: str,
    workload_id: str,
    attempt_recovery_token: str,
    error: str,
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    digest, size_bytes = _artifact_file_identity(source)
    payload_path = _artifact_spool_payload_path(
        root,
        task_id=task_id,
        attempt_id=attempt_id,
        name=name,
        digest=digest,
    )
    _copy_artifact_to_spool(source, payload_path)
    spool_path = payload_path.with_suffix(".upload.json")
    existing: dict[str, Any] = {}
    if spool_path.exists():
        try:
            loaded = json.loads(spool_path.read_text(encoding="utf-8"))
            if (
                isinstance(loaded, dict)
                and loaded.get("schema_version") == ARTIFACT_SPOOL_SCHEMA
            ):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    attempt_count = int(existing.get("attempt_count") or 0) + 1
    delay_seconds = min(3600, 15 * 2 ** min(attempt_count - 1, 8))
    spool_root = _artifact_spool_root(root).resolve()
    receipt = {
        "schema_version": ARTIFACT_SPOOL_SCHEMA,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "payload_ref": str(payload_path.resolve().relative_to(spool_root)),
        "name": name,
        "content_type": content_type,
        "worker_id": worker_id,
        "workload_id": workload_id,
        "attempt_recovery_token": attempt_recovery_token,
        "sha256": digest,
        "size_bytes": size_bytes,
        "attempt_count": attempt_count,
        "max_attempts": ARTIFACT_SPOOL_MAX_ATTEMPTS,
        "last_error": error[:512],
        "next_attempt_at": datetime.fromtimestamp(
            time.time() + delay_seconds, timezone.utc
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "updated_at": _utc_now(),
    }
    _write_receipt(spool_path, receipt)
    return {
        "status": "spooled",
        "name": name,
        "spoolReceipt": str(spool_path),
        "attemptCount": attempt_count,
        "nextAttemptAt": receipt["next_attempt_at"],
    }


def _quarantine_spool(
    root: str | Path,
    spool_path: Path,
    receipt: Mapping[str, Any] | None,
    *,
    reason: str,
) -> None:
    spool_root = _artifact_spool_root(root).resolve()
    task_id = str((receipt or {}).get("task_id") or "unknown-task")
    attempt_id = str((receipt or {}).get("attempt_id") or "unknown-attempt")
    destination = (
        spool_root
        / "quarantine"
        / _safe_artifact_name(task_id)
        / _safe_artifact_name(attempt_id)
        / spool_path.name
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload_path: Path | None = None
    payload_ref = str((receipt or {}).get("payload_ref") or "")
    if payload_ref:
        candidate = (spool_root / payload_ref).resolve()
        try:
            candidate.relative_to(spool_root / "pending")
            payload_path = candidate
        except ValueError:
            payload_path = None
    terminal = dict(receipt or {})
    terminal.update(
        {
            "schema_version": ARTIFACT_SPOOL_SCHEMA,
            "terminal": True,
            "terminal_reason": reason[:512],
            "quarantined_at": _utc_now(),
        }
    )
    _write_receipt(destination, terminal)
    if spool_path.exists() and spool_path != destination:
        spool_path.unlink()
    if payload_path and payload_path.is_file():
        os.replace(payload_path, destination.with_suffix(".payload"))


def artifact_spool_health(
    root: str | Path,
    *,
    last_drain: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    spool_root = _artifact_spool_root(root)
    now = datetime.now(timezone.utc)
    pending = 0
    due = 0
    oldest: datetime | None = None
    for receipt_path in spool_root.glob("pending/*/*/*.upload.json"):
        pending += 1
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            next_attempt = datetime.fromisoformat(
                str(receipt["next_attempt_at"]).replace("Z", "+00:00")
            )
            updated = datetime.fromisoformat(
                str(receipt.get("updated_at") or receipt["next_attempt_at"]).replace(
                    "Z", "+00:00"
                )
            )
            if next_attempt <= now:
                due += 1
            if oldest is None or updated < oldest:
                oldest = updated
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            due += 1
    quarantined = sum(
        1 for _ in spool_root.glob("quarantine/*/*/*.upload.json")
    )
    status = (
        "critical"
        if quarantined
        else "degraded"
        if pending
        else "healthy"
    )
    drain = dict(last_drain or {})
    health = {
        "schema_version": "agentic-os-execution-fabric-artifact-spool-health/v1",
        "status": status,
        "pending": pending,
        "due": due,
        "quarantined": quarantined,
        "oldest_pending_at": (
            oldest.isoformat().replace("+00:00", "Z") if oldest else None
        ),
        "last_drain_at": _utc_now(),
        "last_drain_attempted": int(drain.get("attempted") or 0),
        "last_drain_published": int(drain.get("published") or 0),
    }
    _write_receipt(spool_root / "health.json", health)
    return health


def _heartbeat_spool_health(health: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(health["status"]),
        "pending": int(health["pending"]),
        "due": int(health["due"]),
        "quarantined": int(health["quarantined"]),
        "oldestPendingAt": health.get("oldest_pending_at"),
        "lastDrainAt": str(health["last_drain_at"]),
        "lastDrainAttempted": int(health["last_drain_attempted"]),
        "lastDrainPublished": int(health["last_drain_published"]),
    }


def _publish_or_spool(
    client: ExecutionFabricClient,
    root: str | Path,
    *,
    task_id: str,
    attempt_id: str,
    path: str | Path,
    name: str,
    content_type: str,
    worker_id: str,
    workload_id: str,
    lease_token: str,
    attempt_recovery_token: str,
    fabric_epoch: int,
) -> dict[str, Any]:
    try:
        return client.publish_artifact(
            task_id=task_id,
            attempt_id=attempt_id,
            path=path,
            name=name,
            content_type=content_type,
            worker_id=worker_id,
            lease_token=lease_token,
            fabric_epoch=fabric_epoch,
        )
    except (ExecutionFabricRemoteError, OSError) as exc:
        return _spool_artifact(
            root,
            task_id=task_id,
            attempt_id=attempt_id,
            path=path,
            name=name,
            content_type=content_type,
            worker_id=worker_id,
            workload_id=workload_id,
            attempt_recovery_token=attempt_recovery_token,
            error=type(exc).__name__,
        )


def drain_artifact_spool(
    client: ExecutionFabricClient,
    root: str | Path,
    *,
    worker_id: str,
    workload_id: str,
    registration_token: str,
    fabric_epoch: int,
    limit: int = 20,
) -> dict[str, Any]:
    """Retry durable spools with a fresh grant bound to the current worker session."""
    attempted = 0
    published = 0
    quarantined = 0
    foreign = 0
    now = datetime.now(timezone.utc)
    spool_root = _artifact_spool_root(root).resolve()
    for spool_path in sorted(spool_root.glob("pending/*/*/*.upload.json")):
        if attempted >= limit:
            break
        receipt: dict[str, Any] | None = None
        try:
            loaded = json.loads(spool_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("spool receipt must be an object")
            receipt = loaded
            if receipt.get("schema_version") != ARTIFACT_SPOOL_SCHEMA:
                raise ValueError("unsupported artifact spool receipt schema")
            if str(receipt.get("workload_id") or "") != workload_id:
                foreign += 1
                continue
            if int(receipt.get("attempt_count") or 0) >= int(
                receipt.get("max_attempts") or ARTIFACT_SPOOL_MAX_ATTEMPTS
            ):
                _quarantine_spool(
                    root,
                    spool_path,
                    receipt,
                    reason="artifact spool retry budget exhausted",
                )
                quarantined += 1
                continue
            next_attempt = datetime.fromisoformat(
                str(receipt["next_attempt_at"]).replace("Z", "+00:00")
            )
            if next_attempt > now:
                continue
            payload_path = (spool_root / str(receipt["payload_ref"])).resolve()
            payload_path.relative_to(spool_root / "pending")
            if not payload_path.is_file():
                raise ValueError("artifact spool payload is unavailable")
            actual_sha256, actual_size = _artifact_file_identity(payload_path)
            if (
                actual_sha256 != str(receipt["sha256"])
                or actual_size != int(receipt["size_bytes"])
            ):
                raise ValueError("artifact spool payload identity does not match receipt")
            attempted += 1
            client.publish_recovered_artifact(
                task_id=str(receipt["task_id"]),
                attempt_id=str(receipt["attempt_id"]),
                path=payload_path,
                name=str(receipt["name"]),
                content_type=str(receipt["content_type"]),
                worker_id=worker_id,
                registration_token=registration_token,
                attempt_recovery_token=str(receipt["attempt_recovery_token"]),
                fabric_epoch=fabric_epoch,
            )
            spool_path.unlink()
            payload_path.unlink()
            published += 1
        except (ExecutionFabricRemoteError, OSError, ValueError, KeyError) as exc:
            if receipt is None:
                _quarantine_spool(
                    root,
                    spool_path,
                    None,
                    reason=f"invalid artifact spool receipt: {type(exc).__name__}",
                )
                quarantined += 1
                continue
            attempt_count = int(receipt.get("attempt_count") or 0) + 1
            if attempt_count >= int(
                receipt.get("max_attempts") or ARTIFACT_SPOOL_MAX_ATTEMPTS
            ) or isinstance(exc, (ValueError, KeyError)):
                _quarantine_spool(
                    root,
                    spool_path,
                    receipt,
                    reason=f"terminal artifact spool failure: {type(exc).__name__}",
                )
                quarantined += 1
                continue
            delay_seconds = min(3600, 15 * 2 ** min(attempt_count - 1, 8))
            receipt.update(
                {
                    "attempt_count": attempt_count,
                    "last_error": type(exc).__name__,
                    "next_attempt_at": datetime.fromtimestamp(
                        time.time() + delay_seconds, timezone.utc
                    )
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "updated_at": _utc_now(),
                }
            )
            _write_receipt(spool_path, receipt)
    result: dict[str, Any] = {
        "attempted": attempted,
        "published": published,
        "quarantined": quarantined,
        "foreign": foreign,
    }
    result["health"] = artifact_spool_health(root, last_drain=result)
    return result


def _run_prepared_worker_item(
    os_root: Path,
    assignment: Mapping[str, Any],
    item: dict[str, Any],
    *,
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    from . import runtime_ops

    item = runtime_ops._prepare_queue_item(os_root, item)
    blocker = runtime_ops._dispatch_blocker(item, runtime_ops._registry(os_root))
    if blocker:
        raise TaskExecutionError("dispatch_blocked", blocker, retryable=False)
    timeout_seconds = runtime_ops._dispatch_timeout_seconds(item)
    started_at = _utc_now()
    execution = runtime_ops._run_local_script(
        os_root,
        str(item.get("command") or ""),
        timeout_seconds=timeout_seconds,
    )
    finished_at = _utc_now()
    failure = runtime_ops._execution_failure_class(execution)
    receipt = {
        "schema_version": "agentic-os-execution-fabric-worker-run/v1",
        "task_id": item["id"],
        "attempt_id": str(assignment.get("attemptId") or ""),
        "worker_host": socket.gethostname(),
        "status": "succeeded" if execution.get("ok") else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "execution_target": item.get("execution_target"),
        "task_type": item.get("task_type"),
        "queue_name": item.get("queue_name"),
        "domain_worker": item.get("domain_worker"),
        "evidence": execution,
    }
    receipt_path = (
        os_root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs"
        / item["id"]
        / f"{receipt['attempt_id']}.json"
    )
    _write_receipt(receipt_path, receipt)
    if not execution.get("ok"):
        summary = "; ".join(str(value) for value in execution.get("errors") or [])
        raise TaskExecutionError(
            str(failure.get("failure_class") or "execution_failed"),
            summary or "runtime dispatch failed",
            retryable=bool(failure.get("retryable")),
            receipt_path=str(receipt_path),
        )
    result = {
        "status": "succeeded",
        "startedAt": started_at,
        "finishedAt": finished_at,
        "hostId": socket.gethostname(),
        "receiptPath": str(receipt_path),
        "exitCode": execution.get("exit_code"),
        "stdout": str(execution.get("stdout") or "")[-20000:],
        "stderr": str(execution.get("stderr") or "")[-20000:],
    }
    return {
        "result": result,
        "effects": effects,
        "artifacts": [
            {
                "path": str(receipt_path),
                "name": "run-report.json",
                "contentType": "application/json",
            }
        ],
    }


def _portable_harness_worker(
    harness: str,
    os_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize a closed task reference through the supported harness adapter."""
    payload = dict(task["payload"])
    instruction_ref = str(payload["instruction_ref"])
    instruction_path = (os_root / instruction_ref).resolve()
    try:
        instruction_path.relative_to(os_root.resolve())
    except ValueError:
        raise TaskExecutionError(
            "instruction_ref_rejected",
            "harness task instruction_ref must remain inside the installed OS root",
            retryable=False,
        ) from None
    if not instruction_path.is_file():
        raise TaskExecutionError(
            "instruction_ref_unavailable",
            "harness task instruction_ref is not an installed file",
            retryable=False,
        )
    target = f"{harness}_harness"
    item = {
        "id": str(task.get("id") or ""),
        "kind": "domain_worker",
        "status": "queued",
        "task_type": str(task["taskType"]),
        "queue_name": str(task["queue"]),
        "execution_target": target,
        "approval_state": materialize_approval_state(str(route["approval_class"])),
        "mutation_class": str(route["mutation_class"]),
        "domain_worker": f"{harness}_task",
        "instruction_ref": instruction_ref,
        "work_item_id": str(payload["work_item_id"]),
        "timeout_seconds": 1800,
    }
    return _run_prepared_worker_item(os_root, assignment, item, effects=[])


def _codex_task_worker(
    os_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    return _portable_harness_worker(
        "codex", os_root, assignment, task, route
    )


def _claude_task_worker(
    os_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    return _portable_harness_worker(
        "claude", os_root, assignment, task, route
    )


TEAM_PR_REVIEW_MODE = "review_no_merge"
TEAM_PR_REVIEW_INTENT_SCHEMA = "agentic-os-team-pr-review-intent/v1"
TEAM_PR_HELPER_TIMEOUT_SECONDS = 3700
TEAM_PR_HELPER_STALE_SECONDS = TEAM_PR_HELPER_TIMEOUT_SECONDS + 600


def _team_pr_review_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "repository": str(payload["repository"]).lower(),
        "pull_request": int(payload["pull_request"]),
        "expected_head_sha": str(payload["expected_head_sha"]).lower(),
        "source_key": str(payload["source_key"]).lower(),
        "review_mode": str(payload.get("review_mode") or TEAM_PR_REVIEW_MODE),
    }


def _team_pr_review_intent_key(identity: Mapping[str, Any]) -> str:
    digest = sha256(
        json.dumps(
            dict(identity),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return f"team-pr-review:{digest}"


def _team_pr_review_summary_path(
    os_root: Path, identity: Mapping[str, Any]
) -> Path:
    repository = str(identity["repository"])
    identity_suffix = _team_pr_review_intent_key(identity).split(":", 1)[1]
    run_id = (
        f"team-pr-review-{repository.replace('/', '-')}"
        f"-{identity['pull_request']}-{str(identity['expected_head_sha'])[:12]}"
        f"-{identity_suffix}"
    )
    return (
        os_root
        / "runtime/objects/programs/program/domain/los/team_pr_sync/review-runs"
        / run_id
        / "summary.json"
    )


def _read_json_object(path: Path, *, label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TaskExecutionError(
            "team_pr_durable_receipt_unavailable",
            f"{label} is temporarily unreadable: {type(exc).__name__}",
            retryable=True,
            receipt_path=str(path),
        ) from None
    except json.JSONDecodeError as exc:
        raise TaskExecutionError(
            "invalid_team_pr_durable_receipt",
            f"{label} is unreadable: {type(exc).__name__}",
            retryable=False,
            receipt_path=str(path),
        ) from None
    if not isinstance(value, dict):
        raise TaskExecutionError(
            "invalid_team_pr_durable_receipt",
            f"{label} is not a JSON object",
            retryable=False,
            receipt_path=str(path),
        )
    return value


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_is_team_pr_helper(pid: int, run_id: str) -> bool:
    if not _process_is_alive(pid):
        return False
    command = ""
    proc_command = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_command.is_file():
            command = proc_command.read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        else:
            command = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        args = shlex.split(command)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return (
        any(value.endswith("team_pr_review_fabric.py") for value in args)
        and "--run-id" in args
        and args.index("--run-id") + 1 < len(args)
        and args[args.index("--run-id") + 1] == run_id
    )


class _TeamPRLaunchMarkerLock:
    """Serialize controller and helper launch-marker compare-and-replace steps."""

    def __init__(self, marker_path: Path) -> None:
        self.path = marker_path.with_name("helper-launch.lock")
        self.handle: Any = None

    def __enter__(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("a+", encoding="utf-8")
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            raise TaskExecutionError(
                "team_pr_durable_receipt_unavailable",
                f"Team PR helper launch lock is temporarily unavailable: {type(exc).__name__}",
                retryable=True,
                receipt_path=str(self.path),
            ) from None

    def __exit__(self, *_args: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _validate_team_pr_review_intent(
    intent: Mapping[str, Any],
    *,
    intent_key: str,
    identity: Mapping[str, Any],
    author_identity: str,
    author_kind: str,
    helper_summary_path: Path,
    intent_path: Path,
) -> None:
    if (
        intent.get("schema_version") != TEAM_PR_REVIEW_INTENT_SCHEMA
        or intent.get("intent_key") != intent_key
        or intent.get("identity") != identity
        or intent.get("author_identity") != author_identity
        or intent.get("author_kind") != author_kind
        or intent.get("status") not in {"pending", "completed"}
        or intent.get("helper_summary_path") != str(helper_summary_path)
    ):
        raise TaskExecutionError(
            "team_pr_review_intent_conflict",
            "durable Team PR review intent does not match the admitted request",
            retryable=False,
            receipt_path=str(intent_path),
        )


def _team_pr_review_effect(
    *,
    effect_type: str,
    intent_key: str,
    payload: Mapping[str, Any],
    task_id: str,
    author_identity: str,
    author_kind: str,
) -> dict[str, Any]:
    if "review_mode" in payload:
        effect_key = f"{effect_type}:{intent_key}"
    else:
        # Tasks admitted by the pre-AGE-139 producer omitted review_mode and
        # may already have staged this legacy key before a lost completion ack.
        effect_key = (
            f"{effect_type}:{payload['source_key']}:{payload['expected_head_sha']}"
        )
    return {
        "effectKey": effect_key,
        "effectType": effect_type,
        "payload": {
            "page_id": payload["notion_page_id"],
            "repository": payload["repository"],
            "pull_request": payload["pull_request"],
            "expected_head_sha": payload["expected_head_sha"],
            "base_branch": payload["base_branch"],
            "source_key": payload["source_key"],
            "review_mode": TEAM_PR_REVIEW_MODE,
            "review_intent_key": intent_key,
            "task_identity": task_id,
            "operation": "project_completed_review",
            "author_identity": author_identity,
            "author_kind": author_kind,
        },
        "maxAttempts": 8,
        "baseBackoffSeconds": 60,
    }


def _team_pr_ai_review_worker_locked(
    os_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    from . import runtime_ops

    payload = dict(task["payload"])
    task_id = str(task.get("id") or "")
    author_identity = str(payload.get("author_identity") or "")
    if not author_identity:
        raise TaskExecutionError(
            "authorship_unavailable",
            "team PR review requires provider-read author_identity",
            retryable=False,
        )
    profile_candidates = sorted(
        (os_root / "domains").glob(
            "*/02-projects/los_app_los_django/config/development.yml"
        )
    )
    if len(profile_candidates) != 1:
        raise TaskExecutionError(
            "authorship_policy_unavailable",
            "Team PR review requires exactly one installed canonical project profile",
            retryable=False,
        )
    profile_path = profile_candidates[0]
    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        ours = {
            str(value).strip().lower()
            for value in (
                ((profile.get("review") or {}).get("authorship") or {}).get("ours")
                or []
            )
            if str(value).strip()
        }
    except OSError as exc:
        raise TaskExecutionError(
            "authorship_policy_unavailable",
            f"canonical review authorship policy is temporarily unreadable: {type(exc).__name__}",
            retryable=True,
        ) from None
    except (TypeError, yaml.YAMLError) as exc:
        raise TaskExecutionError(
            "authorship_policy_unavailable",
            f"canonical review authorship policy is unreadable: {type(exc).__name__}",
            retryable=False,
        ) from None
    if not ours:
        raise TaskExecutionError(
            "authorship_policy_unavailable",
            "canonical review.authorship.ours is empty",
            retryable=False,
        )
    author_kind = "ours" if author_identity.lower() in ours else "others"
    identity = _team_pr_review_identity(payload)
    if identity["review_mode"] != TEAM_PR_REVIEW_MODE:
        raise TaskExecutionError(
            "unsupported_team_pr_review_mode",
            "Team PR review mode must remain review_no_merge",
            retryable=False,
        )
    intent_key = _team_pr_review_intent_key(identity)
    intent_path = (
        os_root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs"
        / task_id
        / "review-intent.json"
    )
    helper_summary_path = _team_pr_review_summary_path(os_root, identity)
    helper_launch_path = helper_summary_path.with_name("helper-launch.json")
    intent = _read_json_object(intent_path, label="Team PR review intent")
    if intent is not None:
        _validate_team_pr_review_intent(
            intent,
            intent_key=intent_key,
            identity=identity,
            author_identity=author_identity,
            author_kind=author_kind,
            helper_summary_path=helper_summary_path,
            intent_path=intent_path,
        )
    if intent is None:
        intent = {
            "schema_version": TEAM_PR_REVIEW_INTENT_SCHEMA,
            "intent_key": intent_key,
            "identity": identity,
            "author_identity": author_identity,
            "author_kind": author_kind,
            "task_id": task_id,
            "status": "pending",
            "helper_summary_path": str(helper_summary_path),
            "created_at": _utc_now(),
        }
        if not _write_team_pr_receipt_once(intent_path, intent):
            intent = _read_json_object(intent_path, label="Team PR review intent")
            if intent is None:
                raise TaskExecutionError(
                    "team_pr_durable_receipt_unavailable",
                    "Team PR review intent disappeared during atomic creation",
                    retryable=True,
                    receipt_path=str(intent_path),
                )
            _validate_team_pr_review_intent(
                intent,
                intent_key=intent_key,
                identity=identity,
                author_identity=author_identity,
                author_kind=author_kind,
                helper_summary_path=helper_summary_path,
                intent_path=intent_path,
            )
    helper_candidates = sorted(
        (os_root / "lib/programs/domains").glob(
            "*/team_pr_sync/scripts/team_pr_review_fabric.py"
        )
    )
    if len(helper_candidates) != 1 or not helper_candidates[0].is_file():
        raise TaskExecutionError(
            "team_pr_helper_unavailable",
            "Team PR review requires exactly one installed helper",
            retryable=False,
        )
    helper_path = helper_candidates[0]
    command = shlex.join(
        [
            "python3",
            str(helper_path),
            "execute",
            "--root",
            str(os_root),
            "--repository",
            str(payload["repository"]),
            "--pr-number",
            str(payload["pull_request"]),
            "--expected-head",
            str(payload["expected_head_sha"]),
            "--base-branch",
            str(payload["base_branch"]),
            "--source-key",
            str(payload["source_key"]),
            "--review-mode",
            TEAM_PR_REVIEW_MODE,
            "--run-id",
            helper_summary_path.parent.name,
            "--summary-path",
            str(helper_summary_path),
            "--launch-marker-path",
            str(helper_launch_path),
            "--title",
            str(payload["title"]),
            "--author-identity",
            author_identity,
            "--apply",
        ]
    )
    started_at = _utc_now()
    recovered = False
    helper_result = None
    if intent.get("status") == "completed":
        candidate = intent.get("helper_result")
        if not isinstance(candidate, dict):
            raise TaskExecutionError(
                "invalid_team_pr_durable_receipt",
                "completed Team PR review intent has no helper result",
                retryable=False,
                receipt_path=str(intent_path),
            )
        helper_result = candidate
        recovered = True
    elif intent.get("status") == "pending":
        persisted_summary_path = Path(str(intent["helper_summary_path"]))
        helper_result = _read_json_object(
            persisted_summary_path, label="Team PR helper summary"
        )
        recovered = helper_result is not None
    if helper_result is None:
        with _TeamPRLaunchMarkerLock(helper_launch_path):
            helper_launch = _read_json_object(
                helper_launch_path, label="Team PR helper launch marker"
            )
            if helper_launch is not None and (
                helper_launch.get("schema_version")
                != "agentic-os-team-pr-helper-launch/v1"
                or helper_launch.get("intent_key") != intent_key
                or helper_launch.get("helper_summary_path")
                != str(helper_summary_path)
                or helper_launch.get("status") not in {"running", "failed"}
                or (
                    "helper_pid" in helper_launch
                    and (
                        not isinstance(helper_launch.get("helper_pid"), int)
                        or int(helper_launch["helper_pid"]) <= 0
                    )
                )
            ):
                raise TaskExecutionError(
                    "team_pr_review_intent_conflict",
                    "durable Team PR helper launch marker does not match the admitted request",
                    retryable=False,
                    receipt_path=str(helper_launch_path),
                )
            helper_pid = (
                helper_launch.get("helper_pid") if helper_launch is not None else None
            )
            if isinstance(helper_pid, int) and _process_is_team_pr_helper(
                helper_pid, helper_summary_path.parent.name
            ):
                raise TaskExecutionError(
                    "team_pr_review_in_progress",
                    "a prior Team PR helper is still running",
                    retryable=True,
                    receipt_path=str(helper_launch_path),
                )
            if helper_launch is not None and helper_launch.get("status") == "running":
                try:
                    launched_at = datetime.fromisoformat(
                        str(helper_launch["launched_at"]).replace("Z", "+00:00")
                    )
                    if launched_at.tzinfo is None:
                        raise ValueError("launch time has no timezone")
                    launch_age = (
                        datetime.now(timezone.utc) - launched_at
                    ).total_seconds()
                except (KeyError, TypeError, ValueError):
                    raise TaskExecutionError(
                        "invalid_team_pr_durable_receipt",
                        "Team PR helper launch marker has an invalid launch time",
                        retryable=False,
                        receipt_path=str(helper_launch_path),
                    ) from None
                helper_alive = isinstance(helper_pid, int) and _process_is_alive(
                    helper_pid
                )
                if launch_age < TEAM_PR_HELPER_STALE_SECONDS and (
                    helper_alive or helper_pid is None
                ):
                    raise TaskExecutionError(
                        "team_pr_review_in_progress",
                        "a prior Team PR helper may still be running",
                        retryable=True,
                        receipt_path=str(helper_launch_path),
                    )
            helper_launch = {
                "schema_version": "agentic-os-team-pr-helper-launch/v1",
                "intent_key": intent_key,
                "helper_summary_path": str(helper_summary_path),
                "attempt_id": str(assignment.get("attemptId") or ""),
                "status": "running",
                "launched_at": _utc_now(),
            }
            _write_team_pr_receipt(
                helper_launch_path, helper_launch, durable=True
            )
        try:
            execution = runtime_ops._run_local_script(
                os_root,
                command,
                timeout_seconds=TEAM_PR_HELPER_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            with _TeamPRLaunchMarkerLock(helper_launch_path):
                latest_launch = _read_json_object(
                    helper_launch_path, label="Team PR helper launch marker"
                )
                latest_launch = latest_launch or helper_launch
                latest_pid = latest_launch.get("helper_pid")
                if isinstance(latest_pid, int):
                    raise TaskExecutionError(
                        "team_pr_review_in_progress",
                        "Team PR helper may still be running after a dispatch failure",
                        retryable=True,
                        receipt_path=str(helper_launch_path),
                    ) from None
                _write_team_pr_receipt(
                    helper_launch_path,
                    {
                        **latest_launch,
                        "status": "failed",
                        "finished_at": _utc_now(),
                        "failure_type": type(exc).__name__,
                    },
                    durable=True,
                )
            if isinstance(exc, OSError):
                raise TaskExecutionError(
                    "team_pr_helper_launch_failed",
                    f"Team PR helper launch failed: {type(exc).__name__}",
                    retryable=True,
                    receipt_path=str(helper_launch_path),
                ) from None
            raise
        if not execution.get("ok"):
            with _TeamPRLaunchMarkerLock(helper_launch_path):
                latest_launch = _read_json_object(
                    helper_launch_path, label="Team PR helper launch marker"
                )
                if latest_launch is None or (
                    latest_launch.get("schema_version")
                    != "agentic-os-team-pr-helper-launch/v1"
                    or latest_launch.get("intent_key") != intent_key
                    or latest_launch.get("helper_summary_path")
                    != str(helper_summary_path)
                    or latest_launch.get("status") != "running"
                    or (
                        "helper_pid" in latest_launch
                        and (
                            not isinstance(latest_launch.get("helper_pid"), int)
                            or int(latest_launch["helper_pid"]) <= 0
                        )
                    )
                ):
                    raise TaskExecutionError(
                        "team_pr_review_intent_conflict",
                        "Team PR helper launch marker changed during execution",
                        retryable=False,
                        receipt_path=str(helper_launch_path),
                    )
                latest_pid = latest_launch.get("helper_pid")
                child_may_be_live = isinstance(latest_pid, int) or (
                    bool(execution.get("governed_run"))
                    and (
                        execution.get("governed_status") == "stale"
                        or (
                            execution.get("returncode") is None
                            and not execution.get("timed_out")
                        )
                    )
                )
                if child_may_be_live:
                    raise TaskExecutionError(
                        "team_pr_review_in_progress",
                        "Team PR helper execution is non-terminal and may still be running",
                        retryable=True,
                        receipt_path=str(helper_launch_path),
                    )
                _write_team_pr_receipt(
                    helper_launch_path,
                    {
                        **latest_launch,
                        "status": "failed",
                        "finished_at": _utc_now(),
                    },
                    durable=True,
                )
    else:
        execution = {
            "supported": True,
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps(helper_result, sort_keys=True),
            "stderr": "",
            "errors": [],
            "warnings": ["recovered from durable Team PR review intent"],
        }
    finished_at = _utc_now()
    failure = runtime_ops._execution_failure_class(execution)
    receipt = {
        "schema_version": "agentic-os-execution-fabric-worker-run/v1",
        "task_id": task_id,
        "attempt_id": str(assignment.get("attemptId") or ""),
        "worker_host": socket.gethostname(),
        "status": "succeeded" if execution.get("ok") else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "execution_target": "team_pr_review_helper",
        "task_type": str(task["taskType"]),
        "queue_name": str(task["queue"]),
        "domain_worker": "team_pr_ai_review",
        "review_intent_key": intent_key,
        "review_intent_recovered": recovered,
        "canonical_project_config": str(profile_path),
        "evidence": execution,
    }
    receipt_path = (
        os_root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs"
        / task_id
        / f"{receipt['attempt_id']}.json"
    )
    _write_team_pr_receipt(receipt_path, receipt)
    if not execution.get("ok"):
        summary = "; ".join(str(value) for value in execution.get("errors") or [])
        raise TaskExecutionError(
            str(failure.get("failure_class") or "execution_failed"),
            summary or "Team PR review helper failed",
            retryable=bool(failure.get("retryable")),
            receipt_path=str(receipt_path),
        )
    if helper_result is None:
        helper_result = _read_json_object(
            helper_summary_path, label="Team PR helper summary"
        )
        if helper_result is None:
            try:
                helper_result = json.loads(str(execution.get("stdout") or ""))
            except json.JSONDecodeError:
                raise TaskExecutionError(
                    "invalid_team_pr_helper_receipt",
                    "Team PR review helper did not return a JSON object",
                    retryable=True,
                    receipt_path=str(receipt_path),
                ) from None
    if not isinstance(helper_result, dict):
        raise TaskExecutionError(
            "invalid_team_pr_helper_receipt",
            "Team PR review helper returned a non-object receipt",
            retryable=False,
            receipt_path=str(receipt_path),
        )
    if (
        helper_result.get("run_id") != helper_summary_path.parent.name
        or str(helper_result.get("source_key") or "").lower()
        != identity["source_key"]
    ):
        raise TaskExecutionError(
            "invalid_team_pr_durable_receipt",
            "Team PR helper summary does not match the admitted review identity",
            retryable=False,
            receipt_path=str(helper_summary_path),
        )
    with _TeamPRLaunchMarkerLock(helper_launch_path):
        latest_launch = _read_json_object(
            helper_launch_path, label="Team PR helper launch marker"
        )
        if latest_launch is None:
            if not recovered:
                raise TaskExecutionError(
                    "team_pr_durable_receipt_unavailable",
                    "Team PR helper launch marker disappeared after execution",
                    retryable=True,
                    receipt_path=str(helper_launch_path),
                )
        elif (
            latest_launch.get("schema_version")
            != "agentic-os-team-pr-helper-launch/v1"
            or latest_launch.get("intent_key") != intent_key
            or latest_launch.get("helper_summary_path") != str(helper_summary_path)
            or latest_launch.get("status") not in {"running", "failed", "succeeded"}
        ):
            raise TaskExecutionError(
                "team_pr_review_intent_conflict",
                "Team PR helper launch marker changed before terminalization",
                retryable=False,
                receipt_path=str(helper_launch_path),
            )
        elif latest_launch.get("status") != "succeeded":
            _write_team_pr_receipt(
                helper_launch_path,
                {
                    **latest_launch,
                    "status": "succeeded",
                    "finished_at": _utc_now(),
                },
                durable=True,
            )
    helper_status = str(helper_result.get("status") or "")
    effects: list[dict[str, Any]] = []
    if helper_status != "superseded":
        canonical = helper_result.get("canonical_review_receipt")
        if not isinstance(canonical, dict):
            raise TaskExecutionError(
                "invalid_team_pr_helper_receipt",
                "Team PR review helper omitted the canonical review receipt",
                retryable=False,
                receipt_path=str(receipt_path),
            )
        expected_receipt = {
            "repository": payload["repository"],
            "pull_request": payload["pull_request"],
            "configured_base": payload["base_branch"],
            "reviewed_head_sha": payload["expected_head_sha"],
            "final_head_sha": payload["expected_head_sha"],
            "review_mode": "review_no_merge",
            "author_identity": author_identity,
            "author_kind": author_kind,
            "readback_verified": True,
        }
        if any(canonical.get(key) != value for key, value in expected_receipt.items()):
            raise TaskExecutionError(
                "invalid_team_pr_helper_receipt",
                "Team PR review helper receipt does not match the admitted immutable request",
                retryable=False,
                receipt_path=str(receipt_path),
            )
        receipt_hash = sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        if (
            helper_result.get("receipt_sha256") != receipt_hash
            or helper_status != canonical.get("outcome")
        ):
            raise TaskExecutionError(
                "invalid_team_pr_helper_receipt",
                "Team PR review helper receipt wrapper is inconsistent",
                retryable=False,
                receipt_path=str(receipt_path),
            )
        allowed_effects = {
            str(value) for value in route.get("allowed_effect_types") or []
        }
        if len(allowed_effects) != 1:
            raise TaskExecutionError(
                "invalid_team_pr_effect_route",
                "Team PR route must declare exactly one allowed effect type",
                retryable=False,
                receipt_path=str(receipt_path),
            )
        effect_type = next(iter(allowed_effects))
        effects.append(
            _team_pr_review_effect(
                effect_type=effect_type,
                intent_key=intent_key,
                payload=payload,
                task_id=task_id,
                author_identity=author_identity,
                author_kind=author_kind,
            )
        )
    if intent.get("status") == "completed":
        if (
            intent.get("helper_status") != helper_status
            or intent.get("helper_result") != helper_result
            or intent.get("effects") != effects
        ):
            raise TaskExecutionError(
                "team_pr_review_intent_conflict",
                "completed Team PR review intent changed during recovery",
                retryable=False,
                receipt_path=str(intent_path),
            )
    else:
        current_intent = _read_json_object(
            intent_path, label="Team PR review intent"
        )
        if current_intent is None or current_intent != intent:
            raise TaskExecutionError(
                "team_pr_review_intent_conflict",
                "pending Team PR review intent changed before completion",
                retryable=False,
                receipt_path=str(intent_path),
            )
        completed_intent = {
            **intent,
            "status": "completed",
            "completed_at": finished_at,
            "helper_status": helper_status,
            "helper_result": helper_result,
            "effects": effects,
        }
        _write_team_pr_receipt(intent_path, completed_intent, durable=True)
    effect = {
        "status": "succeeded",
        "startedAt": started_at,
        "finishedAt": finished_at,
        "hostId": socket.gethostname(),
        "receiptPath": str(receipt_path),
        "exitCode": execution.get("exit_code"),
        "stdout": str(execution.get("stdout") or "")[-20000:],
        "stderr": str(execution.get("stderr") or "")[-20000:],
        "helperStatus": helper_status,
    }
    return {
        "result": effect,
        "effects": effects,
        "artifacts": [
            {
                "path": str(receipt_path),
                "name": "run-report.json",
                "contentType": "application/json",
            }
        ],
    }


def _team_pr_ai_review_worker(
    os_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    identity = _team_pr_review_identity(dict(task.get("payload") or {}))
    lock_path = _team_pr_review_summary_path(os_root, identity).with_name(
        "review-intent.lock"
    )
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("a+", encoding="utf-8")
    except OSError as exc:
        raise TaskExecutionError(
            "team_pr_durable_receipt_unavailable",
            f"Team PR review identity lock is temporarily unavailable: {type(exc).__name__}",
            retryable=True,
            receipt_path=str(lock_path),
        ) from None
    with lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TaskExecutionError(
                "team_pr_review_in_progress",
                "another attempt is already executing this Team PR review intent",
                retryable=True,
                receipt_path=str(lock_path),
            ) from None
        except OSError as exc:
            raise TaskExecutionError(
                "team_pr_durable_receipt_unavailable",
                f"Team PR review identity lock is temporarily unavailable: {type(exc).__name__}",
                retryable=True,
                receipt_path=str(lock_path),
            ) from None
        try:
            return _team_pr_ai_review_worker_locked(
                os_root, assignment, task, route
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _validate_domain_worker_result(
    worker_name: str,
    route: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(result)
    effects = normalized.get("effects")
    if not isinstance(effects, list):
        raise TaskExecutionError(
            "invalid_domain_worker_result",
            f"domain worker {worker_name} did not return an effects list",
            retryable=False,
        )
    allowed = set(str(value) for value in route["allowed_effect_types"])
    for effect in effects:
        if (
            not isinstance(effect, dict)
            or str(effect.get("effectType") or "") not in allowed
            or not str(effect.get("effectKey") or "")
            or not isinstance(effect.get("payload"), dict)
        ):
            raise TaskExecutionError(
                "invalid_domain_worker_effect",
                f"domain worker {worker_name} returned an undeclared or malformed effect",
                retryable=False,
            )
    return normalized


register_domain_worker("codex_task", _codex_task_worker)
register_domain_worker("claude_task", _claude_task_worker)
register_domain_worker("team_pr_ai_review", _team_pr_ai_review_worker)


def execute_assignment(root: str | Path, assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one assignment through the existing governed local dispatcher."""
    from . import runtime_ops

    os_root = expand_path(root)
    task = dict(assignment.get("task") or {})
    payload = dict(task.get("payload") or {})
    route = validate_task_route(
        os_root,
        str(task.get("queue") or ""),
        str(task.get("taskType") or ""),
        payload=payload,
        remote=True,
    )
    allowed_host_ids = {str(value) for value in route.get("allowed_host_ids") or []}
    if allowed_host_ids:
        try:
            current_host_id = resolve_execution_fabric_host_id(
                os_root, require_registered=False
            )
        except ExecutionFabricConfigError as exc:
            raise TaskExecutionError(
                "task_host_affinity_unavailable",
                f"execution host identity is temporarily unavailable: {exc}",
                retryable=True,
            ) from None
        if current_host_id not in allowed_host_ids:
            raise TaskExecutionError(
                "task_host_affinity_violation",
                f"task type {task.get('taskType')!r} is pinned to a different execution host",
                retryable=True,
            )
    if route["domain_worker"]:
        worker_name = str(route["domain_worker"])
        handler = _DOMAIN_WORKERS.get(worker_name)
        if handler is None:
            raise TaskExecutionError(
                "domain_worker_unavailable",
                f"domain worker {worker_name} is not installed on this host",
                retryable=False,
            )
        return _validate_domain_worker_result(
            worker_name,
            route,
            handler(os_root, assignment, task, route),
        )
    template = route["command_template"]
    if not isinstance(template, list) or not template:
        raise TaskExecutionError(
            "route_not_materializable",
            "canonical task route has no executable command template",
            retryable=False,
        )
    argv: list[str] = []
    for token in template:
        materialized = str(token)
        for name, value in payload.items():
            materialized = materialized.replace(f"{{{name}}}", str(value))
        if re.search(r"\{[a-z][a-z0-9_]*\}", materialized):
            raise TaskExecutionError(
                "route_not_materializable",
                "canonical command template contains an unresolved field",
                retryable=False,
            )
        argv.append(materialized)
    item = {
        "id": str(task.get("id") or ""),
        "kind": "remote_policy_route",
        "status": "queued",
        "task_type": str(task.get("taskType") or ""),
        "queue_name": str(task.get("queue") or ""),
        "command": shlex.join(argv),
        "execution_target": route["execution_target"],
        "approval_state": materialize_approval_state(str(route["approval_class"])),
        "mutation_class": route["mutation_class"],
    }
    return _run_prepared_worker_item(os_root, assignment, item, effects=[])


class RemoteFabricWorker:
    """Concurrent, heartbeat-driven worker loop for one installed OS host."""

    def __init__(
        self,
        client: ExecutionFabricClient,
        *,
        root: str | Path,
        worker_id: str,
        bootstrap_id: str,
        host_id: str,
        queues: list[str],
        capabilities: list[str] | None = None,
        max_concurrency: int = 1,
        heartbeat_seconds: int = 15,
        spool_drain_seconds: int = 30,
        executor: Callable[[str | Path, Mapping[str, Any]], dict[str, Any]] = execute_assignment,
    ) -> None:
        if not queues:
            raise ValueError("worker must subscribe to at least one queue")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.client = client
        self.root = expand_path(root)
        self.worker_id = worker_id
        self.bootstrap_id = bootstrap_id
        self.host_id = host_id
        self.queues = list(dict.fromkeys(queues))
        self.capabilities = list(dict.fromkeys(capabilities or []))
        self.max_concurrency = max_concurrency
        self.heartbeat_seconds = max(1, heartbeat_seconds)
        self.spool_drain_seconds = max(5, spool_drain_seconds)
        self.executor = executor

    def work(self, *, max_tasks: int | None = None) -> dict[str, Any]:
        registration = self.client.register_worker(
            {
                "bootstrapId": self.bootstrap_id,
                "workerId": self.worker_id,
                "hostId": self.host_id,
                "queues": self.queues,
                "capabilities": self.capabilities,
                "maxConcurrency": self.max_concurrency,
                "metadata": {
                    "runtime": "genomes-agentic-os-python",
                    "transport": "remote",
                },
            }
        )
        registration_token = str(registration["registrationToken"])
        health_path = (
            self.root
            / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-health"
            / f"{self.worker_id}.json"
        )
        def record_health(status: str, active_attempt_ids: list[str]) -> None:
            _write_receipt(
                health_path,
                {
                    "schema_version": "agentic-os-execution-fabric-worker-health/v1",
                    "worker_id": self.worker_id,
                    "host_id": self.host_id,
                    "status": status,
                    "fabric_epoch": int(registration["fabricEpoch"]),
                    "active_attempt_ids": active_attempt_ids,
                    "observed_at": _utc_now(),
                },
            )
        record_health("online", [])
        spool_retry = drain_artifact_spool(
            self.client,
            self.root,
            worker_id=self.worker_id,
            workload_id=self.bootstrap_id,
            registration_token=registration_token,
            fabric_epoch=int(registration["fabricEpoch"]),
        )
        spool_health = _heartbeat_spool_health(spool_retry["health"])
        started_at = _utc_now()
        submitted = 0
        completed = 0
        failed = 0
        active: dict[Future[dict[str, Any]], dict[str, Any]] = {}
        last_heartbeat = 0.0
        last_spool_drain = time.monotonic()
        with ThreadPoolExecutor(
            max_workers=self.max_concurrency,
            thread_name_prefix="aos-fabric",
        ) as pool:
            while max_tasks is None or completed + failed < max_tasks:
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_seconds:
                    if now - last_spool_drain >= self.spool_drain_seconds:
                        spool_retry = drain_artifact_spool(
                            self.client,
                            self.root,
                            worker_id=self.worker_id,
                            workload_id=self.bootstrap_id,
                            registration_token=registration_token,
                            fabric_epoch=int(registration["fabricEpoch"]),
                        )
                        spool_health = _heartbeat_spool_health(
                            spool_retry["health"]
                        )
                        last_spool_drain = now
                    self.client.heartbeat(
                        self.worker_id,
                        registration_token,
                        [str(row["attemptId"]) for row in active.values()],
                        artifact_spool_health=spool_health,
                    )
                    record_health(
                        "online",
                        [str(row["attemptId"]) for row in active.values()],
                    )
                    last_heartbeat = now
                for future, assignment in list(active.items()):
                    if not future.done():
                        continue
                    del active[future]
                    try:
                        outcome = future.result()
                        task_id = str((assignment.get("task") or {}).get("id") or "")
                        artifact_receipts = [
                            _publish_or_spool(
                                self.client,
                                self.root,
                                task_id=task_id,
                                attempt_id=str(assignment["attemptId"]),
                                path=str(artifact["path"]),
                                name=str(artifact.get("name") or "run-report.json"),
                                content_type=str(
                                    artifact.get("contentType") or "application/json"
                                ),
                                worker_id=self.worker_id,
                                workload_id=self.bootstrap_id,
                                lease_token=str(assignment["leaseToken"]),
                                attempt_recovery_token=str(
                                    assignment["attemptRecoveryToken"]
                                ),
                                fabric_epoch=int(assignment["fabricEpoch"]),
                            )
                            for artifact in outcome.get("artifacts") or []
                        ]
                        result = dict(outcome.get("result") or {})
                        result["artifacts"] = artifact_receipts
                        self.client.complete_attempt(
                            str(assignment["attemptId"]),
                            worker_id=self.worker_id,
                            lease_token=str(assignment["leaseToken"]),
                            fabric_epoch=int(assignment["fabricEpoch"]),
                            result=result,
                            effects=outcome.get("effects") or [],
                        )
                        completed += 1
                    except TaskExecutionError as exc:
                        if exc.receipt_path:
                            _publish_or_spool(
                                self.client,
                                self.root,
                                task_id=str(
                                    (assignment.get("task") or {}).get("id") or ""
                                ),
                                attempt_id=str(assignment["attemptId"]),
                                path=exc.receipt_path,
                                name="run-report.json",
                                content_type="application/json",
                                worker_id=self.worker_id,
                                workload_id=self.bootstrap_id,
                                lease_token=str(assignment["leaseToken"]),
                                attempt_recovery_token=str(
                                    assignment["attemptRecoveryToken"]
                                ),
                                fabric_epoch=int(assignment["fabricEpoch"]),
                            )
                        self.client.fail_attempt(
                            str(assignment["attemptId"]),
                            worker_id=self.worker_id,
                            lease_token=str(assignment["leaseToken"]),
                            fabric_epoch=int(assignment["fabricEpoch"]),
                            error_code=exc.code,
                            error_summary=exc.summary,
                            retryable=exc.retryable,
                        )
                        failed += 1
                    except Exception as exc:  # pragma: no cover - defensive worker boundary
                        self.client.fail_attempt(
                            str(assignment["attemptId"]),
                            worker_id=self.worker_id,
                            lease_token=str(assignment["leaseToken"]),
                            fabric_epoch=int(assignment["fabricEpoch"]),
                            error_code="worker_internal_error",
                            error_summary=type(exc).__name__,
                            retryable=False,
                        )
                        failed += 1
                if max_tasks is not None and completed + failed >= max_tasks:
                    break
                capacity = self.max_concurrency - len(active)
                remaining = None if max_tasks is None else max_tasks - submitted
                if capacity > 0 and (remaining is None or remaining > 0):
                    assignment = self.client.claim(
                        worker_id=self.worker_id,
                        registration_token=registration_token,
                        queues=self.queues,
                        capabilities=self.capabilities,
                        wait_ms=(
                            self.client.settings.long_poll_seconds * 1000
                            if not active
                            else 0
                        ),
                    )
                    if assignment:
                        future = pool.submit(self.executor, self.root, assignment)
                        active[future] = assignment
                        submitted += 1
                        continue
                if active:
                    time.sleep(0.05)
                elif self.client.settings.long_poll_seconds == 0:
                    time.sleep(0.1)
                elif max_tasks is not None and submitted >= max_tasks:
                    break
        record_health("stopped", [])
        return {
            "status": "stopped",
            "worker_id": self.worker_id,
            "host_id": self.host_id,
            "queues": self.queues,
            "max_concurrency": self.max_concurrency,
            "submitted": submitted,
            "completed": completed,
            "failed": failed,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "artifact_spool_retry": spool_retry,
        }


def build_remote_runtime_snapshot(
    root: str | Path,
    *,
    task_id: str | None = None,
    limit: int = 200,
    client: ExecutionFabricClient | None = None,
) -> dict[str, Any]:
    """Normalize remote control-plane reads into the existing snapshot contract."""
    os_root = expand_path(root)
    remote = client or ExecutionFabricClient.from_root(os_root, role="observer")
    status_result = remote.status(limit=limit)
    queues = list(status_result.get("queues") or [])
    raw_workers = list(status_result.get("workers") or [])
    runs = list(status_result.get("runs") or [])
    fabric_config = load_execution_fabric_config(os_root).value["execution_fabric"]
    pool_by_queue = {
        str(queue): str(pool["id"])
        for pool in fabric_config["worker_pools"]
        for queue in pool.get("queues") or []
    }
    projected_queues = [
        {
            "queue_name": row.get("queue"),
            "statuses": {
                "queued": int(row.get("queued") or 0),
                "running": int(row.get("running") or 0),
                "done": int(row.get("succeeded") or 0),
                "failed": int(row.get("failed") or 0),
                "dead-letter": int(row.get("deadLettered") or 0),
            },
            "total": sum(
                int(row.get(field) or 0)
                for field in (
                    "queued",
                    "running",
                    "succeeded",
                    "failed",
                    "deadLettered",
                    "cancelled",
                )
            ),
            "depth": int(row.get("queued") or 0),
            "running": int(row.get("running") or 0),
            "failed": int(row.get("failed") or 0),
            "dead_letter": int(row.get("deadLettered") or 0),
            "retrying": int(row.get("retrying") or 0),
            "delayed_retries": int(row.get("delayed") or 0),
            "ready": int(row.get("ready") or 0),
            "throughput_per_hour": int(row.get("throughputPerHour") or 0),
            "failure_rate_last_hour": float(row.get("failureRateLastHour") or 0),
            "oldest_wait_seconds": float(row.get("oldestReadyAgeSeconds") or 0),
            "oldest_queued_at": row.get("oldestQueuedAt"),
            "max_concurrency": row.get("maxRunning"),
            "max_queued": row.get("maxQueued"),
            "enabled": bool(row.get("enabled", True)),
            "saturation": row.get("saturation"),
            "capacity_remaining": row.get("capacityRemaining"),
        }
        for row in queues
    ]
    workers = [
        {
            "id": row.get("workerId"),
            "host_id": row.get("hostId"),
            "queue_names": row.get("queues") or [],
            "pool_name": (
                row.get("poolId")
                or pool_by_queue.get(str((row.get("queues") or [""])[0]), "remote")
                if len(row.get("queues") or []) == 1
                else "remote_multi"
            ),
            "queue_name": (
                str((row.get("queues") or [""])[0])
                if len(row.get("queues") or []) == 1
                else "multi"
            ),
            "provider": row.get("provider") or "remote",
            "capabilities": row.get("capabilities") or [],
            "status": row.get("state"),
            "capacity": row.get("maxConcurrency"),
            "active_tasks": row.get("running"),
            "heartbeat_at": row.get("lastHeartbeatAt"),
            "lease_until": row.get("leaseExpiresAt"),
            "config_fingerprint": row.get("configFingerprint"),
            "session_id": row.get("currentSessionId"),
            "session_started_at": row.get("currentSessionStartedAt"),
            "session_history": row.get("sessionHistory") or [],
        }
        for row in raw_workers
    ]
    tasks = [
        {
            "id": row.get("taskId"),
            "kind": row.get("taskType"),
            "status": "dead-letter" if row.get("status") == "dead_lettered" else row.get("status"),
            "queue_name": row.get("queue"),
            "worker_pool": pool_by_queue.get(str(row.get("queue") or ""), "remote"),
            "attempts": row.get("attemptCount"),
            "priority": row.get("priority"),
            "execution_target": row.get("executionTarget"),
            "created_at": row.get("createdAt"),
            "due_at": row.get("availableAt"),
            "started_at": ((row.get("attempts") or [{}])[0]).get("startedAt")
            if row.get("attempts")
            else None,
            "finished_at": row.get("completedAt"),
            "lease_owner": row.get("workerId"),
            "lease_until": row.get("leaseExpiresAt"),
            "updated_at": row.get("updatedAt"),
        }
        for row in runs
    ]
    requested_task = remote.get_task(task_id) if task_id else None
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    parsed_url = urlsplit(str(remote.settings.control_plane_url))
    recent_run_reports = []
    for row in runs:
        attempts = list(row.get("attempts") or [])
        latest_attempt = attempts[0] if attempts else {}
        effects = list(row.get("effects") or [])
        started_at = latest_attempt.get("startedAt")
        finished_at = latest_attempt.get("finishedAt") or row.get("completedAt")
        duration_seconds = None
        if started_at and finished_at:
            try:
                duration_seconds = max(
                    0.0,
                    (
                        datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
                        - datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                    ).total_seconds(),
                )
            except ValueError:
                duration_seconds = None
        recent_run_reports.append(
            {
            "run_id": row.get("runId") or row.get("taskId"),
            "task_id": row.get("taskId"),
            "task_type": row.get("taskType"),
            "queue_name": row.get("queue"),
            "status": "dead-letter"
            if row.get("status") == "dead_lettered"
            else row.get("status"),
            "attempt_count": row.get("attemptCount"),
            "worker_id": row.get("workerId"),
            "effects_pending": sum(
                1
                for effect in effects
                if effect.get("status") in {"pending", "processing"}
            ),
            "effects_failed": sum(
                1
                for effect in effects
                if effect.get("status") in {"failed", "dead_lettered"}
            ),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "error_summary": row.get("lastErrorSummary")
            or latest_attempt.get("errorSummary"),
            "updated_at": row.get("updatedAt"),
            "artifacts": [
                {
                    "artifact_id": artifact.get("artifactId"),
                    "name": artifact.get("name"),
                    "content_type": artifact.get("contentType"),
                    "sha256": artifact.get("sha256"),
                    "size_bytes": artifact.get("sizeBytes"),
                    "status": artifact.get("status"),
                    "uri": artifact.get("uri"),
                    "available_at": artifact.get("availableAt"),
                    "last_error": artifact.get("lastError"),
                }
                for artifact in row.get("artifacts") or []
            ],
            }
        )
    offline_workers = sum(1 for row in workers if row.get("status") != "online")
    succeeded = sum(int(row.get("succeeded") or 0) for row in queues)
    dead_lettered = sum(int(row.get("deadLettered") or 0) for row in queues)
    retrying = sum(int(row.get("retrying") or 0) for row in queues)
    delayed_retries = sum(int(row.get("delayed") or 0) for row in queues)
    oldest_wait_seconds = max(
        (float(row.get("oldestReadyAgeSeconds") or 0) for row in queues),
        default=0.0,
    )
    failed_last_hour = sum(int(row.get("failedLastHour") or 0) for row in queues)
    admission = fabric_config["admission"]
    raw_control_plane = dict(status_result.get("controlPlane") or {})
    leadership = dict(raw_control_plane.get("leadership") or {})
    active_host = raw_control_plane.get("activeHost") or parsed_url.hostname
    leader_host = raw_control_plane.get("leaderHostId")
    leadership_state = str(leadership.get("state") or "unknown")
    if leadership_state == "active" and active_host == leader_host:
        control_role = "leader"
    elif leader_host and active_host != leader_host:
        control_role = "standby"
    else:
        control_role = "unknown"
    witness_status = (
        "healthy"
        if leadership_state == "active" and leadership.get("lastVerifiedAt")
        else "degraded"
        if leadership_state in {"fenced", "recovery_hold"}
        else "unknown"
    )
    raw_healing = dict(status_result.get("healing") or {})
    finding_details = list(raw_healing.get("findingDetails") or [])
    repair_receipts = list(raw_healing.get("repairReceipts") or [])
    normalized_alarms = []
    for index, alarm_value in enumerate(status_result.get("alarms") or []):
        alarm = dict(alarm_value or {})
        payload = dict(alarm.get("payload") or {})
        raw_status = str(alarm.get("status") or "active")
        alarm_status = (
            "acknowledged"
            if raw_status == "acknowledged"
            else "resolved"
            if raw_status in {"resolved", "cancelled"}
            else "active"
        )
        normalized_alarms.append(
            {
                "id": str(
                    alarm.get("id")
                    or alarm.get("code")
                    or alarm.get("incidentKey")
                    or f"alarm-{index}"
                ),
                "severity": str(alarm.get("severity") or "warning"),
                "status": alarm_status,
                "message": str(
                    alarm.get("message")
                    or alarm.get("summary")
                    or payload.get("summary")
                    or alarm.get("code")
                    or "Execution Fabric alarm"
                ),
                "source": str(
                    alarm.get("source")
                    or payload.get("source")
                    or alarm.get("code")
                    or "execution_fabric"
                ),
                "occurred_at": alarm.get("updatedAt")
                or alarm.get("createdAt")
                or status_result.get("sampledAt"),
                "dedupe_key": alarm.get("incidentKey") or alarm.get("code"),
                "revision": alarm.get("revision"),
                "details": payload.get("details") or alarm.get("statuses") or {},
            }
        )
    return {
        "schema_version": REMOTE_SNAPSHOT_SCHEMA,
        "captured_at": status_result.get("sampledAt") or _utc_now(),
        "root": str(os_root),
        "queue_mode": "execution_fabric",
        "transport": remote.settings.public(),
        "consistency": "remote_api_snapshot",
        "queues": projected_queues,
        "workers": workers,
        "tasks": tasks,
        "running_tasks": [row for row in tasks if row.get("status") == "running"],
        "requested_task": requested_task,
        "summary": {
            "queue_depth": sum(int(row.get("queued") or 0) for row in queues),
            "queued": sum(int(row.get("queued") or 0) for row in queues),
            "running": sum(int(row.get("running") or 0) for row in queues),
            "succeeded": sum(int(row.get("succeeded") or 0) for row in queues),
            "done": succeeded,
            "cancelled": sum(int(row.get("cancelled") or 0) for row in queues),
            "approval_needed": 0,
            "failed": sum(int(row.get("failed") or 0) for row in queues),
            "dead_lettered": dead_lettered,
            "dead_letter": dead_lettered,
            "failed_last_hour": failed_last_hour,
            "registered_workers": len(workers),
            "historical_worker_records": sum(
                len(row.get("sessionHistory") or []) for row in raw_workers
            ),
            "active_workers": sum(1 for row in workers if row.get("status") == "online"),
            "live_worker_count": sum(1 for row in workers if row.get("status") == "online"),
            "unhealthy_worker_count": offline_workers,
            "unhealthy_workers": offline_workers,
            "retrying": retrying,
            "delayed_retries": delayed_retries,
            "oldest_wait_seconds": oldest_wait_seconds,
            "stale_queued": 0,
            "expired_running_leases": 0,
            "reserved_interactive_slots": int(
                admission.get("reserved_interactive_slots") or 0
            ),
            "max_interactive_running": int(
                admission.get("max_interactive_running") or 1
            ),
            "total_records": sum(
                int(row.get(field) or 0)
                for row in queues
                for field in (
                    "queued",
                    "running",
                    "succeeded",
                    "failed",
                    "deadLettered",
                    "cancelled",
                )
            ),
            "status_counts": status_counts,
        },
        "control_plane": {
            "transport": "remote",
            "active_host": active_host,
            "leader_host": leader_host,
            "role": control_role,
            "epoch": raw_control_plane.get("fabricEpoch"),
            "failover_state": leadership_state,
            "last_transition_at": leadership.get("lastVerifiedAt"),
            "witness_status": witness_status,
            "leader_lease_expires_at": raw_control_plane.get(
                "leaderLeaseExpiresAt"
            ),
            "leadership_receipt_id": raw_control_plane.get(
                "leadershipReceiptId"
            )
            or leadership.get("receiptId"),
            "leadership_fence_digest": raw_control_plane.get(
                "leadershipFenceDigest"
            ),
            "recovery_hold_until": raw_control_plane.get(
                "leaderRecoveryHoldUntil"
            )
            or leadership.get("recoveryHoldUntil"),
            "leadership_proof_expires_at": leadership.get("proofExpiresAt"),
            "last_error": leadership.get("lastError"),
            "database_policy_fingerprint": raw_control_plane.get(
                "databasePolicyFingerprint"
            ),
            "event_sequence": raw_control_plane.get("eventSequence"),
        },
        "healing": raw_healing
        or {"status": "unknown", "repairs": 0, "failures": 0},
        "findings": finding_details,
        "repair_receipts": repair_receipts,
        "alarms": normalized_alarms,
        "config": status_result.get("config") or {},
        "effects": status_result.get("effects") or {},
        "role_health": list(status_result.get("roleHealth") or []),
        "recent_run_reports": recent_run_reports,
    }
