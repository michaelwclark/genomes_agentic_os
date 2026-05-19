# Automation Qualifier

Use when deciding whether a workflow can become automation.

## Workflow

1. Review prior run logs.
2. Identify the trigger and all external effects.
3. Classify maturity as `observe`, `prepare`, `propose`, `execute_approved`, or `execute_guarded`.
4. Write inputs, outputs, permissions, failure modes, runbook, and tests.
5. Escalate any unsafe action to human approval.

## Refusal Rule

Do not classify ambiguous, high-risk, or poorly observed work as unattended automation.
