# Agentic OS GUI

Use when the operator asks to open, build, inspect, or operate the local
AgenticOSGui desktop conversation driver.

Primary skill: `agentic-os-gui`.

## CLI Surface

```bash
agentic-os gui snapshot --root ~/agentic_os
agentic-os gui transcript --root ~/agentic_os --provider codex --conversation-id <id>
agentic-os gui open --root ~/agentic_os
```

## Operating Contract

1. Treat domains and projects as the primary focus hierarchy.
2. Build the active conversation list from native provider registries, not a
   bounded scan of transcript files.
3. Keep Claude and Codex stores read-only. Persist GUI pins, focus, leases, and
   route overrides in AgenticOSGui-owned state.
4. Run local provider protocols and subprocesses only from the Electron main
   process through allowlisted argument arrays.
5. Preserve the static `agentic-os cockpit open` path as the read-only rollback.

## Safety

- Do not expose arbitrary shell, filesystem, credential, or connector access to
  the renderer.
- Do not archive threads, delete worktrees/containers, or write Jira, GitHub,
  Slack, Notion, or remote hosts without a separate explicit guarded action.
- Do not claim cross-provider adaptive routing while the installed policy is
  observe-only and provider-specific.
