# Agentic OS Hooks

These hooks are installed into the visible `hooks/` directory of an Agentic OS root.
Harness-specific config files may call them from Codex, Claude, or another agent
runtime, but the installed OS remains the source of truth for which hooks are
part of the operating contract.

Use `agentic-os hook sync --root ~/agentic_os --target all --apply --backup` to
point active Claude and Codex hook settings directly at this installed hook
directory. Do not copy hook scripts into `~/.claude/hooks` or `~/.codex/hooks`
as a separate source of truth.

## Installed Hooks

| Hook | Event | Purpose |
| --- | --- | --- |
| `session-prayer-start.sh` | `SessionStart` | Commit the session and work to Jesus before startup work begins. |
| `memory-session-start.sh` | `SessionStart` | Inject losmon-memory discipline before work starts. |
| `memory-stop.sh` | `Stop` | Remind agents to capture durable learnings before yielding. |
| `harness-emit-trace.sh` | `Stop` | Fire-and-forget an `AGENT_TRACE` memory record from hook payload metadata. |
| `conversation-auto-log.py` | `Stop` | Write redacted transcript and tool-call sidecars to the routed project or work item. |
| `context-mode-cache-heal.mjs` | `SessionStart` | Repair stale Claude context-mode plugin cache symlinks. |
| `parent-chat-polling-guard.py` | `PreToolUse` | Deny observer-only recurring parent-chat automation wakeups, including literal calls wrapped in `functions.exec`. |

## Parent-chat polling guard

Empty assistant replies do not make a recurring model wakeup quiet: the incoming
heartbeat and tool activity still enter the parent conversation. Keep polling in
a background process or worker, with durable state and one actionable or terminal
event delivered back to the parent. See the installed canonical library rule
`lib/rules/root/quiet-async-long-runs/RULES.md`.

The guard is a dependency-free Python command registered on `PreToolUse` with
matcher `*` for both Claude and Codex. Allowed calls produce no output. Denied
calls emit `hookSpecificOutput.permissionDecision=deny`; this does not require
Codex input rewriting or PreToolUse context injection support. Hooks must be
enabled in the host, and already-running sessions may need to restart to load
changed registration.

Direct `automation_update` calls and literal object arguments inside
`functions.exec` are inspected, including batches and bracket property access.
The parser never evaluates JavaScript. View/delete/pause operations and literal
`status=PAUSED` updates are always allowed. One-time followups, ordinary reminders,
and substantive scheduled work remain allowed. A conditional instruction to
repair a failure or to stay silent while pending does not exempt a polling loop.
Writing a status summary or receipt after a status read does not exempt it
either, and switching the same observer-only prompt to a cron job is blocked.

Unresolved automation aliases, variable arguments, spreads, interpolation, or
sparse reactivation fields are denied with guidance to provide a direct complete
call. A maintenance call can always be expressed as a literal. This guard is
not a JavaScript sandbox: tool names constructed dynamically, alternate APIs,
and hosts that do not emit nested or wrapper PreToolUse events require the
policy rule and provider-side enforcement. It cannot establish user intent from
prose or prevent every semantic disguise. Do not claim universal interception
from unit tests alone.
Because inspection is stateless, repeatedly re-creating allowed one-time
followups cannot be distinguished from legitimate one-time requests here.

Install the source hook into the existing OS `harness/hooks/` directory and run
`agentic-os hook sync --root ~/agentic_os --target all --apply --backup`, then
`agentic-os hook doctor --root ~/agentic_os --target all`. `docs install` copies
missing hook assets; it does not overwrite an existing installed hook. Hook sync
preserves unrelated user hooks and is idempotent. Verify the installed script
hash and fresh-session deny/allow behavior after an update.
