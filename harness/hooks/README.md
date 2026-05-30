# Agentic OS Hooks

These hooks are installed into the visible `hooks/` directory of an Agentic OS root.
Harness-specific config files may call them from Codex, Claude, or another agent
runtime, but the installed OS remains the source of truth for which hooks are
part of the operating contract.

## Installed Hooks

| Hook | Event | Purpose |
| --- | --- | --- |
| `memory-session-start.sh` | `SessionStart` | Inject losmon-memory discipline before work starts. |
| `memory-stop.sh` | `Stop` | Remind agents to capture durable learnings before yielding. |
| `harness-emit-trace.sh` | `Stop` | Fire-and-forget an `AGENT_TRACE` memory record from hook payload metadata. |
| `conversation-auto-log.py` | `Stop` | Write redacted transcript and tool-call sidecars to the routed project or work item. |
| `context-mode-cache-heal.mjs` | `SessionStart` | Repair stale Claude context-mode plugin cache symlinks. |
