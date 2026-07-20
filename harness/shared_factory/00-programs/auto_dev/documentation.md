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
│   ├── Development, QA, and Gitflow
│   ├── Investigation Sources
│   └── Artifact Contracts
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
├── Readiness and Context
├── Isolated Implementation
├── Testing, Review, and PR Repair
├── Release Propagation
└── Merge, Deployment, and Cleanup
```

Each workflow page is manually runnable and must include: intended outcome;
implicit and explicit triggers; inputs and prerequisites; ordered states/steps;
root/domain/project/invocation policy inputs; outputs; success validations;
failure classes and exact resume behavior; receipts; command and skill; owner;
and links to its code, tests, policies, and Archive Soon rows.

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
