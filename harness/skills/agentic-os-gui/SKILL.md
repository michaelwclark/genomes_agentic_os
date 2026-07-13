---
name: agentic-os-gui
description: Build or open the local AgenticOSGui desktop app for domain/project-focused Claude and Codex conversations, metadata, pinning, continuation, and model presentation.
---

# AgenticOSGui

Use when the user asks for the Agentic OS desktop app, a unified Claude/Codex
conversation driver, domain/project-focused conversations, native conversation
titles, pins, metadata, or in-app continuation.

## Procedure

1. Route through the installed Agentic OS and the owning project/work item.
2. Prefer `agentic-os gui open --root /Users/genome/agentic_os` for normal use.
3. Use `gui snapshot` for machine-readable provider/index diagnostics.
4. Use the Phase 1 `agentic-os cockpit open` command when a read-only rollback
   surface is sufficient or the desktop package is unavailable.
5. For source changes, work in a registered project worktree and validate the
   Python contract plus desktop typecheck, tests, build, and package smoke test.

## Boundaries

- Provider stores are read-only; pins and route overrides are GUI-owned.
- Electron renderer access is restricted to the typed preload API.
- Imported Claude sessions use fork-on-continue or single-writer ownership.
- Codex app-server is experimental and requires a compatibility fallback.
- Model colors describe the actual provider/model/tier; they do not assert
  cross-provider routing that the current observe-mode policy cannot perform.
- External writes and destructive cleanup require their existing guarded
  workflows and explicit authorization.
