# Rules: spec_grooming

- Write `ORIGINAL_INTENT.md` before any polished `SPEC.md`.
- Do not collapse assumptions into facts. Put assumptions and open questions in
  explicit sections.
- Run an existing-capability discovery gate before creating a new program,
  workflow, automation, skill, or tracker hierarchy.
- Record exactly one route decision: `extend_existing`,
  `create_under_existing`, or `create_new`.
- Keep LOS Django and Jira-primary grooming on `$jira-product-orchestrator`.
- Do not write local filesystem paths, private Notion links, internal run paths,
  secrets, token names, or harness-only details into Jira, GitHub, Slack, email,
  or Linear.
- Verify Genome's Notion before any Notion write. Do not create fallback pages
  in another workspace.
- Use tables or structured sections for flow and state. Do not add Mermaid
  diagrams.

