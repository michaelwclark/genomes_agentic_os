"""Narrow frozen-command matching shared by validation and readiness proof readers."""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
import shlex
from typing import Any, Mapping


def execution_argv(command: Mapping[str, Any], task: Mapping[str, Any] | None = None) -> tuple[list[str], dict[str, str]]:
    """Admit only receipt-bound metadata and contained output/cache controls."""
    argv = command.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return [], {}
    argv = list(argv)
    environment: dict[str, str] = {}
    overrides = command.get("environment_overrides", {})
    if not isinstance(overrides, Mapping):
        return [], {}
    assignments = list(overrides.items())
    if argv[0] == "env":
        argv = argv[1:]
        if argv and argv[0].startswith("-"):
            return [], {}  # Clearing or changing inherited execution is not a frozen annotation.
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            assignments.append(tuple(argv.pop(0).split("=", 1)))
    for key, value in assignments:
        if not isinstance(key, str) or not isinstance(value, str) or key in environment:
            return [], {}
        if key == "REVIEW_POLICY_FINGERPRINT":
            allowed = bool(re.fullmatch(r"[0-9a-f]{64}", value))
        elif key == "PYTEST_ADDOPTS":
            allowed = value == ""  # Explicitly neutralize inherited test selection.
        elif key == "PYTHONDONTWRITEBYTECODE":
            allowed = value == "1"
        elif key in {"COVERAGE_FILE", "NPM_CONFIG_CACHE"}:
            allowed = task is not None and _contained_annotation(value, task, cache_only=True)
        else:
            allowed = False
        if not allowed:
            return [], {}
        environment[key] = value
    return argv, environment


def _contained_annotation(value: str, task: Mapping[str, Any], *, cache_only: bool = False) -> bool:
    if not value:
        return False
    worktree = Path(str(task.get("worktree", {}).get("path") or ""))
    packet = Path(str(task.get("work_item") or ""))
    if not worktree.is_absolute() or not packet.is_absolute():
        return False
    path = Path(value)
    if cache_only and not path.is_absolute():
        return False
    if not path.is_absolute():
        path = worktree / path
    lexical = Path(os.path.abspath(path))
    # Outputs may not escape through an existing symlink or replace either root.
    roots = (packet / "artifacts",) if cache_only else (packet, worktree)
    return any(lexical != root and lexical.is_relative_to(root)
               and lexical.resolve().is_relative_to(root.resolve())
               for root in roots)


def _annotations(extras: list[str], task: Mapping[str, Any]) -> bool:
    index = 0
    cache_seen = False
    while index < len(extras):
        token = extras[index]
        if token == "--cov-branch" or token.startswith(("--cov=", "--cov-fail-under=", "--cov-config=")):
            # Targets, branch mode, configuration and thresholds alter the
            # gate's denominator or acceptance. Only the frozen prefix owns them.
            return False
        elif token.startswith("--basetemp="):
            if not _contained_annotation(token.split("=", 1)[1], task):
                return False
        elif token.startswith("--cov-report="):
            report = token.split("=", 1)[1]
            kind, separator, destination = report.partition(":")
            if kind not in {"term", "term-missing", "html", "xml", "json", "lcov", "annotate"}:
                return False
            if separator and not _contained_annotation(destination, task):
                return False
        elif token == "-o":
            if cache_seen:
                return False
            cache_seen = True
            index += 1
            if index >= len(extras) or not extras[index].startswith("cache_dir="):
                return False
            if not _contained_annotation(extras[index].split("=", 1)[1], task, cache_only=True):
                return False
        else:
            return False
        index += 1
    return True


def _isolated_diagnostic(code: str) -> bool:
    """Small frozen diagnostic grammar; no path loading, site hooks or dependencies."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    allowed = (ast.Module, ast.Import, ast.alias, ast.Assign, ast.Expr, ast.Call,
               ast.Name, ast.Load, ast.Store, ast.Constant, ast.Attribute,
               ast.UnaryOp, ast.Not, ast.IfExp, ast.Compare, ast.Eq, ast.NotEq)
    protected = {"os", "sys", "print"}
    attributes = {"os.environ", "os.environ.get", "sys.exit"}
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Import) and any(a.name not in {"os", "sys"} or a.asname for a in node.names):
            return False
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return False
        if isinstance(node, ast.Assign) and any(not isinstance(t, ast.Name) or t.id in protected for t in node.targets):
            return False
        if isinstance(node, ast.Attribute) and ast.unparse(node) not in attributes:
            return False
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name not in {"print", "os.environ.get", "sys.exit"} or node.keywords:
                return False
            if name == "os.environ.get" and (len(node.args) != 1 or not isinstance(node.args[0], ast.Constant)
                                             or not isinstance(node.args[0].value, str)):
                return False
    return True


def runtime_provenance_check(configured: str, actual: list[str], task: Mapping[str, Any],
                             selected: Mapping[str, Any]) -> str | None:
    """Reject Python dependency recovery; bind a declared isolated base diagnostic."""
    if not actual:
        raise ValueError("executed command is unavailable")
    executable = Path(actual[0])
    roots = (Path(task["work_item"]).resolve(), Path(task["worktree"]["path"]).resolve())
    lexical = Path(os.path.abspath(roots[1] / executable)) if actual[0].startswith(".") else executable
    if lexical.is_absolute() and any(lexical.is_relative_to(root) for root in roots):
        raise ValueError("work-item executable requires independently declared dependency provenance")
    if shlex.split(configured) in (["npm", "ci"], ["npx", "tsc", "--noEmit"],
                                  ["npx", "playwright", "test", "--list"]):
        return None
    if not re.match(r"^(python|pypy)", executable.name, re.IGNORECASE):
        raise ValueError("command runtime/dependency provenance is unsupported for validation recovery")
    declarations = selected.get("validation", {}).get("isolated_python_interpreters") or {}
    declaration = declarations.get(configured) if isinstance(declarations, Mapping) else None
    if (not isinstance(declaration, Mapping) or declaration.get("authority") != "frozen_selected_profile"
            or declaration.get("dependency_mode") != "isolated_stdlib_diagnostic"
            or not executable.is_absolute() or executable != executable.resolve()
            or declaration.get("executable") != str(executable)
            or not re.fullmatch(r"[0-9a-f]{64}", str(declaration.get("sha256") or ""))
            or len(actual) != 5 or actual[1:4] != ["-I", "-S", "-c"]
            or not _isolated_diagnostic(actual[4])):
        raise ValueError("unsafe Python execution requires frozen interpreter/dependency provenance")
    try:
        observed = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("declared base interpreter is unavailable") from exc
    if observed != declaration["sha256"]:
        raise ValueError("declared base interpreter SHA changed")
    # The real governed runner must execute this exact checksum before and
    # after the diagnostic. Caller evidence alone never declares interpreter trust.
    return (shlex.join(["/usr/bin/shasum", "-a", "256", str(executable)])
            + " | /usr/bin/awk " + shlex.quote('$1 == "' + observed + '" {ok=1} END {exit !ok}'))


def matches_command(configured: str, actual: list[str], task: Mapping[str, Any],
                    selected: Mapping[str, Any]) -> bool:
    """Keep the frozen prefix exact; permit only contained pytest annotations."""
    try:
        expected = shlex.split(configured)
    except (TypeError, ValueError):
        return False
    if (not expected or not isinstance(actual, list) or len(actual) < len(expected)
            or not all(isinstance(x, str) for x in actual)):
        return False
    worktree = Path(str(task.get("worktree", {}).get("path") or ""))
    packet = Path(str(task.get("work_item") or ""))
    if not worktree.is_absolute() or not packet.is_absolute():
        return False

    def executable(value: str) -> str:
        # Lexical binding intentionally preserves the named task venv symlink.
        return os.path.abspath(worktree / value) if value.startswith(".") else value

    accepted = executable(expected[0])
    validation = selected.get("validation") or {}
    if not isinstance(validation, Mapping):
        return False
    mappings = validation.get("command_executables") or {}
    mapping = mappings.get(configured) if isinstance(mappings, Mapping) else None
    if mapping is not None:
        if (selected.get("schema") != "development-selected-profile/v2"
                or not isinstance(mapping, Mapping) or mapping.get("authority") != "selected_profile"):
            return False
        try:
            mapped = Path(mapping["executable"].format(work_item=str(packet), worktree=str(worktree)))
            if not mapped.is_absolute():
                return False
            mapped = Path(os.path.abspath(mapped))
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        if not any(mapped.is_relative_to(root) and mapped != root for root in (packet, worktree)):
            return False
        accepted = str(mapped)
    if accepted != executable(actual[0]) or expected[1:] != actual[1:len(expected)]:
        return False
    extras = actual[len(expected):]
    if not extras:
        return True
    # An added selector, test path, plugin, or arbitrary ini override changes
    # what ran and cannot establish the frozen full command.
    return expected[1:3] == ["-m", "pytest"] and _annotations(extras, task)
