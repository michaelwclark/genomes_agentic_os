"""Live source adapters for connected-source polling (offline-verifiable subset).

Architecture
------------
Each adapter (GitHub, Jira, Slack) exposes a single ``fetch_*`` function that:
  - resolves the credential from the env var named in the connected-system config
  - calls its selected provider transport via an injectable boundary so tests
    never touch the network; GitHub issues and pull requests require the shared
    platform bridge configured by ``GENOMES_GITHUB_BRIDGE_COMMAND``
  - returns a list of normalised item dicts (provider-id-keyed)
  - falls back to an empty list with a ``dry_run_reason`` marker when the env var
    is absent — identical observable output to the existing registry dry-run path

Secrets contract
----------------
  - The connected-system config holds env var *names* in ``credential_refs.env_vars``
    (or optionally a watch-source–level ``token_env`` field).  Values are resolved
    at poll time from ``os.environ``; they are never stored in any registry file.
  - A token-shaped-value guard runs before any network call.  If the caller
    mistakenly passes a token *value* inside the config dict, the poll is refused
    with a ``SECRETS_IN_CONFIG`` finding instead of crashing or leaking.
  - Fetched payloads are trimmed to summary fields before being returned — raw
    bodies (including any echoed auth material) are discarded.

Injectable Slack transport
--------------------------
Pass ``fetcher=<callable>`` to override the Slack HTTP transport in tests::

    def fake_fetcher(req):
        return FakeResponse(json.dumps(FIXTURE).encode())

    result = fetch_slack_messages("C0123", token="tok_fake", fetcher=fake_fetcher)

Token-shaped value heuristic
-----------------------------
Strings are considered token-shaped when they satisfy the ``looks_like_token``
predicate: length ≥ 20, no whitespace, and either contains ``_`` or looks like a
long alphanumeric sequence.  This is a best-effort guard — it catches the common
"pasted a real token into YAML" mistake, not adversarial bypass.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from .github_bridge import (
    GitHubBridgeError,
    command_from_environment as github_command_from_environment,
    list_issues,
    list_pull_requests,
)
from .jira_bridge import (
    JiraBridgeClient,
    JiraBridgeError,
    auth_from_environment as jira_auth_from_environment,
    base_url_from_environment as jira_base_url_from_environment,
    command_from_environment as jira_command_from_environment,
)

# ---------------------------------------------------------------------------
# Token-shaped value guard
# ---------------------------------------------------------------------------

# Pattern: ≥20 chars, no whitespace.  Github tokens start with "ghp_" / "github_pat_"
# etc; Slack tokens start with "xoxb-" / "xoxp-" etc.  We catch any long opaque
# string that doesn't look like a plain env var name or file path.
_KNOWN_TOKEN_PREFIXES: tuple[str, ...] = (
    "ghp_", "github_pat_", "ghs_",
    "xoxb-", "xoxp-", "xapp-", "xoxe-",
    "sk-", "tok_", "Bearer ",
)

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-\.]{20,}$")


def looks_like_token(value: Any) -> bool:
    """Return True if *value* looks like a credential value, not a variable name.

    Env var names are UPPER_SNAKE_CASE and typically short (e.g. GITHUB_TOKEN).
    Token values are long opaque strings.  We refuse to poll when this fires.
    """
    if not isinstance(value, str):
        return False
    # Short strings and strings with spaces/slashes are not tokens
    if len(value) < 20 or " " in value or "/" in value or "\\" in value:
        return False
    # Known prefixes used by real tokens
    for prefix in _KNOWN_TOKEN_PREFIXES:
        if value.startswith(prefix):
            return True
    # Long alphanumeric+underscore+hyphen sequences that look like secrets
    return bool(_TOKEN_PATTERN.match(value))


def check_config_for_secrets(config: dict[str, Any]) -> list[str]:
    """Scan a flat config dict for token-shaped values; return a list of offending keys."""
    violations: list[str] = []
    for key, value in config.items():
        if looks_like_token(value):
            violations.append(key)
    return violations


# ---------------------------------------------------------------------------
# Simple HTTP helper
# ---------------------------------------------------------------------------

def _default_fetcher(req: urllib.request.Request) -> Any:
    """Default HTTP transport — wraps urllib.request.urlopen."""
    return urllib.request.urlopen(req, timeout=15)  # noqa: S310


def _get_json(
    url: str,
    headers: dict[str, str],
    fetcher: Callable[[urllib.request.Request], Any],
) -> Any:
    """Fetch *url* with *headers*; parse and return JSON body.

    Raises ``urllib.error.HTTPError`` / ``urllib.error.URLError`` on transport
    failures.  The caller is responsible for handling these.
    """
    req = urllib.request.Request(url, headers=headers)
    response = fetcher(req)
    body = response.read() if hasattr(response, "read") else response
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    return json.loads(body)


# ---------------------------------------------------------------------------
# Credential resolution helpers
# ---------------------------------------------------------------------------

def _resolve_token(
    system_config: dict[str, Any],
    source_config: dict[str, Any],
    preferred_env_names: list[str],
) -> tuple[str | None, str | None]:
    """Return ``(token_value, env_var_name_used)`` or ``(None, None)``.

    Resolution order:
    1. ``source_config["token_env"]`` — explicit override on the watch source
    2. First match in ``system_config["credential_refs"]["env_vars"]`` that
       appears in *preferred_env_names*
    3. First non-empty env var in ``system_config["credential_refs"]["env_vars"]``
    """
    # 1. Explicit override on the watch source
    explicit = source_config.get("token_env")
    if explicit:
        val = os.environ.get(explicit)
        if val:
            return val, explicit

    # 2. Walk system credential_refs
    env_vars: list[str] = (system_config.get("credential_refs") or {}).get("env_vars") or []

    # Preferred names first
    for name in preferred_env_names:
        if name in env_vars:
            val = os.environ.get(name)
            if val:
                return val, name

    # Then any listed env var
    for name in env_vars:
        val = os.environ.get(name)
        if val:
            return val, name

    return None, None


# ---------------------------------------------------------------------------
# GitHub adapter
# ---------------------------------------------------------------------------

# Fields we keep from each PR / issue item — never store full raw payloads
_GITHUB_PR_KEEP = {"id", "number", "title", "state", "created_at", "updated_at",
                   "merged_at", "closed_at", "html_url", "user", "head", "base",
                   "draft", "labels", "requested_reviewers", "requested_teams"}

def _trim_github_item(item: dict[str, Any], keep: frozenset[str]) -> dict[str, Any]:
    """Return a trimmed copy of *item* with only the allowed keys."""
    trimmed: dict[str, Any] = {}
    for key in keep:
        if key in item:
            val = item[key]
            # For nested objects (user, head, base) keep only non-sensitive sub-keys
            if isinstance(val, dict):
                if key == "user":
                    val = {"login": val.get("login"), "id": val.get("id")}
                elif key in ("head", "base"):
                    val = {"ref": val.get("ref"), "sha": val.get("sha")}
                elif key == "labels":
                    # labels is a list, handled below
                    pass
            if isinstance(val, list) and key == "labels":
                val = [lbl.get("name") for lbl in val if isinstance(lbl, dict)]
            if isinstance(val, list) and key in ("requested_reviewers", "assignees"):
                val = [r.get("login") for r in val if isinstance(r, dict)]
            if isinstance(val, list) and key == "requested_teams":
                val = [t.get("slug") for t in val if isinstance(t, dict)]
            trimmed[key] = val
    return trimmed


def _bridge_pull_request_to_source_item(item: dict[str, Any]) -> dict[str, Any]:
    """Adapt the shared port's PR vocabulary to the source-watch event shape.

    The source-watch registry predates the shared GitHub port, so its persisted
    field names are intentionally retained here.  This is a narrow adapter, not
    a second GitHub client: the bridge owns provider calls and normalization.
    The bridge exposes GitHub's database id and requested reviewer/team names in
    its JSON-safe vocabulary; map them back to the legacy keys so downstream
    consumers receive the same shape they received from the direct REST client.
    """
    labels = item.get("labels") if isinstance(item.get("labels"), list) else []
    return {
        "id": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title", ""),
        "state": "closed" if item.get("state") == "merged" else item.get("state", "open"),
        "created_at": item.get("openedAt", ""),
        "updated_at": item.get("updatedAt", ""),
        "merged_at": item.get("mergedAt"),
        "closed_at": item.get("closedAt"),
        "html_url": item.get("url", ""),
        "user": {"login": item.get("author", "")},
        "head": {"ref": item.get("headBranch", ""), "sha": item.get("headSha", "")},
        "base": {"ref": item.get("baseBranch", "")},
        "draft": bool(item.get("draft", False)),
        "labels": [{"name": label} for label in labels if isinstance(label, str)],
        "requested_reviewers": [
            {"login": reviewer}
            for reviewer in item.get("requestedReviewers", [])
            if isinstance(reviewer, str)
        ],
        "requested_teams": [
            {"slug": team}
            for team in item.get("requestedTeams", [])
            if isinstance(team, str)
        ],
    }


def _bridge_issue_to_source_item(
    item: dict[str, Any],
    *,
    owner: str,
    repo: str,
) -> dict[str, Any]:
    """Translate shared-port issue vocabulary to the established watch shape."""
    author = item.get("author")
    labels = item.get("labels")
    assignees = item.get("assignees")
    pull_request = item.get("pullRequest")
    if (
        not isinstance(labels, list)
        or not isinstance(assignees, list)
        or not isinstance(pull_request, bool)
    ):
        raise GitHubBridgeError(
            "BRIDGE_INVALID_RESPONSE",
            "GitHub bridge returned an invalid issue item",
        )
    mapped: dict[str, Any] = {
        "id": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "created_at": item.get("openedAt"),
        "updated_at": item.get("updatedAt"),
        "closed_at": item.get("closedAt"),
        "html_url": item.get("url"),
        "user": (
            {"login": author.get("login"), "id": author.get("id")}
            if isinstance(author, dict)
            else None
        ),
        "labels": [
            {"name": label}
            for label in labels
            if isinstance(label, str)
        ],
        "assignees": [
            {"login": assignee}
            for assignee in assignees
            if isinstance(assignee, str)
        ],
    }
    if pull_request:
        # Preserve the legacy marker's inner ``url`` field as well as its
        # truthiness for consumers that read more than key presence.
        mapped["pull_request"] = {
            "url": f"https://api.github.com/repos/{owner}/{repo}/pulls/{item.get('number')}"
        }
    return mapped


def fetch_github_events(
    owner: str,
    repo: str,
    *,
    token: str,
    event_types: list[str] | None = None,
    since: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Fetch recent PR / issue events from GitHub for ``owner/repo``.

    Parameters
    ----------
    owner:
        GitHub org or username.
    repo:
        Repository name.
    token:
        Bearer token (must not be token-shaped in config — resolved from env).
    event_types:
        Subset of ``["pull_request", "issues", "check_suite"]``.  Defaults to
        ``["pull_request", "issues"]``.
    since:
        ISO-8601 timestamp; only items updated at or after this time are returned.
        Passed to the platform issue-listing port for incremental filtering.
    fetcher:
        Retained for caller compatibility; GitHub polling does not use direct
        HTTP transport. Both issue and pull-request reads use the platform port.

    Returns
    -------
    list[dict]
        Trimmed event summaries.  Each item has a ``_provider`` key set to
        ``"github"`` and ``_event_type`` derived from the API endpoint.
    """
    if event_types is None:
        event_types = ["pull_request", "issues"]

    items: list[dict[str, Any]] = []

    want_prs = any(t in event_types for t in ("pull_request",))
    want_issues = any(t in event_types for t in ("issues", "issue"))

    bridge_command = github_command_from_environment()
    if (want_prs or want_issues) and not bridge_command:
        raise GitHubBridgeError(
            "BRIDGE_UNCONFIGURED",
            "GitHub polling requires the configured platform GitHub bridge",
        )

    if want_issues:
        issue_data = [
            _bridge_issue_to_source_item(item, owner=owner, repo=repo)
            for item in list_issues(
                bridge_command or [],
                owner=owner,
                repo=repo,
                token=token,
                state="all",
                since=since,
                limit=30,
            )
        ]
        for item in issue_data:
            if want_prs and item.get("pull_request") is not None:
                continue
            item["_provider"] = "github"
            item["_event_type"] = "issue"
            item["_idempotency_key"] = f"github:issue:{owner}:{repo}:{item.get('number')}"
            items.append(item)

    if want_prs:
        data: Any = [
            _bridge_pull_request_to_source_item(item)
            for item in list_pull_requests(
                bridge_command or [],
                owner=owner,
                repo=repo,
                token=token,
                state="all",
                limit=30,
            )
        ]
        for item in data if isinstance(data, list) else []:
            if since and item.get("updated_at", "") < since:
                continue
            trimmed = _trim_github_item(item, frozenset(_GITHUB_PR_KEEP))
            trimmed["_provider"] = "github"
            trimmed["_event_type"] = "pull_request"
            trimmed["_idempotency_key"] = f"github:pr:{owner}:{repo}:{item.get('number')}"
            items.append(trimmed)

    return items


def poll_github_source(
    source: dict[str, Any],
    system: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> dict[str, Any]:
    """Top-level adapter entry point for a GitHub watch source.

    Returns a result dict compatible with the ``poll_watch_source`` envelope::

        {
            "ok": True,
            "live": True,
            "items": [...],             # trimmed event summaries
            "item_count": N,
            "provider": "platform_github_port",
            "dry_run_reason": None,     # or string when no creds
        }

    When no token is available the result has ``live=False`` and
    ``dry_run_reason`` set; callers fall back to the existing registry dry-run
    path.
    """
    external_ref = source.get("external_ref") or {}

    # --- secrets guard ---
    violations = check_config_for_secrets(external_ref)
    violations += check_config_for_secrets({k: v for k, v in source.items()
                                            if isinstance(v, str)})
    if violations:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_github_port",
            "findings": [{
                "severity": "blocker",
                "code": "SECRETS_IN_CONFIG",
                "message": f"token-shaped values found in config keys: {violations}; "
                           "use credential_refs.env_vars to reference env var NAMES only",
            }],
        }

    token, env_name = _resolve_token(system, source, preferred_env_names=["GITHUB_TOKEN"])
    if not token:
        return {
            "ok": True,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_github_port",
            "dry_run_reason": (
                "no GitHub token available — set the env var named in "
                "credential_refs.env_vars (e.g. GITHUB_TOKEN) to enable live polling"
            ),
        }

    owner = external_ref.get("owner", "")
    repo = external_ref.get("repo", "")
    event_types = external_ref.get("event_types") or ["pull_request", "issues"]
    if isinstance(event_types, str):
        event_types = [event_types]

    # Cursor-based since filtering
    since: str | None = source.get("_cursor_since")  # injected by caller when advancing

    try:
        want_prs = any(event_type == "pull_request" for event_type in event_types)
        want_issues = any(event_type in ("issues", "issue") for event_type in event_types)
        requested_event_types: list[str] = []
        if want_issues:
            requested_event_types.append("issues")
        if want_prs:
            requested_event_types.append("pull_request")
        items = fetch_github_events(
            owner,
            repo,
            token=token,
            event_types=requested_event_types,
            since=since,
            fetcher=fetcher,
        )
        return {
            "ok": True,
            "live": True,
            "items": items,
            "item_count": len(items),
            "provider": "platform_github_port",
            "credential_env": env_name,
            "dry_run_reason": None,
        }
    except GitHubBridgeError as exc:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_github_port",
            "findings": [{
                "severity": "blocker",
                "code": exc.code,
                "message": str(exc),
            }],
        }


# ---------------------------------------------------------------------------
# Jira adapter
# ---------------------------------------------------------------------------


def _jira_issue_to_source_item(issue: dict[str, Any]) -> dict[str, Any]:
    """Trim one shared-port Jira issue to the established watch event shape."""
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    project = issue.get("project") if isinstance(issue.get("project"), dict) else {}
    status = issue.get("status") if isinstance(issue.get("status"), dict) else {}
    issue_type = issue.get("issueType") if isinstance(issue.get("issueType"), dict) else {}
    return {
        "id": issue.get("id"),
        "key": issue.get("key"),
        "url": issue.get("url"),
        "summary": issue.get("summary"),
        "project_key": project.get("key"),
        "status": status.get("name"),
        "issue_type": issue_type.get("name"),
        "updated_at": fields.get("updated"),
        "labels": fields.get("labels") if isinstance(fields.get("labels"), list) else [],
        "_provider": "jira",
        "_event_type": "issue",
        "_idempotency_key": f"jira:issue:{issue.get('key')}:{fields.get('updated') or ''}",
    }


def fetch_jira_issues(
    jql: str,
    *,
    client: JiraBridgeClient,
) -> list[dict[str, Any]]:
    """Exhaust the shared Jira search port and return trimmed issue summaries."""
    page = client.request(
        "searchIssues",
        {"jql": jql, "fields": ["updated", "labels"]},
    )
    values = page.get("values") if isinstance(page, dict) else None
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise JiraBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Jira bridge returned invalid search results"
        )
    if page.get("complete") is not True:
        raise JiraBridgeError(
            "BRIDGE_INVALID_RESPONSE", "Jira bridge returned an incomplete unbounded search"
        )
    return [_jira_issue_to_source_item(item) for item in values]


def poll_jira_source(
    source: dict[str, Any],
    system: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
    client: JiraBridgeClient | None = None,
) -> dict[str, Any]:
    """Poll a Jira JQL watch through the shared bridge, never direct HTTP."""
    del fetcher
    external_ref = source.get("external_ref") or {}
    violations = check_config_for_secrets(external_ref)
    violations += check_config_for_secrets(
        {key: value for key, value in source.items() if isinstance(value, str)}
    )
    if violations:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_jira_port",
            "findings": [
                {
                    "severity": "blocker",
                    "code": "SECRETS_IN_CONFIG",
                    "message": "token-shaped Jira config values are not allowed",
                }
            ],
        }
    if client is None:
        command = jira_command_from_environment()
        if not command:
            return {
                "ok": True,
                "live": False,
                "items": [],
                "item_count": 0,
                "provider": "platform_jira_port",
                "dry_run_reason": "Jira bridge command is not configured",
            }
        try:
            auth = jira_auth_from_environment()
            base_url = jira_base_url_from_environment()
        except JiraBridgeError as exc:
            return {
                "ok": False,
                "live": False,
                "items": [],
                "item_count": 0,
                "provider": "platform_jira_port",
                "findings": [
                    {"severity": "blocker", "code": exc.code, "message": str(exc)}
                ],
            }
        client = JiraBridgeClient(command, base_url, auth)
    project = str(external_ref.get("project_key") or "").strip()
    jql = str(external_ref.get("jql") or "").strip()
    if not jql and project:
        jql = f'project = "{project}" ORDER BY updated DESC'
    if not jql:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_jira_port",
            "findings": [
                {
                    "severity": "blocker",
                    "code": "INVALID_REQUEST",
                    "message": "Jira watch requires jql or project_key",
                }
            ],
        }
    try:
        items = fetch_jira_issues(jql, client=client)
        return {
            "ok": True,
            "live": True,
            "items": items,
            "item_count": len(items),
            "provider": "platform_jira_port",
            "dry_run_reason": None,
        }
    except JiraBridgeError as exc:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "platform_jira_port",
            "findings": [
                {"severity": "blocker", "code": exc.code, "message": str(exc)}
            ],
        }


# ---------------------------------------------------------------------------
# Slack adapter
# ---------------------------------------------------------------------------

_SLACK_API_BASE = "https://slack.com/api"

# Fields we keep from each Slack message
_SLACK_MSG_KEEP = {"ts", "type", "user", "text", "thread_ts", "reply_count",
                   "reactions", "files", "subtype", "bot_id", "app_id"}

# Maximum text length stored — Slack messages can be arbitrarily long
_SLACK_TEXT_MAX = 500


def _trim_slack_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Return a trimmed copy of a Slack message dict."""
    trimmed: dict[str, Any] = {}
    for key in _SLACK_MSG_KEEP:
        if key in msg:
            val = msg[key]
            if key == "text" and isinstance(val, str):
                val = val[:_SLACK_TEXT_MAX]
            if key == "reactions" and isinstance(val, list):
                val = [{"name": r.get("name"), "count": r.get("count")} for r in val
                       if isinstance(r, dict)]
            if key == "files" and isinstance(val, list):
                # Only keep metadata, not content
                val = [{"id": f.get("id"), "name": f.get("name"),
                        "filetype": f.get("filetype")} for f in val if isinstance(f, dict)]
            trimmed[key] = val
    return trimmed


def fetch_slack_messages(
    channel_id: str,
    *,
    token: str,
    oldest: str | None = None,
    limit: int = 50,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> list[dict[str, Any]]:
    """Fetch recent messages from a Slack channel using conversations.history.

    Parameters
    ----------
    channel_id:
        Slack channel ID (e.g. ``C01234ABCD``).
    token:
        Bot token (``xoxb-...``).  Must not appear in config — resolved from env.
    oldest:
        Unix timestamp float as string; only messages after this time.
    limit:
        Max messages to fetch (default 50, capped by Slack at 1000).
    fetcher:
        Injectable HTTP transport.

    Returns
    -------
    list[dict]
        Trimmed message summaries.  Each item has ``_provider="slack"``,
        ``_event_type="message"``, and ``_idempotency_key``.
    """
    url = f"{_SLACK_API_BASE}/conversations.history"
    params = f"?channel={channel_id}&limit={limit}"
    if oldest:
        params += f"&oldest={oldest}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "genomes-agentic-os/source-watcher",
    }

    data = _get_json(url + params, headers, fetcher)
    if not isinstance(data, dict) or not data.get("ok"):
        error = data.get("error", "unknown") if isinstance(data, dict) else "invalid_response"
        raise ValueError(f"Slack API error: {error}")

    messages = data.get("messages") or []
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        trimmed = _trim_slack_message(msg)
        ts = msg.get("ts", "")
        trimmed["_provider"] = "slack"
        trimmed["_event_type"] = "message"
        trimmed["_idempotency_key"] = f"slack:message:{channel_id}:{ts}"
        result.append(trimmed)
    return result


def poll_slack_source(
    source: dict[str, Any],
    system: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> dict[str, Any]:
    """Top-level adapter entry point for a Slack watch source.

    Returns the same envelope shape as ``poll_github_source``.
    """
    external_ref = source.get("external_ref") or {}

    # --- secrets guard ---
    violations = check_config_for_secrets(external_ref)
    violations += check_config_for_secrets({k: v for k, v in source.items()
                                            if isinstance(v, str)})
    if violations:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "direct_api",
            "findings": [{
                "severity": "blocker",
                "code": "SECRETS_IN_CONFIG",
                "message": f"token-shaped values found in config keys: {violations}; "
                           "use credential_refs.env_vars to reference env var NAMES only",
            }],
        }

    # Slack token env var naming: SLACK_BOT_TOKEN is the conventional name;
    # operators may name it anything and list it in credential_refs.env_vars.
    token, env_name = _resolve_token(
        system, source,
        preferred_env_names=["SLACK_BOT_TOKEN", "SLACK_TOKEN", "COMPOSIO_SLACK_TOKEN"],
    )
    if not token:
        return {
            "ok": True,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "direct_api",
            "dry_run_reason": (
                "no Slack token available — set the env var named in "
                "credential_refs.env_vars (e.g. SLACK_BOT_TOKEN) to enable live polling"
            ),
        }

    channel_id = external_ref.get("channel_id", "")
    oldest: str | None = source.get("_cursor_since")  # injected by caller

    try:
        items = fetch_slack_messages(
            channel_id,
            token=token,
            oldest=oldest,
            fetcher=fetcher,
        )
        return {
            "ok": True,
            "live": True,
            "items": items,
            "item_count": len(items),
            "provider": "direct_api",
            "credential_env": env_name,
            "dry_run_reason": None,
        }
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "ok": False,
            "live": False,
            "items": [],
            "item_count": 0,
            "provider": "direct_api",
            "findings": [{
                "severity": "blocker",
                "code": "FETCH_ERROR",
                "message": f"Slack fetch failed: {exc}",
            }],
        }


# ---------------------------------------------------------------------------
# Dispatch table — maps system type to adapter function
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, Any] = {
    "github": poll_github_source,
    "jira": poll_jira_source,
    "slack": poll_slack_source,
}


def poll_live_source(
    source: dict[str, Any],
    system: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] = _default_fetcher,
) -> dict[str, Any] | None:
    """Dispatch to the correct live adapter for *system["system"]*.

    Returns ``None`` when no live adapter exists for the system type (i.e. the
    caller should fall back to the existing registry dry-run path).
    """
    system_type = system.get("system", "")
    adapter = _ADAPTERS.get(system_type)
    if adapter is None:
        return None
    return adapter(source, system, fetcher=fetcher)
