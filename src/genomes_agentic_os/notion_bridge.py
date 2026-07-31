"""Versioned subprocess boundary for the shared TypeScript Notion port.

Credentials are supplied only to the child process. Mutations also carry an
exact workspace and parent identity guard; provider bodies and token values
never cross this boundary.
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
# Local provider-ready platform revision. Replace with the provider-read merge
# SHA before publication of the OS cutover.
REVIEWED_PLATFORM_BRIDGE_REVISION = "ddbf14a08e62a049bf641ce86dfc8ef7d29580ff"
DEFAULT_WORKSPACE = "Genome's Notion"
_AUTH_KEY = "GENOMES_NOTION_PAT"
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
    }
)


class NotionBridgeError(RuntimeError):
    """A stable, safe failure returned by the Notion bridge."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


BridgeRunner = Callable[..., subprocess.CompletedProcess[str]]


def command_from_environment(
    environ: Mapping[str, str] | None = None,
) -> list[str] | None:
    values = os.environ if environ is None else environ
    value = values.get("GENOMES_NOTION_BRIDGE_COMMAND", "").strip()
    if not value:
        return None
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise NotionBridgeError(
            "CONFIGURATION_ERROR", "Notion bridge command is invalid"
        ) from exc
    if not command:
        raise NotionBridgeError("CONFIGURATION_ERROR", "Notion bridge command is empty")
    return command


def auth_from_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if environ is None else environ
    token = values.get(_AUTH_KEY, "").strip()
    if not token:
        raise NotionBridgeError(
            "CONFIGURATION_ERROR", "GENOMES_NOTION_PAT is required"
        )
    return {_AUTH_KEY: token}


def identity_from_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    values = os.environ if environ is None else environ
    parent_page_id = values.get("GENOMES_NOTION_PARENT_PAGE_ID", "").strip()
    if not parent_page_id:
        return None
    identity = {
        "workspaceName": values.get("GENOMES_NOTION_WORKSPACE", "").strip()
        or DEFAULT_WORKSPACE,
        "parentPageId": parent_page_id,
    }
    bot_id = values.get("GENOMES_NOTION_BOT_ID", "").strip()
    if bot_id:
        identity["botId"] = bot_id
    return identity


def call_notion_bridge(
    command: Sequence[str],
    operation: str,
    args: Mapping[str, Any],
    *,
    auth: Mapping[str, str],
    identity: Mapping[str, str] | None = None,
    runner: BridgeRunner = subprocess.run,
    timeout: float = 30,
) -> Any:
    if not command:
        raise NotionBridgeError(
            "BRIDGE_UNCONFIGURED", "Notion bridge command is not configured"
        )
    supplied = {_AUTH_KEY: str(auth.get(_AUTH_KEY) or "").strip()}
    auth_from_environment(supplied)
    payload: dict[str, Any] = {
        "version": BRIDGE_VERSION,
        "operation": operation,
        "args": dict(args),
    }
    if identity is not None:
        payload["identity"] = dict(identity)
    child_env = {
        key: os.environ[key] for key in _INHERITED_ENV_KEYS if os.environ.get(key)
    }
    child_env.update(supplied)
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
        raise NotionBridgeError(
            "BRIDGE_UNAVAILABLE", "Notion bridge could not be executed"
        ) from exc
    if completed.returncode != 0:
        raise NotionBridgeError("BRIDGE_FAILED", "Notion bridge exited unsuccessfully")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Notion bridge returned invalid JSON"
        ) from exc
    if not isinstance(response, dict) or response.get("version") != BRIDGE_VERSION:
        raise NotionBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Notion bridge returned an unsupported response"
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
        raise NotionBridgeError(code, "Notion bridge operation failed", status=status)
    return response.get("result")


@dataclass(frozen=True)
class NotionBridgeClient:
    command: Sequence[str]
    auth: Mapping[str, str]
    identity: Mapping[str, str] | None = None
    runner: BridgeRunner = subprocess.run
    timeout: float = 30

    def request(
        self,
        operation: str,
        args: Mapping[str, Any],
        *,
        mutation: bool = False,
        identity: Mapping[str, str] | None = None,
    ) -> Any:
        guard = identity or self.identity
        if mutation and guard is None:
            raise NotionBridgeError(
                "IDENTITY_MISMATCH",
                "Notion mutation requires an exact workspace and parent identity",
            )
        return call_notion_bridge(
            self.command,
            operation,
            args,
            auth=self.auth,
            identity=guard,
            runner=self.runner,
            timeout=self.timeout,
        )


def client_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    token: str | None = None,
) -> NotionBridgeClient:
    values = os.environ if environ is None else environ
    command = command_from_environment(values)
    if not command:
        raise NotionBridgeError(
            "BRIDGE_UNCONFIGURED", "Notion bridge command is not configured"
        )
    auth = {_AUTH_KEY: token.strip()} if token and token.strip() else auth_from_environment(values)
    return NotionBridgeClient(command, auth, identity_from_environment(values))
