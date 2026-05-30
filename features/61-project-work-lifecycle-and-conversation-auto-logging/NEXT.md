# Next

## Recommended Implementation Slices

1. Add templates and schemas for project work items.
2. Extend project config with lifecycle and transcript logging policy.
3. Extend `plan capture` or add `project work-item create`.
4. Extend route/context output with lifecycle state and required files.
5. Add the conversation auto logging hook with redaction.
6. Add lifecycle validation and doctor checks.
7. Add docs and harness command updates.

## First Build Slice

Start with local-only work-item templates and project config. Do not implement
Jira, Notion, or transcript copying until the filesystem lifecycle is tested.

## Open Questions

- Should work item IDs use sequential project-local numbers, dates, or both?
- Should transcript raw-copy be enabled by default for customer OS installs, or
  summary-only until explicit opt in?
- Should closeout enforcement be a hook warning first, or a blocking validation
  command only when the user asks for strict mode?
