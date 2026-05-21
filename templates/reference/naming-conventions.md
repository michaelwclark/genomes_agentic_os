# Naming Conventions

Naming conventions are lightweight state. They let humans and agents find files without loading every folder or querying a database.

## Patterns

| Object | Pattern | Example |
| --- | --- | --- |
| Draft | `<slug>-draft.md` | `api-auth-guide-draft.md` |
| Final | `<slug>-final.md` | `api-auth-guide-final.md` |
| Dated note | `<yyyy-mm-dd>-<slug>.md` | `2026-05-20-launch-plan.md` |
| Spec | `<slug>-spec.md` | `notion-sync-spec.md` |
| Versioned artifact | `<slug>-v<n>.<ext>` | `demo-v2.mp4` |

## Status Terms

- `draft`
- `review`
- `final`
- `archived`

## Rules

- Use lowercase filesystem-safe names for folders and generated IDs.
- Use dates when ordering matters.
- Use version numbers for artifacts that may be revised.
- Prefer names that reveal the workflow state.
