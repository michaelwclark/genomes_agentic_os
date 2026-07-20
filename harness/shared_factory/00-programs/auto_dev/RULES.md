# Auto-Dev Rules

- `development_delivery` is the durable state/worktree/recovery engine;
  Auto-Dev is the canonical operator-facing program family. Do not create a
  second SDLC state machine.
- Match intent implicitly. A bug investigation routes to Detective and artifact
  authorship routes to Create Artifacts even if Auto-Dev is not named.
- Every workflow has one manual command/skill, a program/sub-workflow route, a
  trigger-adapter contract, and durable receipts.
- Load the effective root/domain/project policy bundle before analysis,
  implementation, review, QA, PR creation, or artifact rendering.
- Resolve deployed environment version before environment-scoped code analysis.
- Read-only investigation does not authorize a mutation. External writes,
  merges, deployments, and production actions retain their own approval gates.
- A state change or external effect without a verified receipt is invalid.
- Facts, inference, contradictions, hypotheses, confidence, and evidence gaps
  remain distinct in analysis and external artifacts.
- Never expose secrets, customer data, local paths, private Notion links, raw
  logs, or OS internals to Jira, GitHub, Slack, Linear, Confluence, or email.
- Notion is a beautiful, verified projection in Genome's Notion; it is not the
  execution queue or source of runtime truth.
- Retire overlapping behavior only after parity evidence, breadcrumbs, registry
  cleanup, and a rollback note are complete.
