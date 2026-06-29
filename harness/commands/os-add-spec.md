# OS Add Spec

Use when the user asks to add future work, capture a rough request, start a
spec, capture a proposed feature, or create a Notion/project structure for work
that has not happened yet.

Primary slash command: `/add-spec`
Compatibility aliases: `/new-feature`, `/add-feature`, `/new-idea`

## Procedure

1. Load the routed Agentic OS layer: `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
   `TOOLS.md`, and any active project/work-item context.
2. Read `harness/rules/os-authoring-rules.md` when authoring or changing
   conventions, workflows, commands, skills, automations, tools, registries, or
   project worktrees. Use
   `harness/shared_factory/05-knowledge/references/os-conventions.md` only when
   the compact rule needs deeper explanation.
3. Run doc routing before creating anything:

```bash
agentic-os doc-config plan --root <root> --request "<user request>" [--domain <domain>] [--project <project>] [--questions-present]
```

4. If the plan does not resolve a domain/project, ask only for the missing
   routing fact needed to continue.
5. Create or repair the project surface when the project is known:

```bash
agentic-os project onboard <domain> <project> --root <root>
```

6. Create the intake work item in the configured lifecycle lane. Use packet
   format when the spec already needs separate `SPEC`, `PLAN`, `WORKLOG`, or
   `QUESTIONS` files:

```bash
agentic-os project work-item create <domain> <project> \
  --root <root> \
  --title "<spec title>" \
  --summary "<one sentence outcome>" \
  --status captured \
  --format packet
```

7. If source work will use an external checkout, register it with
   `agentic-os project worktree add`.
8. Populate the configured buckets from the doc-config plan. Include
   `QUESTIONS` whenever unresolved questions exist.
9. Before Notion writes, verify Genome's Notion or the explicitly selected
   workspace. Use the Notion path from doc-config and rich Notion blocks/color
   preferences from `doc-config.yml`.
10. Update `WORKLOG.md`, `NEXT.md`, and the project or domain control surface
    when the capture changes durable routing or state.

## Required Outputs

- Routed destination from `agentic-os doc-config plan`.
- Project work item path.
- Filled `SPEC`, `PLAN`, `WORKLOG`, and conditional `QUESTIONS` content.
- Notion projection path or explicit note that Notion write was skipped.
- Next action and validation result.

## Guardrails

- Do not create Notion pages before doc-config planning and workspace
  verification.
- Do not invent a second bucket taxonomy if `doc-config.yml` already resolves
  one.
- Do not use a source repository `features/` folder as lifecycle source of truth
  unless project config explicitly says so; Agentic OS work items own lifecycle
  state by default.
- Do not work from a bare external checkout path when a project `worktrees/`
  registry/link should exist.
- Do not generate `IDEA.md` for new packets. Existing `IDEA.md` files remain
  readable legacy capture.
