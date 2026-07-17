# Project Domain Analysis Toolkit

Portable support for the canonical `project-domain-architecture-analysis`
workflow. Configure a project under `.project-domain-analysis/`; source and
test evidence stay authoritative over generated guidance.

The toolkit's drift command is read-only except for its report artifact. The
program-owned refresh script is the scheduler-safe receipt surface.

## Commands

- `domain-analysis create <id> --title <title>` creates a required-section
  article at the current source revision.
- `domain-analysis refresh <id>` preserves a content-addressed backup before
  updating source-revision metadata.
- `domain-analysis retrieve <query> --receipt <project-relative.yml>` selects
  the smallest matching article set and emits `project-domain-context/v1`.
- `domain-analysis drift [git-range]` records changed and untracked paths.
- `domain-analysis validate` checks configured path containment and every
  article's required evidence, pattern, failure, and extension sections.
- `domain-analysis rollback <id>` restores the latest exact backup.
- `domain-analysis retire <id>` removes obsolete guidance from retrieval while
  preserving its backup.

Manual create, refresh, rollback, and retire operations belong to an approved
project workflow. Scheduled automation invokes only the separate observe-only
refresh receipt script and therefore cannot change articles.
