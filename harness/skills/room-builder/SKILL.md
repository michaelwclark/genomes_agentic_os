# Room Builder

Use when turning operator/customer discovery answers into Agentic OS rooms, routing tables, references, and room-local context contracts.

## Workflow

1. Read the customer or operator profile.
2. Normalize room names into filesystem-safe IDs.
3. Preserve the operator's display names in README/context text.
4. Create one room/domain boundary per real work area, not per internal tool.
5. For each room, define:
   - purpose,
   - inputs,
   - outputs,
   - task routing,
   - read-first references,
   - read-when-needed references,
   - do-not-load defaults,
   - tools and skills,
   - done criteria,
   - approval gates.
6. Generate shared references for naming, tools, style/output rules, and source priority.
7. Keep the top-level map short and move detailed process into room or stage context files.

## Completion Standard

A fresh Codex or Claude run should be able to route a task to the correct room, load only the required references, create the output in the correct folder, and know what validation or approval is needed.

## Guardrails

- Do not force Genome's personal domains onto a customer OS.
- Do not create more than five starting rooms unless the user's real workflow requires it.
- Do not load every reference for every task.
- Do not promote a workflow into automation before run evidence exists.
