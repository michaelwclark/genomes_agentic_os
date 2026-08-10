# Auto-Dev Rules

- `development_delivery` is the durable state/worktree/recovery engine;
  Auto-Dev is the canonical operator-facing program family. Do not create a
  second SDLC state machine.
- Match intent implicitly. A bug investigation routes to Detective and artifact
  authorship routes to Create Artifacts even if Auto-Dev is not named.
- Every workflow has one manual command/skill, a program/sub-workflow route, a
  trigger-adapter contract, and durable receipts.
- Load the effective root/domain/project/invocation bundle for all five nested
  Auto-Dev policy planes before analysis, implementation, review, QA, PR
  creation, or artifact rendering.
- An LOS Rules Engine caller path or rulebook subject selects a candidate, not
  a loaded kit. Freeze and reuse concrete contract, dictionary, checks,
  coverage, redundancy, snapshot, and finding evidence only after a declared
  local catalog identifies one ready kit and all five files hash successfully.
  An absent catalog/kit is `kit-unavailable`; an unmapped rulebook or incomplete
  snapshot is `insufficient-evidence`, never a claim that a rule is unused or
  healthy.
- Object Library changes are authored in the registered source repository.
  Installed `lib/` is a replaceable projection and may not become a second
  source checkout or a place to bypass build, QA, Release, Deploy readback, or
  post-release documentation.
- Resolve deployed environment version before environment-scoped code analysis.
- Read-only investigation does not authorize a mutation. External writes,
  merges, deployments, and production actions retain their own approval gates.
- Rules Engine evidence is compatible with Project Rubicon only as a domain
  evidence producer. It must not duplicate or mutate Control Plane lifecycle,
  queue, lease, fence, cursor, idempotency, or raw tenant-data records.
- A state change or external effect without a verified receipt is invalid.
- Facts, inference, contradictions, hypotheses, confidence, and evidence gaps
  remain distinct in analysis and external artifacts.
- Never expose secrets, customer data, local paths, private Notion links, raw
  logs, or OS internals to Jira, GitHub, Slack, Linear, Confluence, or email.
- Notion is a beautiful, verified projection in Genome's Notion; it is not the
  execution queue or source of runtime truth.
- When Execution Fabric is the selected runtime, admit Auto-Dev work through
  its configured named queue with one stable idempotency key. Worker capacity
  comes from the configured pool and global/provider limits, never work-item
  folder names, `02-active` counts, or detached process counts.
- Retire overlapping behavior only after parity evidence, breadcrumbs, registry
  cleanup, and a rollback note are complete.
