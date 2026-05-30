# Summary

Created a planned OS feature that promotes feature-60-style tracking into the
default project work lifecycle and adds a default conversation auto logging hook
as a required value proof for the OS.

Key decisions:

- Project work items should live under
  `<domain>/02-projects/<project>/work-items/`.
- Reusable OS product plans belong in source `PLANS/` and install into
  `harness/shared_factory/05-knowledge/plans/`.
- `shared_factory` is a shared OS product layer, not a normal user-facing
  domain.
- Conversation logs should use `YYYY_MM_DD_<slug>` names.
- Tool-call sidecars should be extracted, redacted, and written next to the
  conversation log.
- Project config decides whether a specified item promotes to local source,
  Jira, Notion, or another external tracker.
