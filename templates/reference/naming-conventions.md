# Naming Conventions

## Durable Entity Date Prefixes

Read `harness/config/artifact-naming.yml` before creating top-level durable
entities. The default is enabled and renders `MMDDYY-` (`%m%d%y` plus `-`) for
work items, registered worktrees, conversation sidecars, async runs, run logs, report runs,
development runs, and thread closeouts. For example:

```text
071826-011_date_prefixed_durable_artifact_naming
071826-aos-date-naming-date-prefixed-durable-artifact-naming
071826-144100Z-shared_factory-validation
```

Do not hand-prefix stable files inside those entities. Names such as
`work.yml`, `run-log.md`, `artifact.json`, and `state.json` are interface
contracts. Use `agentic-os naming migrate` for existing entities so filesystem,
registry, and SQLite references move together.

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
