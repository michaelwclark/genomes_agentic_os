# Rules: Spec Engine

- Use only the canonical statuses `idea`, `grooming`, `blocked`, `ready`,
  `in_progress`, and `built` for new Specs.
- Use only the canonical types `bug`, `feature`, and `config`.
- Resolve root/domain/project/explicit policy before selecting adapters.
- Write `ORIGINAL_INTENT.md` before any polished `SPEC.md`.
- Do not collapse assumptions into facts. Put assumptions and open questions in
  explicit sections.
- Run an existing-capability discovery gate before creating a new program,
  workflow, automation, skill, or tracker hierarchy.
- Record exactly one route decision: `extend_existing`,
  `create_under_existing`, or `create_new`.
- Store provider IDs, URLs, native status, canonical status, idempotency key,
  and readback evidence in adapter receipts.
- A blocked Spec must retain the status it was blocked from so it can resume.
- Cancellation, duplication, rejection, and archival are dispositions; never
  report them as `built`.
- Keep LOS team-specific grooming on `$jira-product-orchestrator` when project
  policy selects that adapter.
- Do not write local filesystem paths, private Notion links, internal run paths,
  secrets, token names, or harness-only details into Jira, GitHub, Slack, email,
  or Linear.
- Verify Genome's Notion before any Notion write. Do not create fallback pages
  in another workspace.
- Use tables or structured sections for flow and state. Do not add Mermaid
  diagrams.
