"""Versioned subprocess boundary for the shared TypeScript Linear port."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BRIDGE_VERSION = 1
REVIEWED_PLATFORM_BRIDGE_REVISION = "9a4e34fb3b6120524877e117ac201ec0b46337eb"
_AUTH_KEYS = ("LINEAR_TOKEN", "LINEAR_API_KEY", "LINEAR_API_TOKEN")
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
        "MUTATION_REJECTED",
        "NETWORK_ERROR",
        "NOT_FOUND",
        "PERMISSION_ERROR",
        "PROVIDER_ERROR",
        "RATE_LIMITED",
        "TIMEOUT",
        "USAGE_LIMITED",
    }
)


class LinearBridgeError(RuntimeError):
    """A safe, structured failure returned by the Linear bridge."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


BridgeRunner = Callable[..., subprocess.CompletedProcess[str]]


def command_from_environment(
    environ: Mapping[str, str] | None = None,
) -> list[str] | None:
    values = os.environ if environ is None else environ
    value = values.get("GENOMES_LINEAR_BRIDGE_COMMAND", "").strip()
    if not value:
        return None
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise LinearBridgeError(
            "CONFIGURATION_ERROR", "Linear bridge command is invalid"
        ) from exc
    if not command:
        raise LinearBridgeError("CONFIGURATION_ERROR", "Linear bridge command is empty")
    return command


def auth_from_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if environ is None else environ
    supplied = {
        key: values.get(key, "").strip()
        for key in _AUTH_KEYS
        if values.get(key, "").strip()
    }
    if len(supplied) != 1:
        raise LinearBridgeError(
            "CONFIGURATION_ERROR",
            "Exactly one Linear token environment variable is required",
        )
    return supplied


def call_linear_bridge(
    command: Sequence[str],
    operation: str,
    args: Mapping[str, Any],
    *,
    auth: Mapping[str, str],
    runner: BridgeRunner = subprocess.run,
    timeout: float = 30,
) -> Any:
    if not command:
        raise LinearBridgeError(
            "BRIDGE_UNCONFIGURED", "Linear bridge command is not configured"
        )
    supplied = {key: value for key, value in auth.items() if key in _AUTH_KEYS and value}
    auth_from_environment(supplied)
    payload = {"version": BRIDGE_VERSION, "operation": operation, "args": dict(args)}
    child_env = {
        key: os.environ[key] for key in _INHERITED_ENV_KEYS if os.environ.get(key)
    }
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
        raise LinearBridgeError(
            "BRIDGE_UNAVAILABLE", "Linear bridge could not be executed"
        ) from exc
    if completed.returncode != 0:
        raise LinearBridgeError("BRIDGE_FAILED", "Linear bridge exited unsuccessfully")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LinearBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Linear bridge returned invalid JSON"
        ) from exc
    if not isinstance(response, dict) or response.get("version") != BRIDGE_VERSION:
        raise LinearBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Linear bridge returned an unsupported response"
        )
    if response.get("ok") is not True:
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        provider_code = str(error.get("code") or "")
        code = provider_code if provider_code in _BRIDGE_ERROR_CODES else "BRIDGE_OPERATION_FAILED"
        status = error.get("status") if isinstance(error.get("status"), int) else None
        raise LinearBridgeError(code, "Linear bridge operation failed", status=status)
    return response.get("result")


@dataclass(frozen=True)
class LinearBridgeClient:
    command: Sequence[str]
    auth: Mapping[str, str]
    runner: BridgeRunner = subprocess.run
    timeout: float = 30

    def request(self, operation: str, args: Mapping[str, Any]) -> Any:
        return call_linear_bridge(
            self.command,
            operation,
            args,
            auth=self.auth,
            runner=self.runner,
            timeout=self.timeout,
        )


def client_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    token: str | None = None,
    token_env: str = "LINEAR_TOKEN",
) -> LinearBridgeClient:
    values = os.environ if environ is None else environ
    command = command_from_environment(values)
    if not command:
        raise LinearBridgeError(
            "BRIDGE_UNCONFIGURED", "Linear bridge command is not configured"
        )
    supplied_token = token.strip() if token and token.strip() else ""
    if token_env not in _AUTH_KEYS:
        supplied_token = supplied_token or values.get(token_env, "").strip()
        if not supplied_token:
            raise LinearBridgeError(
                "CONFIGURATION_ERROR",
                f"Configured Linear token environment variable {token_env} is missing",
            )
        auth = {"LINEAR_TOKEN": supplied_token}
    else:
        auth = {token_env: supplied_token} if supplied_token else auth_from_environment(values)
    return LinearBridgeClient(command, auth)
