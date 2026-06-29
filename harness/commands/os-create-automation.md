# OS Create Automation

Use when a proven workflow can become trigger-driven work.

## Procedure

1. Confirm the workflow has successful run logs.
2. Read `harness/rules/os-authoring-rules.md`.
3. Run `agentic-os automation create <domain> <lane> <automation> --root ~/agentic_os`.
4. Fill trigger, invocation contract, inputs, outputs, permissions, failure
   modes, runbook, and tests.
5. Add or update the matching command, skill, source watcher, schedule, or
   runtime registry entry before enabling the automation.
6. Update visible registries and readable `TOOLS.md` surfaces for new command,
   skill, rule, hook, plugin, library, tool, or MCP surfaces.
7. Set the starting maturity level to `observe` or `prepare`.
8. Link the automation from the related project or domain active-work file and
   append the setup receipt to the relevant worklog.

## Safety Rule

External writes, production changes, destructive actions, secrets, billing, legal records, and customer-visible output require explicit human approval.

## Registry Rule

Runnable automations must have an explicit command, skill, trigger, or runtime
registry entry. `agentic-os validate` warns on draft automations without one and
blocks active automations that are missing one.
