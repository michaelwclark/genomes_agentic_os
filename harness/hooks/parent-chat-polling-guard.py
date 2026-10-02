#!/usr/bin/env python3
"""Block observer-only recurring chat wakeups without executing wrapper code.

This is a narrow PreToolUse guard, not a JavaScript interpreter or authorization
engine. Direct automation arguments and literal calls in functions.exec are
supported. Unresolved automation references require a direct, complete call.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from typing import Any


AUTOMATION = "automation_update"
MUTATIONS = {"create", "suggested_create", "update", "suggested_update"}
MAINTENANCE = {"view", "delete", "pause", "remove"}
WRAPPERS = {"exec", "functions.exec", "functions_exec"}
GUIDANCE = (
    "Use a background watcher or worker that writes durable state and delivers "
    "one actionable/terminal event. A silent recurring parent-chat heartbeat "
    "still consumes conversation context. Do not create a cron workaround."
)
UNRESOLVED = (
    "Cannot statically inspect this automation mutation. Use a direct "
    "automation_update call or a literal argument object containing mode, kind, "
    "status, prompt, and rrule. Literal view/delete or status=PAUSED calls remain allowed."
)
TOKEN = re.compile(
    r"(?P<space>\s+|//[^\n]*|/\*[\s\S]*?\*/)"
    r"|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)"
    r"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<identifier>[A-Za-z_$][\w$]*)|(?P<symbol>.)",
    re.DOTALL,
)


class Unresolved(ValueError):
    """A value would require evaluating JavaScript."""


def string_value(raw: str) -> str:
    if raw.startswith("`"):
        if "${" in raw:
            raise Unresolved("template interpolation")
        return raw[1:-1]
    try:
        result = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise Unresolved("string escape") from exc
    if not isinstance(result, str):
        raise Unresolved("string value")
    return result


def literal(tokens: list[tuple[str, str]], index: int) -> tuple[Any, int]:
    if index >= len(tokens):
        raise Unresolved("missing value")
    kind, value = tokens[index]
    if kind == "string":
        return string_value(value), index + 1
    if kind == "number":
        return json.loads(value), index + 1
    if value in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[value], index + 1
    if value not in ("{", "["):
        raise Unresolved("nonliteral value")
    result: Any = {} if value == "{" else []
    end = "}" if value == "{" else "]"
    index += 1
    while index < len(tokens) and tokens[index][1] != end:
        key = None
        if isinstance(result, dict):
            key_kind, raw_key = tokens[index]
            if key_kind not in ("identifier", "string"):
                raise Unresolved("computed object key")
            key = string_value(raw_key) if key_kind == "string" else raw_key
            index += 1
            if index >= len(tokens) or tokens[index][1] != ":" or key in result:
                raise Unresolved("shorthand or duplicate object key")
            index += 1
        item, index = literal(tokens, index)
        if isinstance(result, dict):
            result[key] = item
        else:
            result.append(item)
        if index < len(tokens) and tokens[index][1] == ",":
            index += 1
        elif index >= len(tokens) or tokens[index][1] != end:
            raise Unresolved("nonliteral expression")
    if index >= len(tokens):
        raise Unresolved("unclosed literal")
    return result, index + 1


def observer_prompt(prompt: str) -> bool:
    """Recognize routine status observation; conditional repairs do not exempt it."""
    text = prompt.lower()
    # Decisions following an observation (including conditional repair) do not
    # turn a scheduled status read into substantive scheduled work.
    primary = re.split(r"\b(?:if|when|unless|on (?:terminal|actionable|failure|success))\b", text)[0]
    substantive = re.search(
        r"\b(?:implement|refactor|write|draft|generate|produce|build|analy[sz]e|"
        r"investigate|research|fix|repair)\b", primary
    )
    # Nouns such as "the authorized PR repair" are not work instructions.
    action = re.search(
        r"(?:^|[.!?;\n]\s*|\band\s+)(?:please\s+)?"
        r"(?:implement|refactor|write|draft|generate|produce|build|analy[sz]e|"
        r"investigate|research|fix|repair)\b", primary
    )
    if substantive and action:
        observation_first = re.search(r"\b(?:read|check|watch|monitor|poll|inspect|verify|wait)\b", primary[:action.start()])
        records_status = re.search(r"\b(?:status|receipt|progress|watch.state|log|summary)\b", primary[action.start():])
        if not (observation_first and records_status):
            return False
    if re.match(r"\s*(?:please\s+)?remind (?:me|the user)\b", primary):
        return False
    observes = re.search(r"\b(?:watch|monitor|poll|check|read|inspect|wait|verify|validate|validation|follow.up)\b", text)
    target = re.search(
        r"\b(?:pr\s*#?\s*\d+|pull request|ci|checks?|jobs?|builds?|tests?|"
        r"watcher|watch.state|status|pending|completion|terminal|validation)\b", text
    )
    return bool(observes and target)


def inspect_arguments(args: Any) -> str | None:
    if not isinstance(args, dict):
        return UNRESOLVED
    mode = str(args.get("mode", "")).lower()
    status = str(args.get("status", "")).upper()
    if mode in MAINTENANCE or status in {"PAUSED", "DISABLED", "INACTIVE"}:
        return None
    if mode not in MUTATIONS:
        return UNRESOLVED if not mode else None
    # Cosmetic updates cannot create/reactivate a watcher.
    if mode.endswith("update") and status not in {"ACTIVE", "ENABLED"} and not any(
        key in args for key in ("prompt", "rrule", "kind", "destination", "targetThreadId")
    ):
        return None
    kind = args.get("kind")
    if kind not in {"heartbeat", "cron"}:
        return UNRESOLVED
    prompt, schedule = args.get("prompt"), args.get("rrule")
    if not isinstance(prompt, str) or not isinstance(schedule, str):
        return UNRESOLVED
    # One-time followups do not constitute recurring polling.
    if re.search(r"(?:^|[;:])COUNT=1(?:;|$)", schedule, re.IGNORECASE):
        return None
    if observer_prompt(prompt):
        return "Routine recurring parent-chat polling is blocked. " + GUIDANCE
    return None


def wrapper_arguments(source: str) -> list[Any]:
    tokens = [(m.lastgroup or "", m.group()) for m in TOKEN.finditer(source) if m.lastgroup != "space"]
    calls = []
    for index, (kind, value) in enumerate(tokens):
        bracket = kind == "string" and index > 0 and tokens[index - 1][1] == "["
        if kind != "identifier" and not bracket:
            continue
        if kind == "identifier" and (index == 0 or tokens[index - 1][1] != "."):
            continue
        if bracket and AUTOMATION not in value:
            continue
        name = string_value(value) if bracket else value
        if not name.endswith(AUTOMATION):
            continue
        cursor = index + 1
        if bracket:
            if cursor >= len(tokens) or tokens[cursor][1] != "]":
                raise Unresolved("dynamic tool property")
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor][1] != "(":
            raise Unresolved("aliased automation tool")
        args, cursor = literal(tokens, cursor + 1)
        if cursor >= len(tokens) or tokens[cursor][1] != ")":
            raise Unresolved("dynamic automation arguments")
        calls.append(args)
    return calls


def denial(payload: dict[str, Any]) -> str | None:
    name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    if name.endswith(AUTOMATION):
        return inspect_arguments(tool_input)
    if name not in WRAPPERS:
        return None
    source = tool_input if isinstance(tool_input, str) else next(
        (tool_input.get(key) for key in ("code", "source", "input") if isinstance(tool_input, dict) and isinstance(tool_input.get(key), str)), ""
    )
    try:
        for args in wrapper_arguments(source):
            reason = inspect_arguments(args)
            if reason:
                return reason
    except (Unresolved, RecursionError):
        return UNRESOLVED
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    reason = denial(payload)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "parent-chat-polling-guard: " + reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
