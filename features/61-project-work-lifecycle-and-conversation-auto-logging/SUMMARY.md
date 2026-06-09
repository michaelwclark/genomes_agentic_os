# Summary

Implemented the project work lifecycle slice that promotes feature-60-style
tracking into the default project work-item surface and adds a conversation auto
logging hook as a reusable OS capture path.

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

Implemented surface:

- `project work-item create` creates markdown-backed work items in the configured
  project lane.
- Routing and context helpers expose lifecycle state and the required files an
  agent should read before resuming.
- Plan capture can route OS source ideas and project ideas into the right work
  item location.
- The conversation auto logging hook writes redacted transcript logs and
  tool-call sidecars next to the routed work item.
- Validation includes lifecycle drift checks for active project work items.
