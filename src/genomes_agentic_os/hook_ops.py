"""Hook configuration operations for active agent harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from .scaffold import expand_path, harness_path


HOOK_FILENAMES = (
    "session-prayer-start.sh",
    "memory-session-start.sh",
    "memory-stop.sh",
    "harness-emit-trace.sh",
    "conversation-auto-log.py",
    "context-mode-cache-heal.mjs",
)


def context_mode_command(target: str, event: str) -> str:
    return f"context-mode hook {target} {event}"


def mempalace_command(hook: str) -> str:
    return f"{Path.home()}/.local/share/mempalace-venv/bin/mempalace hook run --hook {hook} --harness claude-code"


@dataclass
class HookConfigResult:
    root: Path
    target: str
    dry_run: bool
    config_paths: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "target": self.target,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "config_paths": [str(path) for path in self.config_paths],
            "updated": [str(path) for path in self.updated],
            "skipped": [str(path) for path in self.skipped],
            "backups": [str(path) for path in self.backups],
            "findings": self.findings,
        }


def default_codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


def default_claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.{stamp}.bak")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def command_value(entry: dict[str, Any]) -> str:
    value = entry.get("command")
    return str(value) if value else ""


def set_command(entry: dict[str, Any], command: str) -> bool:
    if command_value(entry) == command:
        return False
    entry["command"] = command
    return True


def hook_command(root: Path, filename: str, *args: str) -> str:
    command = str(harness_path(root, "hooks", filename))
    if args:
        command += " " + " ".join(args)
    return command


def replace_legacy_hook_commands(data: dict[str, Any], root: Path, target: str) -> bool:
    changed = False
    legacy_fragments = {
        f".{target}/hooks/memory-session-start.sh": hook_command(root, "memory-session-start.sh"),
        f".{target}/hooks/memory-stop.sh": hook_command(root, "memory-stop.sh"),
        f".{target}/hooks/context-mode-cache-heal.mjs": hook_command(root, "context-mode-cache-heal.mjs"),
        ".local/bin/harness-emit-trace": hook_command(root, "harness-emit-trace.sh", target),
    }
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event_entries in hooks.values():
        if not isinstance(event_entries, list):
            continue
        for event_entry in event_entries:
            if not isinstance(event_entry, dict):
                continue
            for hook in event_entry.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = command_value(hook).strip('"')
                for legacy_fragment, replacement in legacy_fragments.items():
                    if legacy_fragment in command:
                        changed = set_command(hook, replacement) or changed
                        break
    return changed


def ensure_hook_entry(
    data: dict[str, Any],
    event: str,
    command: str,
    *,
    matcher: str | None = None,
    timeout: int | None = None,
    status_message: str | None = None,
) -> bool:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        data["hooks"] = hooks = {}
    event_entries = hooks.setdefault(event, [])
    if not isinstance(event_entries, list):
        hooks[event] = event_entries = []

    for event_entry in event_entries:
        if not isinstance(event_entry, dict):
            continue
        for hook in event_entry.get("hooks") or []:
            if isinstance(hook, dict) and command_value(hook) == command:
                return False

    event_entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        event_entry["matcher"] = matcher
    hook = event_entry["hooks"][0]
    if timeout is not None:
        hook["timeout"] = timeout
    if status_message:
        hook["statusMessage"] = status_message
    event_entries.append(event_entry)
    return True


def sync_codex_hooks(data: dict[str, Any], root: Path) -> bool:
    changed = replace_legacy_hook_commands(data, root, "codex")
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        hook_command(root, "session-prayer-start.sh"),
        matcher="startup",
        timeout=5,
        status_message="Committing the session",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        hook_command(root, "memory-session-start.sh"),
        matcher="startup|resume|clear",
        timeout=5,
        status_message="Loading memory discipline",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "Stop",
        hook_command(root, "memory-stop.sh"),
        timeout=5,
        status_message="Reminding memory capture",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "Stop",
        hook_command(root, "harness-emit-trace.sh", "codex"),
        timeout=5,
        status_message="Emitting AGENT_TRACE envelope",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "Stop",
        hook_command(root, "conversation-auto-log.py"),
        timeout=30,
        status_message="Logging Agentic OS conversation",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        context_mode_command("codex", "sessionstart"),
        matcher="",
    ) or changed
    changed = ensure_hook_entry(data, "Stop", context_mode_command("codex", "stop"), matcher="") or changed
    changed = ensure_hook_entry(
        data,
        "PreToolUse",
        context_mode_command("codex", "pretooluse"),
        matcher=(
            "local_shell|shell|shell_command|exec_command|Bash|Shell|apply_patch|"
            "Edit|Write|grep_files|ctx_execute|ctx_execute_file|ctx_batch_execute|"
            "ctx_fetch_and_index|ctx_search|ctx_index|mcp__"
        ),
    ) or changed
    changed = ensure_hook_entry(data, "PostToolUse", context_mode_command("codex", "posttooluse"), matcher="") or changed
    changed = ensure_hook_entry(data, "PreCompact", context_mode_command("codex", "precompact"), matcher="") or changed
    changed = ensure_hook_entry(
        data,
        "UserPromptSubmit",
        context_mode_command("codex", "userpromptsubmit"),
        matcher="",
    ) or changed
    return changed


def sync_claude_hooks(data: dict[str, Any], root: Path) -> bool:
    changed = replace_legacy_hook_commands(data, root, "claude")
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        hook_command(root, "session-prayer-start.sh"),
        matcher="startup",
        timeout=5,
        status_message="Committing the session",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        hook_command(root, "memory-session-start.sh"),
        matcher="startup|resume|clear",
    ) or changed
    changed = ensure_hook_entry(data, "SessionStart", hook_command(root, "context-mode-cache-heal.mjs")) or changed
    changed = ensure_hook_entry(data, "Stop", hook_command(root, "memory-stop.sh")) or changed
    changed = ensure_hook_entry(data, "Stop", hook_command(root, "harness-emit-trace.sh", "claude")) or changed
    changed = ensure_hook_entry(
        data,
        "Stop",
        hook_command(root, "conversation-auto-log.py"),
        timeout=30,
        status_message="Logging Agentic OS conversation",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "SessionStart",
        mempalace_command("session-start"),
        matcher="startup|resume|clear",
        timeout=30,
        status_message="MemPalace session-start",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "Stop",
        mempalace_command("stop"),
        matcher="*",
        timeout=30,
        status_message="MemPalace stop",
    ) or changed
    changed = ensure_hook_entry(
        data,
        "PreCompact",
        mempalace_command("precompact"),
        timeout=30,
        status_message="MemPalace precompact",
    ) or changed
    return changed


def required_commands(root: Path, target: str) -> tuple[str, ...]:
    if target == "codex":
        return (
            hook_command(root, "session-prayer-start.sh"),
            hook_command(root, "memory-session-start.sh"),
            hook_command(root, "memory-stop.sh"),
            hook_command(root, "harness-emit-trace.sh", "codex"),
            hook_command(root, "conversation-auto-log.py"),
            context_mode_command("codex", "sessionstart"),
            context_mode_command("codex", "stop"),
            context_mode_command("codex", "pretooluse"),
            context_mode_command("codex", "posttooluse"),
            context_mode_command("codex", "precompact"),
            context_mode_command("codex", "userpromptsubmit"),
        )
    if target == "claude":
        return (
            hook_command(root, "session-prayer-start.sh"),
            hook_command(root, "memory-session-start.sh"),
            hook_command(root, "memory-stop.sh"),
            hook_command(root, "harness-emit-trace.sh", "claude"),
            hook_command(root, "conversation-auto-log.py"),
            hook_command(root, "context-mode-cache-heal.mjs"),
            mempalace_command("session-start"),
            mempalace_command("stop"),
            mempalace_command("precompact"),
        )
    raise ValueError(f"unknown hook target: {target}")


def configured_commands(data: dict[str, Any]) -> set[str]:
    commands: set[str] = set()
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return commands
    for event_entries in hooks.values():
        if not isinstance(event_entries, list):
            continue
        for event_entry in event_entries:
            if not isinstance(event_entry, dict):
                continue
            for hook in event_entry.get("hooks") or []:
                if isinstance(hook, dict) and command_value(hook):
                    commands.add(command_value(hook).strip('"'))
    return commands


def validate_source_hooks(root: Path, result: HookConfigResult) -> None:
    for filename in HOOK_FILENAMES:
        path = harness_path(root, "hooks", filename)
        if not path.is_file():
            result.findings.append(f"missing source hook: {path}")
            continue
        if not path.stat().st_mode & 0o111:
            result.findings.append(f"source hook is not executable: {path}")


def sync_hook_target(
    root: Path,
    target: str,
    config_path: Path,
    *,
    dry_run: bool,
    backup: bool,
    result: HookConfigResult,
) -> None:
    data = load_json(config_path)
    original = json.dumps(data, indent=2, sort_keys=True)
    changed = sync_codex_hooks(data, root) if target == "codex" else sync_claude_hooks(data, root)
    result.config_paths.append(config_path)
    if not changed or json.dumps(data, indent=2, sort_keys=True) == original:
        result.skipped.append(config_path)
        return
    if dry_run:
        result.updated.append(config_path)
        return
    if backup and config_path.exists():
        destination = backup_path(config_path)
        shutil.copy2(config_path, destination)
        result.backups.append(destination)
    write_json(config_path, data)
    result.updated.append(config_path)


def hook_sync(
    root: str | Path,
    *,
    target: str = "all",
    dry_run: bool = True,
    backup: bool = False,
    codex_hooks_path: str | Path | None = None,
    claude_settings_path: str | Path | None = None,
) -> HookConfigResult:
    os_root = expand_path(root)
    result = HookConfigResult(root=os_root, target=target, dry_run=dry_run)
    validate_source_hooks(os_root, result)
    targets = ("codex", "claude") if target == "all" else (target,)
    for item in targets:
        if item == "codex":
            path = expand_path(codex_hooks_path) if codex_hooks_path else default_codex_hooks_path()
        elif item == "claude":
            path = expand_path(claude_settings_path) if claude_settings_path else default_claude_settings_path()
        else:
            raise ValueError(f"target must be one of all, codex, claude: {target!r}")
        sync_hook_target(os_root, item, path, dry_run=dry_run, backup=backup, result=result)
    return result


def hook_doctor(
    root: str | Path,
    *,
    target: str = "all",
    codex_hooks_path: str | Path | None = None,
    claude_settings_path: str | Path | None = None,
) -> HookConfigResult:
    os_root = expand_path(root)
    result = HookConfigResult(root=os_root, target=target, dry_run=True)
    validate_source_hooks(os_root, result)
    targets = ("codex", "claude") if target == "all" else (target,)
    for item in targets:
        if item == "codex":
            path = expand_path(codex_hooks_path) if codex_hooks_path else default_codex_hooks_path()
        elif item == "claude":
            path = expand_path(claude_settings_path) if claude_settings_path else default_claude_settings_path()
        else:
            raise ValueError(f"target must be one of all, codex, claude: {target!r}")
        result.config_paths.append(path)
        if not path.is_file():
            result.findings.append(f"missing active {item} hook config: {path}")
            continue
        data = load_json(path)
        commands = configured_commands(data)
        for command in required_commands(os_root, item):
            if command not in commands:
                result.findings.append(f"missing active {item} hook command: {command}")
        for command in commands:
            if f".{item}/hooks/" in command:
                result.findings.append(f"active {item} hook still points at copied hook path: {command}")
    if result.findings:
        return result
    result.skipped.extend(result.config_paths)
    return result
