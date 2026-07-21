# Auto-Dev: document

Use `/auto-dev-document` at any lifecycle stage to create or improve durable
explanation of code, configuration, APIs, architecture, data flow, operations,
issues, decisions, RCA, QA, release, deployment, support, or handoff.

## Define the documentation job

Before writing, name:

- audience and what they should be able to do afterward;
- document type, owner, destination, and source of truth;
- exact subject version/revision/environment;
- freshness contract and what event should update the document;
- sensitivity and whether the output is internal, teammate-facing,
  customer-visible, or public.

Do not create a new document when an owned canonical page/file should be
updated. Do not make a private projection the team's source of truth.

## Authoring behavior

1. Read code/configuration at the exact applicable revision plus existing docs,
   tests, decisions, provider truth, and recent receipts.
2. Verify behavior by tracing the implementation or running a focused example;
   do not document names and comments as if they prove runtime behavior.
3. Explain purpose and behavior in plain English before implementation detail.
4. Include prerequisites, examples, failure modes, safety/approval boundaries,
   ownership, verification, and recovery where the audience needs them.
5. Keep code comments focused on why, invariants, or non-obvious constraints;
   avoid narrating obvious syntax.
6. Prefer diagrams or tables only when they make relationships or exact
   mappings materially clearer.
7. Link to durable team-visible sources, verify the links, and identify version
   or last-verified date where drift matters.
8. Render and validate external documentation through Create Artifacts, with
   target verification, approval, sanitization, apply, and provider readback.

Use subagents to inspect separate modules or validate instructions, but have one
editor reconcile terminology, remove duplication, and check the final narrative.

## Quality and done criteria

Documentation must be accurate at the stated evidence boundary, navigable,
plain English, and usable without this chat. It distinguishes current behavior,
future work, assumptions, and unresolved questions. Never copy transient logs,
secrets, customer data, local-only paths, private links, or unsupported claims
into durable external documentation.

Record sources, subject version, validation performed, destination, owner,
freshness rule, and provider readback where applicable. The stage is complete
when the intended audience can follow or verify the documented behavior and the
canonical destination matches the validated content.
