# OS Create Workflow

Use when a repeatable process needs judgment, context assembly, validation, or approval gates.

## Procedure

1. Route the request first.
2. Read `harness/rules/os-authoring-rules.md`.
3. Run `agentic-os workflow create <domain> <lane> <workflow> --root ~/agentic_os`.
4. Fill `workflow.md`, including the invocation contract.
5. Fill `outcome-brief.md`.
6. Fill `alignment-questions.md`.
7. Fill `prd.md`.
8. Fill `implementation-plan.md`.
9. Fill `context-pack.md`.
10. Fill `approval-rules.md`.
11. Add or update the matching slash command and skill when this workflow should
    be directly invoked by a harness.
12. Update visible registries and readable `TOOLS.md` surfaces for any command,
    skill, rule, hook, plugin, library, tool, or MCP surface added.
13. Update active work, the related project, and the relevant `WORKLOG.md`.

## Stop Condition

Do not dispatch implementation work until the outcome, scope, context, and approval gates are clear enough for a fresh agent to continue.

## Registry Rule

Active reusable workflows that are directly invoked must have a command or skill
invocation listed in `harness/registries/commands.yml` or
`harness/registries/skills.yml`.
