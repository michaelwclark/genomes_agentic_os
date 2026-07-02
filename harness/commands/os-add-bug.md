# OS Add Bug

Use when the user reports broken behavior, missed Agentic OS enforcement, drift
between config and runtime, or a product bug.

Primary slash command: `/add-bug`

Examples:

```text
/add-bug in los django the login button stopped working
/add-bug in the os we are not logging conversations
```

## Procedure

1. Load the routed Agentic OS layer and `harness/rules/os-authoring-rules.md`.
2. Run doc routing before creating anything:

```bash
agentic-os doc-config plan --root <root> --request "<bug report>" [--domain <domain>] [--project <project>] --questions-present
```

3. Resolve the affected domain/project. If the bug is about Agentic OS itself,
   route to `clarks_consulting/genomes_agentic_os`.
4. Create or update a project work item in intake unless an active matching bug
   already exists:

```bash
agentic-os project work-item create <domain> <project> \
  --root <root> \
  --title "Bug: <short failure>" \
  --summary "<current behavior vs expected behavior>" \
  --status captured \
  --format packet
```

5. Add `BUG.md` when the packet needs a bug-specific summary. Keep existing
   `SPEC`, `PLAN`, `WORKLOG`, `QUESTIONS`, and `NEXT` files consistent.
6. If source work uses an external checkout, confirm it is registered in the
   project `worktrees/` surface.
7. Project to Notion only after workspace verification.
8. Create the unified intake row (non-blocking):

```bash
agentic-os-intake-row \
  --title "Bug: <short failure>" \
  --type bug \
  --route-text '<user's original bug report words>' \
  --body-file <packet BUG.md or SPEC.md path>
```

   Example: `--route-text 'in los django the login button stopped working'` resolves to
   `Project=LOS Django` via NL routing. If the row create fails, record the error
   in `WORKLOG.md` and continue.

## Bug Fields

- Affected area
- Severity
- Current behavior
- Expected behavior
- Reproduction or evidence
- Suspected source
- Owner/status
- Next action

## Guardrails

- Do not store secrets, raw tokens, or private transcript payloads in bug files.
- Do not create duplicate bug packets before searching existing work-items.
- Do not assume `harness/logs/conversations` is the only conversation-log
  destination; routed project/work-item logs may be correct.
