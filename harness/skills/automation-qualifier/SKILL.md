# Automation Qualifier

Use when deciding whether a workflow can become automation.

## Workflow

1. Read `harness/rules/os-authoring-rules.md`.
2. Review prior run logs.
3. Identify the trigger and all external effects.
4. Classify maturity as `observe`, `prepare`, `propose`, `execute_approved`, or `execute_guarded`.
5. Write inputs, outputs, permissions, failure modes, runbook, and tests.
6. Add a matching slash command and skill when the automation should be directly invoked.
7. Update registries, readable `TOOLS.md`, related project/domain state, and worklog.
8. Escalate any unsafe action to human approval.

## Refusal Rule

Do not classify ambiguous, high-risk, or poorly observed work as unattended automation.
