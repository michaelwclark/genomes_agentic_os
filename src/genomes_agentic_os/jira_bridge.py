"""Versioned subprocess boundary for the shared TypeScript Jira port.

The Agentic OS package is Python while ``@genomes/jira`` is an ESM package.
This module keeps that boundary explicit: one JSON request and response per
process, with credentials supplied only through the child environment.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BRIDGE_VERSION = 1
REVIEWED_PLATFORM_BRIDGE_REVISION = "576e09f5653471a221b857cea91977ab82abd581"
_AUTH_KEYS = ("JIRA_OAUTH_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN")
_INHERITED_ENV_KEYS = (
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LANG",
    "LC_ALL",
    "NODE_EXTRA_CA_CERTS",
    "NODE_OPTIONS",
    "NODE_PATH",
    "NO_PROXY",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
_BRIDGE_ERROR_CODES = frozenset(
    {
        "AMBIGUOUS_MUTATION",
        "AUTH_ERROR",
        "CONFIGURATION_ERROR",
        "CONFLICT",
        "IDENTITY_MISMATCH",
        "INTERNAL_ERROR",
        "INVALID_JSON",
        "INVALID_REQUEST",
        "NETWORK_ERROR",
        "NOT_FOUND",
        "PERMISSION_ERROR",
        "PROVIDER_ERROR",
        "RATE_LIMITED",
        "TIMEOUT",
    }
)


class JiraBridgeError(RuntimeError):
    """A safe, structured failure returned by the Jira bridge."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


BridgeRunner = Callable[..., subprocess.CompletedProcess[str]]


def command_from_environment(
    environ: Mapping[str, str] | None = None,
) -> list[str] | None:
    """Return the explicitly configured bridge command, never invoking a shell."""
    values = os.environ if environ is None else environ
    value = values.get("GENOMES_JIRA_BRIDGE_COMMAND", "").strip()
    if not value:
        return None
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise JiraBridgeError(
            "CONFIGURATION_ERROR", "Jira bridge command is invalid"
        ) from exc
    if not command:
        raise JiraBridgeError("CONFIGURATION_ERROR", "Jira bridge command is empty")
    return command


def auth_from_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return exactly one complete bridge auth mode without exposing values."""
    values = os.environ if environ is None else environ
    bearer = values.get("JIRA_OAUTH_TOKEN", "").strip()
    email = values.get("JIRA_EMAIL", "").strip()
    api_token = values.get("JIRA_API_TOKEN", "").strip()
    if bearer and (email or api_token):
        raise JiraBridgeError(
            "CONFIGURATION_ERROR", "Jira authentication mode is ambiguous"
        )
    if bearer:
        return {"JIRA_OAUTH_TOKEN": bearer}
    if email and api_token:
        return {"JIRA_EMAIL": email, "JIRA_API_TOKEN": api_token}
    raise JiraBridgeError(
        "CONFIGURATION_ERROR",
        "Exactly one complete Jira bearer or email/API-token auth mode is required",
    )


def base_url_from_environment(environ: Mapping[str, str] | None = None) -> str:
    """Resolve the provider base URL appropriate for the configured auth mode."""
    values = os.environ if environ is None else environ
    if values.get("JIRA_OAUTH_TOKEN", "").strip():
        explicit = (
            values.get("ATLASSIAN_BASE_URL", "").strip()
            or values.get("JIRA_OAUTH_BASE_URL", "").strip()
        )
        if explicit:
            return explicit.rstrip("/")
        cloud_id = (
            values.get("ATLASSIAN_JIRA_CLOUDID", "").strip()
            or values.get("JIRA_CLOUD_ID", "").strip()
            or values.get("ATLASSIAN_CLOUD_ID", "").strip()
        )
        if cloud_id:
            return f"https://api.atlassian.com/ex/jira/{cloud_id}"
        raise JiraBridgeError(
            "CONFIGURATION_ERROR",
            "Jira bearer authentication requires an Atlassian gateway base URL or cloud ID",
        )
    base_url = values.get("JIRA_BASE_URL", "").strip()
    if not base_url:
        raise JiraBridgeError(
            "CONFIGURATION_ERROR", "Jira base URL is not configured"
        )
    return base_url.rstrip("/")


def call_jira_bridge(
    command: Sequence[str],
    operation: str,
    args: Mapping[str, Any],
    *,
    base_url: str,
    auth: Mapping[str, str],
    runner: BridgeRunner = subprocess.run,
    timeout: float = 30,
) -> Any:
    """Execute one shared Jira operation and return its JSON-safe result."""
    if not command:
        raise JiraBridgeError(
            "BRIDGE_UNCONFIGURED", "Jira bridge command is not configured"
        )
    if not base_url.strip():
        raise JiraBridgeError("CONFIGURATION_ERROR", "Jira base URL is not configured")
    supplied = {
        key: value for key, value in auth.items() if key in _AUTH_KEYS and value
    }
    auth_from_environment(supplied)
    payload = {"version": BRIDGE_VERSION, "operation": operation, "args": dict(args)}
    child_env = {
        key: os.environ[key] for key in _INHERITED_ENV_KEYS if os.environ.get(key)
    }
    child_env["JIRA_BASE_URL"] = base_url.rstrip("/")
    child_env.update(supplied)
    for key in _AUTH_KEYS:
        if key not in supplied:
            child_env.pop(key, None)
    try:
        completed = runner(
            list(command),
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=child_env,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JiraBridgeError(
            "BRIDGE_UNAVAILABLE", "Jira bridge could not be executed"
        ) from exc
    if completed.returncode != 0:
        raise JiraBridgeError("BRIDGE_FAILED", "Jira bridge exited unsuccessfully")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise JiraBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Jira bridge returned invalid JSON"
        ) from exc
    if not isinstance(response, dict) or response.get("version") != BRIDGE_VERSION:
        raise JiraBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Jira bridge returned an unsupported response"
        )
    if response.get("ok") is not True:
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        provider_code = str(error.get("code") or "")
        code = (
            provider_code
            if provider_code in _BRIDGE_ERROR_CODES
            else "BRIDGE_OPERATION_FAILED"
        )
        status = error.get("status") if isinstance(error.get("status"), int) else None
        raise JiraBridgeError(code, "Jira bridge operation failed", status=status)
    return response.get("result")


@dataclass(frozen=True)
class JiraBridgeClient:
    """Injected Jira bridge client used by CLI and provider adapters."""

    command: Sequence[str]
    base_url: str
    auth: Mapping[str, str]
    runner: BridgeRunner = subprocess.run
    timeout: float = 30

    def request(self, operation: str, args: Mapping[str, Any]) -> Any:
        return call_jira_bridge(
            self.command,
            operation,
            args,
            base_url=self.base_url,
            auth=self.auth,
            runner=self.runner,
            timeout=self.timeout,
        )


def adf_paragraph(text: str) -> dict[str, Any]:
    """Return the legacy plain-text comment as native ADF without flattening it."""
    return {
        "version": 1,
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }
