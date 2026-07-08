# OS Groom Spec

Use when the user asks to turn a rough idea, feature request, product thought,
OS improvement, or future software proposal into an implementation-grade spec.

Primary slash command: `/groom-spec`

## Procedure

1. Load the routed Agentic OS layer and active project/work item context.
2. Load `harness/shared_factory/00-programs/spec_grooming/` and
   `harness/skills/spec-groomer/SKILL.md`.
3. Run doc-config before creating or moving packet or Notion artifacts:

```bash
agentic-os doc-config plan --root <root> --request "<user request>" [--domain <domain>] [--project <project>] [--questions-present]
```

4. Write `ORIGINAL_INTENT.md` first, preserving raw capture, anchors,
   assumptions, questions, and iteration deltas.
5. Run the existing-capability discovery gate:
   - local work items;
   - programs, workflows, automations, skills, commands, docs, and templates;
   - tracker or Notion surfaces when requested and verified.
6. Record one route decision in `JUDGMENT.md`:
   `extend_existing`, `create_under_existing`, or `create_new`.
7. Produce the full packet: `SPEC.md`, `PLAN.md`, `INVESTIGATION.md`,
   `HOLDOUT_QA.md`, `NEXT.md`, `WORKLOG.md`, and conditional projection
   receipts.
8. For LOS Django or Jira-primary work, delegate grooming to
   `$jira-product-orchestrator`.
9. For Linear projection, create a sanitized parent/child hierarchy only when
   project config or the user explicitly requests it. Otherwise create the
   unified intake row and let intake sync own Linear.
10. For Notion projection, verify Genome's Notion and write an operator-facing
    product report. If verification fails, record the blocker and do not create
    a fallback page.

## Required Outputs

- Packet path.
- Original intent summary.
- Discovery evidence summary.
- Route decision.
- Acceptance criteria and Gherkin.
- QA/holdout plan.
- Tracker and Notion receipts or explicit skip/blocker notes.

## Guardrails

- Do not implement the groomed spec unless the user separately asks.
- Do not create duplicate owner surfaces when an existing program, workflow,
  automation, skill, or tracker item should be extended.
- Do not include private local paths, private Notion links, secrets, token
  names, internal run paths, or harness-only details in external tracker text.
- Do not use Mermaid diagrams. Use flow and state tables instead.

