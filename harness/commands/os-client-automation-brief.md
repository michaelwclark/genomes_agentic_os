# OS Client Automation Brief

Use when a customer or operator wants to evaluate whether repeated work should become a workflow, automation, or manual runbook.

## Procedure

1. Capture the desired business outcome and current manual workflow.
2. List systems, inputs, outputs, frequency, time cost, error cost, and owner.
3. Classify each step as deterministic, rule-based, LLM-needed, or human judgment.
4. Mark steps that must stay manual.
5. Identify approval gates before customer-visible, external, production, billing, legal, destructive, credential, or irreversible actions.
6. Define the smallest safe pilot and metrics baseline.
7. Write the result using `templates/customer/client-automation-brief.md`.

## Output

Return the brief path, recommended work type, approval gate, pilot scope, validation plan, and next action.
