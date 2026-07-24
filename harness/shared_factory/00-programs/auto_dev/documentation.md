# Documentation Contract

The source of truth is this installed program, the workflow folders, policy
plane READMEs, command/skill adapters, and tested receipt schemas. Genome's
Notion is a rich operator projection of those verified surfaces; it must never
become a second specification that silently drifts.

Current verified projection: [Auto-Dev — Canonical SDLC Program](https://www.notion.so/3a3683b48dab81b88875f5ec875dab3e),
under Genome’s Agentic OS → OS Programs in Genome's Notion. Publication and
readback receipts belong to the active implementation work item, not this
versioned program definition.

## Required Notion hierarchy

```text
Auto Dev
├── Start Here and Operating Model
├── Policy and Configuration
│   ├── Auto-Dev Workflow Policy
│   ├── Environment Access
│   ├── Development, QA, and Gitflow
│   ├── Investigation Sources
│   └── Artifact Contracts
├── Object Library Self-Hosting
├── Receipts and Observability
├── Archive Soon
├── Create Artifacts
│   ├── Contract Resolution
│   ├── Provider Playbook
│   └── Failure and Recovery
├── Detective
│   ├── Evidence Standard
│   ├── LOS Investigation
│   ├── Kanga Investigation
│   └── Failure and Recovery
├── Everything
├── Groom
├── Readiness and Context
├── Develop
├── Document
├── PR Create
├── Review Self
├── Review Others
├── QA
├── Finalize
├── Merge
├── Release
├── Deploy
├── Closeout
└── Health
```

The stage child-page sequence is the shared safe order: Groom,
Detective, Create Artifacts, Readiness, Develop, Document, PR Create, Review
Self, Review Others, QA, Finalize, Merge, Release, Deploy, Closeout, Health.
Everything explains the orchestration across those pages; it is not a
seventeenth stage. Project profiles define Default and Everything start/end
boundaries and may supply a full alternative order that preserves required
lifecycle precedence. Bare Auto-Dev uses Default and must include PR Create.
Stages outside a run boundary are `out_of_scope`. Single-stage commands use the
same predecessor receipts.

Release Propagation is not a child stage or a `not_required` stage choice. It
is the lower-level compatibility recorder and legacy alias for PR Create.

Object Library Self-Hosting is also a profile, not a stage. It must show the
canonical source repository versus installed projection boundary and map build
to Develop, exact-artifact validation to QA, publication to Release,
installation/readback to Deploy, and post-release truth to a Document rerun.

Each workflow page is manually runnable and must include: intended outcome;
implicit and explicit triggers; inputs and prerequisites; ordered states/steps;
root/domain/project/invocation policy inputs; outputs; success validations;
failure classes and exact resume behavior; receipts; command and skill; owner;
and links to its code, tests, policies, and Archive Soon rows.

The Closeout page must describe provider/delivery reconciliation and the
`delivery_complete` gate. The Health page must describe receipt-first audit,
the resume manifest, the complete pre-cleanup packet manifest and hashes,
immutable packet-local preflight, target-local runtime receipt bound to that
preflight hash, exact known-root worktree cleanup, one atomic two-resource
receipt, a packet-local closed-worktree registry readback cross-checked against
live `worktrees/closed.yml`, the semantic relocation exception for only
`work.yml` and `autodev.json`, the finished-lane move, and reopen/hold
protection. It must state that worktree identity, path, branch, and HEAD are
exact; runtime identity includes domain/project/worktree; teardown and readback
commands are identity-bound; the readback is at most 15 minutes old and is
executed again immediately; and exit 0 means only the registered worktree
runtime is absent. It must forbid force, Git metadata sweeps, host-wide/all
cleanup, guessed resources, and shared-runtime teardown. Health is manually
runnable and has no enabled schedule.

Provider-specific Health documentation must name every durable item-owned
surface its readback proves. For LOS fast worktrees that means the declared
runtime identity, exact Git worktree and compose project, per-worktree
containers, exact project-labeled/prefixed networks and volumes, Postgres
database, Redis and Valkey namespaces, fast-worktree registry row, and
`.env.worktree`. It must distinguish the shared external LOS network from
project residue and state that Docker enumeration errors or unavailable shared
infra make those resources unprovable and block cleanup; an ordinary status
display or grep is not a substitute.

The Finalize, Review Others, and Merge pages must explain the authorship
boundary. Provider-read `author_identity` is classified against the frozen task
`authorship.ours` list; callers cannot select `author_kind`. Finalize authorizes
only `ours` and only records `readiness_decision: ready_for_merge`. Review
Others authorizes only `others` and records a clean `review_no_merge` result.
Merge consumes the hashed completed receipt from the correct owner and keeps
provider, pull request, repository, base branch, reviewed revision, author
identity, and derived author kind identical through open/ready/merged readback.
The completed Merge receipt also contains `merge_sha`, provider-read
`source_head_sha` equal to `subject_revision`, and `readback_verified: true`.
The Health page must show that terminal-authority provider/reference and
revision match those Merge fields exactly, with no renamed or inferred
substitute.

Every page that permits `not_required` must show the strict
`auto-dev-stage-policy-decision/v1` fields and explain that `policy_source` is
the exact frozen delivery policy receipt plus SHA-256. Recording materializes
the policy and decision into packet-local immutable proof. The frozen stage
policy marks each stage required, contextual, or disabled. Contextual or
disabled Detective, Create Artifacts, Document, Review Others, QA, Finalize,
and Release may use `not_required`; delivery-managed stages route their typed
decision through Development Delivery. Required stages must complete.

The work-item page must explain `autodev.json` as a projection over canonical
delivery state, not an independent state machine. It must show Default,
Everything, and single-stage invocation, configurable boundaries/order,
required/contextual/disabled applicability, typed completion/not-required
receipts, and resume.
For a multi-ticket invocation, it must show one packet and `autodev.json` per
ticket and ticket-local `--state` resume. Finished packets are immutable: an
explicit receipt-backed canonical work-item reopen starts a new delivery run
and new resources while the old packet remains unchanged.

The Health evidence page must list these ten exact receipt kinds:
`terminal_authority`, `closeout`, `receipt_audit`, `resume_manifest`,
`packet_manifest`, `resource_cleanup`, `runtime_cleanup`, `work_state`,
`active_index`, and `validation`.

## Visual and readability standard

- Start with a one-sentence outcome callout and a compact properties table.
- Place a flowchart image above detailed steps for every multi-step workflow.
- Use columns for “inputs” and “outputs,” a table for states and gates, toggles
  for schemas/examples, and callouts for destructive-action or approval gates.
- Keep paragraphs short. Prefer headings, checklists, tables, and scoped child
  pages over a single dense page.
- Show the happy path and pause/repair/retry path on the same diagram.
- Never use private local paths or private workspace URLs in external pages.

## Publication and verification

1. Verify the destination parent is in Genome's Notion.
2. Resolve the applicable Notion artifact contract and render from source
   facts; do not improvise a separate format.
3. Create/update the complete hierarchy with stable titles and child links.
4. Upload the canonical SVG/PNG flow assets and verify that they render.
5. Read back every page. Verify parent, title, headings, tables, child links,
   images, and current version/fingerprint.
6. Record page IDs, URLs, source fingerprint, published time, and readback
   result in the work-item/run receipts.

If the connector is bound to another workspace, unavailable, or cannot prove
the target parent, pause publication. Preserve the rendered content and resume
the same handoff after access is verified; never create a fallback page in a
different workspace.
