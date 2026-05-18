# Agent Surfaces

The OS should work from both Claude and Codex. The repo should provide installable instructions, skills, and rules for each harness.

## Shared Requirements

Each harness needs:

- OS discovery rules.
- Context loading rules.
- Workflow execution rules.
- Run log rules.
- Approval handling rules.
- Tool safety rules.
- Notion control plane update rules.

## Codex Surface

Codex should receive:

- `AGENTS.md` project rules for installed OS roots.
- Skills for workflow execution and OS bootstrapping.
- Optional hooks or scripts for context pack validation.
- Clear instruction to preserve user worktree changes.

## Claude Surface

Claude should receive:

- `CLAUDE.md` global or project rules.
- Skills or commands matching the Codex workflow names.
- Memory policy references.
- Context loading conventions that mirror Codex.

## Cross-Harness Rule

Claude and Codex should not have separate operating philosophies. They can have different mechanics, but they should read the same specs and produce the same run logs.
