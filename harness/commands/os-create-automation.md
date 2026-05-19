# OS Create Automation

Use when a proven workflow can become trigger-driven work.

## Procedure

1. Confirm the workflow has successful run logs.
2. Run `agentic-os automation create <domain> <lane> <automation> --root ~/agentic_os`.
3. Fill trigger, inputs, outputs, permissions, failure modes, runbook, and tests.
4. Set the starting maturity level to `observe` or `prepare`.
5. Link the automation from the related project or domain active-work file.

## Safety Rule

External writes, production changes, destructive actions, secrets, billing, legal records, and customer-visible output require explicit human approval.
