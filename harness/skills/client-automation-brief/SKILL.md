# Client Automation Brief

Use this skill to turn a customer workflow discovery conversation into an automation brief that separates deterministic work, rule-based work, LLM-needed work, and human judgment.

## Workflow

1. Load `templates/customer/client-automation-brief.md`.
2. Capture outcome, current manual workflow, systems, inputs, outputs, frequency, time cost, error cost, approval gates, rollback, pilot scope, data boundaries, and metrics baseline.
3. Use `templates/customer/automation-fit-matrix.md` to decide whether this is a good first automation.
4. Keep customer-visible output behind explicit approval.
5. Write the brief to the customer project or domain artifacts folder.

## Done

- The brief names the recommended work type.
- The approval gate is explicit.
- The pilot is small, measurable, and reversible.
